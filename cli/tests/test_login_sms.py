"""Offline tests for the app-side SMS login flow (no network, no JAR)."""
import base64

import pytest

from xhh_sdk import login
from xhh_sdk.exceptions import XhhConfigError

PHONE = "13800000000"


@pytest.mark.parametrize("phone", ["", "12345", "23800000000", "1380000000x", "138000000004"])
def test_rejects_invalid_phone(phone):
    with pytest.raises(XhhConfigError, match="phone"):
        login.login_sms_request(phone)


def test_request_code_uses_the_documented_endpoint(monkeypatch):
    seen = {}

    def fake(path, **kwargs):
        seen.update(path=path, **kwargs)
        return {"status": "ok", "result": {"sid": "abc"}}, {}

    monkeypatch.setattr(login, "_signed_post", fake)
    body = login.login_sms_request(PHONE, identity="12345678", risk_token="risk-value")
    assert seen["path"] == "/account/get_login_code/"
    cipher = seen["form"]["phone_num"]
    assert PHONE not in cipher
    assert cipher.endswith("\n")
    assert len(base64.b64decode(cipher.strip())) == 128
    assert seen["identity"] == "12345678" and seen["risk_token"] == "risk-value"
    assert body["status"] == "ok"


def test_verify_sends_code_and_returns_session(monkeypatch):
    seen = {}

    def fake(path, **kwargs):
        seen.update(path=path, **kwargs)
        return {"status": "ok", "result": {}}, {"pkey": "PK", "heybox_id": "4242"}

    monkeypatch.setattr(login, "_signed_post", fake)
    result = login.login_sms_verify(PHONE, "123456", identity="12345678", risk_token="r")
    assert seen["path"] == "/account/login_code/"
    assert PHONE not in seen["form"]["phone_num"]
    assert seen["query"]["code"] == "123456"
    assert "is_new_device" in seen["query"]
    assert (result.pkey, result.identity) == ("PK", "4242")


def test_verify_accepts_session_from_response_body(monkeypatch):
    monkeypatch.setattr(login, "_signed_post", lambda path, **kw: (
        {"status": "ok", "result": {"pkey": "BODY-PK",
                                    "account_detail": {"userid": "777"}}}, {}))
    result = login.login_sms_verify(PHONE, "123456")
    assert (result.pkey, result.identity) == ("BODY-PK", "777")


def test_verify_enforces_expected_identity(monkeypatch):
    monkeypatch.setattr(login, "_signed_post", lambda path, **kw: (
        {"status": "ok", "result": {}}, {"pkey": "PK", "heybox_id": "111"}))
    with pytest.raises(XhhConfigError, match="does not match"):
        login.login_sms_verify(PHONE, "123456", expected_identity="222")


def test_verify_rejects_short_code():
    with pytest.raises(XhhConfigError, match="code"):
        login.login_sms_verify(PHONE, "12")


def test_platform_refusal_is_reported_without_secrets(monkeypatch):
    monkeypatch.setattr(login, "_signed_post", lambda path, **kw: (
        {"status": "failed", "msg": "需要图形验证码"}, {}))
    with pytest.raises(XhhConfigError, match="failed"):
        login.login_sms_request(PHONE)


def test_missing_session_is_an_error(monkeypatch):
    monkeypatch.setattr(login, "_signed_post", lambda path, **kw: ({"status": "ok", "result": {}}, {}))
    with pytest.raises(XhhConfigError, match="session"):
        login.login_sms_verify(PHONE, "123456")


def test_signed_post_parses_body_and_cookies(monkeypatch):
    class FakeTransport:
        def __init__(self, config):
            self.config = config

        def _app_query(self, path):
            return {"os_type": "Android", "_time": "1"}

    class Response:
        def read(self):
            return b'{"status":"ok","result":{"sid":"x"}}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Opener:
        def open(self, request, timeout=None):
            assert "account/get_login_code" in request.full_url
            assert request.data == b"phone_num=x"
            assert request.get_header("Cookie") == "x_xhh_tokenid=risk-value"
            return Response()

    monkeypatch.setattr("xhh_sdk.transport.Transport", FakeTransport)
    monkeypatch.setattr(login.urllib.request, "build_opener", lambda *a, **k: Opener())
    body, cookies = login._signed_post("/account/get_login_code/",
                                       form={"phone_num": "x"}, risk_token="risk-value")
    assert body["status"] == "ok"
    assert cookies == {}


def test_encrypt_phone_uses_the_embedded_key():
    from xhh_sdk.secure_phone import _public_numbers, encrypt_phone

    modulus, exponent = _public_numbers()
    assert modulus.bit_length() == 1024 and exponent == 65537
    first = encrypt_phone("+8613800000000")
    second = encrypt_phone("+8613800000000")
    assert first != second                      # random PKCS#1 v1.5 padding
    for value in (first, second):
        raw = base64.b64decode(value.strip())
        assert len(raw) == 128 and value.endswith("\n")


def test_risk_token_helper_ignores_unsafe_values():
    good = [{"name": "lang", "value": "zh-cn"},
            {"name": "x_xhh_tokenid", "value": "device-token"}]
    assert login.risk_token_from_cookies(good) == "device-token"
    assert login.risk_token_from_cookies([{"name": "x_xhh_tokenid", "value": "bad;value"}]) is None
    assert login.risk_token_from_cookies([]) is None

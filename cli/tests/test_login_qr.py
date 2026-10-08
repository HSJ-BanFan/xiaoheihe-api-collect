"""Offline tests for the callback-based QR login flow (no browser, no network)."""
import base64
import json
import urllib.error

import pytest

from xhh_sdk import login
from xhh_sdk.exceptions import XhhConfigError


def test_qr_flow_prefers_pkey_over_user_pkey(monkeypatch):
    monkeypatch.setattr(login, "_fetch_login_page", lambda: "<script>var uuid=abc123_XYZ;</script>")
    shown = []
    monkeypatch.setattr(login, "_show_qr", lambda url: shown.append(url))
    polls = iter(["window.wx_errcode=404", "window.wx_errcode=405;window.wx_code='CODE-1'"])
    monkeypatch.setattr(login, "_poll_once", lambda uuid: next(polls))
    monkeypatch.setattr(login, "_exchange_code", lambda code: {
        "user_pkey": "wrong-value", "pkey": "right-value",
        "heybox_id": "12345", "user_heybox_id": "12345"})
    result = login.login_wechat_qr(timeout=30)
    assert (result.pkey, result.identity) == ("right-value", "12345")
    assert shown == ["https://open.weixin.qq.com/connect/qrcode/abc123_XYZ"]
    assert "right-value" not in repr(result)


def test_qr_flow_keeps_original_cookie_names(monkeypatch):
    monkeypatch.setattr(login, "_fetch_login_page", lambda: "uuid=u1")
    monkeypatch.setattr(login, "_show_qr", lambda url: None)
    monkeypatch.setattr(login, "_poll_once", lambda uuid: "window.wx_errcode=405;window.wx_code='C'")
    monkeypatch.setattr(login, "_exchange_code", lambda code: {
        "user_pkey": "only-user-pkey", "user_heybox_id": "99999"})
    result = login.login_wechat_qr(timeout=30)
    assert (result.pkey, result.identity) == ("only-user-pkey", "99999")


def test_qr_flow_enforces_expected_identity(monkeypatch):
    monkeypatch.setattr(login, "_fetch_login_page", lambda: "uuid=u1")
    monkeypatch.setattr(login, "_show_qr", lambda url: None)
    monkeypatch.setattr(login, "_poll_once", lambda uuid: "window.wx_errcode=405;window.wx_code='C'")
    monkeypatch.setattr(login, "_exchange_code", lambda code: {"pkey": "v", "heybox_id": "11111"})
    with pytest.raises(XhhConfigError, match="does not match"):
        login.login_wechat_qr(expected_identity="22222", timeout=30)


@pytest.mark.parametrize("response,message", [
    ("window.wx_errcode=403", "cancel"),
    ("window.wx_errcode=402", "expired"),
])
def test_qr_flow_reports_cancel_and_expiry(monkeypatch, response, message):
    monkeypatch.setattr(login, "_fetch_login_page", lambda: "uuid=u1")
    monkeypatch.setattr(login, "_show_qr", lambda url: None)
    monkeypatch.setattr(login, "_poll_once", lambda uuid: response)
    with pytest.raises(XhhConfigError, match=message):
        login.login_wechat_qr(timeout=30)


def test_qr_flow_requires_uuid(monkeypatch):
    monkeypatch.setattr(login, "_fetch_login_page", lambda: "<html>no code here</html>")
    with pytest.raises(XhhConfigError, match="QR code"):
        login.login_wechat_qr(timeout=30)


def test_qr_flow_rejects_empty_session(monkeypatch):
    monkeypatch.setattr(login, "_fetch_login_page", lambda: "uuid=u1")
    monkeypatch.setattr(login, "_show_qr", lambda url: None)
    monkeypatch.setattr(login, "_poll_once", lambda uuid: "window.wx_errcode=405;window.wx_code='C'")
    monkeypatch.setattr(login, "_exchange_code", lambda code: {"unrelated": "value"})
    with pytest.raises(XhhConfigError, match="session"):
        login.login_wechat_qr(timeout=30)


def test_qr_flow_times_out(monkeypatch):
    monkeypatch.setattr(login, "_fetch_login_page", lambda: "uuid=u1")
    monkeypatch.setattr(login, "_show_qr", lambda url: None)
    monkeypatch.setattr(login, "_poll_once", lambda uuid: "window.wx_errcode=404")
    ticks = iter([0.0, 0.0, 999.0])
    monkeypatch.setattr(login.time, "monotonic", lambda: next(ticks, 999.0))
    with pytest.raises(XhhConfigError, match="timed out"):
        login.login_wechat_qr(timeout=5)


def test_exchange_code_uses_callback_url_and_captures_cookies(monkeypatch):
    captured = {}

    class Response:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Opener:
        def open(self, request, timeout=None):
            captured["url"] = request.full_url
            captured["cookies"] = request.get_header("Cookie")
            return Response()

    def fake_build(processor):
        processor.cookiejar.set_cookie(_cookie("pkey", "PK"))
        processor.cookiejar.set_cookie(_cookie("heybox_id", "4242"))
        return Opener()

    monkeypatch.setattr(login.urllib.request, "build_opener", fake_build)
    values = login._exchange_code("WXCODE", opener_factory=login.urllib.request.build_opener)
    assert values == {"pkey": "PK", "heybox_id": "4242"}
    assert "code=WXCODE" in captured["url"] and "state=xiaoheihe" in captured["url"]
    assert captured["url"].startswith("https://api.xiaoheihe.cn/account/wechat/login_redirect/v2/web_sso/")


def _cookie(name, value):
    import http.cookiejar
    return http.cookiejar.Cookie(0, name, value, None, False, ".xiaoheihe.cn", False, False, "/", True,
                                 False, None, True, None, None, {})

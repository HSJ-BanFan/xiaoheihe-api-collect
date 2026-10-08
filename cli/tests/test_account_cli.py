"""Public multi-account CLI flows using synthetic identities and fake network."""
import argparse
import json
import sys
from types import SimpleNamespace

import pytest

from xhh_sdk import cli
from xhh_sdk.exceptions import XhhAuthError, XhhConfigError

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI integration")


@pytest.fixture
def store(tmp_path):
    from xhh_sdk.accounts import AccountStore
    return AccountStore(tmp_path / "managed")


def invoke(store, *args):
    return cli.main(["--data-dir", str(store.root), "account", *args])


def authenticate(store, alias, identity):
    store.add(alias, identity=identity)
    account = store.get(alias)
    store.save_login(alias, pkey="synthetic-session-" + alias, identity=identity,
                     expected_revision=account.revision)


def test_add_list_and_local_status_without_client(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "XhhClient", lambda *a: pytest.fail("must be offline"))
    assert invoke(store, "add", "work") == 0
    assert invoke(store, "add", "personal") == 0
    capsys.readouterr()
    assert invoke(store, "list") == 0
    assert {a["alias"] for a in json.loads(capsys.readouterr().out)["accounts"]} == {"work", "personal"}
    assert invoke(store, "status", "work") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["authenticated"] is False
    assert data["session_valid"] == "not_checked"


@pytest.mark.parametrize("action", ["login", "logout", "remove", "configure"])
def test_account_changes_require_confirm_before_store_access(store, monkeypatch, capsys, action):
    monkeypatch.setattr(cli, "_account_store", lambda *a: pytest.fail("must refuse first"), raising=False)
    args = [action, "work"] + (["--set", "timeout=10"] if action == "configure" else [])
    assert invoke(store, *args) == 2
    assert "--confirm" in capsys.readouterr().err


def test_no_implicit_account_or_ambient_credentials(monkeypatch):
    monkeypatch.setenv("XHH_PKEY", "synthetic-other-account")
    monkeypatch.setenv("XHH_HEYBOX_ID", "99999")
    monkeypatch.setattr(cli, "DEFAULT_CONFIG", __import__("pathlib").Path("missing.json"))
    args = argparse.Namespace(account=None, config=None, env=False, data_dir=None)
    with pytest.raises(XhhConfigError, match="account"):
        cli._load(args)


def test_missing_explicit_config_does_not_fall_back(monkeypatch, tmp_path):
    monkeypatch.setenv("XHH_PKEY", "synthetic-other-account")
    monkeypatch.setenv("XHH_HEYBOX_ID", "99999")
    args = argparse.Namespace(account=None, config=str(tmp_path / "missing.json"), env=False, data_dir=None)
    with pytest.raises(XhhConfigError):
        cli._load(args)


def test_requests_use_explicit_account_only(store, monkeypatch, capsys):
    authenticate(store, "work", "12345")
    authenticate(store, "personal", "67890")
    monkeypatch.setenv("XHH_PKEY", "synthetic-unrelated")
    seen = []
    class Client:
        def __init__(self, config):
            seen.append((config.heybox_id, config.pkey))
        def my_posts(self):
            return []
    monkeypatch.setattr(cli, "XhhClient", Client)
    for alias in ("work", "personal"):
        assert cli.main(["--data-dir", str(store.root), "--account", alias, "posts"]) == 0
    assert seen == [("12345", "synthetic-session-work"), ("67890", "synthetic-session-personal")]
    assert "synthetic-session" not in capsys.readouterr().out


def test_login_stores_and_verifies_only_the_selected_account(store, monkeypatch, capsys):
    from xhh_sdk import login
    store.add("work", identity="12345")
    store.add("personal", identity="67890")
    seen = []
    def fake(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(identity="12345", pkey="synthetic-qr-session")
    monkeypatch.setattr(login, "login_wechat", fake)
    monkeypatch.setattr(login, "login_wechat_qr", fake)
    class Verified:
        def __init__(self, *_):
            pass
        def account_info(self):
            return {"account_detail": {"userid": "12345"}}
    monkeypatch.setattr(cli, "XhhClient", Verified)
    assert invoke(store, "login", "work", "--confirm") == 0
    assert seen[0]["expected_identity"] == "12345"
    assert store.get("work").pkey == "synthetic-qr-session"
    assert store.get("personal").pkey is None
    output = capsys.readouterr().out
    assert "synthetic-qr-session" not in output and "12345" not in output
    assert json.loads(output)["api_identity_verified"] is True


def test_login_reports_a_session_the_api_rejects(store, monkeypatch, capsys):
    from xhh_sdk import login
    from xhh_sdk.exceptions import XhhAPIError
    store.add("work", identity="12345")
    monkeypatch.setattr(login, "login_wechat_qr",
                        lambda **k: SimpleNamespace(identity="12345", pkey="synthetic-qr"))

    class Rejected:
        def __init__(self, *_):
            pass
        def account_info(self):
            raise XhhAPIError("platform returned status='relogin'")
    monkeypatch.setattr(cli, "XhhClient", Rejected)
    assert invoke(store, "login", "work", "--confirm") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["state"] == "rejected"
    assert report["session_valid"] is False
    assert report["api_identity_verified"] is False
    assert store.get("work").pkey == "synthetic-qr"


def test_wrong_account_qr_does_not_overwrite(store, monkeypatch, capsys):
    from xhh_sdk import login
    authenticate(store, "work", "12345")
    wrong = lambda **k: SimpleNamespace(identity="67890", pkey="synthetic-wrong")
    monkeypatch.setattr(login, "login_wechat", wrong)
    monkeypatch.setattr(login, "login_wechat_qr", wrong)
    assert invoke(store, "login", "work", "--confirm") == 1
    assert store.get("work").pkey == "synthetic-session-work"
    assert "synthetic" not in capsys.readouterr().err


def test_configure_safe_settings(store, capsys):
    store.add("work")
    assert invoke(store, "configure", "work", "--set", "timeout=12", "--set", "java=java", "--confirm") == 0
    assert store.get("work").config["timeout"] == 12
    capsys.readouterr()
    assert invoke(store, "configure", "work", "--set", "pkey=do-not-echo-this", "--confirm") == 1
    assert "do-not-echo-this" not in capsys.readouterr().err


def test_logout_and_remove_are_local_and_isolated(store, monkeypatch, capsys):
    authenticate(store, "work", "12345")
    authenticate(store, "personal", "67890")
    monkeypatch.setattr(cli, "XhhClient", lambda *a: pytest.fail("must be offline"))
    assert invoke(store, "logout", "work", "--confirm") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["server_session_revoked"] is False
    assert store.get("work").pkey is None
    assert invoke(store, "remove", "work", "--confirm") == 0
    assert [a["alias"] for a in store.list()] == ["personal"]
    assert store.get("personal").pkey == "synthetic-session-personal"


@pytest.mark.parametrize("payload,verified,code", [
    ({"user": {"heybox_id": "12345", "pkey": "synthetic-leak"}}, True, 0),
    ({"account_detail": {"userid": "12345", "username": "synthetic-name"}}, True, 0),
    ({"result": {"account_detail": {"userid": "12345"}}}, False, 1),
    ({"user": {"userid": "67890"}}, False, 1),
    ({"nickname": "synthetic-private-name"}, False, 1),
])
def test_online_status_requires_matching_explicit_identity(store, monkeypatch, capsys, payload, verified, code):
    authenticate(store, "work", "12345")
    monkeypatch.setattr(cli, "XhhClient", lambda config: SimpleNamespace(account_info=lambda: payload))
    assert invoke(store, "status", "work", "--online") == code
    raw = capsys.readouterr().out
    result = json.loads(raw)
    assert result["api_identity_verified"] is verified
    assert "synthetic-" not in raw and "12345" not in raw and "67890" not in raw


def test_expired_session_is_reported_without_exposing_server_message(store, monkeypatch, capsys):
    authenticate(store, "work", "12345")
    def expired():
        raise XhhAuthError("synthetic-secret-in-server-message")
    monkeypatch.setattr(cli, "XhhClient", lambda config: SimpleNamespace(account_info=expired))
    assert invoke(store, "status", "work", "--online") == 1
    raw = capsys.readouterr().out
    assert json.loads(raw)["state"] == "expired"
    assert "synthetic" not in raw


def test_business_output_redacts_session_values_and_secret_fields(store, monkeypatch, capsys):
    authenticate(store, "work", "12345")
    payload = {"result": {"name": "public-name", "pkey": "server-key",
                          "nested": ["prefix synthetic-session-work suffix"],
                          "refresh_token": "server-refresh", "Cookie": "server-cookie"}}
    monkeypatch.setattr(cli, "XhhClient", lambda config: SimpleNamespace(call=lambda *a, **k: payload))
    assert cli.main(["--data-dir", str(store.root), "--account", "work", "call", "/account/info"]) == 0
    raw = capsys.readouterr().out
    assert "public-name" in raw
    for secret in ("server-key", "server-refresh", "server-cookie", "synthetic-session-work"):
        assert secret not in raw


def test_status_refuses_result_if_account_changed_during_request(store, monkeypatch, capsys):
    authenticate(store, "work", "12345")
    def read():
        store.logout("work")
        return {"user": {"heybox_id": "12345"}}
    monkeypatch.setattr(cli, "XhhClient", lambda config: SimpleNamespace(account_info=read))
    assert invoke(store, "status", "work", "--online") == 1
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "account_changed"
    assert result["api_identity_verified"] is False


def test_short_identity_is_fully_masked(store, capsys):
    store.add("short", identity="12")
    assert invoke(store, "status", "short") == 0
    assert json.loads(capsys.readouterr().out)["identity_masked"] == "**"


def test_sms_login_requires_phone_and_confirmation(store, monkeypatch, capsys):
    store.add("work", identity="4242")
    assert invoke(store, "login", "work", "--method", "sms", "--phone", "13800000000") == 2
    assert "--confirm" in capsys.readouterr().err
    assert invoke(store, "login", "work", "--method", "sms", "--confirm") == 1
    assert "phone" in capsys.readouterr().err
    assert invoke(store, "login", "work", "--method", "sms", "--phone", "13800000000",
                  "--confirm") == 1
    assert "risk-token" in capsys.readouterr().err


def test_sms_login_sends_code_then_saves_session(store, monkeypatch, capsys):
    from xhh_sdk import login
    store.add("work", identity="4242")
    calls = []
    monkeypatch.setattr(login, "login_sms_request",
                        lambda phone, **kw: calls.append(("send", phone)) or {"status": "ok"})
    assert invoke(store, "login", "work", "--method", "sms", "--phone", "13800000000",
                  "--risk-token", "risk-value", "--confirm") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["code_sent"] is True
    assert store.get("work").pkey is None

    monkeypatch.setattr(login, "login_sms_verify",
                        lambda phone, code, **kw: calls.append(("verify", phone, code))
                        or SimpleNamespace(identity="4242", pkey="synthetic-sms-session"))
    class Verified:
        def __init__(self, *_):
            pass
        def account_info(self):
            return {"account_detail": {"userid": "4242"}}
    monkeypatch.setattr(cli, "XhhClient", Verified)
    assert invoke(store, "login", "work", "--method", "sms", "--phone", "13800000000",
                  "--risk-token", "risk-value", "--code", "123456", "--confirm") == 0
    out = capsys.readouterr().out
    assert store.get("work").pkey == "synthetic-sms-session"
    assert store.get("work").identity == "4242"
    assert "synthetic-sms-session" not in out
    assert calls == [("send", "13800000000"), ("verify", "13800000000", "123456")]


def test_browser_login_method_dispatches_to_playwright_flow(store, monkeypatch, capsys):
    from xhh_sdk import login
    store.add("work", identity="4242")
    calls = []
    monkeypatch.setattr(
        login, "login_wechat",
        lambda **kwargs: calls.append(kwargs)
        or SimpleNamespace(identity="4242", pkey="synthetic-browser-session"))

    class Verified:
        def __init__(self, *_):
            pass

        def account_info(self):
            return {"user": {"heybox_id": "4242"}}

    monkeypatch.setattr(cli, "XhhClient", Verified)
    assert invoke(store, "login", "work", "--method", "browser", "--confirm") == 0
    report = json.loads(capsys.readouterr().out)
    assert calls == [{"expected_identity": "4242", "browser_channel": "msedge",
                      "timeout": 180.0}]
    assert report["login_method"] == "browser"
    assert report["api_identity_verified"] is True
    assert store.get("work").pkey == "synthetic-browser-session"


def test_account_login_help_explains_web_and_app_session_results(store, capsys):
    with pytest.raises(SystemExit) as exited:
        invoke(store, "login", "work", "--help")
    assert exited.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "qr/browser: WeChat web SSO" in help_text
    assert "status=relogin" in help_text
    assert "sms: app session from a phone code (verified working)" in help_text


def test_account_index_names_both_login_families(store, capsys):
    with pytest.raises(SystemExit) as exited:
        cli.main(["--data-dir", str(store.root), "account", "--help"])
    assert exited.value.code == 0
    index = " ".join(capsys.readouterr().out.split())
    assert "WeChat web session" in index
    assert "App session from an SMS code" in index


def test_sms_login_uses_stored_device_token(store, monkeypatch, capsys):
    from xhh_sdk import login
    store.add("work", identity="4242")
    store.set_risk_token("work", "synthetic-device-token")
    seen = {}
    monkeypatch.setattr(login, "login_sms_request",
                        lambda phone, **kw: seen.update(kw) or {"status": "ok"})
    assert invoke(store, "login", "work", "--method", "sms", "--phone", "13800000000",
                  "--confirm") == 0
    capsys.readouterr()
    assert seen["risk_token"] == "synthetic-device-token"
    assert seen["identity"] == "4242"
    assert "synthetic-device-token" not in json.dumps(store.list())
    assert store.get("work").risk_token == "synthetic-device-token"


def test_risk_token_command_requires_confirmation(store, monkeypatch, capsys):
    store.add("work", identity="4242")
    monkeypatch.setattr(cli, "_account_store", lambda *a: pytest.fail("must refuse first"),
                        raising=False)
    assert invoke(store, "risk-token", "work") == 2
    assert "--confirm" in capsys.readouterr().err


@pytest.mark.parametrize("key", ["heybox_id", "imei", "device_info", "_time", "hkey", "nonce", "_rnd"])
def test_transport_blocks_query_identity_or_signature_override(key):
    from xhh_sdk.config import XhhConfig
    from xhh_sdk.transport import Transport
    class Signer:
        def sign(self, *a):
            pytest.fail("must reject before signing or network")
    transport = Transport(XhhConfig(pkey="synthetic-only", heybox_id="12345"), signer=Signer())
    with pytest.raises(XhhConfigError, match="protected"):
        transport.signed_request("/account/info", query={key: "override"})

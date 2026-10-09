"""Protocol selection and login replacement with synthetic, temporary accounts."""
import argparse
import builtins
import json
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from xhh_sdk import cli, login
from xhh_sdk.accounts import AccountStore
from xhh_sdk.config import XhhConfig
from xhh_sdk.exceptions import XhhAPIError, XhhAuthError, XhhConfigError, XhhTransportError
from xhh_sdk.transport import Transport


@pytest.fixture
def store(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Real DPAPI requires Windows")
    store = AccountStore(tmp_path / "private")
    store.add("work", identity="12345")
    store.save_login("work", pkey="synthetic-old", identity="12345",
                     expected_revision=store.get("work").revision)
    return store


def invoke(store, *args, protocol=None):
    prefix = ["--data-dir", str(store.root)]
    if protocol:
        prefix += ["--protocol", protocol]
    return cli.main([*prefix, "account", *args])


def test_account_mode_persists_and_reports_without_credentials(store, capsys):
    assert invoke(store, "configure", "work", "--set", "protocol_mode=web", "--confirm") == 0
    assert store.get_config("work").protocol_mode == "web"
    assert json.loads(capsys.readouterr().out)["protocol_mode"] == "web"
    assert invoke(store, "status", "work") == 0
    output = capsys.readouterr().out
    assert json.loads(output)["protocol_mode"] == "web"
    assert "synthetic-old" not in output and "12345" not in output


@pytest.mark.parametrize("mode", ["", "WEB", "web;app", "fallback", None, {}, 1])
def test_invalid_account_mode_does_not_mutate(store, mode):
    before = (store.root / "accounts.json").read_bytes()
    with pytest.raises(XhhConfigError):
        store.configure("work", {"protocol_mode": mode})
    with pytest.raises(XhhConfigError):
        store.save_login("work", pkey="synthetic-new", identity="12345",
                         expected_revision=store.get("work").revision, protocol_mode=mode)
    assert (store.root / "accounts.json").read_bytes() == before


def test_saved_login_mode_and_credentials_change_atomically(store, monkeypatch):
    from xhh_sdk import accounts
    before = (store.root / "accounts.json").read_bytes()
    def fail(*args):
        raise OSError("synthetic-private-path")
    monkeypatch.setattr(accounts.os, "replace", fail)
    with pytest.raises(XhhConfigError):
        store.save_login("work", pkey="synthetic-new", identity="12345",
                         expected_revision=store.get("work").revision, protocol_mode="web")
    assert (store.root / "accounts.json").read_bytes() == before


def test_mode_override_is_invocation_local_and_old_namespaces_work(store):
    args = argparse.Namespace(account="work", config=None, env=False,
                              data_dir=str(store.root), protocol="web")
    before = (store.root / "accounts.json").read_bytes()
    assert cli._load(args).protocol_mode == "web"
    assert store.get_config("work").protocol_mode == "app"
    assert (store.root / "accounts.json").read_bytes() == before
    del args.protocol
    assert cli._load(args).protocol_mode == "app"


def test_legacy_record_without_mode_still_uses_app(store):
    with store._locked():
        records = store._read()
        records["work"].config.pop("protocol_mode", None)
        store._write(records)
    assert store.get_config("work").protocol_mode == "app"


def test_override_does_not_fall_back_to_ambient_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("XHH_PKEY", "synthetic-ambient")
    monkeypatch.setenv("XHH_HEYBOX_ID", "99999")
    args = argparse.Namespace(account=None, config=str(tmp_path / "missing.json"),
                              env=False, data_dir=None, protocol="web")
    with pytest.raises(XhhConfigError):
        cli._load(args)


@pytest.mark.parametrize("method,mode", [("qr", "web"), ("browser", "web"), ("creator", "web"), ("sms", "app")])
def test_login_verifies_candidate_before_atomic_replacement(store, monkeypatch, capsys, method, mode):
    previous = store.get("work")
    result = SimpleNamespace(identity="12345", pkey="synthetic-new")
    monkeypatch.setattr(login, "login_wechat_qr", lambda **kw: result)
    monkeypatch.setattr(login, "login_wechat", lambda **kw: result)
    monkeypatch.setattr(login, "login_creator", lambda **kw: result, raising=False)
    monkeypatch.setattr(login, "login_sms_verify", lambda *args, **kw: result)
    seen = []
    def client(config):
        seen.append((config.pkey, config.heybox_id, config.protocol_mode))
        assert store.get("work").revision == previous.revision
        assert store.get("work").pkey == "synthetic-old"
        return SimpleNamespace(account_info=lambda: {"user": {"heybox_id": "12345"}})
    monkeypatch.setattr(cli, "XhhClient", client)
    options = (["--phone", "13800000000", "--code", "123456", "--risk-token", "synthetic-risk"]
               if method == "sms" else [])
    assert invoke(store, "login", "work", "--method", method, *options, "--confirm") == 0
    assert seen == [("synthetic-new", "12345", mode)]
    assert store.get("work").pkey == "synthetic-new"
    assert store.get_config("work").protocol_mode == mode
    output = capsys.readouterr().out
    assert json.loads(output)["api_identity_verified"] is True
    assert json.loads(output)["protocol_mode"] == mode
    assert "synthetic" not in output and "12345" not in output


@pytest.mark.parametrize("failure", ["auth", "api", "wrong", "missing"])
def test_failed_login_identity_check_preserves_previous_session(store, monkeypatch, capsys, failure):
    before = (store.root / "accounts.json").read_bytes()
    monkeypatch.setattr(login, "login_wechat_qr",
                        lambda **kw: SimpleNamespace(identity="12345", pkey="synthetic-candidate"))
    def check():
        if failure == "auth":
            raise XhhAuthError("synthetic-candidate synthetic-server-secret")
        if failure == "api":
            raise XhhAPIError("synthetic-candidate synthetic-server-secret")
        return {"user": {"heybox_id": "67890"}} if failure == "wrong" else {}
    monkeypatch.setattr(cli, "XhhClient", lambda config: SimpleNamespace(account_info=check))
    assert invoke(store, "login", "work", "--confirm") == 1
    assert (store.root / "accounts.json").read_bytes() == before
    output = capsys.readouterr()
    assert "synthetic" not in output.out + output.err
    assert json.loads(output.out)["changed"] is False


def test_login_revision_conflict_keeps_newer_mode_and_session(store, monkeypatch, capsys):
    monkeypatch.setattr(login, "login_wechat_qr",
                        lambda **kw: SimpleNamespace(identity="12345", pkey="synthetic-candidate"))
    def check():
        store.configure("work", {"timeout": 12})
        return {"user": {"heybox_id": "12345"}}
    monkeypatch.setattr(cli, "XhhClient", lambda config: SimpleNamespace(account_info=check))
    assert invoke(store, "login", "work", "--confirm") == 1
    assert store.get("work").pkey == "synthetic-old"
    assert store.get_config("work").protocol_mode == "app"
    assert store.get("work").config["timeout"] == 12
    output = capsys.readouterr()
    assert "changed during login" in output.err
    assert "synthetic" not in output.out + output.err


def test_conflicting_login_override_fails_before_browser(store, monkeypatch, capsys):
    monkeypatch.setattr(login, "login_wechat_qr", lambda **kw: pytest.fail("browser opened"))
    assert invoke(store, "login", "work", "--confirm", protocol="app") == 1
    assert "protocol" in capsys.readouterr().err


def test_creator_login_passes_explicit_browser_and_human_timeout(store, monkeypatch, capsys):
    seen = []
    def creator(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(identity="12345", pkey="synthetic-creator")
    monkeypatch.setattr(login, "login_creator", creator, raising=False)
    monkeypatch.setattr(cli, "XhhClient", lambda _: SimpleNamespace(
        account_info=lambda: {"user": {"heybox_id": "12345"}}))
    assert invoke(store, "login", "work", "--method", "creator", "--browser", "chrome",
                  "--timeout", "600", "--confirm") == 0
    assert seen == [{"expected_identity": "12345", "browser_channel": "chrome", "timeout": 600.0}]
    assert store.get_config("work").protocol_mode == "web"
    assert "synthetic-creator" not in capsys.readouterr().out


def test_online_status_override_uses_one_mode_without_persisting(store, monkeypatch, capsys):
    before = (store.root / "accounts.json").read_bytes()
    modes = []
    def client(config):
        modes.append(config.protocol_mode)
        return SimpleNamespace(account_info=lambda: {"user": {"heybox_id": "12345"}})
    monkeypatch.setattr(cli, "XhhClient", client)
    assert invoke(store, "status", "work", "--online", protocol="web") == 0
    assert modes == ["web"]
    assert json.loads(capsys.readouterr().out)["protocol_mode"] == "web"
    assert (store.root / "accounts.json").read_bytes() == before


@pytest.mark.parametrize("selected", [False, True])
def test_web_offline_doctor_never_discovers_java_imports_bundle_or_executes_signer(
        tmp_path, monkeypatch, capsys, selected):
    path = tmp_path / "web.json"
    XhhConfig(pkey="synthetic-only", heybox_id="12345", protocol_mode="web",
              signer_bundle="bundle:" + "0" * 64).save(path)
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        assert "signer_bundle" not in name
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(cli.shutil, "which", lambda *a: pytest.fail("Java discovery"))
    monkeypatch.setattr(cli, "XhhClient", lambda *a: pytest.fail("client construction"))
    from xhh_sdk import web_signer
    monkeypatch.setattr(web_signer, "sign_web_request", lambda *a: pytest.fail("signer execution"))
    prefix = ["--config", str(path)] if selected else ["--protocol", "web"]
    assert cli.main([*prefix, "doctor", "--offline"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["protocol_mode"] == "web"
    assert report["signer_ready"] is True
    assert report["signer_executed"] is False
    assert report["java_required"] is False


def test_web_doctor_executes_python_signer_without_app_resources(tmp_path, monkeypatch, capsys):
    path = tmp_path / "web.json"
    XhhConfig(pkey="synthetic-only", heybox_id="12345", protocol_mode="web").save(path)
    monkeypatch.setattr(Transport, "signer", property(lambda self: pytest.fail("App signer accessed")))
    assert cli.main(["--config", str(path), "doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["protocol_mode"] == "web" and report["signer"] == "ok"
    assert report["signer_kind"] == "python-web"
    assert report["signer_executed"] is True


def test_web_verify_uses_python_signature_and_web_cookie(tmp_path, monkeypatch, capsys):
    path = tmp_path / "web.json"
    XhhConfig(pkey="synthetic-only", heybox_id="12345", protocol_mode="web").save(path)
    monkeypatch.setattr(Transport, "signer", property(lambda self: pytest.fail("App signer accessed")))
    requests = []
    def respond(self, request):
        requests.append(request)
        return b'{"status":"ok","result":{"links":[]}}'
    monkeypatch.setattr(Transport, "_open", respond)
    assert cli.main(["--config", str(path), "verify"]) == 0
    assert len(requests) == 1
    query = parse_qs(urlsplit(requests[0].full_url).query)
    assert {"_time", "hkey", "nonce"} <= query.keys()
    assert query["os_type"] == ["web"]
    assert requests[0].get_header("Cookie") == "user_pkey=synthetic-only; user_heybox_id=12345;"
    output = capsys.readouterr().out
    assert json.loads(output)["protocol_mode"] == "web"
    assert "synthetic-only" not in output


def test_web_failure_does_not_retry_using_app(store, monkeypatch, capsys):
    requests = []
    monkeypatch.setattr(Transport, "signer", property(lambda self: pytest.fail("App fallback")))
    def fail(self, request):
        requests.append(request)
        raise XhhTransportError("request failed")
    monkeypatch.setattr(Transport, "_open", fail)
    assert cli.main(["--data-dir", str(store.root), "--account", "work",
                     "--protocol", "web", "posts"]) == 1
    assert len(requests) == 1
    assert store.get_config("work").protocol_mode == "app"
    assert "synthetic-old" not in capsys.readouterr().err


@pytest.mark.parametrize("command,paths", [
    (["edit-info", "42"], ["/bbs/app/link/edit/info"]),
    (["creator-options", "--link-id", "42"],
     ["/bbs/app/api/topic/index", "/bbs/app/api/post_editor/topic_selection/index"]),
])
def test_creator_commands_use_scoped_client_routes(store, monkeypatch, capsys, command, paths):
    requests = []
    def read(self, path, **kwargs):
        requests.append((path, kwargs.get("query", {})))
        return {"result": {"link": {"title": "Draft"}, "post_plan": {"type": 1},
                           "hashtag_list": [{"name": "synthetic-tag"}]}}
    monkeypatch.setattr(Transport, "signed_request", read)
    assert cli.main(["--data-dir", str(store.root), "--account", "work", "--protocol", "web", *command]) == 0
    assert [path for path, _ in requests] == paths
    assert requests[0][1]["link_id"] == "42"
    report = json.loads(capsys.readouterr().out)
    if command[0] == "edit-info":
        assert report["title"] == "Draft"
    else:
        assert report["topic_index"]["post_plan"] == {"type": 1}
        assert report["topic_selection"]["hashtag_list"] == [{"name": "synthetic-tag"}]

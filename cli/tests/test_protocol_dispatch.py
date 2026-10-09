"""Exercise protocol routing without a real session, network, or Java runtime."""
import json
import subprocess
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from xhh_sdk.client import XhhClient
from xhh_sdk.config import XhhConfig
from xhh_sdk.exceptions import XhhAPIError, XhhAuthError, XhhConfigError
from xhh_sdk.payload import Post
from xhh_sdk.transport import Transport
import xhh_sdk.signer as signer_module
import xhh_sdk.transport as transport_module


class AppSigner:
    def sign(self, path):
        return {"_time": "1", "nonce": "synthetic", "hkey": "app", "_rnd": "1"}


def config(**kwargs):
    return XhhConfig(pkey="synthetic-session", heybox_id="12345",
                     api_base="https://api.invalid", **kwargs)


@pytest.fixture
def no_java(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Web operation attempted to resolve or execute the App signer")

    monkeypatch.setattr(transport_module, "Signer", forbidden)
    monkeypatch.setattr(signer_module.shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def capture(monkeypatch, transport, response=None):
    response = response if response is not None else {"status": "ok", "result": {}}
    opened = Mock(return_value=json.dumps(response).encode())
    monkeypatch.setattr(transport, "_open", opened)
    return opened


def test_legacy_config_and_client_remain_app_without_recursion(monkeypatch):
    cfg = config()
    transport = Transport(cfg, signer=AppSigner())
    opened = capture(monkeypatch, transport, {"status": "ok", "result": {"id": "99"}})
    assert cfg.protocol_mode == "app"
    assert XhhClient(cfg, transport=transport).read_post("99")["result"] == {"id": "99"}
    query = parse_qs(urlsplit(opened.call_args.args[0].full_url).query)
    assert query["os_type"] == ["Android"]
    assert query["hkey"] == ["app"]


def test_web_creator_metadata_accepts_only_known_bare_contract(monkeypatch, no_java):
    cfg = config(protocol_mode="web")
    transport = Transport(cfg)
    metadata = {"post_article_plan": [], "post_pic_link_plan": [],
                "extra_declaration_choice": [], "topics_list_v2": {}}
    capture(monkeypatch, transport, metadata)
    assert XhhClient(cfg, transport=transport).topic_index() == metadata
    with pytest.raises(XhhAPIError):
        transport.web_signed_request("/account/restore_login")


def test_web_publish_accepts_verified_top_level_creation_id(monkeypatch, no_java):
    cfg = config(protocol_mode="web")
    transport = Transport(cfg)
    opened = capture(monkeypatch, transport, {"status": "ok", "link_id": 12345, "msg": ""})
    result = XhhClient(cfg, transport=transport).publish(Post(content="synthetic"))
    assert result["link_id"] == "12345"
    assert opened.call_count == 1


@pytest.mark.parametrize("mode,envelope", [("web", "top"), ("web", "nested"), ("app", "nested")])
@pytest.mark.parametrize("link_id", [True, False, 0, -1, 1.5, {}, {"id": 123}, [], [123],
                                    "", "0", "00", "-1", "1.5", " 123", "123\n",
                                    "../other?x=1", "\uff11\uff12\uff13", "1" * 31])
def test_publish_rejects_malformed_creation_ids_without_retry(monkeypatch, mode, envelope, link_id):
    cfg = config(protocol_mode=mode)
    transport = Transport(cfg, signer=AppSigner())
    body = {"link_id": link_id}
    response = {"status": "ok", **body} if envelope == "top" else {"status": "ok", "result": body}
    opened = capture(monkeypatch, transport, response)
    with pytest.raises(XhhAPIError, match="link_id"):
        XhhClient(cfg, transport=transport).publish(Post(content="synthetic"))
    assert opened.call_count == 1


@pytest.mark.parametrize("mode,envelope", [("web", "top"), ("web", "nested"), ("app", "nested")])
@pytest.mark.parametrize("link_id", [1, "12345", "1" * 30, 10 ** 29])
def test_publish_returns_valid_positive_id_consistently(monkeypatch, mode, envelope, link_id):
    cfg = config(protocol_mode=mode)
    transport = Transport(cfg, signer=AppSigner())
    body = {"link_id": link_id}
    response = {"status": "ok", **body} if envelope == "top" else {"status": "ok", "result": body}
    opened = capture(monkeypatch, transport, response)
    result = XhhClient(cfg, transport=transport).publish(Post(content="synthetic"))
    assert result["link_id"] == str(link_id)
    assert result["url"] == "https://www.xiaoheihe.cn/app/bbs/link/" + str(link_id)
    assert opened.call_count == 1


@pytest.mark.parametrize("bad", [
    {"post_article_plan": []},
    {"post_article_plan": [], "post_pic_link_plan": [],
     "extra_declaration_choice": [], "topics_list_v2": {}, "status": "failed"},
    {"post_article_plan": [], "post_pic_link_plan": [],
     "extra_declaration_choice": [], "topics_list_v2": {}, "error": "failure"},
])
def test_creator_metadata_does_not_hide_errors(monkeypatch, bad):
    transport = Transport(config(protocol_mode="web"))
    capture(monkeypatch, transport, bad)
    with pytest.raises(XhhAPIError):
        transport.web_signed_request("/bbs/app/api/topic/index")


def test_explicit_app_read_does_not_recurse(monkeypatch):
    cfg = config(protocol_mode="app")
    transport = Transport(cfg, signer=AppSigner())
    opened = capture(monkeypatch, transport, {"status": "ok", "result": {"id": "99"}})
    assert XhhClient(cfg, transport=transport).read_post("99")["result"] == {"id": "99"}
    assert opened.call_count == 1


def test_new_protocol_field_preserves_legacy_positional_java_argument():
    cfg = XhhConfig("synthetic-session", "12345", "device", "device",
                    "https://api.invalid", "https://web.invalid", "1", "14",
                    None, None, "synthetic-java")
    assert cfg.java == "synthetic-java"
    assert cfg.protocol_mode == "app"


@pytest.mark.parametrize("mode", ["auto", "WEB", "", None, 1])
def test_invalid_protocol_rejected(mode):
    with pytest.raises(XhhConfigError, match="protocol"):
        config(protocol_mode=mode).validate()


def test_protocol_roundtrips_file_and_env(tmp_path, monkeypatch):
    saved = config(protocol_mode="web").save(tmp_path / "config.json")
    assert XhhConfig.from_file(saved).protocol_mode == "web"
    monkeypatch.setenv("XHH_PKEY", "synthetic-env")
    monkeypatch.setenv("XHH_HEYBOX_ID", "12345")
    monkeypatch.setenv("XHH_PROTOCOL_MODE", "web")
    assert XhhConfig.from_env().protocol_mode == "web"
    monkeypatch.setenv("XHH_PROTOCOL_MODE", "auto")
    with pytest.raises(XhhConfigError, match="protocol"):
        XhhConfig.from_env()


@pytest.mark.parametrize("operation", ["read", "browse", "catalog", "drafts", "publish"])
def test_web_client_routes_named_and_catalog_operations_without_java(operation, monkeypatch, no_java):
    cfg = config(protocol_mode="web", java="missing-java", signer_jar="missing.jar")
    client = XhhClient(cfg)
    opened = capture(monkeypatch, client.transport,
                     {"status": "ok", "result": {"link_id": "99", "links": []}})
    if operation == "read":
        client.read_post("99")
    elif operation == "browse":
        client.hot_news()
    elif operation == "catalog":
        client.call("/account/info")
    elif operation == "drafts":
        client.drafts()
    else:
        assert client.publish(Post(content="synthetic", content_format="text"))["link_id"] == "99"
    request = opened.call_args.args[0]
    query = parse_qs(urlsplit(request.full_url).query)
    assert query["os_type"] == ["web"]
    assert query["heybox_id"] == ["12345"]
    assert "_rnd" not in query
    assert {"_time", "nonce", "hkey", "version"} <= query.keys()
    assert request.get_header("Cookie") == "user_pkey=synthetic-session; user_heybox_id=12345;"
    assert request.get_method() == ("POST" if operation == "publish" else "GET")
    assert opened.call_count == 1


def test_web_interaction_uses_web_for_validation_and_write(monkeypatch, no_java):
    client = XhhClient(config(protocol_mode="web"))
    opened = capture(monkeypatch, client.transport,
                     {"status": "ok", "result": {"link": {"id": "99"}}})
    assert client.favourite("99", confirm=True)["favour_type"] == "1"
    assert opened.call_count == 2
    for call in opened.call_args_list:
        assert parse_qs(urlsplit(call.args[0].full_url).query)["os_type"] == ["web"]
    request = opened.call_args.args[0]
    assert request.get_method() == "POST"
    assert parse_qs(request.data.decode())["link_id"] == ["99"]


@pytest.mark.parametrize("key", [
    "heybox_id", "user_heybox_id", "x_heybox_id", "pkey", "user_pkey", "x_pkey",
    "_time", "nonce", "hkey", "_rnd", "version", "os_type", "x_os_type",
    "app", "x_app", "x_client_type", "x_client_version", "channel", "imei", "device_info",
])
def test_web_query_collisions_fail_before_signing_or_http(key, monkeypatch):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    signed = Mock(side_effect=AssertionError("query must be checked before signing"))
    monkeypatch.setattr(transport_module, "sign_web_request", signed)
    with pytest.raises(XhhConfigError, match="protected"):
        transport.web_signed_request("/synthetic", query={key: "override"})
    signed.assert_not_called()
    opened.assert_not_called()


@pytest.mark.parametrize("path", ["https://other.invalid/route", "//other.invalid/route",
                                  "/synthetic?heybox_id=99", "/synthetic#fragment",
                                  "/synthetic/../account/info", "/synthetic\\route",
                                  "/synthetic\r\nheader", "/synthetic/%2e%2e/route"])
def test_web_rejects_non_route_paths_before_http(path, monkeypatch):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    with pytest.raises(XhhConfigError, match="path"):
        transport.web_signed_request(path)
    opened.assert_not_called()


@pytest.mark.parametrize("method,payload", [("DELETE", None), ("PUT", {}), ("GET", {})])
def test_web_rejects_unsupported_method_or_get_body(method, payload, monkeypatch):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    with pytest.raises(XhhConfigError, match="method|GET"):
        transport.web_signed_request("/synthetic", method=method, payload=payload)
    opened.assert_not_called()


@pytest.mark.parametrize("response", [{}, {"result": {}}, {"error": "failure"},
                                      {"status": False}, {"status": "unexpected"}])
@pytest.mark.parametrize("mode", ["app", "web"])
def test_unexpected_status_never_reports_success(mode, response, monkeypatch):
    transport = Transport(config(protocol_mode=mode), signer=AppSigner())
    opened = capture(monkeypatch, transport, response)
    with pytest.raises(XhhAPIError):
        transport.signed_request("/synthetic")
    assert opened.call_count == 1


@pytest.mark.parametrize("status", ["login", "relogin"])
def test_web_auth_failure_does_not_retry_app(status, monkeypatch, no_java):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport, {"status": status})
    with pytest.raises(XhhAuthError):
        transport.signed_request("/synthetic", payload={"draft": "1"})
    assert opened.call_count == 1


def test_app_auth_failure_does_not_retry_web(monkeypatch):
    transport = Transport(config(), signer=AppSigner())
    opened = capture(monkeypatch, transport, {"status": "relogin"})
    web_signer = Mock(side_effect=AssertionError("App rejection retried Web"))
    monkeypatch.setattr(transport_module, "sign_web_request", web_signer)
    with pytest.raises(XhhAuthError):
        transport.signed_request("/synthetic", payload={"draft": "1"})
    assert opened.call_count == 1
    web_signer.assert_not_called()


def test_web_explicit_post_can_have_no_body(monkeypatch, no_java):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    transport.web_signed_request("/synthetic", method="POST")
    assert opened.call_args.args[0].get_method() == "POST"


def test_app_session_upload_post_remains_unsigned(monkeypatch, no_java):
    transport = Transport(config(protocol_mode="app"))
    opened = capture(monkeypatch, transport)
    signer = Mock(side_effect=AssertionError("unsigned upload was signed"))
    monkeypatch.setattr(transport_module, "sign_web_request", signer)
    transport.web_request("/bbs/app/api/qcloud/cos/upload/heartbeat", {"keys": "[]"})
    request = opened.call_args.args[0]
    assert request.get_method() == "POST"
    assert urlsplit(request.full_url).query == ""
    assert parse_qs(request.data.decode()) == {"keys": ["[]"]}
    signer.assert_not_called()


def test_web_session_upload_uses_creator_signature(monkeypatch, no_java):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    transport.web_request("/bbs/app/api/qcloud/cos/upload/info/v2", {"file_infos": "[]"})
    request = opened.call_args.args[0]
    query = parse_qs(urlsplit(request.full_url).query)
    assert request.get_method() == "POST"
    assert query["x_client_type"] == ["weboutapp"]
    assert {"hkey", "nonce", "_time"} <= query.keys()
    assert request.get_header("Cookie").startswith("user_pkey=")


@pytest.mark.parametrize("path", ["/chat_group/my_list", "/chatroom/v2/chat_group_msg/list"])
def test_web_refuses_app_only_groups_before_http(path, monkeypatch, no_java):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    with pytest.raises(XhhConfigError, match="App|app"):
        transport.signed_request(path)
    opened.assert_not_called()


def test_web_extra_cookie_preserved_but_identity_override_refused(monkeypatch, no_java):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    transport.signed_request("/synthetic", extra_cookies={"x_xhh_tokenid": "synthetic-risk"})
    cookie = opened.call_args.args[0].get_header("Cookie")
    assert "x_xhh_tokenid=synthetic-risk" in [part.strip() for part in cookie.split(";")]
    with pytest.raises(XhhConfigError, match="protected"):
        transport.signed_request("/synthetic", extra_cookies={"pkey": "override"})
    assert opened.call_count == 1


def test_web_verify_never_resolves_app_signer(monkeypatch, no_java):
    client = XhhClient(config(protocol_mode="web"))
    opened = capture(monkeypatch, client.transport, {"status": "ok", "result": {"links": []}})
    result = client.verify()
    assert result["ok"] is True
    assert result["protocol_mode"] == "web"
    assert result["signer"] == "python-web"
    assert result["draft_access"] is True
    assert result["api_identity_verified"] is False
    assert opened.call_count == 1


def test_web_sends_observed_creator_client_context(monkeypatch, no_java):
    transport = Transport(config(protocol_mode="web"))
    opened = capture(monkeypatch, transport)
    transport.signed_request("/synthetic")
    query = parse_qs(urlsplit(opened.call_args.args[0].full_url).query, keep_blank_values=True)
    assert query["x_client_type"] == ["weboutapp"]
    assert query["x_client_version"] == [""]


@pytest.mark.parametrize("mode,path", [("app", "/account/info"),
                                      ("web", "/account/restore_login")])
def test_account_info_uses_protocol_current_session_endpoint(mode, path, monkeypatch):
    cfg = config(protocol_mode=mode)
    transport = Transport(cfg, signer=AppSigner())
    opened = capture(monkeypatch, transport,
                     {"status": "ok", "result": {"user": {"heybox_id": "12345"}}})
    assert XhhClient(cfg, transport=transport).account_info() == {"user": {"heybox_id": "12345"}}
    request = opened.call_args.args[0]
    assert urlsplit(request.full_url).path == path
    assert request.get_method() == "GET"


def test_web_current_session_does_not_invent_identity_from_config(monkeypatch, no_java):
    client = XhhClient(config(protocol_mode="web"))
    capture(monkeypatch, client.transport, {"status": "ok", "result": {"permissions": []}})
    assert client.account_info() == {"permissions": []}

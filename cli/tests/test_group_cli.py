import json
from types import SimpleNamespace

import pytest

from xhh_sdk import cli
from xhh_sdk.client import XhhClient
from xhh_sdk.config import XhhConfig
from xhh_sdk.exceptions import XhhAPIError, XhhConfigError


@pytest.fixture
def group_client():
    calls = []

    def request(route, **kwargs):
        calls.append((route, kwargs))
        if route == "/chat_group/my_list":
            return {"status": "ok", "result": {"my_chat_groups": [
                {"chat_group_id": "123", "chat_group_name": "example"}]}}
        return {"status": "ok", "result": {"list": []}}

    client = XhhClient(XhhConfig(pkey="dummy", heybox_id="999"),
                       transport=SimpleNamespace(signed_request=request))
    return client, calls


def test_group_list_uses_exact_read_contract(group_client):
    client, calls = group_client
    assert client.group_list() == [{"chat_group_id": "123", "chat_group_name": "example"}]
    assert calls == [("/chat_group/my_list", {"extra_cookies": None})]


def test_group_members_and_messages_preserve_parameters(group_client):
    client, calls = group_client
    assert client.group_members("123", offset=20, limit=10) == {"list": []}
    assert calls[-1] == ("/chat_group/user/list", {
        "query": {"chat_group_id": "123", "offset": "20", "limit": "10"},
        "extra_cookies": None})
    assert client.group_messages("123", last_msg_id="42", limit=5) == {"list": []}
    assert calls[-1] == ("/chatroom/v2/chat_group_msg/list", {
        "query": {"chat_group_id": "123", "last_msg_id": "42", "limit": "5"},
        "extra_cookies": None})
    assert all("payload" not in kwargs for _, kwargs in calls)


def test_unknown_group_is_rejected_before_group_read(group_client):
    client, calls = group_client
    with pytest.raises(XhhConfigError, match="membership"):
        client.group_messages("456")
    assert [r for r, _ in calls] == ["/chat_group/my_list"]


def test_malformed_membership_response_is_not_empty_success(group_client):
    client, _ = group_client
    client.transport.signed_request = lambda *a, **k: {"status": "ok", "result": {}}
    with pytest.raises(XhhAPIError):
        client.group_list()


@pytest.mark.parametrize("args", [
    ["members", "invalid"], ["messages", "123", "--limit", "0"],
    ["messages", "123", "--last-msg-id", "-1"], ["members", "123", "--offset", "-1"],
])
def test_invalid_group_arguments_do_not_load_accounts(args, monkeypatch):
    monkeypatch.setattr(cli, "_load", lambda _: pytest.fail("invalid arguments loaded account"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["group", *args])
    assert exc.value.code == 2


def test_cli_group_reads_run_sdk_contracts(group_client, monkeypatch, capsys):
    client, calls = group_client
    monkeypatch.setattr(cli, "_load", lambda _: client.config)
    monkeypatch.setattr(cli, "XhhClient", lambda _: client)
    assert cli.main(["--env", "group", "messages", "123", "--limit", "5"]) == 0
    assert json.loads(capsys.readouterr().out) == {"list": []}
    assert calls[-1][0] == "/chatroom/v2/chat_group_msg/list"


def test_group_writes_are_not_promoted_to_cli(monkeypatch):
    monkeypatch.setattr(cli, "_load", lambda _: pytest.fail("unverified group write loaded config"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["group", "approve", "123"])
    assert exc.value.code == 2

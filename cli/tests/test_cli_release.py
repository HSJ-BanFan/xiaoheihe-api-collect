"""Release-facing CLI behavior, without credentials, Java or network."""
import json

import pytest

from xhh_sdk import cli
from xhh_sdk.exceptions import XhhConfigError
from xhh_sdk.routes import call, is_verified_read


@pytest.fixture(autouse=True)
def no_client(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline command tried to load credentials or create a client")
    monkeypatch.setattr(cli, "_load", forbidden)
    monkeypatch.setattr(cli, "XhhClient", forbidden)


def test_catalog_is_offline(capsys):
    assert cli.main(["catalog", "--search", "/account/info", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["route"] for r in data["routes"]] == ["/account/info"]
    assert data["live_retested"] is True
    assert data["summary"]["live_probe"]["routes_ok"] > 0


def test_catalog_lists_app_only_group_routes(capsys):
    assert cli.main(["catalog", "--group", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["routes"] == []
    routes = {row["route"]: row for row in data["group_routes"]}
    assert "/chat_group/my_list" in routes
    assert all(row["callable"] is False for row in data["group_routes"])
    assert routes["/chat_group/my_list"]["live_probe"]["outcome"] == "ok"


def test_catalog_route_lookup_covers_group_inventory(capsys):
    assert cli.main(["catalog", "--route", "/chat_group/card_info", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["route"] for r in data["group_routes"]] == ["/chat_group/card_info"]
    assert data["routes"] == []


def test_catalog_unknown_route_is_error(capsys):
    assert cli.main(["catalog", "--route", "/not-a-route", "--json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_catalog_finds_explicit_write_route(capsys):
    assert cli.main(["catalog", "--route", "/bbs/app/comment/create", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "comment" in [c["name"] for c in data["commands"]]
    assert data["routes"] == []


@pytest.mark.parametrize("args", [
    ["upload", "image.png"], ["publish", "missing.json"],
    ["publish", "missing.json", "--publish"], ["delete", "123"],
    ["comment", "123", "test"], ["canary", "123"],
])
def test_writes_refused_before_loading_credentials(args, capsys):
    assert cli.main(args) == 2
    assert "--confirm" in capsys.readouterr().err


@pytest.mark.parametrize("route", [
    "/account/check_account_state", "/account/manual_refresh_steam_screenshot",
    "/account/qr_redirect", "/account/resolve_clipboard",
    "/bbs/app/api/post_editor/topic_selection/index",
    "/bbs/app/api/recommend/feedback", "/account/refresh_steam_stats",
    "/account/getui/fix", "/bbs/app/link/steam/game/ignore_review",
])
def test_unresolved_contracts_not_in_read_gate(route):
    assert not is_verified_read(route)
    with pytest.raises(XhhConfigError):
        call(None, route)


def test_read_gate_rejects_payload():
    with pytest.raises(XhhConfigError, match="payload"):
        call(None, "/account/info", payload={"unexpected": "write"})

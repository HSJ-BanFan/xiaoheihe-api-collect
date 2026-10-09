"""The shipped catalogue is an offline, sanitized evidence index."""
import ast
import json
from pathlib import Path
import subprocess
import sys


SDK = Path(__file__).resolve().parents[1]
CATALOG = SDK / "xhh_sdk" / "api_catalog.json"


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_catalog_counts_separate_historical_and_current_probe_results():
    catalog = load_catalog()
    assert catalog["verification_date"] == "2026-10-04"
    assert catalog["generated_date"] == "2026-10-06"
    assert catalog["live_retested"] is True
    assert catalog["summary"]["historical_results"] == {
        "total": 783, "ok": 189, "rejected": 176,
        "not_found": 382, "error": 36,
    }
    assert catalog["summary"]["current_probe_results"] == {
        "total": 755, "ok": 185, "rejected": 165,
        "not_found": 370, "error": 35,
    }


def test_live_probe_evidence_is_recorded_for_every_callable_route():
    catalog = load_catalog()
    probe = catalog["summary"]["live_probe"]
    assert probe["checked_date"] == "2026-10-06"
    assert probe["sources"]
    assert all(not Path(source).is_absolute() for source in probe["sources"])
    missing = [entry["route"] for entry in catalog["routes"]
               if "live_probe" not in entry]
    assert missing == []
    statuses = {entry["live_probe"]["outcome"] for entry in catalog["routes"]}
    assert statuses == {"ok"}
    assert probe["routes_probed"] >= len(catalog["routes"])
    assert probe["routes_ok"] >= len(catalog["routes"])
    # Write-chain evidence must never leak into the per-route read evidence.
    sources = " ".join(probe["sources"])
    assert "probe-group-write" not in sources
    assert "probe-voice-room" not in sources


def test_group_inventory_covers_app_only_routes_without_widening_the_gate():
    catalog = load_catalog()
    groups = catalog["group_routes"]
    assert catalog["summary"]["group_routes"] == {
        "total": len(groups),
        "read": sum(1 for g in groups if g["classification"] == "read"),
        "write": sum(1 for g in groups if g["classification"] == "write"),
    }
    assert len(groups) >= 90
    assert all(g["callable"] is False for g in groups)
    assert all(g["sources"] and not Path(g["sources"][0]).is_absolute() for g in groups)
    assert not ({g["route"] for g in groups}
                & {entry["route"] for entry in catalog["routes"]})
    live_ok = [g for g in groups
               if g.get("live_probe", {}).get("outcome") == "ok"]
    assert len(live_ok) >= 30
    assert all(g["classification"] == "read" for g in live_ok)
    # A later bare call (no parameters) fails where an earlier parameterised
    # call succeeded; the recorded verdict must stay the success.
    param_scoped = next(g for g in groups if g["route"] == "/chat_group/user/list")
    assert param_scoped["live_probe"]["outcome"] == "ok"
    assert param_scoped["live_probe"]["pass"].startswith("group-pass")
    # No write-classified group route ever answered ok to the probe; the only
    # recorded write entry is /chat_group/show, where GET returned HTTP 405 and
    # the route was reclassified afterwards.
    assert all(g.get("live_probe", {}).get("outcome") != "ok" for g in groups
               if g["classification"] == "write")


def test_catalog_exactly_matches_the_current_call_allowlist():
    catalog = load_catalog()
    tree = ast.parse((SDK / "xhh_sdk" / "routes.py").read_text(encoding="utf-8"))
    expected = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.AnnAssign)
                    and node.target.id == "VERIFIED_READ_ROUTES")
    assert [entry["route"] for entry in catalog["routes"]] == sorted(expected)
    assert catalog["summary"]["callable_routes"] == len(expected)
    account = next(entry for entry in catalog["routes"]
                   if entry["route"] == "/account/info")
    assert account["purpose"] == "账号概览"
    assert account["method"] == "GET"
    assert account["cli"] == "xhh-sdk --account <alias> call /account/info"
    assert account["evidence_outcome"] == "ok"


def test_method_conflicts_and_possible_side_effects_are_not_callable():
    catalog = load_catalog()
    reviews = {entry["route"]: entry for entry in catalog["review_required"]}
    assert set(reviews) == {
        "/account/check_account_state",
        "/account/manual_refresh_steam_screenshot",
        "/account/qr_redirect",
        "/account/resolve_clipboard",
        "/bbs/app/api/post_editor/topic_selection/index",
        "/bbs/app/api/recommend/feedback",
        "/account/refresh_steam_stats",
        "/account/getui/fix",
        "/bbs/app/link/steam/game/ignore_review",
    }
    assert not set(reviews) & {entry["route"] for entry in catalog["routes"]}
    refresh = reviews["/account/manual_refresh_steam_screenshot"]
    assert refresh["static_method"] == "POST"
    assert refresh["call_allowed"] is False
    assert refresh["params"][0]["name"] == "steam_id"


def test_commands_separate_reversible_writes_from_read_snapshots():
    commands = {entry["name"]: entry for entry in load_catalog()["commands"]}
    assert commands["comment"]["evidence_level"] == "historical_functional_roundtrip"
    assert "live_probe" not in commands["comment"]
    assert commands["comment"]["safety"] == "write_own_post_confirm"
    assert commands["comment"]["routes"] == ["/bbs/app/comment/create"]
    assert commands["publish"]["safety"] == "write_confirm_draft_default_publish_opt_in"
    assert commands["upload"]["safety"] == "write_upload_confirm"
    assert "--confirm" in commands["upload"]["params"]
    assert "--confirm" in commands["publish"]["params"]
    assert "--confirm" in commands["delete"]["params"]
    assert "--yes" in commands["delete"]["params"]
    assert commands["topic-feeds"]["routes"] == ["/bbs/app/topic/feeds"]
    assert commands["topic-feeds"]["evidence_level"] != "historical_response_ok"


def test_read_only_commands_carry_live_command_evidence():
    catalog = load_catalog()
    probe = catalog["summary"]["command_live_probe"]
    assert probe["live_retested"] is True
    assert probe["commands_checked"] >= 10
    assert probe["commands_ok"] == probe["commands_checked"]
    assert probe["source"].endswith("probe-commands/probe-results.json")
    commands = {entry["name"]: entry for entry in catalog["commands"]}
    for name in ("posts", "drafts", "my-comments", "read", "comments",
                 "sub-comments", "topic-feeds", "hashtag-feed", "verify", "doctor"):
        entry = commands[name]
        assert entry["live_probe"]["ok"] is True, name
        assert entry["live_probe"]["exit_code"] == 0, name
        assert entry["evidence_level"] == "live_verified_read_only_command", name
        assert entry["historical_evidence_level"], name
    # Writes were never executed, so they must not carry command evidence.
    for name in ("upload", "publish", "delete", "comment", "reply",
                 "delete-comment", "favourite", "unfavourite", "canary"):
        assert "live_probe" not in commands[name], name


def test_catalog_lists_every_cli_parser_and_interaction_result_counts():
    catalog = load_catalog()
    tree = ast.parse((SDK / "xhh_sdk/cli.py").read_text(encoding="utf-8"))
    parsers = {node.args[0].value for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "add_parser" and node.args
               and isinstance(node.func.value, ast.Name) and node.func.value.id == "sub"
               and isinstance(node.args[0], ast.Constant)}
    assert {entry["name"].split()[0] for entry in catalog["commands"]} == parsers
    assert {entry["name"] for entry in catalog["commands"] if entry["name"].startswith("account ")} == {
        "account add", "account list", "account login", "account configure",
        "account status", "account logout", "account remove", "account risk-token"}
    assert catalog["summary"]["commands"] == 46
    assert {entry["name"] for entry in catalog["commands"] if entry["name"].startswith("signer ")} == {
        "signer bundle-inspect", "signer bundle-install", "signer inspect",
        "signer inspect-apk", "signer inspect-resources", "signer install",
        "signer prepare-apk", "signer selftest"}
    assert all(not entry["live_retested"] for entry in catalog["commands"]
               if entry["name"].startswith("signer "))
    assert catalog["summary"]["interaction_roundtrip"]["total"] == 28
    assert catalog["summary"]["interaction_roundtrip"]["passed"] == 28
    assert catalog["summary"]["interaction_roundtrip"]["failed"] == 0


def test_evidence_is_attributed_and_raw_responses_are_not_embedded():
    catalog = load_catalog()
    for entry in catalog["routes"]:
        assert entry["purpose_basis"] in {"report", "sdk", "static", "inferred"}
        assert entry["parameters_note"]
        assert entry["sources"]
        assert all(not Path(source).is_absolute() and "\\" not in source
                   for source in entry["sources"])
        assert "detail" not in entry
        assert "response" not in entry
        assert "msg" not in entry
    text = CATALOG.read_text(encoding="utf-8")
    assert "tmpSecretKey" not in text
    assert "sessionToken" not in text
    assert "pkey" not in text




def test_parameterised_pass_records_real_values_and_never_guesses():
    catalog = load_catalog()
    probe = catalog["summary"]["param_live_probe"]
    assert probe["live_retested"] is True
    assert probe["source"].endswith("probe-params/probe-results.json")
    assert probe["routes_called"] >= 85
    assert probe["routes_ok"] == probe["routes_called"]
    assert probe["routes_with_data"] >= 40
    # A later pass filled in values for most of the previously unmapped routes,
    # so only the obfuscated-name / no-data remainder stays unmapped.
    assert 0 < probe["routes_unmapped"] <= 8
    assert probe["value_basis"]["harvested"] > 0
    assert probe["value_basis"]["enum_probe"] > 0

    with_evidence = [r for r in catalog["routes"] if "live_param_probe" in r]
    assert len(with_evidence) >= 90
    for entry in with_evidence:
        evidence = entry["live_param_probe"]
        if evidence["outcome"] == "unmapped":
            # Unknown parameter names are listed, never invented.
            assert evidence["query_names"] == []
            assert evidence["unmapped"]
        elif evidence["outcome"] == "ok":
            assert evidence["query_names"]
            assert isinstance(evidence["result_nonempty"], bool)

    game_list = next(r for r in catalog["routes"] if r["route"] == "/account/game_list")
    assert game_list["live_param_probe"]["result_nonempty"] is True
    assert set(game_list["live_param_probe"]["query_names"]) == {"limit", "offset", "userid"}

    # Harvested identifiers and documented enum values are labelled separately.
    dota = next(r for r in catalog["routes"] if r["route"] == "/game/dota2/player/overview")
    assert dota["live_param_probe"]["outcome"] == "ok"
    assert dota["live_param_probe"]["value_basis"]["steam_id"] == "harvested"
    task = next(r for r in catalog["routes"] if r["route"] == "/task/shared")
    assert task["live_param_probe"]["outcome"] == "ok"
    assert set(task["live_param_probe"]["value_basis"].values()) == {"enum_probe"}

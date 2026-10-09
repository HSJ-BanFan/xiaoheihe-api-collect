"""Public research data must retain evidence boundaries and omit raw account data."""
import json
from collections import Counter
from pathlib import Path


RESEARCH = Path(__file__).resolve().parents[2] / "docs" / "research"


def load(name):
    return json.loads((RESEARCH / name).read_text(encoding="utf-8"))


def test_static_methods_do_not_default_unknown_routes_to_post():
    data = load("web-exact-methods.json")
    routes = data["routes"]
    assert set(routes) == set(load("web-endpoints.json"))
    assert len(routes) == 63
    assert sum(row["methods"] is not None for row in routes.values()) == 36
    assert sum(row["methods"] is None for row in routes.values()) == 27
    assert routes["/account/restore_login"]["methods"] == ["GET"]
    assert routes["/bbs/app/api/link/post"]["methods"] == ["POST"]
    assert routes["/bbs/app/link/tree/v2"]["methods"] is None
    assert data["source"]["bundle_sha256"] == "b30c3e28b15d69e57e918bd57b21803ce95e8cc5f83e9d33614ab8614d553a0a"
    assert data["complete_platform_inventory"] is False


def test_public_probe_batches_keep_distinct_results_and_unknown_causes():
    for filename, expected in [
        ("web-endpoints-test-report.json", {"ok": 11, "error": 42, "skipped_safe_write_guard": 10}),
        ("web-endpoints-verified.json", {"ok": 14, "error": 39, "skipped_safe_guard": 10}),
    ]:
        data = load(filename)
        assert dict(Counter(row["status"] for row in data["observations"])) == expected
        assert data["summary"] == expected
        assert data["live_retested_by_current_candidate"] is False
        for row in data["observations"]:
            assert "recorded_method" in row and "method" not in row
            assert row["cause_verified"] is False
            assert not {"error", "msg", "account_alias", "heybox_id", "pkey", "response"} & row.keys()


def test_public_endpoint_details_separate_method_evidence_from_signing_claim():
    methods = load("web-exact-methods.json")["routes"]
    details = load("web-endpoint-details.json")
    assert set(details["routes"]) == set(methods)
    for path, row in details["routes"].items():
        assert row["methods"] == methods[path]["methods"]
        assert row["signing_verified"] is False
        assert "signed" not in row

"""Offline extraction checks that do not need the research checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


CLI = Path(__file__).resolve().parents[1]


def test_help_names_historical_allowlist_without_side_effect_guarantee():
    result = subprocess.run(
        [sys.executable, "-B", "-m", "xhh_sdk.cli", "--help"],
        cwd=CLI, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "historical GET allowlist" in result.stdout
    assert "verified read-only route" not in result.stdout


def test_route_snapshot_check_works_without_case_inventory(tmp_path):
    package = tmp_path / "xhh_sdk"
    package.mkdir()
    for source in (CLI / "xhh_sdk").glob("*.py"):
        shutil.copyfile(source, package / source.name)
    shutil.copyfile(CLI / "xhh_sdk" / "api_catalog.json", package / "api_catalog.json")
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("XHH_", "PYTHON"))}
    result = subprocess.run(
        [sys.executable, "-B", "-m", "xhh_sdk.routes", "--check"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "snapshot integrity verified" in result.stdout


def test_release_builder_has_no_private_generation_dependencies():
    source = (CLI / "scripts" / "build_release.py").read_text(encoding="utf-8")
    assert "generate_catalog.py" not in source
    assert "render_live_report.py" not in source
    assert "case-2026-apk01" not in source


def test_catalog_does_not_expose_account_aliases_or_parameter_values():
    def inspect(value):
        if isinstance(value, dict):
            assert not {"account_alias", "query_values", "actual_values", "value", "values"} & value.keys()
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(json.loads((CLI / "xhh_sdk" / "api_catalog.json").read_text(encoding="utf-8")))


def test_catalog_tampering_fails_integrity_check(monkeypatch, tmp_path):
    from xhh_sdk import routes

    (tmp_path / "api_catalog.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes, "__file__", str(tmp_path / "routes.py"))
    with pytest.raises(ValueError, match="catalog snapshot SHA-256 mismatch"):
        routes.check_snapshot()


def test_route_gate_tampering_fails_integrity_check(monkeypatch):
    from xhh_sdk import routes

    monkeypatch.setattr(routes, "VERIFIED_READ_ROUTES", (*routes.VERIFIED_READ_ROUTES, "/fake"))
    with pytest.raises(ValueError, match="route allowlist SHA-256 mismatch"):
        routes.check_snapshot()


def test_private_regeneration_is_explicitly_unsupported(capsys):
    from xhh_sdk.routes import _main

    assert _main(["routes", "--generate"]) == 2
    assert "Private research regeneration is not included" in capsys.readouterr().err

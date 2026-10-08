"""Acceptance must reject successful processes that report failed predicates."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


@pytest.fixture
def verifier(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("installed_verifier", scripts / "verify_release_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_zero_exit_and_valid_json_do_not_hide_failed_predicates(verifier, value):
    checks = []
    proc = subprocess.CompletedProcess([], 0, json.dumps({"checks": {"installed": value}}), "")
    verifier.record_check(checks, "installed acceptance", proc, predicates=lambda data: data["checks"])
    assert checks[0]["passed"] is False
    assert checks[0]["predicates"] == {"installed": False}


@pytest.mark.parametrize("output", ['{}', '{"checks": {}}', '[]', 'not JSON'])
def test_missing_acceptance_evidence_fails_closed(verifier, output):
    checks = []
    proc = subprocess.CompletedProcess([], 0, output, "")
    verifier.record_check(checks, "installed acceptance", proc, predicates=lambda data: data["checks"])
    assert checks[0]["passed"] is False
    assert checks[0]["parse_error"]


def test_failed_command_cannot_pass_with_true_json_predicates(verifier):
    checks = []
    proc = subprocess.CompletedProcess([], 1, '{"checks":{"installed":true}}', "fixture failure")
    verifier.record_check(checks, "installed acceptance", proc, predicates=lambda data: data["checks"])
    assert checks[0]["passed"] is False
    assert checks[0]["predicates"] == {"installed": True}


def test_expected_version_comes_from_wheel_metadata(verifier, tmp_path):
    wheel = tmp_path / "unrelated-filename.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("xhh_sdk-9.2rc3.dist-info/METADATA", "Name: xhh-sdk\nVersion: 9.2rc3+fixture.7\n")
    assert verifier.wheel_version(wheel) == "9.2rc3+fixture.7"


def test_offline_guard_blocks_child_and_connection_before_side_effects(verifier, tmp_path):
    log = tmp_path / "blocked.txt"
    child = tmp_path / "child-ran.txt"
    code = "\n".join([
        "import os, socket, subprocess, sys",
        f"exec({verifier.OFFLINE_GUARD!r})",
        "blocked = 0",
        "try:",
        f"    subprocess.Popen([sys.executable, '-c', {('from pathlib import Path; Path(' + repr(str(child)) + ').write_text("unexpected")')!r}])",
        "except RuntimeError:",
        "    blocked += 1",
        "try:",
        "    socket.socket().connect(('127.0.0.1', 9))",
        "except RuntimeError:",
        "    blocked += 1",
        "assert blocked == 2",
    ])
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("XHH_", "PYTHON"))}
    env["XHH_VERIFY_GUARD_LOG"] = str(log)
    proc = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                          env=env, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    assert log.read_text(encoding="ascii").splitlines() == ["subprocess.Popen", "socket.connect"]
    assert not child.exists()

import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assemble_local_release.py"
SPEC = importlib.util.spec_from_file_location("assemble_local_release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def make_inputs(tmp_path):
    wheel = tmp_path / "xhh_sdk-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("xhh_sdk/__init__.py", "__version__ = '1.0'\n")
    sdist = tmp_path / "xhh_sdk-1.0.tar.gz"
    source = tmp_path / "pyproject.toml"
    source.write_text("[project]\nname='xhh-sdk'\n", encoding="utf-8")
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(source, arcname="xhh_sdk-1.0/pyproject.toml")
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({
        "release_ready": True,
        "local_steps_passed": True,
        "live": {"valid": True},
        "rights": {"valid": True},
        "open_items": [],
        "steps": [{"name": "wheel-matches-source", "status": "passed"}],
        "artifacts": {"wheel": {"sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}},
    }), encoding="utf-8")
    return wheel, sdist, gate


def test_assembles_only_a_hash_bound_ready_candidate(tmp_path):
    wheel, sdist, gate = make_inputs(tmp_path)
    out = tmp_path / "release"
    result = release.assemble(wheel, sdist, gate, out)
    assert result["release_ready"] is True
    assert sorted(path.name for path in out.iterdir()) == [
        "README.md", "SHA256SUMS", "release-audit.json",
        wheel.name, sdist.name]
    assert not list(out.glob("*.jar"))
    assert "local release gate passed" in (out / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("change", ["release_ready", "blocker", "wheel_hash"])
def test_refuses_unready_or_unbound_gate_reports(tmp_path, change):
    wheel, sdist, gate = make_inputs(tmp_path)
    report = json.loads(gate.read_text(encoding="utf-8"))
    if change == "release_ready":
        report["release_ready"] = False
    elif change == "blocker":
        report["open_items"] = [{"item": "rights", "blocking": True}]
    else:
        report["artifacts"]["wheel"]["sha256"] = "0" * 64
    gate.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        release.assemble(wheel, sdist, gate, tmp_path / "release")
    assert not (tmp_path / "release").exists()

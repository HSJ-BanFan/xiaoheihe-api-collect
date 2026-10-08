"""Assemble a clean wheel and sdist directory from a passing gate report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "cli" / "scripts" / "build_release.py"


def _archive_auditor():
    spec = importlib.util.spec_from_file_location("xhh_build_release", BUILD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the archive auditor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit_archive


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_gate(report: object, wheel: Path) -> dict:
    if not isinstance(report, dict):
        raise ValueError("gate report is not an object")
    if report.get("release_ready") is not True:
        raise ValueError("gate report does not say release_ready")
    if report.get("local_steps_passed") is not True:
        raise ValueError("local gate steps did not pass")
    if not isinstance(report.get("live"), dict) or report["live"].get("valid") is not True:
        raise ValueError("live evidence did not validate")
    if not isinstance(report.get("rights"), dict) or report["rights"].get("valid") is not True:
        raise ValueError("rights review did not validate")
    items = report.get("open_items")
    if not isinstance(items, list) or any(
            not isinstance(item, dict) or item.get("blocking") is not False
            for item in items):
        raise ValueError("gate report contains an open or malformed item")
    steps = report.get("steps")
    if not isinstance(steps, list) or not steps or any(
            not isinstance(step, dict) or step.get("status") != "passed"
            for step in steps):
        raise ValueError("one or more local gate steps did not pass")
    if not any(step.get("name") == "wheel-matches-source" for step in steps):
        raise ValueError("gate report does not prove the wheel matches its source")
    wheel_record = (report.get("artifacts") or {}).get("wheel")
    if not isinstance(wheel_record, dict) or wheel_record.get("sha256") != _sha256(wheel):
        raise ValueError("gate report is not bound to the supplied wheel")
    return report


def assemble(wheel: Path, sdist: Path, gate_report: Path, out: Path) -> dict:
    wheel, sdist, gate_report, out = (
        Path(wheel).resolve(), Path(sdist).resolve(),
        Path(gate_report).resolve(), Path(out).resolve())
    for path, label in ((wheel, "wheel"), (sdist, "source archive"), (gate_report, "gate report")):
        if not path.is_file():
            raise ValueError(f"{label} is missing")
    if not wheel.name.endswith("-py3-none-any.whl"):
        raise ValueError("wheel filename must use the py3-none-any tag")
    expected_sdist = wheel.name.removesuffix("-py3-none-any.whl") + ".tar.gz"
    if sdist.name != expected_sdist:
        raise ValueError("wheel and source archive versions do not match")
    if out.exists():
        raise ValueError("output directory already exists")

    report = _validate_gate(json.loads(gate_report.read_text(encoding="utf-8")), wheel)
    audit_archive = _archive_auditor()
    wheel_audit = audit_archive(wheel)
    sdist_audit = audit_archive(sdist)
    if wheel_audit["binary_count"] or sdist_audit["binary_count"]:
        raise ValueError("release archives contain a prohibited binary")

    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".release-stage-", dir=out.parent))
    try:
        staged_wheel = stage / wheel.name
        staged_sdist = stage / sdist.name
        shutil.copy2(wheel, staged_wheel)
        shutil.copy2(sdist, staged_sdist)
        artifacts = [wheel_audit, sdist_audit]
        (stage / "SHA256SUMS").write_text(
            "".join(f"{item['sha256']}  {item['file']}\n" for item in artifacts),
            encoding="ascii")
        version = wheel.name.removesuffix("-py3-none-any.whl").removeprefix("xhh_sdk-")
        summary = {
            "format_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "release_ready": True,
            "local_steps_passed": True,
            "live_evidence_valid": True,
            "rights_review_valid": True,
            "blocking_open_items": 0,
            "gate_steps": len(report["steps"]),
            "artifacts": artifacts,
            "excluded": ["APK", "JAR", "SO", "account store", "browser profile",
                         "raw live evidence"],
        }
        (stage / "release-audit.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (stage / "README.md").write_text(
            f"# xhh-sdk {version} local release bundle\n\n"
            "This directory contains the Python wheel, source archive, SHA256SUMS "
            "and a sanitized gate summary. The local release gate passed. Raw "
            "live evidence and user-owned signing files are not included.\n",
            encoding="utf-8")
        stage.rename(out)
    except Exception:
        if stage.exists() and stage.parent == out.parent and stage.name.startswith(".release-stage-"):
            shutil.rmtree(stage)
        raise
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--gate-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(assemble(args.wheel, args.sdist, args.gate_report, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

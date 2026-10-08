"""Run package checks and combine them with recorded release evidence.

The gate binds every result to artifact hashes. Live requests are not made by
this script. A recent, hash-bound live record and rights review are inputs.

Usage:
    python scripts/release_gate.py --wheel <whl> --apk <supported.apk> \
        --loader <loader.jar> --out <new-dir>
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release  # noqa: E402  (sibling module)
import gate_evidence  # noqa: E402  (sibling module)

EXPECTED_SIGNATURE = {"hkey": "FC0EAF1B", "_rnd": "14:E94DBC87"}
TEST_IDENTITY = "123"
TEST_IMEI = "0123456789abcdef"
TEST_DEVICE = "25102RKBEC"
REPOSITORY = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class Gate:
    def __init__(self, work: Path, env_extra: dict):
        self.work = work
        self.env_extra = env_extra
        self.steps = []

    def run(self, name, command, *, env=None, cwd=None, required=True, parse=None,
            timeout=900):
        environment = dict(os.environ)
        environment.update(self.env_extra)
        environment.update(env or {})
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run([str(part) for part in command], capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, env=environment, cwd=cwd)
        detail = {"exit_code": result.returncode}
        if parse is not None:
            try:
                detail["parsed"] = parse(result)
            except Exception as error:  # noqa: BLE001 - reported, not raised
                detail["parse_error"] = str(error)
        ok = result.returncode == 0 and "parse_error" not in detail
        if not ok:
            detail["stderr_tail"] = result.stderr.strip()[-400:]
        self.steps.append({"name": name, "status": "passed" if ok else "failed",
                           "command": " ".join(str(part) for part in command),
                           "detail": detail})
        if required and not ok:
            raise SystemExit(f"gate step failed: {name}")
        return detail


def parse_json(result):
    return json.loads(result.stdout)


def loader_choice(args) -> str:
    """Exactly one loader source: a supplied JAR or a build inside the gate."""
    if bool(args.loader) == bool(args.build_loader):
        raise SystemExit("pass exactly one of --loader or --build-loader")
    if args.prepare_deps and not args.build_loader:
        raise SystemExit("--prepare-deps only applies together with --build-loader")
    if args.prepare_deps and args.loader_repo:
        raise SystemExit("--prepare-deps builds its own repository; drop --loader-repo")
    if args.build_loader and not (args.loader_repo or args.prepare_deps):
        raise SystemExit("--build-loader needs --loader-repo (the repository built by signer/scripts/prepare_unidbg.py)")
    return "supplied" if args.loader else "built"


def live_status(evidence_path, binding: dict, template_path: Path) -> dict:
    """Summarise the live half: no record, an invalid record, or a usable one."""
    if evidence_path is None:
        return {"provided": False, "valid": False,
                "problems": ["no live evidence recorded"], "template": str(template_path)}
    try:
        record = gate_evidence.load(evidence_path)
        problems = gate_evidence.validate(record, binding, evidence_path=evidence_path)
    except Exception:  # noqa: BLE001 - keep paths and parser details out of the report
        problems = ["live_evidence.read: evidence could not be read"]
    return {"provided": True, "path": str(evidence_path),
            "valid": not problems, "problems": problems}


def build_open_items(local_passed: bool, live: dict, rights: dict) -> list[dict]:
    """Derive every blocking item from the three release-gate results."""
    items = []
    if not local_passed:
        items.append({"item": "local package checks", "state": "blocked", "blocking": True,
                      "reason": "local package checks did not all pass"})
    if not live.get("valid"):
        reason = ("live evidence is missing"
                  if not live.get("provided")
                  else "live evidence is invalid; inspect the recorded problem codes")
        items.extend([
            {"item": "fresh login", "state": "blocked", "blocking": True, "reason": reason},
            {"item": "online functional parity", "state": "blocked", "blocking": True,
             "reason": reason},
        ])
    if not rights.get("valid"):
        reason = ("rights review is missing"
                  if not rights.get("provided")
                  else "rights review is invalid; inspect the recorded problems")
        items.append({"item": "rights and licence review", "state": "blocked",
                      "blocking": True, "reason": reason})
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True, help="supported APK sample")
    parser.add_argument("--loader", type=Path, help="loader JAR built from source")
    parser.add_argument("--build-loader", action="store_true",
                        help="build signer/ inside the gate instead of taking a JAR")
    parser.add_argument("--loader-repo", type=Path,
                        help="Maven repository holding the pinned unidbg build")
    parser.add_argument("--prepare-deps", action="store_true",
                        help="clone and build the pinned public unidbg commit inside the gate")
    parser.add_argument("--maven", default="mvn")
    parser.add_argument("--out", type=Path, required=True, help="new working directory")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--identity", default=TEST_IDENTITY)
    parser.add_argument("--imei", default=TEST_IMEI)
    parser.add_argument("--device-info", default=TEST_DEVICE)
    parser.add_argument("--live-evidence", type=Path,
                        help="record of the authorized live run; without it the gate stays closed")
    parser.add_argument("--rights-review", type=Path,
                        help="record of the licence and ownership decision; distribution gate")
    parser.add_argument("--require-release-ready", action="store_true",
                        help="exit non-zero unless the record also clears the live half")
    args = parser.parse_args(argv)

    mode = loader_choice(args)
    work = args.out.resolve()
    work.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    inputs_to_hash = [("wheel", args.wheel), ("apk", args.apk)]
    if mode == "supplied":
        inputs_to_hash.append(("loader", args.loader))
    for name, path in inputs_to_hash:
        if not path.is_file():
            raise SystemExit(f"missing {name}: {path}")
        artifacts[name] = {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}

    wheel = args.wheel.resolve()
    audit = build_release.audit_archive(wheel)
    if audit["binary_count"]:
        raise SystemExit("wheel contains binary members; refusing to continue")

    # Work on copies so the caller's inputs are never moved or modified.
    inputs = work / "inputs"
    inputs.mkdir()
    apk = inputs / "supported.apk"
    loader = inputs / "loader.jar"
    shutil.copy2(args.apk, apk)
    bundle_home = work / "bundles"
    gate_env = {"XHH_BUNDLE_HOME": str(bundle_home)}
    gate = Gate(work, gate_env)
    gate.steps.append({"name": "wheel-audit", "status": "passed",
                       "command": f"audit_archive({wheel.name})",
                       "detail": {"files": audit["files"], "binary_count": audit["binary_count"],
                                  "sha256": audit["sha256"], "bytes": audit["bytes"]}})
    failure = None
    try:
        if mode == "supplied":
            shutil.copy2(args.loader, loader)
        else:
            if args.prepare_deps:
                prepare_dependencies(gate, work, args)
            build_loader(gate, loader, args)
        artifacts["loader"] = {"path": str(loader), "sha256": sha256(loader),
                               "bytes": loader.stat().st_size, "built_in_gate": mode == "built"}
        loader_digest = sha256(loader)
        env = work / "venv"
        venv.EnvBuilder(with_pip=True).create(env)
        python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = env / ("Scripts/xhh-sdk.exe" if os.name == "nt" else "bin/xhh-sdk")
        run_local_steps(gate, work, python, cli, wheel, apk, loader, loader_digest,
                        args, gate_env)
    except (SystemExit, OSError, ValueError, RuntimeError, KeyError) as error:
        failure = str(error)
    local_passed = failure is None and all(step["status"] == "passed" for step in gate.steps)
    binding = {"wheel_sha256": artifacts["wheel"]["sha256"],
               "loader_sha256": artifacts.get("loader", {}).get("sha256", ""),
               "apk_sha256": artifacts["apk"]["sha256"]}
    template_path = work / "live-evidence-template.json"
    template_path.write_text(json.dumps(gate_evidence.template(binding), indent=2) + "\n",
                             encoding="utf-8")
    rights_template_path = work / "rights-review-template.json"
    rights_template_path.write_text(
        json.dumps(gate_evidence.rights_template(), indent=2) + "\n", encoding="utf-8")
    live = live_status(args.live_evidence, binding, template_path)
    if args.rights_review:
        try:
            rights_problems = gate_evidence.validate_rights(
                gate_evidence.load(args.rights_review), repository=REPOSITORY)
        except Exception:  # noqa: BLE001 - keep paths and parser details out of the report
            rights_problems = ["rights_review.read: review could not be read"]
        rights = {"provided": True, "path": str(args.rights_review),
                  "valid": not rights_problems, "problems": rights_problems}
        if rights["valid"]:
            rights["assets_checked"] = len(gate_evidence.find_assets(REPOSITORY))
    else:
        rights = {"provided": False, "valid": False,
                  "problems": ["no rights review recorded"],
                  "template": str(rights_template_path)}
    open_items = build_open_items(local_passed, live, rights)
    report = {
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
        "artifacts": artifacts,
        "expected_signature": EXPECTED_SIGNATURE,
        "local_steps_passed": local_passed,
        "failure": failure,
        "steps": gate.steps,
        "live": live,
        "rights": rights,
        "open_items": open_items,
        "release_ready": bool(local_passed and live["valid"] and rights["valid"]
                               and not any(item["blocking"] for item in open_items)),
        "claim": ("local build and signing steps, the recorded live acceptance, and the "
                  "recorded licence decision; release_ready requires all three"),
    }
    (work / "release-gate.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"local_steps_passed": local_passed, "steps": len(gate.steps),
                      "failure": failure, "live_valid": live["valid"],
                      "live_problems": live["problems"][:4],
                      "rights_valid": rights["valid"],
                      "rights_problems": rights["problems"][:4],
                      "open_items": len(open_items),
                      "release_ready": report["release_ready"],
                      "report": str(work / "release-gate.json")}, indent=2))
    if not local_passed:
        return 1
    return 0 if (report["release_ready"] or not args.require_release_ready) else 2


def run_local_steps(gate, work, python, cli, wheel, apk, loader, loader_digest, args, gate_env):
    verify_wheel_matches_source(gate, wheel)
    gate.run("isolated-install", [python, "-m", "pip", "install", "--no-index",
                                  "--no-deps", wheel])
    gate.run("installed-module", [python, "-c",
              "import importlib.metadata as m, xhh_sdk; print(m.version('xhh-sdk'))"])
    apk_report = gate.run("inspect-apk", [cli, "signer", "inspect-apk", apk], parse=parse_json)
    if not apk_report["parsed"].get("supported"):
        raise SystemExit("the supplied APK is not the supported sample for this release")
    gate.run("catalog-offline", [cli, "catalog", "--json", "--route", "/account/info"],
             parse=parse_json)
    prepared = work / "resources"
    gate.run("prepare-apk", [cli, "signer", "prepare-apk", apk,
                             "--out", prepared, "--confirm"], parse=parse_json)
    installed = gate.run("bundle-install", [cli, "signer", "bundle-install",
                                            "--resources", prepared, "--loader", loader,
                                            "--loader-sha256", loader_digest, "--confirm"],
                         parse=parse_json)
    reference = installed["parsed"]["reference"]
    gate.run("bundle-inspect", [cli, "signer", "bundle-inspect", reference], parse=parse_json)
    config = work / "gate-config.json"
    config.write_text(json.dumps({
        "pkey": "<synthetic-session>", "heybox_id": args.identity, "imei": args.imei,
        "device_info": args.device_info, "app_version": "1.3.385", "os_version": "14",
        "signer_bundle": reference}), encoding="utf-8")
    doctor = gate.run("doctor-offline", [cli, "--config", config, "doctor", "--offline"],
                      parse=parse_json)
    if not doctor["parsed"].get("signer_ready"):
        raise SystemExit("offline doctor reported the bundle as not ready")

    def selftest():
        return gate.run("selftest", [cli, "signer", "selftest", reference,
                                     "--identity", args.identity, "--imei", args.imei,
                                     "--device-info", args.device_info], parse=parse_json)

    produced = selftest()["parsed"]
    signature = produced.get("signature", {})
    matches = all(signature.get(key) == value for key, value in EXPECTED_SIGNATURE.items())
    gate.steps[-1]["detail"]["expected"] = EXPECTED_SIGNATURE
    gate.steps[-1]["detail"]["actual"] = signature
    if not matches:
        gate.steps[-1]["status"] = "failed"
        raise SystemExit("self-test signature does not match the reference values")

    # The bundle must stand alone: move the prepared inputs away and re-run.
    inputs = work / "inputs"
    moved = work / "inputs-moved"
    inputs.rename(moved)
    gate.run("selftest-after-inputs-moved",
             [cli, "signer", "selftest", reference, "--identity", args.identity,
              "--imei", args.imei, "--device-info", args.device_info], parse=parse_json)
    moved.rename(inputs)



def verify_wheel_matches_source(gate, wheel):
    """Refuse a wheel that was built before the current sources changed.

    The metadata long description is the package README. Comparing it here turns
    a documentation edit into a named failure instead of a live-evidence digest
    mismatch that looks like a broken live record.
    """
    package = Path(__file__).resolve().parents[1]
    source_sdk = package / "xhh_sdk"
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        members = {name: archive.read(name) for name in names if name.startswith("xhh_sdk/")}
        metadata = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
        embedded_readme = (_metadata_body(archive.read(metadata).decode("utf-8"))
                           if metadata else None)
    stale = []
    for name, content in sorted(members.items()):
        source = source_sdk / name.split("/", 1)[1]
        if not source.is_file() or source.read_bytes() != content:
            stale.append(name)
    current_readme = (package / "README.md").read_text(encoding="utf-8")
    readme_matches = embedded_readme is not None and embedded_readme == _normalized(current_readme)
    gate.steps.append({
        "name": "wheel-matches-source",
        "status": "passed" if not stale and readme_matches else "failed",
        "command": f"compare {len(members)} wheel members against cli/xhh_sdk",
        "detail": {"compared": len(members), "stale": stale,
                   "readme_matches_source": readme_matches},
    })
    if stale:
        raise SystemExit("wheel does not match the current sources: " + ", ".join(stale))
    if not readme_matches:
        raise SystemExit("the wheel embeds a different cli/README.md; "
                         "rebuild the release wheel after editing it")


def _metadata_body(metadata: str) -> str:
    lines = _normalized(metadata).splitlines()
    for index, line in enumerate(lines):
        if not line:
            return _normalized("\n".join(lines[index + 1:]))
    return ""


def _normalized(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def build_loader(gate, destination: Path, args) -> None:
    """Build signer/ from the shipped sources and publish that JAR for the gate."""
    signer_dir = Path(__file__).resolve().parents[2] / "signer"
    pom = signer_dir / "pom.xml"
    if not pom.is_file():
        raise SystemExit(f"signer project not found: {signer_dir}")
    repo = loader_repository(args)
    # Not offline: a freshly prepared repository still needs the Maven plugins.
    gate.run("loader-build", [args.maven, "-B",
                              f"-Dmaven.repo.local={repo}",
                              "-f", pom, "clean", "package"])
    built = signer_dir / "target" / "xhh-signer-loader.jar"
    if not built.is_file():
        raise SystemExit(f"loader build produced no artifact: {built}")
    shutil.copy2(built, destination)
    gate.steps[-1]["detail"]["artifact_sha256"] = sha256(destination)


def loader_repository(args) -> Path:
    """Where the pinned unidbg build lives: prepared in-gate or supplied."""
    if args.prepare_deps:
        return (args.out.resolve() / "maven-repo").resolve()
    return args.loader_repo.resolve()


def prepare_dependencies(gate, work: Path, args) -> None:
    """Clone and build the pinned public unidbg commit inside the gate."""
    signer_dir = Path(__file__).resolve().parents[2] / "signer"
    script = signer_dir / "scripts" / "prepare_unidbg.py"
    if not script.is_file():
        raise SystemExit(f"dependency preparation script not found: {script}")
    source = work / "unidbg-src"
    repo = work / "maven-repo"
    gate.run("dependency-prepare",
             [sys.executable, "-B", script, "--work", source, "--repo", repo,
              "--maven", args.maven],
             timeout=3600)
    gate.steps[-1]["detail"]["commit"] = "2ded0545d4ae053055f469ef4a4c49e3f15196a7"

if __name__ == "__main__":
    sys.exit(main())

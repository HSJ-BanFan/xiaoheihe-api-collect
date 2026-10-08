"""Build a JAR-free candidate from an explicit source allowlist. Never publish."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

SDK = Path(__file__).resolve().parents[1]
MODULES = (
    "__init__.py", "accounts.py", "browse.py", "catalog.py", "cli.py",
    "client.py", "config.py", "exceptions.py", "groups.py", "interaction.py",
    "login.py", "payload.py", "routes.py", "secure_phone.py", "signer.py",
    "transport.py", "signer_resources.py", "signer_bundle.py",
)
PACKAGE_FILES = (*MODULES, "api_catalog.json")
SOURCE_FILES = ("pyproject.toml", "README.md", "RELEASE.md", "MANIFEST.in", "LICENSE")
BINARY = {".jar", ".apk", ".so", ".dll", ".exe", ".class", ".key", ".pem", ".pyc"}
SECRET = re.compile(
    r'''["']?(?:pkey|x_pkey|password|secret_key|api_token)["']?\s*[:=]\s*["']([^"'\r\n]+)["']''',
    re.IGNORECASE)


def audit_archive(path: Path) -> dict:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if archive.testzip():
                raise ValueError("archive CRC failure")
            entries = [(n, archive.read(n)) for n in archive.namelist() if not n.endswith("/")]
    else:
        with tarfile.open(path, "r:gz") as archive:
            if any(not (m.isfile() or m.isdir()) for m in archive.getmembers()):
                raise ValueError("links or special archive members forbidden")
            entries = [(m.name, archive.extractfile(m).read()) for m in archive.getmembers() if m.isfile()]
    for name, content in entries:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
            raise ValueError(f"unsafe archive member: {name}")
        if p.suffix.lower() in BINARY or any(part.lower() in {"vendor", "samples", "working", ".git", "profiles"} for part in p.parts):
            raise ValueError(f"binary or case asset forbidden: {name}")
        if p.name.lower() in {"config.json", "accounts.json", ".env", "cookies.txt", "cookies", "local.key"}:
            raise ValueError(f"credential file forbidden: {name}")
        parts = p.parts
        if path.name.endswith(".tar.gz"):
            parts = parts[1:]
        permitted = (
            len(parts) == 2 and parts[0] == "xhh_sdk" and parts[1] in PACKAGE_FILES
            or len(parts) == 1 and parts[0] in (*SOURCE_FILES, "PKG-INFO", "setup.cfg")
            or len(parts) == 2 and parts[0].endswith((".dist-info", ".egg-info"))
            and parts[1] in {"METADATA", "WHEEL", "RECORD", "entry_points.txt",
                            "top_level.txt", "PKG-INFO", "SOURCES.txt",
                            "dependency_links.txt", "requires.txt"}
            # setuptools ships the project licence under dist-info/licenses/.
            or len(parts) == 3 and parts[0].endswith((".dist-info", ".egg-info"))
            and parts[1] == "licenses" and parts[2] in {"LICENSE", "LICENSE.txt", "COPYING"}
        )
        if not permitted:
            raise ValueError(f"archive member not in source allowlist: {name}")
        text = content.decode("utf-8", errors="strict")
        for match in SECRET.finditer(text):
            value = match.group(1)
            if not (value.startswith("<") and value.endswith(">")):
                raise ValueError(f"possible literal credential in {name}; value suppressed")
    return {"file": path.name, "files": len(entries), "binary_count": 0,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
            "credential_scan": "heuristic_pass_not_a_security_guarantee"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(SDK))
    from xhh_sdk.routes import check_snapshot
    snapshot = check_snapshot()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stage = Path(tempfile.mkdtemp(prefix="source-", dir=out))
    try:
        (stage / "xhh_sdk").mkdir()
        for name in SOURCE_FILES:
            shutil.copy2(SDK / name, stage / name)
        for name in PACKAGE_FILES:
            shutil.copy2(SDK / "xhh_sdk" / name, stage / "xhh_sdk" / name)
        uv = shutil.which("uv")
        if not uv:
            raise SystemExit("uv is required; no tools were installed")
        subprocess.run([uv, "build", str(stage), "--out-dir", str(out), "--offline"], check=True)
    finally:
        if stage.resolve().parent != out or not stage.name.startswith("source-"):
            raise ValueError("refusing cleanup outside release staging directory")
        shutil.rmtree(stage, ignore_errors=True)
    packages = sorted([*out.glob("*.whl"), *out.glob("*.tar.gz")])
    if len(packages) != 2:
        raise ValueError("expected one wheel and one sdist")
    records = [audit_archive(p) for p in packages]
    report = {"status": "local_candidate_only", "public_publish_ready": False,
              "blockers": ["source license and ownership review before public redistribution",
                           "no online acceptance performed for this extracted project"],
              "snapshot": snapshot,
              "jar_bundled": False, "artifacts": records}
    (out / "release-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {r['file']}\n" for r in records), encoding="ascii")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

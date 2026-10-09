"""Build a JAR-free candidate from an explicit source allowlist. Never publish."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

SDK = Path(__file__).resolve().parents[1]
SOURCE_DATE_EPOCH = 946684800
SETUPTOOLS_VERSION = "84.0.0"
UV_VERSION = "0.12.7"
MODULES = (
    "__init__.py", "accounts.py", "browse.py", "catalog.py", "cli.py",
    "client.py", "config.py", "exceptions.py", "groups.py", "interaction.py",
    "login.py", "payload.py", "routes.py", "secure_phone.py", "signer.py",
    "transport.py", "signer_resources.py", "signer_bundle.py", "web_signer.py",
)
PACKAGE_FILES = (*MODULES, "api_catalog.json")
SOURCE_FILES = ("pyproject.toml", "README.md", "RELEASE.md", "MANIFEST.in", "LICENSE")
BINARY = {".jar", ".apk", ".so", ".dll", ".exe", ".class", ".key", ".pem", ".pyc"}
SECRET = re.compile(
    r'''["']?(?:pkey|x_pkey|password|secret_key|api_token)["']?\s*[:=]\s*["']([^"'\r\n]+)["']''',
    re.IGNORECASE)


def audit_archive(path: Path) -> dict:
    directories = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if any(member.is_dir() for member in members):
                raise ValueError("explicit ZIP directories forbidden")
            if archive.testzip():
                raise ValueError("archive CRC failure")
            entries = [(member.filename, archive.read(member)) for member in members]
            names = [member.filename for member in members]
    else:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if any(not (m.isfile() or m.isdir()) for m in members):
                raise ValueError("links or special archive members forbidden")
            directories = [member.name for member in members if member.isdir()]
            if any(member.isdir() and member.size for member in members):
                raise ValueError("archive directory payload forbidden")
            entries = [(m.name, archive.extractfile(m).read()) for m in members if m.isfile()]
            names = [member.name.rstrip("/") for member in members]
    if len(set(names)) != len(names):
        raise ValueError("duplicate archive members forbidden")
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
    parents = {str(parent) for name, _ in entries for parent in PurePosixPath(name).parents
               if str(parent) != "."}
    for name in directories:
        normalized = name.rstrip("/")
        directory = PurePosixPath(normalized)
        if (directory.is_absolute() or ".." in directory.parts or "\\" in name or ":" in name
                or normalized != str(directory) or normalized not in parents):
            raise ValueError(f"unsafe or unlisted archive directory: {name}")
    return {"file": path.name, "files": len(entries), "binary_count": 0,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
            "credential_scan": "heuristic_pass_not_a_security_guarantee"}


def _lf_bytes(content: bytes) -> bytes:
    return content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def stage_source(source: Path, stage: Path) -> None:
    """Copy the text allowlist, independent of checkout line endings and mtimes."""
    (stage / "xhh_sdk").mkdir(parents=True)
    for name in (*SOURCE_FILES, *("xhh_sdk/" + name for name in PACKAGE_FILES)):
        target = stage / name
        target.write_bytes(_lf_bytes((source / name).read_bytes()))
        os.utime(target, (SOURCE_DATE_EPOCH, SOURCE_DATE_EPOCH))


def canonicalize_wheel(path: Path) -> None:
    """Canonicalize text and RECORD; stored ZIP entries avoid zlib-version drift."""
    audit_archive(path)
    with zipfile.ZipFile(path) as archive:
        entries = {name: _lf_bytes(archive.read(name))
                   for name in archive.namelist()}
    records = [name for name in entries if name.endswith(".dist-info/RECORD")]
    if len(records) != 1:
        raise ValueError("expected exactly one wheel RECORD")
    record = records[0]
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    for name in sorted(entries):
        content = entries[name]
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
        writer.writerow((name, "", "") if name == record else (name, "sha256=" + digest, len(content)))
    entries[record] = text.getvalue().encode("utf-8")
    canonical = io.BytesIO()
    with zipfile.ZipFile(canonical, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content)
    path.write_bytes(canonical.getvalue())
    audit_archive(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stage = Path(tempfile.mkdtemp(prefix="source-", dir=out))
    try:
        stage_source(SDK, stage)
        snapshot_probe = subprocess.run(
            [sys.executable, "-I", "-B", "-c",
             "import json,sys; sys.path.insert(0,sys.argv[1]); "
             "from xhh_sdk.routes import check_snapshot; print(json.dumps(check_snapshot()))",
             str(stage)], check=True, capture_output=True, text=True)
        snapshot = json.loads(snapshot_probe.stdout)
        uv = shutil.which("uv")
        if not uv:
            raise SystemExit("uv is required; no tools were installed")
        version = subprocess.run([uv, "--version"], check=True, capture_output=True, text=True).stdout.split()
        if len(version) < 2 or version[1] != UV_VERSION:
            raise SystemExit(f"uv {UV_VERSION} is required for the canonical build; no tools were installed")
        constraints = out / "build-constraints.txt"
        constraints.write_bytes(f"setuptools=={SETUPTOOLS_VERSION}\n".encode("ascii"))
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(("UV_", "PIP_", "PYTHON"))}
        environment.update(SOURCE_DATE_EPOCH=str(SOURCE_DATE_EPOCH),
                           PYTHONHASHSEED="0", UV_OFFLINE="1")
        subprocess.run([uv, "build", str(stage), "--out-dir", str(out), "--offline",
                        "--python", sys.executable, "--no-python-downloads",
                        "--build-constraints", str(constraints)], check=True, env=environment)
    finally:
        if stage.resolve().parent != out or not stage.name.startswith("source-"):
            raise ValueError("refusing cleanup outside release staging directory")
        shutil.rmtree(stage, ignore_errors=True)
    packages = sorted([*out.glob("*.whl"), *out.glob("*.tar.gz")])
    if len(packages) != 2:
        raise ValueError("expected one wheel and one sdist")
    wheel = next(path for path in packages if path.suffix == ".whl")
    with zipfile.ZipFile(wheel) as archive:
        wheel_metadata = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
        if len(wheel_metadata) != 1 or f"Generator: setuptools ({SETUPTOOLS_VERSION})" not in archive.read(wheel_metadata[0]).decode():
            raise ValueError("wheel was not generated by the pinned setuptools backend")
    canonicalize_wheel(wheel)
    records = [audit_archive(p) for p in packages]
    # This script only builds: publishability is decided by the release gate
    # record bound to these bytes, never by the build report.
    report = {"status": "local_build_only", "public_publish_ready": False,
              "blockers": ["a release gate record bound to this wheel, covering the local "
                           "steps, the live acceptance and the rights review"],
              "snapshot": snapshot,
              "canonical_wheel": {"uv": UV_VERSION, "setuptools": SETUPTOOLS_VERSION,
                                  "wheel_backend": "setuptools built-in bdist_wheel",
                                  "source_date_epoch": SOURCE_DATE_EPOCH,
                                  "line_endings": "LF", "zip_compression": "stored",
                                  "member_order": "lexicographic", "member_mode": "unix-100644"},
              "sdist_reproducibility_claimed": False,
              "jar_bundled": False, "artifacts": records}
    (out / "release-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {r['file']}\n" for r in records), encoding="ascii")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

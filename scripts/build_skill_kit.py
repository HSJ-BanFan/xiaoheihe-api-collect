"""Build a portable App/Web publisher kit from the exact pinned wheel, offline."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skill-kit" / "xiaoheihe-publisher"


def build(wheel: Path, out: Path) -> Path:
    module_spec = importlib.util.spec_from_file_location("kit_definition", SOURCE / "scripts" / "xhh_cli.py")
    kit = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(kit)
    if out.exists() or out.is_symlink():
        raise ValueError("output must not exist")
    raw = wheel.read_bytes()
    if kit.digest(raw) != kit.WHEEL_SHA256:
        raise ValueError("wheel digest does not match the pinned CLI release")
    actual = {p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*") if p.is_file()}
    if actual != set(kit.SOURCE_MEMBERS) or any(p.is_symlink() for p in SOURCE.rglob("*")):
        raise ValueError("unknown or missing source member")
    members = {name: (SOURCE / name).read_bytes() for name in kit.SOURCE_MEMBERS}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.namelist()) != len(kit.RUNTIME_MEMBERS) or set(archive.namelist()) != set(kit.RUNTIME_MEMBERS):
            raise ValueError("unknown or missing runtime member")
        members.update({"runtime/" + name: archive.read(name) for name in kit.RUNTIME_MEMBERS})
    manifest = {
        "schema_version": 1, "kit_name": kit.KIT_NAME, "kit_version": kit.KIT_VERSION,
        "cli_version": kit.CLI_VERSION, "wheel_sha256": kit.WHEEL_SHA256,
        "files": {name: kit.digest(data) for name, data in sorted(members.items())},
    }
    members["kit-manifest.json"] = kit.canonical(manifest) + b"\n"
    out.mkdir(parents=True, exist_ok=False)
    expanded = out / "xiaoheihe-publisher"
    for name, data in sorted(members.items()):
        path = expanded / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    archive_path = out / (kit.KIT_NAME + "-" + kit.KIT_VERSION + ".zip")
    # Stored entries avoid compressor-version drift as well as timestamp drift.
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo("xiaoheihe-publisher/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    checksum = kit.digest(archive_path.read_bytes()) + "  " + archive_path.name + "\n"
    (out / "SHA256SUMS").write_bytes(checksum.encode("ascii"))
    return expanded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        output = build(args.wheel, args.out)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"state": "refused", "reason": str(exc)}))
        return 2
    print(json.dumps({"state": "built", "kit": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

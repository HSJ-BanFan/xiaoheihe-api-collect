"""Prepare pinned local APK resources without executing the application.

The profile identifies a research sample, not its distributor or authenticity.
Prepared resources are local user assets, never public package contents.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from .exceptions import XhhSignerError
from .signer import _reject_links

PROFILE = {
    "id": "heybox-arm64-001c9a49-v1",
    "apk_sha256": "001c9a498a41780f6bd42bdaeed2ec3e644ef17afbb6dae0347cafe68c791e3e",
    "apk_bytes": 106453626,
    "members": {
        "AndroidManifest.xml": {"bytes": 109632, "sha256": "df7c1a46e5e62cbec7ce79e3ff67826018c7a49030e0ee158673d11fe5df0388"},
        "META-INF/CERT.SF": {"bytes": 579306, "sha256": "826c212b953e52e0d110d55f0cc38e33124e8e1b3af8016f85a80ff22decdcbb"},
        "META-INF/CERT.RSA": {"bytes": 1364, "sha256": "bef8fcf4f71df945343f9b569eb588106cf9db1257738fa9a472062b0184f6a8"},
        "lib/arm64-v8a/libglesv3_1.so": {"bytes": 2064456, "sha256": "d95d7c52daa012a84c644c9e1f62ca31444c989c65773d75400c0cf26bc06d9e"},
    },
}
LIBRARY = "lib/arm64-v8a/libglesv3_1.so"
APK_MEMBERS = ("AndroidManifest.xml", "META-INF/CERT.SF", "META-INF/CERT.RSA")
OUTPUT_NAMES = {"minimal-app.apk", "libglesv3_1.so", "manifest.json"}


def _digest(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _zip_members(archive: zipfile.ZipFile) -> dict:
    result = {}
    for member in archive.infolist():
        name = member.filename
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise XhhSignerError("unsafe APK member path")
        if name in result:
            raise XhhSignerError("duplicate APK member")
        if stat.S_ISLNK(member.external_attr >> 16):
            raise XhhSignerError("unsafe APK member link")
        result[name] = member
    return result


def _read_member(archive: zipfile.ZipFile, index: dict, name: str) -> bytes:
    expected = PROFILE["members"][name]
    member = index.get(name)
    if member is None or member.file_size != expected["bytes"] or member.flag_bits & 1:
        raise XhhSignerError("APK member integrity mismatch")
    data = archive.read(member)
    if _digest(data) != expected:
        raise XhhSignerError("APK member integrity mismatch")
    return data


def _minimal_apk(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in APK_MEMBERS:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def _manifest(files: dict[str, bytes]) -> dict:
    return {"schema_version": 1, "profile_id": PROFILE["id"],
            "source_apk_sha256": PROFILE["apk_sha256"],
            "files": {name: _digest(data) for name, data in files.items()}}


def _is_arm64_elf(data: bytes) -> bool:
    return len(data) >= 64 and data[:6] == b"\x7fELF\x02\x01" and data[18:20] == b"\xb7\x00"


def _check_library(data: bytes) -> None:
    if not _is_arm64_elf(data):
        raise XhhSignerError("signer library is not little-endian ARM64 ELF")


def inspect_apk(apk: str | Path) -> dict:
    """Diagnose whether an APK can supply the pinned resources. Read-only.

    Returns a report instead of raising for a mismatching APK, so a user with a
    different app version learns exactly which component differs.
    """
    source = Path(apk).expanduser().absolute()
    report: dict = {
        "apk": str(source),
        "profile_id": PROFILE["id"],
        "supported_apk_sha256": PROFILE["apk_sha256"],
        "supported_apk_bytes": PROFILE["apk_bytes"],
        "members": {},
        "problems": [],
        "supported": False,
    }
    try:
        _reject_links(source)
        if not source.is_file():
            raise XhhSignerError(f"APK not found: {source}")
    except OSError as exc:
        raise XhhSignerError(f"cannot read APK: {exc}") from exc
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    report["apk_sha256"] = digest.hexdigest()
    report["apk_bytes"] = source.stat().st_size
    report["matches_supported_apk"] = report["apk_sha256"] == PROFILE["apk_sha256"]
    if not report["matches_supported_apk"]:
        report["problems"].append("this APK is not the supported sample for this release")
    try:
        with zipfile.ZipFile(source) as archive:
            index = _zip_members(archive)
            for name, expected in PROFILE["members"].items():
                member = index.get(name)
                entry: dict = {"present": member is not None, "matches": False,
                               "expected_bytes": expected["bytes"],
                               "expected_sha256": expected["sha256"]}
                if member is not None:
                    try:
                        data = archive.read(member)
                    except (RuntimeError, OSError, zipfile.BadZipFile):
                        entry["error"] = "member is encrypted or unreadable"
                    else:
                        entry["bytes"] = len(data)
                        entry["sha256"] = hashlib.sha256(data).hexdigest()
                        entry["matches"] = entry["sha256"] == expected["sha256"]
                        if name == LIBRARY:
                            entry["arm64_elf"] = _is_arm64_elf(data)
                report["members"][name] = entry
                if not entry["present"]:
                    report["problems"].append(f"missing member: {name}")
                elif entry.get("error"):
                    report["problems"].append(f"unreadable member: {name}")
                elif not entry["matches"]:
                    report["problems"].append(f"member differs from the pinned profile: {name}")
                elif name == LIBRARY and not entry.get("arm64_elf"):
                    report["problems"].append("the signer library is not a little-endian ARM64 ELF")
    except XhhSignerError as exc:
        report["problems"].append(f"archive member list is unusable: {exc}")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        report["problems"].append("the file is not a readable APK zip")
        report["zip_error"] = str(exc)
    report["supported"] = not report["problems"]
    return report


def _read_file(path: Path, limit: int) -> bytes:
    _reject_links(path)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise XhhSignerError("resource size exceeds compatibility profile")
    return data


def inspect_resources(directory: str | Path) -> dict:
    """Verify prepared bytes against the shipped profile, not mutable metadata."""
    root = Path(directory).expanduser().absolute()
    try:
        _reject_links(root)
        root = root.resolve()
        if {p.name for p in root.iterdir()} != OUTPUT_NAMES:
            raise XhhSignerError("incomplete or unexpected signer resources")
        manifest = json.loads(_read_file(root / "manifest.json", 8192))
        so = _read_file(root / "libglesv3_1.so", PROFILE["members"][LIBRARY]["bytes"])
        if _digest(so) != PROFILE["members"][LIBRARY]:
            raise XhhSignerError("signer resource integrity mismatch")
        _check_library(so)
        limit = sum(PROFILE["members"][n]["bytes"] for n in APK_MEMBERS) + 4096
        apk = _read_file(root / "minimal-app.apk", limit)
        with zipfile.ZipFile(io.BytesIO(apk)) as archive:
            index = _zip_members(archive)
            if set(index) != set(APK_MEMBERS):
                raise XhhSignerError("unexpected minimal APK members")
            members = {name: _read_member(archive, index, name) for name in APK_MEMBERS}
        canonical = _minimal_apk(members)
        expected = _manifest({"minimal-app.apk": canonical, "libglesv3_1.so": so})
        if apk != canonical or manifest != expected:
            raise XhhSignerError("signer resource manifest mismatch")
        return {"profile_id": PROFILE["id"], "manifest": str(root / "manifest.json"),
                "integrity_verified": True, "signer_executed": False, "online_verified": False}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        raise XhhSignerError("cannot inspect prepared signer resources") from exc


def prepare_resources(apk: str | Path, output: str | Path) -> dict:
    """Extract only the exact supported sample. Existing output is never reused."""
    source = Path(apk).expanduser().absolute()
    root = Path(output).expanduser().absolute()
    created = False
    complete = False
    written = []
    try:
        _reject_links(source)
        _reject_links(root)
        source = source.resolve()
        root = root.resolve()
        if root.exists():
            raise XhhSignerError("resource output already exists; choose a new directory")
        with source.open("rb") as stream:
            if source.stat().st_size != PROFILE["apk_bytes"]:
                raise XhhSignerError("unsupported APK; exact supported sample required")
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != PROFILE["apk_sha256"]:
                raise XhhSignerError("unsupported APK; exact supported sample required")
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                index = _zip_members(archive)
                members = {name: _read_member(archive, index, name) for name in PROFILE["members"]}
        _check_library(members[LIBRARY])
        files = {"minimal-app.apk": _minimal_apk(members), "libglesv3_1.so": members[LIBRARY]}
        files["manifest.json"] = (json.dumps(_manifest(files), sort_keys=True, indent=2) + "\n").encode()
        root.parent.mkdir(parents=True, exist_ok=True)
        _reject_links(root)
        root.mkdir()
        created = True
        # Manifest is written last. Interrupted preparations are not selectable.
        for name, data in files.items():
            path = root / name
            with path.open("xb") as stream:
                written.append(path)
                stream.write(data)
        result = inspect_resources(root)
        complete = True
        return result
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        raise XhhSignerError("cannot prepare signer resources") from exc
    finally:
        if created and not complete:
            for path in written:
                path.unlink(missing_ok=True)
            root.rmdir()

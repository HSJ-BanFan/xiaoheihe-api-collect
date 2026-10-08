"""Run the unchanged, hash-checked CLI included in this portable kit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

KIT_NAME = "xhh-publisher-kit"
KIT_VERSION = "0.1.0rc1"
CLI_VERSION = "0.5.0rc4+standalone.7"
WHEEL_SHA256 = "2ca9af8ece4e105631e62c6c4043e1fa758c766e16031afd4e52028bc44293ff"
SOURCE_MEMBERS = (
    "SKILL.md", "LICENSE", "scripts/xhh_cli.py", "scripts/xhh_publish.py",
    "references/setup.md", "references/publishing.md",
)
RUNTIME_MEMBERS = tuple("xhh_sdk/" + name for name in (
    "__init__.py", "accounts.py", "api_catalog.json", "browse.py", "catalog.py",
    "cli.py", "client.py", "config.py", "exceptions.py", "groups.py", "interaction.py",
    "login.py", "payload.py", "routes.py", "secure_phone.py", "signer.py",
    "signer_bundle.py", "signer_resources.py", "transport.py",
)) + tuple("xhh_sdk-" + CLI_VERSION + ".dist-info/" + name for name in (
    "licenses/LICENSE", "METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD",
))
KIT_ROOT = Path(__file__).resolve().parents[1]


class Refused(ValueError):
    """A safe, fixed reason suitable for machine output."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(path: Path) -> object:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refused("duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused("invalid_json_number")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise Refused("invalid_json") from exc


def verify_runtime() -> dict:
    manifest = read_json(KIT_ROOT / "kit-manifest.json")
    expected = {
        "schema_version": 1, "kit_name": KIT_NAME, "kit_version": KIT_VERSION,
        "cli_version": CLI_VERSION, "wheel_sha256": WHEEL_SHA256,
    }
    if not isinstance(manifest, dict) or set(manifest) != set(expected) | {"files"}:
        raise Refused("invalid_kit_manifest")
    if any(manifest[key] != value for key, value in expected.items()):
        raise Refused("kit_version_mismatch")
    members = set(SOURCE_MEMBERS) | {"runtime/" + name for name in RUNTIME_MEMBERS}
    if not isinstance(manifest["files"], dict) or set(manifest["files"]) != members:
        raise Refused("kit_member_mismatch")
    actual = set()
    for path in KIT_ROOT.rglob("*"):
        if path.is_symlink():
            raise Refused("kit_symlink")
        if path.is_file():
            actual.add(path.relative_to(KIT_ROOT).as_posix())
    if actual != members | {"kit-manifest.json"}:
        raise Refused("kit_member_mismatch")
    try:
        for name, sha256 in manifest["files"].items():
            if digest((KIT_ROOT / name).read_bytes()) != sha256:
                raise Refused("kit_hash_mismatch")
    except OSError as exc:
        raise Refused("kit_unreadable") from exc
    return manifest


def activate_runtime() -> dict:
    manifest = verify_runtime()
    runtime = KIT_ROOT / "runtime"
    for name, module in tuple(sys.modules.items()):
        if name == "xhh_sdk" or name.startswith("xhh_sdk."):
            origin = getattr(module, "__file__", None)
            if not origin or runtime not in Path(origin).resolve().parents:
                del sys.modules[name]
    sys.path.insert(0, str(runtime))
    return manifest


def main(argv=None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        activate_runtime()
    except (Refused, OSError):
        print(json.dumps({"state": "refused", "reason": "kit_integrity_failed"}))
        return 2
    from xhh_sdk.cli import main as original_main
    return original_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

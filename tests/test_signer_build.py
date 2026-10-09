import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "signer/scripts/build_precompiled.py"


def test_precompiled_builder_exists():
    assert SCRIPT.is_file(), "release builder missing"


def test_resource_jar_is_deterministic_and_stored(tmp_path):
    if not SCRIPT.exists():
        return
    spec = importlib.util.spec_from_file_location("build_precompiled", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first, second = tmp_path / "first.jar", tmp_path / "second.jar"
    module.write_zip(first, {"b": b"2", "a": b"1"})
    module.write_zip(second, {"a": b"1", "b": b"2"})
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["a", "b"]
        assert all(i.compress_type == zipfile.ZIP_STORED for i in archive.infolist())


def test_generated_release_json_has_portable_lf_bytes(tmp_path):
    spec = importlib.util.spec_from_file_location("build_precompiled", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "write_json"), "release JSON needs a byte-stable writer"
    value = {"z": 2, "a": {"hash": "abc"}}
    target = tmp_path / "lock.json"
    module.write_json(target, value)
    assert target.read_bytes() == (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    assert b"\r\n" not in target.read_bytes()


def test_source_archive_uses_explicit_members_not_local_scratch(tmp_path):
    spec = importlib.util.spec_from_file_location("build_precompiled", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "source_payload"), "public source archive needs an explicit allowlist"
    for relative in module.PROJECT_SOURCE_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"allowed\r\n")
    hidden = tmp_path / "signer/contract/accounts.json"
    hidden.write_text('{"private_fixture":true}', encoding="utf-8")
    module.ROOT = tmp_path
    entries = module.source_payload({}, b"upstream license")
    assert set(entries) == set(module.PROJECT_SOURCE_FILES) | {"unidbg/LICENSE"}
    assert "signer/contract/accounts.json" not in entries
    assert all(b"\r\n" not in value for value in entries.values())

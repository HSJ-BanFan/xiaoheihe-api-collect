import importlib.util
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

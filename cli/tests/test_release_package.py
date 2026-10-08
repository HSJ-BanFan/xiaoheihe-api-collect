"""Distribution audit rejects binary and credential-bearing payloads."""
import importlib.util
from pathlib import Path
import zipfile

import pytest

SDK = Path(__file__).resolve().parents[1]


def auditor():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
    assert path.is_file(), "release audit script is missing"
    spec = importlib.util.spec_from_file_location("build_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name,content", [
    ("xhh_sdk/vendor/secret.jar", b"jar"),
    ("xhh_sdk/config.json", b'{"pkey":"private-session"}'),
    ("xhh_sdk/client.py", b'pkey = "private-session"'),
    ("../escaped.py", b"print(1)"),
    ("xhh_sdk/accounts.json", b'{"accounts":{}}'),
    ("profiles/Default/Cookies", b"browser-data"),
])
def test_audit_rejects_forbidden_files(tmp_path, name, content):
    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr(name, content)
    with pytest.raises(ValueError):
        auditor().audit_archive(wheel)


def test_clean_text_archive_auditable(tmp_path):
    wheel = tmp_path / "clean.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("xhh_sdk/__init__.py", '__version__ = "0.5.0rc1"')
    result = auditor().audit_archive(wheel)
    assert result["binary_count"] == 0
    assert result["files"] == 1
    assert len(result["sha256"]) == 64


def test_declared_version_matches_package_version():
    import re
    pyproject = (SDK / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)
    init = (SDK / "xhh_sdk" / "__init__.py").read_text(encoding="utf-8")
    package = re.search(r'^__version__ = "([^"]+)"', init, re.MULTILINE).group(1)
    assert declared == package


def test_packaged_documents_name_the_declared_version():
    """A stale version in the packaged README would ship contradictory metadata."""
    import re
    pyproject = (SDK / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)
    readme = (SDK / "README.md").read_text(encoding="utf-8")
    named = set(re.findall(r"0\.5\.0rc4\+standalone\.\d+", readme))
    assert named <= {version}, f"README.md names another candidate: {named}"
    release = (SDK / "RELEASE.md").read_text(encoding="utf-8")
    assert f"Current candidate: `{version}`" in release









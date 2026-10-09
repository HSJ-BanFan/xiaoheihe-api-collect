"""Distribution audit rejects binary and credential-bearing payloads."""
import importlib.util
import base64
import csv
import hashlib
import io
import os
from pathlib import Path
import tarfile
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


def test_web_signer_source_is_allowed_in_candidate_archive(tmp_path):
    wheel = tmp_path / "web.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("xhh_sdk/web_signer.py", (SDK / "xhh_sdk/web_signer.py").read_bytes())
    result = auditor().audit_archive(wheel)
    assert result["files"] == 1
    assert result["binary_count"] == 0


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


def test_staging_normalizes_text_line_endings_and_source_timestamps(tmp_path):
    build = auditor()
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "xhh_sdk").mkdir(parents=True)
    for name in build.SOURCE_FILES:
        (source / name).write_bytes(b"line one\r\nline two\r\n")
    for name in build.PACKAGE_FILES:
        (source / "xhh_sdk" / name).write_bytes(b"line one\nline two\n")
    for path in source.rglob("*"):
        if path.is_file():
            os.utime(path, (1700000001, 1700000001))
    build.stage_source(source, target)
    for path in target.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == b"line one\nline two\n"
            assert int(path.stat().st_mtime) == build.SOURCE_DATE_EPOCH


def test_canonical_wheel_ignores_platform_order_timestamps_and_line_endings(tmp_path):
    build = auditor()
    entries = {
        "xhh_sdk/__init__.py": b'__version__ = "0.6.0rc1"\n',
        "xhh_sdk-0.6.0rc1.dist-info/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        "xhh_sdk-0.6.0rc1.dist-info/METADATA": b"Metadata-Version: 2.4\nName: xhh-sdk\nVersion: 0.6.0rc1\n",
        "xhh_sdk-0.6.0rc1.dist-info/RECORD": b"old-record-content\n",
    }
    wheels = [tmp_path / "windows.whl", tmp_path / "linux.whl"]
    for index, wheel in enumerate(wheels):
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, content in (list(entries.items()) if index else reversed(list(entries.items()))):
                info = zipfile.ZipInfo(name, (2025 + index, 2, 3, 4, 5, 6))
                info.create_system = index * 3
                info.external_attr = (0o100600 + index * 0o44) << 16
                info.compress_type = zipfile.ZIP_DEFLATED if index else zipfile.ZIP_STORED
                archive.writestr(info, content if index else content.replace(b"\n", b"\r\n"))
        build.canonicalize_wheel(wheel)
    assert wheels[0].read_bytes() == wheels[1].read_bytes()
    canonical = wheels[0].read_bytes()
    build.canonicalize_wheel(wheels[0])
    assert wheels[0].read_bytes() == canonical
    with zipfile.ZipFile(wheels[0]) as archive:
        assert archive.namelist() == sorted(entries)
        for info in archive.infolist():
            assert info.date_time == (2000, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert info.external_attr == 0o100644 << 16
            assert info.compress_type == zipfile.ZIP_STORED
        record_name = "xhh_sdk-0.6.0rc1.dist-info/RECORD"
        record = list(csv.reader(io.StringIO(archive.read(record_name).decode())))
        assert [row[0] for row in record] == sorted(entries)
        for name, digest, size in record:
            if name == record_name:
                assert (digest, size) == ("", "")
            else:
                content = archive.read(name)
                expected = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
                assert (digest, size) == ("sha256=" + expected, str(len(content)))


def test_canonicalizer_does_not_hide_forbidden_input(tmp_path):
    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("xhh_sdk/vendor/signer.jar", b"not allowed")
    before = wheel.read_bytes()
    with pytest.raises(ValueError, match="forbidden"):
        auditor().canonicalize_wheel(wheel)
    assert wheel.read_bytes() == before


@pytest.mark.parametrize("name,content", [
    ("xhh_sdk/", b""),
    ("../outside/", b""),
    ("xhh_sdk/vendor/secret.jar/", b"synthetic-private-payload"),
])
def test_canonicalizer_rejects_explicit_zip_directories_without_rewriting(tmp_path, name, content):
    wheel = tmp_path / "directory.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("xhh_sdk/__init__.py", b"")
        archive.writestr("xhh_sdk-0.6.0rc1.dist-info/RECORD", b"")
        archive.writestr(name, content)
    before = wheel.read_bytes()
    with pytest.raises(ValueError, match="directory|directories"):
        auditor().canonicalize_wheel(wheel)
    assert wheel.read_bytes() == before


@pytest.mark.parametrize("extra_directory", [None, "../outside", "package/vendor", "package/unused"])
def test_sdist_only_allows_safe_parent_directories(tmp_path, extra_directory):
    source = tmp_path / "source.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        for name in ["package", "package/xhh_sdk", *([extra_directory] if extra_directory else [])]:
            member = tarfile.TarInfo(name)
            member.type = tarfile.DIRTYPE
            archive.addfile(member)
        archive.addfile(tarfile.TarInfo("package/xhh_sdk/__init__.py"), io.BytesIO(b""))
    if extra_directory:
        with pytest.raises(ValueError, match="unsafe|directory"):
            auditor().audit_archive(source)
    else:
        assert auditor().audit_archive(source)["files"] == 1

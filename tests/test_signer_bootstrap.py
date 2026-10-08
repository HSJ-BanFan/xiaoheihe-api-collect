"""Compile a JDK-only bootstrap fixture; no emulator or native code runs here."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "signer/src/main/java/com/xiaoheihe/SignerBootstrap.java"


def test_bootstrap_source_exists():
    assert SOURCE.is_file(), "verified dependency bootstrap is not implemented"


@pytest.fixture
def bootstrap(tmp_path):
    if not SOURCE.exists():
        pytest.skip("bootstrap not implemented")
    javac = shutil.which("javac")
    java = shutil.which("java")
    if not javac or not java:
        pytest.fail("bootstrap tests require JDK 17+ on PATH")
    source = tmp_path / "XhhSignerMain.java"
    source.write_text('package com.xiaoheihe; public class XhhSignerMain {'
                      'static { System.out.println("INITIALIZED"); }'
                      'public static void main(String[] args) { System.out.println("CALLED"); }}')
    classes = tmp_path / "classes"
    classes.mkdir()
    subprocess.run([javac, "--release", "17", "-d", str(classes), str(SOURCE), str(source)], check=True)
    deps = tmp_path / "deps"
    deps.mkdir()
    jar = deps / "resources.jar"
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("native/resource.txt", b"new-resource")
    data = jar.read_bytes()
    lock = f"resources.jar\t{hashlib.sha256(data).hexdigest()}\t{len(data)}\n"
    resource = f"native/resource.txt\t{hashlib.sha256(b'new-resource').hexdigest()}\t12\n"
    loader = tmp_path / "loader.jar"
    with zipfile.ZipFile(loader, "w") as z:
        z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nMain-Class: com.xiaoheihe.SignerBootstrap\n\n")
        z.writestr("META-INF/xhh-deps.tsv", lock)
        z.writestr("META-INF/xhh-resources.tsv", resource)
        for path in classes.rglob("*.class"):
            z.write(path, path.relative_to(classes).as_posix())
    return java, loader, jar


@pytest.mark.parametrize("change", ["none", "missing", "tampered", "extra", "directory"])
def test_exact_dependencies_before_application_initialization(bootstrap, change):
    java, loader, dependency = bootstrap
    if change == "missing":
        dependency.unlink()
    if change == "tampered":
        dependency.write_bytes(b"not the locked artifact")
    if change == "extra":
        (dependency.parent / "extra.jar").write_bytes(b"x")
    if change == "directory":
        (dependency.parent / "extra").mkdir()
    result = subprocess.run([java, "-jar", str(loader)], capture_output=True, text=True,
                            encoding="utf-8", timeout=15)
    if change == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["INITIALIZED", "CALLED"]
        assert "verified_runtime_resources=1" in result.stderr
    else:
        assert result.returncode == 2
        assert "INITIALIZED" not in result.stdout
        assert "dependency_verification_failed" in result.stderr

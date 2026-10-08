"""Release boundary checks. All Java invocations are replaced by a fake child."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

import pytest

from xhh_sdk import signer as signer_module
from xhh_sdk.exceptions import XhhSignerError
from xhh_sdk.signer import Signer


@pytest.fixture
def jar(tmp_path, monkeypatch):
    file = tmp_path / "signer.jar"
    file.write_bytes(b"test signer artifact")
    monkeypatch.setattr(signer_module.os, "environ", {})
    monkeypatch.setattr(signer_module, "VENDOR_JAR", file)
    monkeypatch.setattr(signer_module.shutil, "which", lambda _: str(tmp_path / "java"))
    return file


@pytest.fixture
def child(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if "cwd" in kwargs:
            assert Path(kwargs["cwd"]).is_dir()
        return subprocess.CompletedProcess(
            args, 0, '{"_time":"1700000000","nonce":"n","hkey":"h","_rnd":"r"}\n', "")

    monkeypatch.setattr(signer_module.subprocess, "run", run)
    return calls


def make_signer(**kwargs):
    return Signer(identity="123", imei="test-device", device_info="test-model", **kwargs)


def test_environment_jar_is_used_when_config_path_is_none(jar, tmp_path, monkeypatch):
    external = tmp_path / "external.jar"
    external.write_bytes(b"external signer")
    monkeypatch.setenv("XHH_SIGNER_JAR", str(external))
    assert make_signer(jar=None).jar == external.resolve()


def test_explicit_jar_wins_over_environment(jar, monkeypatch):
    monkeypatch.setenv("XHH_SIGNER_JAR", "missing.jar")
    assert make_signer(jar=jar).jar == jar.resolve()


def test_relative_jar_is_resolved_before_child_changes_directory(jar, monkeypatch, child):
    monkeypatch.chdir(jar.parent)
    signer = make_signer(jar="signer.jar")
    assert signer.jar == jar.resolve()
    assert signer.sign("/test", 1700000000) == {
        "_time": "1700000000", "nonce": "n", "hkey": "h", "_rnd": "r"}
    assert child[0][0][child[0][0].index("-jar") + 1] == str(jar.resolve())


def test_missing_external_jar_has_actionable_error(jar, monkeypatch):
    monkeypatch.setenv("XHH_SIGNER_JAR", str(jar.parent / "missing.jar"))
    with pytest.raises(XhhSignerError, match="XHH_SIGNER_JAR"):
        make_signer()


@pytest.mark.parametrize("digest", ["", "xyz", "a" * 63, "g" * 64, "a" * 65])
def test_invalid_expected_digest_is_rejected(jar, digest, child):
    with pytest.raises(XhhSignerError, match="64 hexadecimal"):
        make_signer(sha256=digest)
    assert child == []


def test_digest_mismatch_never_executes_child(jar, child):
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        make_signer(sha256="0" * 64).sign("/test", 1700000000)
    assert child == []


def test_environment_digest_is_verified(jar, monkeypatch, child):
    monkeypatch.setenv("XHH_SIGNER_SHA256", "0" * 64)
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        make_signer().sign("/test", 1700000000)
    assert child == []


def test_explicit_digest_wins_and_accepts_uppercase(jar, monkeypatch, child):
    monkeypatch.setenv("XHH_SIGNER_SHA256", "0" * 64)
    digest = hashlib.sha256(jar.read_bytes()).hexdigest().upper()
    assert make_signer(sha256=digest).sign("/test", 1700000000)["hkey"] == "h"
    assert len(child) == 1


def test_changed_jar_is_rechecked_before_execution(jar, child):
    signer = make_signer(sha256=hashlib.sha256(jar.read_bytes()).hexdigest())
    jar.write_bytes(b"changed after initialization")
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        signer.sign("/test", 1700000000)
    assert child == []


def test_child_environment_excludes_credentials_and_jvm_injection(jar, monkeypatch, child):
    forbidden = ["XHH_PKEY", "PRIVATE_API_TOKEN", "JAVA_TOOL_OPTIONS",
                 "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "LD_PRELOAD"]
    for key in forbidden:
        monkeypatch.setenv(key, "secret-canary")
    monkeypatch.setenv("JAVA_HOME", "test-java-home")
    monkeypatch.setenv("LANG", "C.UTF-8")
    assert make_signer().sign("/test", 1700000000)["nonce"] == "n"
    env = child[0][1]["env"]
    assert set(forbidden).isdisjoint(env)
    assert env["HEYBOX_ID"] == "123"
    assert env["HEYBOX_IMEI"] == "test-device"
    assert env["JAVA_HOME"] == "test-java-home"
    assert env["LANG"] == "C.UTF-8"


def test_child_uses_temporary_work_directory_not_project(jar, child):
    assert make_signer().sign("/test", 1700000000)["_rnd"] == "r"
    args, kwargs = child[0]
    cwd = Path(kwargs["cwd"])
    assert cwd.is_absolute()
    assert cwd != Path.cwd()
    assert not cwd.exists()
    assert f"-Djava.io.tmpdir={cwd}" in args
    assert kwargs["env"]["TMP"] == str(cwd)
    assert kwargs["env"]["TEMP"] == str(cwd)
    assert kwargs["shell"] is False
    assert Path(args[0]).is_absolute()


@pytest.mark.skipif(os.name != "nt", reason="Windows subprocess flag")
def test_windows_child_does_not_open_console(jar, child):
    assert make_signer().sign("/test", 1700000000)["hkey"] == "h"
    assert child[0][1]["creationflags"] & subprocess.CREATE_NO_WINDOW



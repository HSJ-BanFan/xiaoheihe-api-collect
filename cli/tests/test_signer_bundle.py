"""Signer bundles: install, resolve, and the loader request contract.

Everything here uses synthetic resources and a fake child process. No Java,
no network and no real account store is involved.
"""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from xhh_sdk import signer as signer_module
from xhh_sdk.exceptions import XhhSignerError
from xhh_sdk.signer import Signer


def bundle_module():
    name = "xhh_sdk.signer_bundle"
    assert importlib.util.find_spec(name) is not None, "signer bundle module is missing"
    return importlib.import_module(name)


@pytest.fixture
def resources(tmp_path, monkeypatch):
    module = importlib.import_module("xhh_sdk.signer_resources")
    elf = bytearray(64)
    elf[:6] = b"\x7fELF\x02\x01"
    elf[18:20] = (183).to_bytes(2, "little")
    members = {
        "AndroidManifest.xml": b"synthetic binary manifest",
        "META-INF/CERT.SF": b"synthetic certificate digest",
        "META-INF/CERT.RSA": b"synthetic public certificate",
        "lib/arm64-v8a/libglesv3_1.so": bytes(elf),
    }
    apk = tmp_path / "user.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    monkeypatch.setattr(module, "PROFILE", {
        "id": "synthetic-test-profile",
        "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "apk_bytes": apk.stat().st_size,
        "members": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                    for name, data in members.items()},
    })
    out = tmp_path / "resources"
    module.prepare_resources(apk, out)
    return out


@pytest.fixture
def installed(tmp_path, monkeypatch, resources):
    monkeypatch.setenv("XHH_BUNDLE_HOME", str(tmp_path / "bundles"))
    loader = tmp_path / "loader.jar"
    loader.write_bytes(b"synthetic signer loader bytes")
    digest = hashlib.sha256(loader.read_bytes()).hexdigest()
    reference = bundle_module().install_bundle(resources, loader, loader_sha256=digest)
    return reference, loader, digest, resources


def _expected_digest(resources, loader_digest):
    digest = hashlib.sha256()
    digest.update(b"xhh-signer-bundle\x00")
    digest.update(b"1\x00")
    digest.update(b"synthetic-test-profile\x00")
    digest.update((resources / "manifest.json").read_bytes())
    digest.update(b"\x00" + loader_digest.encode("ascii"))
    return digest.hexdigest()


def _stored_entries(root):
    return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


def test_install_and_resolve_roundtrip(installed):
    reference, loader, digest, resources = installed
    assert reference == "bundle:" + _expected_digest(resources, digest)
    resolved = bundle_module().resolve_bundle(reference)
    assert resolved["profile_id"] == "synthetic-test-profile"
    assert resolved["loader_sha256"] == digest
    assert Path(resolved["loader"]).read_bytes() == b"synthetic signer loader bytes"
    assert Path(resolved["resources"]).joinpath("manifest.json").is_file()
    assert resolved["signer_executed"] is False and resolved["online_verified"] is False


def test_reinstall_is_idempotent(installed):
    reference, loader, digest, resources = installed
    again = bundle_module().install_bundle(resources, loader, loader_sha256=digest)
    assert again == reference
    root = Path(bundle_module().resolve_bundle(reference)["directory"]).parent
    assert sorted(path.name for path in root.iterdir()) == [reference.removeprefix("bundle:")]


def test_loader_digest_mismatch_leaves_nothing_behind(tmp_path, monkeypatch, resources):
    monkeypatch.setenv("XHH_BUNDLE_HOME", str(tmp_path / "bundles"))
    loader = tmp_path / "loader.jar"
    loader.write_bytes(b"bytes that do not match the pinned digest")
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        bundle_module().install_bundle(resources, loader, loader_sha256="0" * 64)
    assert _stored_entries(tmp_path / "bundles") == []


def test_unverified_resources_are_rejected(tmp_path, monkeypatch, resources):
    monkeypatch.setenv("XHH_BUNDLE_HOME", str(tmp_path / "bundles"))
    (resources / "libglesv3_1.so").write_bytes(b"tampered")
    loader = tmp_path / "loader.jar"
    loader.write_bytes(b"loader")
    digest = hashlib.sha256(loader.read_bytes()).hexdigest()
    with pytest.raises(XhhSignerError):
        bundle_module().install_bundle(resources, loader, loader_sha256=digest)
    assert _stored_entries(tmp_path / "bundles") == []


def test_tampered_loader_or_resource_fails_resolution(installed):
    reference, loader, digest, resources = installed
    resolved = bundle_module().resolve_bundle(reference)
    Path(resolved["loader"]).write_bytes(b"different loader")
    with pytest.raises(XhhSignerError):
        bundle_module().resolve_bundle(reference)
    Path(resolved["loader"]).write_bytes(b"synthetic signer loader bytes")
    assert bundle_module().resolve_bundle(reference)["loader_sha256"] == digest
    Path(resolved["resources"], "libglesv3_1.so").write_bytes(b"tampered")
    with pytest.raises(XhhSignerError):
        bundle_module().resolve_bundle(reference)


@pytest.mark.parametrize("reference", ["bundle:" + "0" * 64, "managed:" + "0" * 64, "nothing"])
def test_unknown_references_are_rejected(installed, reference):
    with pytest.raises(XhhSignerError):
        bundle_module().resolve_bundle(reference)


def test_signer_sends_the_documented_request(installed, monkeypatch):
    reference, loader, _, resources = installed
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args, 0, '{"_time":"1700000000","nonce":"n","hkey":"h","_rnd":"14:r"}\n', "")

    monkeypatch.setattr(signer_module.subprocess, "run", run)
    monkeypatch.setattr(signer_module.shutil, "which", lambda _: sys.executable)
    signer = Signer(bundle=reference, identity="123", imei="0123456789abcdef",
                    device_info="25102RKBEC", os_version="14", app_version="1.3.385")
    result = signer.sign("/account/info", 1700000000)
    assert result == {"_time": "1700000000", "nonce": "n", "hkey": "h", "_rnd": "14:r"}
    args, kwargs = calls[0]
    assert args[0] == sys.executable
    resolved_for_paths = bundle_module().resolve_bundle(reference)
    assert args[args.index("-jar") + 1] == resolved_for_paths["loader"]
    assert "/account/info/" not in args  # the path travels on stdin, not the command line
    resolved = resolved_for_paths
    expected = (
        "protocol=1\n"
        f"resource_dir={resolved['resources']}\n"
        "path=/account/info/\n"
        "timestamp=1700000000\n"
        "identity=123\n"
        "imei=0123456789abcdef\n"
        "device_info=25102RKBEC\n"
        "os_version=14\n"
        "app_version=1.3.385\n"
    )
    assert kwargs["input"] == expected
    assert kwargs["shell"] is False


def test_signer_rejects_values_the_loader_would_refuse(installed, monkeypatch):
    reference, _, _, _ = installed
    monkeypatch.setattr(signer_module.shutil, "which", lambda _: sys.executable)
    for bad in ("bad;value", "bad\\value", "bad\nvalue"):
        with pytest.raises(XhhSignerError):
            Signer(bundle=reference, identity="123", imei="0123456789abcdef",
                   device_info=bad, os_version="14", app_version="1.3.385")


def test_cli_bundle_install_requires_confirmation(tmp_path):
    cli_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-B", "-m", "xhh_sdk.cli", "signer", "bundle-install",
         "--resources", str(tmp_path / "missing"), "--loader", str(tmp_path / "missing.jar"),
         "--loader-sha256", "0" * 64],
        cwd=cli_dir, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "refusing bundle installation without --confirm" in result.stderr


def test_cli_selftest_runs_the_bundle_signer(installed, monkeypatch, capsys):
    from xhh_sdk import cli
    reference, _, _, _ = installed
    calls = []

    def run(args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            args, 0, '{"_time":"1700000000","nonce":"n","hkey":"FC0EAF1B","_rnd":"14:E94DBC87"}\n', "")

    monkeypatch.setattr(signer_module.subprocess, "run", run)
    monkeypatch.setattr(signer_module.shutil, "which", lambda _: sys.executable)
    exit_code = cli.main(["signer", "selftest", reference, "--identity", "123",
                          "--imei", "0123456789abcdef", "--device-info", "25102RKBEC"])
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["signer_executed"] is True
    assert printed["online_request_sent"] is False
    assert printed["signature"] == {"_time": "1700000000", "nonce": "n",
                                    "hkey": "FC0EAF1B", "_rnd": "14:E94DBC87"}
    assert calls[0]["input"].startswith("protocol=1\nresource_dir=")

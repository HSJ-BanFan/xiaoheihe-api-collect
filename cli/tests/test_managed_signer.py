"""Managed artifact checks use synthetic bytes and never execute a JAR."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from xhh_sdk import signer as signer_module
from xhh_sdk.exceptions import XhhSignerError


@pytest.fixture
def managed(tmp_path, monkeypatch):
    root = tmp_path / "store"
    source = tmp_path / "synthetic.jar"
    source.write_bytes(b"synthetic signer; not executable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv("XHH_SIGNER_HOME", str(root))
    monkeypatch.setattr(signer_module, "VENDOR_JAR", tmp_path / "missing-vendor.jar")

    def no_java(*args, **kwargs):
        pytest.fail("artifact management must not discover or execute Java")

    monkeypatch.setattr(signer_module.shutil, "which", no_java)
    monkeypatch.setattr(signer_module.subprocess, "run", no_java)
    return root, source, digest


def make_signer(reference, **kwargs):
    return signer_module.Signer(
        jar=reference, identity="synthetic-user", imei="synthetic-device",
        device_info="synthetic-model", **kwargs)


def test_imported_copy_survives_original_source_move(managed):
    root, source, digest = managed
    reference = signer_module.install_signer(source, sha256=digest.upper())
    assert reference == f"managed:{digest}"
    source.rename(source.with_suffix(".moved"))
    assert signer_module.inspect_signer(reference) == {
        "reference": reference, "resolved_path": str(root / f"{digest}.jar"),
        "sha256": digest, "passed": True,
    }


@pytest.mark.parametrize("digest", ["", "g" * 64, "a" * 63, "a" * 65, " a" * 32])
def test_install_rejects_invalid_pin_before_creating_store(managed, digest):
    root, source, _ = managed
    with pytest.raises(XhhSignerError, match="64 hexadecimal"):
        signer_module.install_signer(source, sha256=digest)
    assert not root.exists()


def test_install_mismatch_publishes_nothing_and_cleans_temp(managed):
    root, source, _ = managed
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        signer_module.install_signer(source, sha256="0" * 64)
    assert not root.exists() or list(root.iterdir()) == []


def test_install_rejects_missing_or_directory_source(managed):
    root, source, digest = managed
    for invalid in (source.with_suffix(".missing"), source.parent):
        with pytest.raises(XhhSignerError):
            signer_module.install_signer(invalid, sha256=digest)
    assert not root.exists() or list(root.iterdir()) == []


def test_install_idempotence_does_not_replace_existing_inode(managed):
    root, source, digest = managed
    reference = signer_module.install_signer(source, sha256=digest)
    destination = root / f"{digest}.jar"
    original_stat = destination.stat()
    assert signer_module.install_signer(source, sha256=digest) == reference
    assert destination.stat().st_ino == original_stat.st_ino
    assert destination.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert list(root.iterdir()) == [destination]


def test_existing_corrupt_destination_is_not_repaired(managed):
    root, source, digest = managed
    root.mkdir()
    destination = root / f"{digest}.jar"
    destination.write_bytes(b"corrupt destination")
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        signer_module.install_signer(source, sha256=digest)
    assert destination.read_bytes() == b"corrupt destination"
    assert list(root.iterdir()) == [destination]


def test_parallel_installers_publish_one_complete_file(managed):
    root, source, digest = managed
    with ThreadPoolExecutor(max_workers=8) as executor:
        references = list(executor.map(
            lambda _: signer_module.install_signer(source, sha256=digest), range(16)))
    assert references == [f"managed:{digest}"] * 16
    assert (root / f"{digest}.jar").read_bytes() == source.read_bytes()
    assert list(root.iterdir()) == [root / f"{digest}.jar"]


def test_interrupted_publish_cleans_own_temp_and_preserves_stale_temp(managed, monkeypatch):
    root, source, digest = managed
    root.mkdir()
    stale = root / ".stale-install.tmp"
    stale.write_bytes(b"incomplete")

    def interrupted(*args, **kwargs):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(signer_module.os, "link", interrupted)
    with pytest.raises(XhhSignerError):
        signer_module.install_signer(source, sha256=digest)
    assert list(root.iterdir()) == [stale]


def test_cleanup_permission_error_is_a_signer_error(managed, monkeypatch):
    root, source, digest = managed
    original_unlink = Path.unlink

    def denied(path, *args, **kwargs):
        if path.parent == root and path.name.startswith(".install-"):
            raise PermissionError("synthetic cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    with pytest.raises(XhhSignerError, match="cleanup"):
        signer_module.install_signer(source, sha256=digest)


def test_relative_store_override_is_rejected_without_writes(managed, monkeypatch, tmp_path):
    _, source, digest = managed
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XHH_SIGNER_HOME", "relative-store")
    with pytest.raises(XhhSignerError, match="absolute"):
        signer_module.install_signer(source, sha256=digest)
    assert not (tmp_path / "relative-store").exists()


def test_default_store_is_user_home_not_cwd(managed, monkeypatch, tmp_path):
    _, source, digest = managed
    monkeypatch.delenv("XHH_SIGNER_HOME")
    home = tmp_path / "home"
    monkeypatch.setattr(signer_module.Path, "home", classmethod(lambda cls: home))
    reference = signer_module.install_signer(source, sha256=digest)
    assert signer_module.inspect_signer(reference)["resolved_path"] == str(
        home / ".xhh_sdk" / "signers" / f"{digest}.jar")


@pytest.mark.parametrize("reference", ["managed:", "managed:../elsewhere", "managed:" + "g" * 64,
                                       "managed:" + "a" * 63, "managed:" + "a" * 65, ""])
def test_invalid_explicit_reference_never_falls_back(managed, monkeypatch, reference):
    _, source, _ = managed
    monkeypatch.setenv("XHH_SIGNER_JAR", str(source))
    with pytest.raises(XhhSignerError):
        signer_module.inspect_signer(reference)


def test_missing_managed_artifact_never_falls_back(managed, monkeypatch):
    _, source, digest = managed
    monkeypatch.setenv("XHH_SIGNER_JAR", str(source))
    with pytest.raises(XhhSignerError, match="not found"):
        signer_module.inspect_signer(f"managed:{digest}")


def test_inspect_uses_external_precedence_and_verifies_environment_pin(managed, monkeypatch):
    _, source, digest = managed
    monkeypatch.setenv("XHH_SIGNER_JAR", str(source))
    assert signer_module.inspect_signer()["sha256"] == digest
    missing = source.with_suffix(".missing")
    with pytest.raises(XhhSignerError, match="not found"):
        signer_module.inspect_signer(str(missing))
    monkeypatch.setenv("XHH_SIGNER_SHA256", "0" * 64)
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        signer_module.inspect_signer()


def test_managed_reference_rejects_conflicting_pin_before_java(managed, monkeypatch):
    _, source, digest = managed
    reference = signer_module.install_signer(source, sha256=digest)
    with pytest.raises(XhhSignerError, match="conflict"):
        make_signer(reference, sha256="0" * 64)
    monkeypatch.setenv("XHH_SIGNER_SHA256", "0" * 64)
    with pytest.raises(XhhSignerError, match="conflict"):
        signer_module.inspect_signer(reference)


def test_managed_signing_rehashes_before_every_child(managed, monkeypatch, tmp_path):
    root, source, digest = managed
    reference = signer_module.install_signer(source, sha256=digest)
    monkeypatch.setattr(signer_module.shutil, "which", lambda _: str(tmp_path / "fake-java"))
    calls = []

    def child(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args, 0, '{"_time":"1700000000","nonce":"n","hkey":"h","_rnd":"r"}', "")

    monkeypatch.setattr(signer_module.subprocess, "run", child)
    signer = make_signer(reference)
    assert signer.sha256 == digest
    assert signer.sign("/test", 1700000000)["hkey"] == "h"
    (root / f"{digest}.jar").write_bytes(b"changed after first signature")
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        signer.sign("/test", 1700000000)
    assert len(calls) == 1


def symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"host cannot create symlinks: {exc}")


@pytest.mark.parametrize("location", ["root", "ancestor", "destination"])
def test_managed_store_rejects_symlink_paths(managed, monkeypatch, tmp_path, location):
    root, source, digest = managed
    outside = tmp_path / "outside"
    outside.mkdir()
    if location == "destination":
        root.mkdir()
        symlink_or_skip(root / f"{digest}.jar", source)
    elif location == "root":
        symlink_or_skip(root, outside, directory=True)
    else:
        linked = tmp_path / "linked"
        symlink_or_skip(linked, outside, directory=True)
        monkeypatch.setenv("XHH_SIGNER_HOME", str(linked / "nested"))
    with pytest.raises(XhhSignerError, match="link|reparse"):
        signer_module.install_signer(source, sha256=digest)
    assert list(outside.iterdir()) == []


def test_inspect_rejects_linked_managed_artifact(managed):
    root, source, digest = managed
    root.mkdir()
    symlink_or_skip(root / f"{digest}.jar", source)
    with pytest.raises(XhhSignerError, match="link|reparse"):
        signer_module.inspect_signer(f"managed:{digest}")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction validation")
def test_store_rejects_windows_junction_before_any_write(managed, tmp_path):
    import _winapi

    root, source, digest = managed
    outside = tmp_path / "outside"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(root))
    with pytest.raises(XhhSignerError, match="link|reparse"):
        signer_module.install_signer(source, sha256=digest)
    with pytest.raises(XhhSignerError, match="link|reparse"):
        signer_module.inspect_signer(f"managed:{digest}")
    assert list(outside.iterdir()) == []


def test_source_changed_during_import_is_hashed_from_copied_bytes(managed, monkeypatch):
    root, source, digest = managed
    original_open = Path.open

    def changed_open(path, *args, **kwargs):
        if path == source and args == ("rb",):
            source.write_bytes(b"changed before source read")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changed_open)
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        signer_module.install_signer(source, sha256=digest)
    assert list(root.iterdir()) == []


def test_tampered_managed_artifact_fails_before_java_discovery(managed):
    root, source, digest = managed
    reference = signer_module.install_signer(source, sha256=digest)
    (root / f"{digest}.jar").write_bytes(b"tampered")
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        make_signer(reference)
    with pytest.raises(XhhSignerError, match="SHA-256 mismatch"):
        signer_module.inspect_signer(reference)

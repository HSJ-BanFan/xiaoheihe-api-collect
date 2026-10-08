"""BYO-APK preparation uses synthetic ZIPs and never starts Java."""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from xhh_sdk.exceptions import XhhSignerError


def resources_module():
    name = "xhh_sdk.signer_resources"
    assert importlib.util.find_spec(name) is not None, "BYO-APK resource preparation is missing"
    return importlib.import_module(name)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    module = resources_module()
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

    def write(extra=None):
        with zipfile.ZipFile(apk, "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)
            if extra:
                archive.writestr(*extra)
        profile = {
            "id": "synthetic-test-profile", "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            "apk_bytes": apk.stat().st_size,
            "members": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                        for name, data in members.items()},
        }
        monkeypatch.setattr(module, "PROFILE", profile)
        return profile

    profile = write()
    return module, apk, tmp_path / "resources", members, profile, write


def test_prepare_creates_only_verified_resources_and_manifest(sample):
    module, apk, out, members, profile, _ = sample
    result = module.prepare_resources(apk, out)
    assert result["profile_id"] == profile["id"]
    assert result["signer_executed"] is False
    assert result["online_verified"] is False
    assert {p.name for p in out.iterdir()} == {"minimal-app.apk", "libglesv3_1.so", "manifest.json"}
    with zipfile.ZipFile(out / "minimal-app.apk") as minimal:
        assert set(minimal.namelist()) == set(members) - {"lib/arm64-v8a/libglesv3_1.so"}
        for name in minimal.namelist():
            assert minimal.read(name) == members[name]
    assert (out / "libglesv3_1.so").read_bytes() == members["lib/arm64-v8a/libglesv3_1.so"]
    assert str(apk) not in (out / "manifest.json").read_text()
    assert module.inspect_resources(out)["profile_id"] == profile["id"]


def test_unknown_apk_leaves_no_output(sample):
    module, apk, out, _, _, _ = sample
    apk.write_bytes(b"not the supported APK")
    with pytest.raises(XhhSignerError, match="unsupported APK"):
        module.prepare_resources(apk, out)
    assert not out.exists()


def test_member_digest_mismatch_is_rejected(sample):
    module, apk, out, _, profile, _ = sample
    profile["members"]["AndroidManifest.xml"]["sha256"] = "0" * 64
    with pytest.raises(XhhSignerError, match="member integrity"):
        module.prepare_resources(apk, out)
    assert not out.exists()


@pytest.mark.parametrize("extra", [("AndroidManifest.xml", b"duplicate"), ("../escape", b"unsafe")])
def test_ambiguous_or_unsafe_zip_is_rejected(sample, extra):
    module, apk, out, _, _, write = sample
    write(extra)
    with pytest.raises(XhhSignerError, match="duplicate|unsafe"):
        module.prepare_resources(apk, out)
    assert not out.exists()


def test_wrong_abi_is_rejected_even_with_matching_test_profile(sample):
    module, apk, out, members, _, write = sample
    members["lib/arm64-v8a/libglesv3_1.so"] = b"not an ARM64 ELF file"
    write()
    with pytest.raises(XhhSignerError, match="ARM64"):
        module.prepare_resources(apk, out)
    assert not out.exists()


def test_existing_output_is_never_overwritten(sample):
    module, apk, out, _, _, _ = sample
    out.mkdir()
    (out / "keep.txt").write_text("user content")
    with pytest.raises(XhhSignerError, match="already exists"):
        module.prepare_resources(apk, out)
    assert (out / "keep.txt").read_text() == "user content"
    assert list(out.iterdir()) == [out / "keep.txt"]


@pytest.mark.parametrize("name", ["minimal-app.apk", "libglesv3_1.so", "manifest.json"])
def test_tampered_prepared_resource_fails_inspection(sample, name):
    module, apk, out, _, _, _ = sample
    module.prepare_resources(apk, out)
    (out / name).write_bytes(b"tampered")
    with pytest.raises(XhhSignerError):
        module.inspect_resources(out)


def test_manifest_cannot_replace_the_shipped_compatibility_hashes(sample):
    module, apk, out, _, _, _ = sample
    module.prepare_resources(apk, out)
    (out / "libglesv3_1.so").write_bytes(b"changed library")
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files"]["libglesv3_1.so"]["sha256"] = hashlib.sha256(b"changed library").hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(XhhSignerError):
        module.inspect_resources(out)


def test_outputs_are_deterministic_and_survive_source_removal(sample, tmp_path):
    module, apk, out, _, _, _ = sample
    module.prepare_resources(apk, out)
    other = tmp_path / "other"
    module.prepare_resources(apk, other)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == {p.name: p.read_bytes() for p in other.iterdir()}
    apk.unlink()
    assert module.inspect_resources(other)["profile_id"] == "synthetic-test-profile"


def test_inspection_returns_normalized_absolute_manifest(sample):
    module, apk, out, _, _, _ = sample
    module.prepare_resources(apk, out)
    result = module.inspect_resources(out / ".." / out.name)
    assert result["manifest"] == str(out.resolve() / "manifest.json")


def test_failed_final_verification_removes_only_the_new_preparation(sample, monkeypatch):
    module, apk, out, _, _, _ = sample

    def failed(_):
        raise XhhSignerError("injected final verification failure")

    monkeypatch.setattr(module, "inspect_resources", failed)
    with pytest.raises(XhhSignerError, match="injected"):
        module.prepare_resources(apk, out)
    assert not out.exists()


def test_extra_resource_file_is_rejected(sample):
    module, apk, out, _, _, _ = sample
    module.prepare_resources(apk, out)
    (out / "unreviewed.dll").write_bytes(b"extra")
    with pytest.raises(XhhSignerError, match="unexpected"):
        module.inspect_resources(out)


def test_partial_manifest_write_is_cleaned(sample, monkeypatch):
    module, apk, out, _, _, _ = sample
    original = Path.open

    class BrokenWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, data):
            self.stream.write(data[:10])
            raise OSError("injected full disk")

    def opened(path, mode="r", *args, **kwargs):
        stream = original(path, mode, *args, **kwargs)
        if path.name == "manifest.json" and mode == "xb":
            return BrokenWriter(stream)
        return stream

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(XhhSignerError, match="cannot prepare"):
        module.prepare_resources(apk, out)
    assert not out.exists()


def test_cli_preparation_requires_confirmation_without_reading_apk(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-B", "-m", "xhh_sdk.cli", "signer", "prepare-apk", "missing.apk",
         "--out", str(tmp_path / "output")], cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "refusing APK preparation without --confirm" in result.stderr
    assert not (tmp_path / "output").exists()


def test_catalogue_explains_preparation_without_online_claims():
    from xhh_sdk.catalog import select
    names = {entry["name"]: entry for entry in select(search="signer")["commands"]}
    assert "signer prepare-apk" in names
    assert "signer inspect-resources" in names
    for name in ("signer prepare-apk", "signer inspect-resources"):
        assert names[name]["routes"] == []
        assert names[name]["live_retested"] is False


def test_inspect_apk_reports_a_supported_sample(sample):
    module, apk, _, _, profile, _ = sample
    report = module.inspect_apk(apk)
    assert report["supported"] is True
    assert report["problems"] == []
    assert report["matches_supported_apk"] is True
    assert report["profile_id"] == profile["id"]
    assert all(entry["matches"] for entry in report["members"].values())
    assert report["members"][module.LIBRARY]["arm64_elf"] is True


def test_inspect_apk_explains_a_different_app_version(sample):
    module, apk, _, members, _, write = sample
    pinned = {name: dict(entry) for name, entry in module.PROFILE["members"].items()}
    pinned_sha = module.PROFILE["apk_sha256"]
    pinned_bytes = module.PROFILE["apk_bytes"]
    members["lib/arm64-v8a/libglesv3_1.so"] = b"\x7fELF\x02\x01" + bytes(58)
    write()
    module.PROFILE["members"] = pinned
    module.PROFILE["apk_sha256"] = pinned_sha
    module.PROFILE["apk_bytes"] = pinned_bytes
    report = module.inspect_apk(apk)
    assert report["supported"] is False
    assert report["matches_supported_apk"] is False
    assert any("not the supported sample" in problem for problem in report["problems"])
    assert any(module.LIBRARY in problem for problem in report["problems"])


def test_inspect_apk_reports_a_missing_member(sample):
    module, apk, _, members, _, write = sample
    pinned = {name: dict(entry) for name, entry in module.PROFILE["members"].items()}
    del members["META-INF/CERT.RSA"]
    write()
    module.PROFILE["members"] = pinned
    report = module.inspect_apk(apk)
    assert report["supported"] is False
    assert report["members"]["META-INF/CERT.RSA"]["present"] is False
    assert any("missing member" in problem for problem in report["problems"])


def test_inspect_apk_rejects_a_non_zip_file(sample, tmp_path):
    module, _, _, _, _, _ = sample
    broken = tmp_path / "not-an-apk.apk"
    broken.write_bytes(b"this is not a zip archive")
    report = module.inspect_apk(broken)
    assert report["supported"] is False
    assert any("not a readable APK" in problem for problem in report["problems"])


def test_inspect_apk_rejects_a_missing_file(sample, tmp_path):
    module, _, _, _, _, _ = sample
    with pytest.raises(XhhSignerError, match="not found"):
        module.inspect_apk(tmp_path / "absent.apk")


def test_cli_inspect_apk_exit_code_follows_support(sample, capsys):
    from xhh_sdk import cli
    module, apk, _, _, _, _ = sample
    assert cli.main(["signer", "inspect-apk", str(apk)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["supported"] is True

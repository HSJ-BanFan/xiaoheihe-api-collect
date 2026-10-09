import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import warnings
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill-kit/xiaoheihe-publisher/scripts"


def load(name):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if name == "xhh_setup" and module.runtime is None:
        # Unit tests inject the helper; real subprocess tests exercise its integrity gate.
        module.runtime = load("setup_runtime")
    return module


@pytest.fixture
def runtime():
    if not (SCRIPTS / "setup_runtime.py").exists():
        pytest.skip("runtime not implemented")
    return load("setup_runtime")


def artifact(raw, name="fixture.jar"):
    return {"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "url": "https://repo.maven.apache.org/maven2/fixture/" + name}


def test_one_command_entrypoint_exists():
    assert (SCRIPTS / "xhh_setup.py").is_file(), "one-command setup missing"
    assert (SCRIPTS / "setup_runtime.py").is_file()


def test_help_and_confirmation_need_no_runtime_or_writes(tmp_path):
    if not (SCRIPTS / "xhh_setup.py").exists():
        pytest.skip("setup not implemented")
    env = {**os.environ, "XHH_SETUP_HOME": str(tmp_path / "cache")}
    for argv in (["--help"], ["--apk", "does-not-exist.apk"]):
        result = subprocess.run([sys.executable, "-I", str(SCRIPTS / "xhh_setup.py"), *argv],
                                capture_output=True, text=True, encoding="utf-8", env=env, timeout=10)
        assert result.returncode == (0 if argv == ["--help"] else 2)
    assert not (tmp_path / "cache").exists()


def test_offline_cache_rechecks_digest_and_refuses_missing(runtime, tmp_path):
    value = artifact(b"exact artifact")
    with pytest.raises(runtime.Refused, match="offline_cache_missing"):
        runtime.download(value, tmp_path, True)
    path = tmp_path / (value["sha256"] + "-" + value["name"])
    path.write_bytes(b"exact artifact")
    assert runtime.download(value, tmp_path, True) == path
    path.write_bytes(b"tampered")
    with pytest.raises(runtime.Refused, match="artifact_mismatch"):
        runtime.download(value, tmp_path, True)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a\\b", "C:drive", "a/../b", "CON", "x."])
def test_archive_unsafe_members_refused(runtime, tmp_path, name):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(name, b"x")
    if "\\" in name:
        archive.write_bytes(archive.read_bytes().replace(b"a/b", b"a\\b"))
    with zipfile.ZipFile(archive) as source, pytest.raises(runtime.Refused):
        runtime.zip_index(source)


@pytest.mark.parametrize("kind", ["duplicate", "case", "symlink"])
def test_archive_duplicate_case_and_symlink_refused(runtime, tmp_path, kind):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("a", b"x")
        if kind == "symlink":
            info = zipfile.ZipInfo("b")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            output.writestr(info, "a")
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                output.writestr("a" if kind == "duplicate" else "A", b"x")
    with zipfile.ZipFile(archive) as source, pytest.raises(runtime.Refused):
        runtime.zip_index(source)


def test_release_lock_rejects_unknown_fields(runtime):
    lock = json.loads((SCRIPTS.parent / "references/signer-release.json").read_text())
    runtime.validate_lock(lock)
    lock["unreviewed"] = True
    with pytest.raises(runtime.Refused, match="release_lock_invalid"):
        runtime.validate_lock(lock)


@pytest.mark.parametrize("url", ["http://github.com/a", "https://evil.example/a", "https://github.com:443/a",
                                 "https://user:secret@github.com/a", "https://github.com.evil.example/a"])
def test_untrusted_download_urls_refused(runtime, url):
    with pytest.raises(runtime.Refused):
        runtime.check_url(url)


def test_dependency_install_concurrent_and_corrupt_refusal(runtime, tmp_path):
    source = tmp_path / "source.jar"
    source.write_bytes(b"bytes")
    pins = {source.name: {key: value for key, value in artifact(b"bytes").items() if key in {"bytes", "sha256"}}}
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(lambda _: runtime.install_dependencies(bundle, pins, {source.name: source}), range(2)))
    assert (bundle / "deps" / source.name).read_bytes() == b"bytes"
    (bundle / "deps" / "extra.jar").write_bytes(b"x")
    with pytest.raises(runtime.Refused, match="dependency_inventory_mismatch"):
        runtime.install_dependencies(bundle, pins, {source.name: source})
    assert (bundle / "deps" / "extra.jar").read_bytes() == b"x"


def test_java_probe_filters_environment(runtime, tmp_path, monkeypatch):
    path = tmp_path / "java.exe"
    path.write_bytes(b"fixture")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:secret")
    monkeypatch.setenv("XHH_PKEY", "synthetic-secret")
    def run(argv, **kwargs):
        assert "JAVA_TOOL_OPTIONS" not in kwargs["env"]
        assert "XHH_PKEY" not in kwargs["env"]
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(argv, 0, "", "java.specification.version = 17\nsun.arch.data.model = 64\n")
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.probe_java(path) == 17


def test_selftest_checks_reference_not_only_safe_fields(runtime):
    expected = {"timestamp": 1700000000, "hkey": "FC0EAF1B", "_rnd": "14:E94DBC87"}
    good = {"_time": "1700000000", "hkey": "FC0EAF1B", "_rnd": "14:E94DBC87", "nonce": "synthetic"}
    runtime.match_selftest(good, expected)
    for key in good:
        bad = {**good, key: "" if key == "nonce" else "wrong"}
        with pytest.raises(runtime.Refused, match="selftest_mismatch"):
            runtime.match_selftest(bad, expected)


@pytest.mark.parametrize("outcome", ["success", "mismatch", "timeout"])
def test_account_binding_is_last_and_only_after_reference_match(tmp_path, monkeypatch, outcome):
    setup = load("xhh_setup")
    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setattr(setup.platform, "machine", lambda: "AMD64")
    lock = json.loads((SCRIPTS.parent / "references/signer-release.json").read_text())
    loader = tmp_path / "loader.jar"
    loader.write_bytes(b"synthetic pinned loader")
    lock["bootstrap"].update({key: value for key, value in artifact(loader.read_bytes()).items()
                              if key in {"bytes", "sha256"}})
    monkeypatch.setattr(setup.cli, "read_json", lambda _: lock)
    monkeypatch.setattr(setup.cli, "activate_runtime", lambda: None)
    monkeypatch.syspath_prepend(str(ROOT / "cli"))
    from xhh_sdk import signer_resources, signer_bundle, signer, accounts
    monkeypatch.setattr(signer_resources, "prepare_resources", lambda *args: {})
    monkeypatch.setattr(setup.runtime, "select_java", lambda *args: (tmp_path / "java.exe", 17, "explicit"))
    monkeypatch.setattr(setup.runtime, "download", lambda value, *args: tmp_path / value["name"])
    monkeypatch.setattr(setup.runtime, "resource_jar", lambda *args: tmp_path / "resources.jar")
    monkeypatch.setattr(setup.runtime, "install_dependencies", lambda *args: None)
    monkeypatch.setattr(setup, "verify_embedded_lock", lambda *args: None)
    monkeypatch.setattr(signer_bundle, "install_bundle", lambda *args, **kwargs: "bundle:" + "a" * 64)
    monkeypatch.setattr(signer_bundle, "resolve_bundle", lambda *args: {
        "directory": str(tmp_path), "loader": str(loader),
        "loader_sha256": lock["bootstrap"]["sha256"], "resources": str(tmp_path / "resources")})
    events = []
    class SyntheticSigner:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 60
            self.jar = loader
            self.sha256 = lock["bootstrap"]["sha256"]
            self.resources = tmp_path / "resources"
        def sign(self, path, timestamp):
            events.append("sign")
            assert path == "/account/info" and timestamp == 1700000000
            if outcome == "timeout":
                raise TimeoutError("private data")
            return {"_time": "1700000000", "nonce": "safe", "_rnd": lock["selftest"]["_rnd"],
                    "hkey": lock["selftest"]["hkey"] if outcome == "success" else "wrong"}
    monkeypatch.setattr(signer, "Signer", SyntheticSigner)
    class Store:
        def __init__(self, root):
            assert events == ["sign"]
            events.append("account")
            assert root == tmp_path / "store"
        def get(self, alias):
            assert alias == "synthetic"
            return SimpleNamespace(config={"imei": "preserved"})
        def configure(self, alias, patch):
            assert set(patch) == {"signer_bundle", "java"}
            events.append("configure")
    monkeypatch.setattr(accounts, "AccountStore", Store)
    args = SimpleNamespace(confirm=True, apk=tmp_path / "source.apk", java=None, install_java=False,
                           offline=True, account="synthetic", data_dir=tmp_path / "store")
    receipt = {"selftest": {"executed": False, "matched": False}}
    if outcome == "success":
        assert setup.setup(args, receipt)["state"] == "ready"
        assert events == ["sign", "account", "configure"]
    else:
        with pytest.raises((setup.Refused, setup.runtime.Refused), match="selftest_"):
            setup.setup(args, receipt)
        assert events == ["sign"]


def test_unsupported_apk_does_not_download_or_inspect_accounts(tmp_path, monkeypatch):
    setup = load("xhh_setup")
    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setattr(setup.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(setup.cli, "activate_runtime", lambda: None)
    monkeypatch.syspath_prepend(str(ROOT / "cli"))
    monkeypatch.setattr(setup.runtime, "select_java", lambda *args: pytest.fail("Java called before APK validation"))
    monkeypatch.setattr(setup.runtime, "download", lambda *args: pytest.fail("download before APK validation"))
    bad = tmp_path / "wrong.apk"
    bad.write_bytes(b"not supported")
    args = SimpleNamespace(confirm=True, apk=bad, account=None)
    with pytest.raises(setup.Refused, match="unsupported_apk"):
        setup.setup(args, {"selftest": {"executed": False, "matched": False}})


def test_managed_java_reuse_checks_every_extracted_file(runtime, tmp_path, monkeypatch):
    lock = json.loads((SCRIPTS.parent / "references/signer-release.json").read_text())
    root = tmp_path / "runtimes" / lock["artifacts"]["temurin-jre"]["sha256"]
    root.mkdir(parents=True)
    (root / "unexpected").write_bytes(b"x")
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setattr(runtime, "download", lambda *args: pytest.fail("must refuse corrupt installed JRE"))
    with pytest.raises(runtime.Refused, match="java_inventory_mismatch"):
        runtime.select_java(None, True, True, tmp_path, lock)


@pytest.mark.parametrize("change", ["manifest", "bytes", "signer-reresolve", "signer-bytes", "signer-resources"])
def test_existing_bundle_cannot_substitute_the_release_loader(tmp_path, monkeypatch, change):
    setup = load("xhh_setup")
    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setattr(setup.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(setup.cli, "activate_runtime", lambda: None)
    monkeypatch.syspath_prepend(str(ROOT / "cli"))
    from xhh_sdk import signer_resources, signer_bundle, signer
    lock = json.loads((SCRIPTS.parent / "references/signer-release.json").read_text())
    good = b"synthetic pinned loader"
    pin = artifact(good)
    lock["bootstrap"].update({key: pin[key] for key in ("bytes", "sha256")})
    monkeypatch.setattr(setup.cli, "read_json", lambda _: lock)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    loader = bundle / "loader.jar"
    loader.write_bytes(b"untrusted loader" if change == "bytes" else good)
    other = bundle / "other.jar"
    other.write_bytes(b"untrusted loader")
    reference = "bundle:" + "a" * 64
    resolved = {"reference": reference, "directory": str(bundle), "loader": str(loader),
                "loader_sha256": "b" * 64 if change == "manifest" else pin["sha256"],
                "resources": str(bundle / "resources")}
    resolutions = []
    def resolve(_):
        resolutions.append(True)
        if change == "signer-reresolve" and len(resolutions) > 1:
            return {**resolved, "loader": str(other), "loader_sha256": hashlib.sha256(other.read_bytes()).hexdigest()}
        if change == "signer-bytes" and len(resolutions) > 1:
            loader.write_bytes(b"untrusted loader")
        if change == "signer-resources" and len(resolutions) > 1:
            return {**resolved, "resources": str(tmp_path / "different-resources")}
        return resolved
    monkeypatch.setattr(signer_bundle, "resolve_bundle", resolve)
    monkeypatch.setattr(signer_bundle, "install_bundle", lambda *args, **kwargs: reference)
    monkeypatch.setattr(signer_resources, "prepare_resources", lambda *args: {})
    monkeypatch.setattr(setup.runtime, "select_java", lambda *args: (tmp_path / "java.exe", 17, "explicit"))
    monkeypatch.setattr(setup.runtime, "download", lambda value, *args: tmp_path / value["name"])
    monkeypatch.setattr(setup.runtime, "resource_jar", lambda *args: tmp_path / "resources.jar")
    monkeypatch.setattr(setup.runtime, "install_dependencies", lambda *args: None)
    monkeypatch.setattr(setup, "verify_embedded_lock", lambda *args: None)
    monkeypatch.setattr(signer.shutil, "which", lambda _: str(tmp_path / "java.exe"))
    monkeypatch.setattr(signer.Signer, "sign", lambda *args, **kwargs: pytest.fail("unpinned loader reached execution"))
    monkeypatch.setattr(setup, "bind_account", lambda *args: pytest.fail("unverified loader reached account binding"))
    args = SimpleNamespace(confirm=True, apk=tmp_path / "source.apk", java=None, install_java=False,
                           offline=True, account="synthetic", data_dir=tmp_path / "store")
    receipt = {"selftest": {"executed": False, "matched": False}}
    with pytest.raises(ValueError, match="(?:loader_pin_mismatch|artifact_mismatch)"):
        setup.setup(args, receipt)
    assert receipt["selftest"] == {"executed": False, "matched": False}


@pytest.mark.parametrize("mode", ["help", "no-confirm", "confirm"])
def test_unverified_helper_never_executes(tmp_path, mode):
    copied = tmp_path / "kit" / "scripts"
    copied.mkdir(parents=True)
    for name in ("xhh_setup.py", "xhh_cli.py", "setup_runtime.py"):
        shutil.copyfile(SCRIPTS / name, copied / name)
    cli = load("xhh_cli")
    files = {}
    for name in {*cli.SOURCE_MEMBERS, *("runtime/" + item for item in cli.RUNTIME_MEMBERS)}:
        path = copied.parent / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic member")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "kit_name": cli.KIT_NAME, "kit_version": cli.KIT_VERSION,
                "cli_version": cli.CLI_VERSION, "wheel_sha256": cli.WHEEL_SHA256, "files": files}
    (copied.parent / "kit-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    cli.KIT_ROOT = copied.parent
    cli.verify_runtime()
    sentinel = tmp_path / "helper-executed"
    helper = copied / "setup_runtime.py"
    helper.write_text(helper.read_text(encoding="utf-8") +
                      f"\nPath({str(sentinel)!r}).write_text('executed')\n", encoding="utf-8")
    args = ["--help"] if mode == "help" else ["--apk", "missing.apk"]
    if mode == "confirm":
        args.append("--confirm")
    result = subprocess.run([sys.executable, "-I", str(copied / "xhh_setup.py"), *args],
                            capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert not sentinel.exists(), "Helper executed before confirmation and kit verification"
    assert result.returncode == (0 if mode == "help" else 2)
    if mode != "help":
        assert json.loads(result.stdout)["reason"] == (
            "confirmation_required" if mode == "no-confirm" else "kit_integrity_failed")

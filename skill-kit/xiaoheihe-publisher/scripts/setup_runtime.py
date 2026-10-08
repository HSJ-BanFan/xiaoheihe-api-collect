"""Pinned downloads, local runtime storage and Java checks for xhh_setup."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
import urllib.request
import zipfile


class Refused(ValueError):
    """Fixed machine-readable refusal reason, never a raw upstream message."""


HOSTS = {"github.com", "codeload.github.com", "release-assets.githubusercontent.com",
         "objects.githubusercontent.com", "repo.maven.apache.org"}
ENV_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT",
            "LANG", "LC_ALL", "TEMP", "TMP", "TMPDIR"}
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"{name}{i}" for name in ("COM", "LPT") for i in range(1, 10))}
ARTIFACT_IDS = {"apk-parser", "capstone", "commons-codec", "commons-collections4", "commons-io",
                "demumble", "fastjson", "fastjson2", "fastjson2-extension", "jna", "keystone",
                "native-lib-loader", "slf4j-api", "slf4j-simple", "temurin-jre", "unicorn",
                "unidbg-dynarmic", "unidbg-source", "unidbg-unicorn2"}


def reject_links(path):
    path = Path(path).absolute()
    for entry in (*reversed(path.parents), path):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Refused("unsafe_link_path")
    return path


def check_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username
            or parsed.password or parsed.port or parsed.fragment
            or any(ord(char) < 33 for char in url)):
        raise Refused("untrusted_download_url")
    return url


def safe_member(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise Refused("unsafe_archive_member")
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or any(
        part in {"..", "."} or part.endswith((".", " ")) or part.split(".")[0].upper() in RESERVED
        or any(ord(char) < 32 for char in part) for part in path.parts
    ):
        raise Refused("unsafe_archive_member")
    return name


def check_pin(value):
    if (not isinstance(value, dict) or set(value) != {"sha256", "bytes"}
            or type(value["bytes"]) is not int or not 0 <= value["bytes"] <= 512 * 1024 * 1024
            or not isinstance(value["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", value["sha256"])):
        raise Refused("release_lock_invalid")


def validate_lock(lock):
    try:
        if (not isinstance(lock, dict) or set(lock) != {"schema_version", "version", "platform", "profile_id",
                "bootstrap", "artifacts", "dependencies", "resources", "java", "selftest"}
                or lock["schema_version"] != 1 or lock["version"] != "0.2.0"
                or lock["platform"] != "windows-x86_64"
                or lock["profile_id"] != "heybox-arm64-001c9a49-v1"):
            raise Refused("release_lock_invalid")
        artifacts = lock["artifacts"]
        if not isinstance(artifacts, dict) or set(artifacts) != ARTIFACT_IDS:
            raise Refused("release_lock_invalid")
        names = set()
        for value in [lock["bootstrap"], *artifacts.values()]:
            if set(value) != {"name", "url", "sha256", "bytes"}:
                raise Refused("release_lock_invalid")
            if safe_member(value["name"]) != Path(value["name"]).name or value["name"].casefold() in names:
                raise Refused("release_lock_invalid")
            names.add(value["name"].casefold())
            check_url(value["url"])
            check_pin({key: value[key] for key in ("sha256", "bytes")})
        resources = lock["resources"]
        if set(resources) != {"name", "artifact", "members"} or resources["artifact"] != "unidbg-source":
            raise Refused("release_lock_invalid")
        safe_member(resources["name"])
        if not isinstance(resources["members"], dict) or not resources["members"]:
            raise Refused("release_lock_invalid")
        targets = set()
        for name, value in resources["members"].items():
            safe_member(name)
            if set(value) != {"path", "sha256", "bytes"}:
                raise Refused("release_lock_invalid")
            target = safe_member(value["path"])
            if target.casefold() in targets:
                raise Refused("release_lock_invalid")
            targets.add(target.casefold())
            check_pin({key: value[key] for key in ("sha256", "bytes")})
        expected = {value["name"]: {key: value[key] for key in ("sha256", "bytes")}
                    for value in artifacts.values() if value["name"].endswith(".jar")}
        dependencies = lock["dependencies"]
        if set(dependencies) != set(expected) | {resources["name"]}:
            raise Refused("release_lock_invalid")
        for name, value in dependencies.items():
            if "/" in safe_member(name) or not name.endswith(".jar"):
                raise Refused("release_lock_invalid")
            check_pin(value)
            if name in expected and expected[name] != value:
                raise Refused("release_lock_invalid")
        java = lock["java"]
        if set(java) != {"artifact", "executable", "files"} or java["artifact"] != "temurin-jre":
            raise Refused("release_lock_invalid")
        if java["executable"] not in java["files"] or not java["executable"].endswith("/bin/java.exe"):
            raise Refused("release_lock_invalid")
        targets = set()
        for name, value in java["files"].items():
            safe_member(name)
            if name.casefold() in targets:
                raise Refused("release_lock_invalid")
            targets.add(name.casefold())
            check_pin(value)
        vector = lock["selftest"]
        if (set(vector) != {"path", "timestamp", "identity", "imei", "device_info", "os_version", "app_version", "hkey", "_rnd"}
                or vector["timestamp"] != 1700000000 or vector["path"] != "/account/info"):
            raise Refused("release_lock_invalid")
        return lock
    except (KeyError, TypeError, ValueError) as error:
        raise Refused("release_lock_invalid") from error


def verify_file(path, expected):
    path = reject_links(path)
    if not path.is_file() or path.stat().st_size != expected["bytes"]:
        raise Refused("artifact_mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise Refused("artifact_mismatch")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected["sha256"]:
        raise Refused("artifact_mismatch")
    return path


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        check_url(url)
        return super().redirect_request(request, response, code, message, headers, url)


def download(artifact, cache, offline):
    check_url(artifact["url"])
    cache = reject_links(cache)
    destination = cache / (artifact["sha256"] + "-" + artifact["name"])
    reject_links(destination)
    if destination.exists():
        return verify_file(destination, artifact)
    if offline:
        raise Refused("offline_cache_missing")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        opener = urllib.request.build_opener(TrustedRedirect())
        deadline = time.monotonic() + 180
        with opener.open(artifact["url"], timeout=30) as response, tempfile.NamedTemporaryFile(
                prefix=".download-", dir=cache, delete=False) as output:
            temporary = Path(output.name)
            count = 0
            while True:
                block = response.read(min(1024 * 1024, artifact["bytes"] + 1 - count))
                if time.monotonic() > deadline:
                    raise Refused("download_timeout")
                if not block:
                    break
                count += len(block)
                if count > artifact["bytes"]:
                    raise Refused("artifact_mismatch")
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        verify_file(temporary, artifact)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            pass
        return verify_file(destination, artifact)
    except (OSError, TimeoutError) as error:
        raise Refused("download_failed") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def zip_index(archive):
    result, folded, total = {}, set(), 0
    for info in archive.infolist():
        safe_member(info.orig_filename.rstrip("/") if info.is_dir() else info.orig_filename)
        name = safe_member(info.filename.rstrip("/") if info.is_dir() else info.filename)
        mode = info.external_attr >> 16
        if (name.casefold() in folded or stat.S_ISLNK(mode) or info.flag_bits & 1
                or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
            raise Refused("unsafe_archive_member")
        folded.add(name.casefold())
        total += info.file_size
        if total > 1024 * 1024 * 1024 or info.file_size > 512 * 1024 * 1024:
            raise Refused("archive_size_limit")
        if not info.is_dir():
            result[name] = info
    return result


def member_bytes(archive, index, name, expected):
    if name not in index or index[name].file_size != expected["bytes"]:
        raise Refused("archive_member_mismatch")
    with archive.open(index[name]) as source:
        raw = source.read(expected["bytes"] + 1)
    if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise Refused("archive_member_mismatch")
    return raw


def resource_jar(lock, source, cache):
    value = lock["resources"]
    expected = lock["dependencies"][value["name"]]
    target = cache / (expected["sha256"] + "-" + value["name"])
    reject_links(target)
    if target.exists():
        return verify_file(target, expected)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".resources-", dir=cache, delete=False) as output:
            temporary = Path(output.name)
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(temporary, "w") as output:
            index = zip_index(archive)
            for name, member in sorted(value["members"].items(), key=lambda pair: pair[1]["path"]):
                raw = member_bytes(archive, index, name, member)
                info = zipfile.ZipInfo(member["path"], (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                output.writestr(info, raw)
        verify_file(temporary, expected)
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        return verify_file(target, expected)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_tree(root, pins, reason):
    reject_links(root)
    actual = set()
    for path in root.rglob("*"):
        reject_links(path)
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise Refused(reason)
    directories = {str(parent) for name in pins for parent in PurePosixPath(name).parents if str(parent) != "."}
    actual_directories = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()}
    if actual != set(pins) or actual_directories != directories:
        raise Refused(reason)
    for name, expected in pins.items():
        verify_file(root / name, expected)


def publish_directory(staging, destination, pins, reason):
    verify_tree(staging, pins, reason)
    reject_links(destination)
    try:
        staging.rename(destination)
    except OSError:
        if not destination.is_dir():
            raise
    verify_tree(destination, pins, reason)


def install_dependencies(bundle, pins, sources):
    destination = reject_links(bundle) / "deps"
    reject_links(destination)
    if destination.exists():
        verify_tree(destination, pins, "dependency_inventory_mismatch")
        return
    with tempfile.TemporaryDirectory(prefix=".deps-", dir=bundle) as temporary:
        staging = Path(temporary) / "complete"
        staging.mkdir()
        for name, expected in pins.items():
            verify_file(sources[name], expected)
            shutil.copyfile(sources[name], staging / name)
        publish_directory(staging, destination, pins, "dependency_inventory_mismatch")


def probe_java(java):
    java = reject_links(java)
    if not java.is_file():
        raise Refused("java_invalid")
    env = {key: value for key, value in os.environ.items() if key.upper() in ENV_KEYS}
    try:
        result = subprocess.run([str(java), "-XshowSettings:properties", "-version"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=15, env=env,
                                shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused("java_invalid") from error
    version = re.search(r"java\.specification\.version\s*=\s*(\d+)\s", result.stderr + "\n")
    architecture = re.search(r"sun\.arch\.data\.model\s*=\s*64\s", result.stderr + "\n")
    if result.returncode or not version or int(version[1]) < 17 or not architecture:
        raise Refused("java_invalid")
    return int(version[1])


def select_java(explicit, install, offline, home, lock):
    if explicit:
        path = Path(shutil.which(str(explicit)) or explicit).expanduser().absolute()
        return path, probe_java(path), "explicit"
    candidates = [shutil.which("java")]
    if os.environ.get("JAVA_HOME"):
        candidates.append(str(Path(os.environ["JAVA_HOME"]) / "bin/java.exe"))
    for value in candidates:
        if value:
            try:
                path = Path(value).absolute()
                return path, probe_java(path), "system"
            except Refused:
                pass
    artifact = lock["artifacts"][lock["java"]["artifact"]]
    root = home / "runtimes" / artifact["sha256"]
    reject_links(root)
    if root.exists():
        verify_tree(root, lock["java"]["files"], "java_inventory_mismatch")
    else:
        if not install:
            raise Refused("java_missing")
        archive_path = download(artifact, home / "downloads", offline)
        root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".java-", dir=root.parent) as temporary:
            staging = Path(temporary) / "complete"
            staging.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                index = zip_index(archive)
                if set(index) != set(lock["java"]["files"]):
                    raise Refused("java_inventory_mismatch")
                for name, expected in lock["java"]["files"].items():
                    path = staging / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(member_bytes(archive, index, name, expected))
            publish_directory(staging, root, lock["java"]["files"], "java_inventory_mismatch")
    path = root / lock["java"]["executable"]
    return path, probe_java(path), "managed"


def match_selftest(actual, expected):
    if (actual.get("_time") != str(expected["timestamp"]) or actual.get("hkey") != expected["hkey"]
            or actual.get("_rnd") != expected["_rnd"] or not actual.get("nonce")):
        raise Refused("selftest_mismatch")

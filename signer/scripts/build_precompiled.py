"""Maintainer-only Java build. End users run the precompiled release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "2ded0545d4ae053055f469ef4a4c49e3f15196a7"
VERSION = "0.2.0"
RELEASE_URL = "https://github.com/HSJ-BanFan/xiaoheihe-api-collect/releases/download/xhh-signer-v" + VERSION
FACTORIES = (
    "backend/unicorn2/src/main/java/com/github/unidbg/arm/backend/Unicorn2Factory.java",
    "backend/dynarmic/src/main/java/com/github/unidbg/arm/backend/DynarmicFactory.java",
)
JAVA_ROOTS = ("unidbg-api/src/main/java/", "unidbg-android/src/main/java/")
RESOURCE_ROOTS = ("unidbg-api/src/main/resources/", "unidbg-android/src/main/resources/",
                  "backend/unicorn2/src/main/resources/", "backend/dynarmic/src/main/resources/")
PATCHES = ("unidbg-api/src/main/java/com/github/unidbg/arm/AbstractARMDebugger.java",
           "unidbg-android/src/main/java/com/github/unidbg/linux/AndroidElfLoader.java")


def pin(raw):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def write_zip(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(members.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)


def tsv(pins):
    return "".join(f"{name}\t{value['sha256']}\t{value['bytes']}\n"
                   for name, value in pins.items()).encode("ascii")


def acquire(artifact, cache):
    path = cache / artifact["name"]
    if not path.exists():
        with urllib.request.urlopen(artifact["url"], timeout=60) as response:
            raw = response.read(artifact["bytes"] + 1)
        if pin(raw) != {k: artifact[k] for k in ("sha256", "bytes")}:
            raise ValueError("upstream artifact hash mismatch")
        path.write_bytes(raw)
    if pin(path.read_bytes()) != {k: artifact[k] for k in ("sha256", "bytes")}:
        raise ValueError("cached artifact hash mismatch")
    return path


def build(cache, out, javac):
    artifacts = json.loads((ROOT / "signer/contract/upstream-artifacts.json").read_text("utf-8"))
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=False)
    local = {key: acquire(value, cache) for key, value in artifacts.items()}
    prefix = "unidbg-" + COMMIT + "/"
    java_sources, resources, resource_map = {}, {}, {}
    with zipfile.ZipFile(local["unidbg-source"]) as archive:
        for item in archive.infolist():
            relative = item.filename.removeprefix(prefix)
            if item.is_dir():
                continue
            if relative in FACTORIES or (relative.endswith(".java") and relative.startswith(JAVA_ROOTS)):
                raw = archive.read(item)
                if relative in PATCHES:
                    text = raw.decode("utf-8")
                    offset = text.index(";") + 1
                    raw = (text[:offset] + "\n// Modified by xiaoheihe-api-collect: explicit Module import for Java 17.\n"
                           + "import com.github.unidbg.Module;" + text[offset:]).encode("utf-8")
                java_sources[relative] = raw
            for root in RESOURCE_ROOTS:
                if relative.startswith(root):
                    name = relative[len(root):]
                    raw = archive.read(item)
                    if name in resources:
                        raise ValueError("duplicate runtime resource")
                    resources[name] = raw
                    resource_map[item.filename] = {"path": name, **pin(raw)}
        license_bytes = archive.read(prefix + "LICENSE")
    resource_name = "unidbg-resources-2ded0545.jar"
    resource_jar = out / resource_name
    write_zip(resource_jar, resources)
    dependencies = {resource_name: pin(resource_jar.read_bytes())}
    dependencies.update({artifact["name"]: {k: artifact[k] for k in ("sha256", "bytes")}
                         for artifact in artifacts.values() if artifact["name"].endswith(".jar")})
    with tempfile.TemporaryDirectory(prefix="build-", dir=out) as work:
        work = Path(work)
        sources = {}
        for name, raw in java_sources.items():
            sources["overlay/" + name] = raw
        for path in (ROOT / "signer/src/main/java").rglob("*.java"):
            sources["own/" + path.relative_to(ROOT / "signer/src/main/java").as_posix()] = path.read_bytes().replace(b"\r\n", b"\n")
        source_paths = []
        for name, raw in sources.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            source_paths.append(path)
        classes = work / "classes"
        classes.mkdir()
        classpath = os.pathsep.join(str(path) for path in local.values() if path.suffix == ".jar")
        arguments = ["--release", "17", "-encoding", "UTF-8", "-cp", classpath, "-d", str(classes)]
        arguments.extend(str(path) for path in sorted(source_paths))
        argsfile = work / "javac.args"
        argsfile.write_text("\n".join('"' + arg.replace("\\", "/") + '"' for arg in arguments), "utf-8")
        subprocess.run([javac, "@" + str(argsfile)], check=True, timeout=240)
        members = {path.relative_to(classes).as_posix(): path.read_bytes() for path in classes.rglob("*.class")}
        members["META-INF/MANIFEST.MF"] = b"Manifest-Version: 1.0\nMain-Class: com.xiaoheihe.SignerBootstrap\n\n"
        members["META-INF/xhh-deps.tsv"] = tsv(dependencies)
        members["META-INF/xhh-resources.tsv"] = tsv({name: pin(raw) for name, raw in sorted(resources.items())})
        members["META-INF/LICENSE-project.txt"] = (ROOT / "LICENSE").read_bytes().replace(b"\r\n", b"\n")
        members["META-INF/LICENSE-unidbg.txt"] = license_bytes
        for path in sorted((ROOT / "signer/contract").glob("*-LICENSE.txt")):
            members["META-INF/" + path.name] = path.read_bytes().replace(b"\r\n", b"\n")
        members["META-INF/LICENSE-jelf.txt"] = (ROOT / "signer/contract/jelf-MIT.txt").read_bytes().replace(b"\r\n", b"\n")
        members["META-INF/NOTICE.txt"] = (ROOT / "signer/THIRD-PARTY.md").read_bytes().replace(b"\r\n", b"\n")
        jar = out / ("xhh-signer-bootstrap-" + VERSION + ".jar")
        write_zip(jar, members)
        duplicate_classes = {}
        owners = {name: ["bootstrap"] for name in members if name.endswith(".class")}
        for key, path in local.items():
            if path.suffix != ".jar":
                continue
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith(".class"):
                        owners.setdefault(name, []).append(key)
        duplicate_classes = {name: value for name, value in owners.items() if len(value) > 1}
        allowed = {"com/github/unidbg/arm/backend/Unicorn2Factory.class",
                   "com/github/unidbg/arm/backend/DynarmicFactory.class", "module-info.class",
                   "META-INF/versions/9/module-info.class"}
        if set(duplicate_classes) - allowed:
            raise ValueError("unexpected duplicate classes: " + str(sorted(set(duplicate_classes) - allowed)))
        (out / "duplicate-classes.json").write_text(json.dumps(duplicate_classes, indent=2) + "\n", "utf-8")
        source_members = {"unidbg/" + key: value for key, value in java_sources.items()}
        source_members["unidbg/LICENSE"] = license_bytes
        for folder in ("src", "scripts", "contract"):
            for path in (ROOT / "signer" / folder).rglob("*"):
                if path.is_file() and path.suffix in {".java", ".py", ".json", ".txt"}:
                    source_members["signer/" + path.relative_to(ROOT / "signer").as_posix()] = path.read_bytes().replace(b"\r\n", b"\n")
        source_members["LICENSE"] = (ROOT / "LICENSE").read_bytes().replace(b"\r\n", b"\n")
        source_members["signer/THIRD-PARTY.md"] = (ROOT / "signer/THIRD-PARTY.md").read_bytes().replace(b"\r\n", b"\n")
        source_members["signer/README.md"] = (ROOT / "signer/README.md").read_bytes().replace(b"\r\n", b"\n")
        write_zip(out / ("xhh-signer-bootstrap-" + VERSION + "-sources.zip"), source_members)
    with zipfile.ZipFile(local["temurin-jre"]) as archive:
        runtime_files = {i.filename: pin(archive.read(i)) for i in archive.infolist() if not i.is_dir()}
    java_members = [name for name in runtime_files if name.endswith("/bin/java.exe")]
    if len(java_members) != 1:
        raise ValueError("unexpected JRE layout")
    lock = {
        "schema_version": 1, "version": VERSION, "platform": "windows-x86_64",
        "profile_id": "heybox-arm64-001c9a49-v1",
        "bootstrap": {"name": jar.name, "url": RELEASE_URL + "/" + jar.name, **pin(jar.read_bytes())},
        "artifacts": artifacts, "dependencies": dependencies,
        "resources": {"name": resource_name, "artifact": "unidbg-source", "members": resource_map},
        "java": {"artifact": "temurin-jre", "executable": java_members[0], "files": runtime_files},
        "selftest": {"path": "/account/info", "timestamp": 1700000000, "identity": "123",
                     "imei": "0123456789abcdef", "device_info": "25102RKBEC", "os_version": "14",
                     "app_version": "1.3.385", "hkey": "FC0EAF1B", "_rnd": "14:E94DBC87"},
    }
    lock_path = ROOT / "skill-kit/xiaoheihe-publisher/references/signer-release.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", "utf-8")
    (out / "signer-release.json").write_bytes(lock_path.read_bytes())
    (out / "THIRD-PARTY.md").write_bytes((ROOT / "signer/THIRD-PARTY.md").read_bytes())
    # Native resources are a private local build artifact, never a release asset.
    release_files = [jar, out / ("xhh-signer-bootstrap-" + VERSION + "-sources.zip"),
                     out / "signer-release.json", out / "THIRD-PARTY.md"]
    (out / "SHA256SUMS").write_text("".join(
        pin(path.read_bytes())["sha256"] + "  " + path.name + "\n" for path in sorted(release_files)), "ascii")
    return jar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--javac", default="javac")
    args = parser.parse_args()
    print(build(args.cache.resolve(), args.out.resolve(), args.javac))


if __name__ == "__main__":
    main()

"""Install a local wheel in a disposable venv and verify offline portability."""
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile

from build_release import audit_archive


# This is installed only in the disposable venv, so the native launcher and -I
# module probes share the same fail-closed guard without relying on PYTHONPATH.
OFFLINE_GUARD = '''\
import builtins
import os
import sys

builtins._xhh_offline_guard = True
def _xhh_guard(event, args):
    if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
                 "socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        with open(os.environ["XHH_VERIFY_GUARD_LOG"], "a", encoding="ascii") as stream:
            stream.write(event + "\\n")
        raise RuntimeError("offline installation verifier blocked " + event)
sys.addaudithook(_xhh_guard)
'''

INSTALLED_PROBE = '''\
import builtins, importlib.metadata, json, os, sys, sysconfig
from pathlib import Path
import xhh_sdk
import xhh_sdk.web_signer
from xhh_sdk.routes import check_snapshot
dist = importlib.metadata.distribution("xhh-sdk")
prefix = Path(sys.prefix).resolve()
direct = json.loads(dist.read_text("direct_url.json") or "{}")
purelib = Path(sysconfig.get_path("purelib"))
snapshot = check_snapshot()
print(json.dumps({"checks": {
    "guard_active": getattr(builtins, "_xhh_offline_guard", False),
    "pythonpath_absent": "PYTHONPATH" not in os.environ,
    "isolated_interpreter": sys.flags.isolated == 1,
    "package_inside_venv": Path(xhh_sdk.__file__).resolve().is_relative_to(prefix),
    "web_signer_inside_venv": Path(xhh_sdk.web_signer.__file__).resolve().is_relative_to(prefix),
    "web_signer_in_distribution": any(str(f).replace(chr(92), "/") == "xhh_sdk/web_signer.py"
                                       for f in dist.files or []),
    "distribution_inside_venv": all(Path(dist.locate_file(f)).resolve().is_relative_to(prefix)
                                    for f in dist.files or []),
    "distribution_files_present": bool(dist.files),
    "not_editable": direct.get("dir_info", {}).get("editable") is not True
                    and not list(purelib.glob("*editable*"))
                    and not list(purelib.glob("*.egg-link")),
    "metadata_version_matches_wheel": dist.version == sys.argv[1],
    "package_version_matches_metadata": xhh_sdk.__version__ == dist.version,
    "snapshot_routes_present": snapshot["routes"] > 0,
    "snapshot_scope_offline": snapshot["scope"] == "offline_snapshot_integrity_only",
}, "snapshot": snapshot, "version": dist.version}))
'''

UNSIGNED_PROBE = '''\
import json, sys, urllib.parse
from pathlib import Path
from xhh_sdk.config import XhhConfig
import xhh_sdk.transport as module
import xhh_sdk.signer as signer_module
signer_calls = []
def forbidden_signer(*args, **kwargs):
    signer_calls.append(True)
    raise AssertionError("unsigned operation requested a signer or Java discovery")
module.Signer = forbidden_signer
signer_module.shutil.which = forbidden_signer
config = XhhConfig(pkey="<offline-fixture>", heybox_id="12345",
                   imei="synthetic-device", device_info="synthetic-model",
                   api_base="https://api.invalid", web_origin="https://web.invalid",
                   signer_jar=sys.argv[1], java="missing-synthetic-java")
transport = module.Transport(config)
requests = []
def fixture_open(request):
    requests.append(request)
    return b'{"status":"ok","result":{"offline_fixture":true}}'
transport._open = fixture_open
response = transport.web_request("/synthetic/heartbeat", {"keys": "[]"})
request = requests[0]
print(json.dumps({"checks": {
    "synthetic_response_success": response == {"status": "ok", "result": {"offline_fixture": True}},
    "signer_never_constructed": not signer_calls and transport._signer is None,
    "missing_jar_fixture": not Path(config.signer_jar).exists(),
    "one_fixture_request": len(requests) == 1,
    "unsigned_post": request.get_method() == "POST",
    "synthetic_url": request.full_url == "https://api.invalid/synthetic/heartbeat",
    "cookie_contract": request.get_header("Cookie") == config.cookie_web,
    "payload_without_signature": urllib.parse.parse_qs(request.data.decode()) == {"keys": ["[]"]},
}}))
'''

WEB_PROBE = '''\
import argparse, builtins, contextlib, io, json, sys, urllib.parse
from pathlib import Path
from xhh_sdk import cli
from xhh_sdk.client import XhhClient
from xhh_sdk.config import XhhConfig
from xhh_sdk.web_signer import calc_hkey
import xhh_sdk.transport as module
import xhh_sdk.signer as signer_module
signer_calls, discoveries, bundle_imports, requests = [], [], [], []
def forbidden_signer(*args, **kwargs):
    signer_calls.append(True)
    raise AssertionError("Web operation requested an App signer")
def forbidden_java(*args, **kwargs):
    discoveries.append(True)
    raise AssertionError("Web operation requested Java discovery")
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if "signer_bundle" in name:
        bundle_imports.append(name)
        raise AssertionError("Web operation imported App bundle resolver")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
module.Signer = forbidden_signer
signer_module.shutil.which = forbidden_java
path = Path(sys.argv[1])
config = XhhConfig(pkey="<offline-fixture>", heybox_id="12345", protocol_mode="web",
                   api_base="https://api.invalid", web_origin="https://web.invalid",
                   signer_jar=str(path.with_suffix(".missing.jar")),
                   signer_bundle="bundle:" + "0" * 64, java="missing-synthetic-java")
config.save(path)
loaded = XhhConfig.from_file(path)
before = path.read_bytes()
args = argparse.Namespace(account=None, config=str(path), env=False, protocol="app")
override = cli._load(args)
def fixture_open(self, request):
    requests.append(request)
    if urllib.parse.urlsplit(request.full_url).path == "/account/restore_login":
        return b'{"status":"ok","result":{"user":{"heybox_id":"12345"}}}'
    return b'{"status":"ok","result":{"links":[]}}'
module.Transport._open = fixture_open
client = XhhClient(loaded)
identity = client.account_info()
verification = client.verify()
with contextlib.redirect_stdout(io.StringIO()) as output:
    doctor_code = cli.main(["--config", str(path), "doctor", "--offline"])
doctor = json.loads(output.getvalue())
with contextlib.redirect_stdout(io.StringIO()) as output:
    signer_code = cli.main(["--config", str(path), "doctor"])
doctor_signer = json.loads(output.getvalue())
signed = True
for request in requests:
    url = urllib.parse.urlsplit(request.full_url)
    query = urllib.parse.parse_qs(url.query)
    signed = signed and {"_time", "nonce", "hkey"} <= query.keys()
    if signed:
        signed = (query["hkey"] == [calc_hkey(url.path, int(query["_time"][0]), query["nonce"][0])]
                  and query.get("os_type") == ["web"]
                  and request.get_header("Cookie") == "user_pkey=<offline-fixture>; user_heybox_id=12345;")
print(json.dumps({"checks": {
    "guard_active": getattr(builtins, "_xhh_offline_guard", False),
    "web_mode_persisted": loaded.protocol_mode == "web"
                          and json.loads(before)["protocol_mode"] == "web",
    "override_not_persisted": override.protocol_mode == "app" and path.read_bytes() == before,
    "synthetic_identity_result": identity == {"user": {"heybox_id": "12345"}},
    "web_request_signed": signed and len(requests) == 2,
    "scoped_fixture_requests": [urllib.parse.urlsplit(r.full_url).path for r in requests]
                               == ["/account/restore_login", "/bbs/app/link/drafts"],
    "web_verify_success": verification.get("ok") is True
                          and verification.get("protocol_mode") == "web",
    "offline_doctor_success": doctor_code == 0 and doctor.get("protocol_mode") == "web"
                              and doctor.get("signer_executed") is False,
    "python_doctor_success": signer_code == 0 and doctor_signer.get("signer") == "ok"
                             and doctor_signer.get("signer_kind") == "python-web",
    "app_signer_never_constructed": not signer_calls and client.transport._signer is None,
    "java_not_discovered": not discoveries,
    "bundle_not_imported": not bundle_imports,
    "missing_jar_fixture": not Path(config.signer_jar).exists(),
}}))
'''

TAMPER_PROBE = '''\
import json, sys
import xhh_sdk.signer as module
from xhh_sdk.exceptions import XhhSignerError
discoveries = []
def forbidden_java(*args, **kwargs):
    discoveries.append(True)
    raise AssertionError("tampered signer reached Java discovery")
module.shutil.which = forbidden_java
rejected = False
try:
    module.Signer(jar=sys.argv[1], identity="12345", imei="synthetic-device",
                  device_info="synthetic-model")
except XhhSignerError as exc:
    rejected = "SHA-256 mismatch" in str(exc)
print(json.dumps({"checks": {"tampered_signer_rejected": rejected,
                            "java_not_discovered": not discoveries}}))
'''


def wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("expected exactly one wheel distribution metadata file")
        version = BytesParser().parsebytes(archive.read(metadata[0])).get("Version")
    if not version:
        raise ValueError("wheel metadata has no version")
    return version


def record_check(checks, name, proc, *, expected=0, contains=None, predicates=None):
    """A successful exit/JSON parse cannot hide a failed acceptance predicate."""
    passed = proc.returncode == expected
    if contains is not None:
        passed = passed and contains in proc.stdout + proc.stderr
    record = {"check": name, "returncode": proc.returncode,
              "expected_returncode": expected, "passed": passed}
    data = None
    if predicates is not None:
        try:
            data = json.loads(proc.stdout)
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            values = predicates(data)
            if not isinstance(values, dict) or not values:
                raise ValueError("expected nonempty named acceptance predicates")
            record["predicates"] = {key: value is True for key, value in values.items()}
            record["passed"] = passed and all(record["predicates"].values())
            record["result"] = data
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            record["passed"] = False
            record["parse_error"] = str(exc)
    if not record["passed"]:
        record["diagnostic"] = (proc.stdout + proc.stderr)[-1000:]
    checks.append(record)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    args = parser.parse_args(argv)
    release = args.release.resolve()
    wheels = sorted(release.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("expected exactly one local wheel")
    wheel = wheels[0]
    audit = audit_archive(wheel)
    version = wheel_version(wheel)
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is required; no tools were installed")

    checks = []
    with tempfile.TemporaryDirectory(prefix="xhh-offline-install-") as directory:
        root = Path(directory).resolve()
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(("XHH_", "PYTHON", "VIRTUAL_ENV"))}
        guard_log = root / "blocked-actions.txt"
        env.update(HOME=str(root), USERPROFILE=str(root), APPDATA=str(root / "appdata"),
                   LOCALAPPDATA=str(root / "localappdata"), UV_OFFLINE="1",
                   PYTHONDONTWRITEBYTECODE="1", XHH_SIGNER_HOME=str(root / "user-signers"),
                   XHH_VERIFY_GUARD_LOG=str(guard_log))
        cwd = root / "unrelated-cwd"
        cwd.mkdir()
        origin = root / "distribution-origin"
        origin.mkdir()
        disposable_wheel = origin / wheel.name
        shutil.copy2(wheel, disposable_wheel)
        venv = root / "venv"
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = venv / ("Scripts/xhh-sdk.exe" if os.name == "nt" else "bin/xhh-sdk")

        def run(arguments):
            return subprocess.run(arguments, cwd=cwd, env=env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=120)

        setup = run([uv, "venv", "--offline", "--no-project", "--python", sys.executable, str(venv)])
        if setup.returncode:
            raise RuntimeError(setup.stderr)
        install = run([uv, "pip", "install", "--offline", "--no-index", "--no-deps",
                       "--python", str(python), str(disposable_wheel)])
        if install.returncode:
            raise RuntimeError(install.stderr)
        checks.append({"check": "clean wheel install without index or dependencies", "passed": True})

        purelib = run([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"])
        if purelib.returncode:
            raise RuntimeError(purelib.stderr)
        guard_path = Path(purelib.stdout.strip()).resolve()
        if not guard_path.is_relative_to(venv):
            raise RuntimeError("refusing guard installation outside disposable venv")
        (guard_path / "sitecustomize.py").write_text(OFFLINE_GUARD, encoding="ascii")

        moved_origin = root / "relocated-distribution-origin"
        origin.rename(moved_origin)
        checks.append({"check": "disposable wheel origin moved before launcher acceptance",
                       "passed": not origin.exists() and (moved_origin / wheel.name).is_file()})

        def check(name, arguments, **kwargs):
            return record_check(checks, name, run(arguments), **kwargs)

        def probe(name, code, *arguments):
            return check(name, [str(python), "-I", "-c", textwrap.dedent(code), *arguments],
                         predicates=lambda data: data["checks"])

        check("installed launcher help after origin move", [str(cli), "--help"], contains="catalog")
        check("installed launcher version from wheel metadata", [str(cli), "--version"], contains=version)
        catalog_predicates = lambda data: {
            "route_rows_present": bool(data.get("routes")),
            "command_rows_present": bool(data.get("commands")),
            "summary_present": isinstance(data.get("summary"), dict),
        }
        check("installed catalogue after origin move", [str(cli), "catalog", "--json"],
              predicates=catalog_predicates)
        check("installed group catalogue after origin move", [str(cli), "catalog", "--group", "--json"],
              predicates=lambda data: {"group_rows_present": bool(data.get("group_routes")),
                                       "app_route_rows_empty": data.get("routes") == []})
        check("isolated installed catalogue after origin move",
              [str(python), "-I", "-m", "xhh_sdk.cli", "catalog", "--json"],
              predicates=catalog_predicates)
        probe("isolated installed metadata and snapshot", INSTALLED_PROBE, version)
        check("isolated installed module help", [str(python), "-I", "-m", "xhh_sdk.cli", "--help"],
              contains="catalog")
        check("upload refuses before configuration", [str(cli), "upload", "missing.png"],
              expected=2, contains="refusing live write without --confirm")
        check("publish refuses before configuration", [str(cli), "publish", "missing.json", "--publish"],
              expected=2, contains="refusing live write without --confirm")
        check("missing explicit account fails closed",
              [str(cli), "--data-dir", str(root / "absent-store"), "--account", "absent",
               "call", "/account/info"], expected=2)

        missing_jar = root / "does-not-exist.jar"
        config = root / "synthetic-config.json"
        config.write_text(json.dumps({"pkey": "<offline-fixture>", "heybox_id": "12345",
                                      "imei": "synthetic-device", "device_info": "synthetic-model",
                                      "signer_jar": str(missing_jar)}), encoding="utf-8")
        check("missing JAR fails before Java or HTTP",
              [str(cli), "--config", str(config), "call", "/account/info"],
              expected=1, contains="signer jar not found")
        check("offline doctor reports missing artifact structurally",
              [str(cli), "--config", str(config), "doctor", "--offline"], expected=1,
              predicates=lambda data: {"offline": data.get("offline") is True,
                                       "signer_not_executed": data.get("signer_executed") is False,
                                       "signer_not_ready": data.get("signer_ready") is False,
                                       "diagnostic_present": "signer jar not found" in data.get("error", "")})
        probe("installed unsigned transport without signer or Java", UNSIGNED_PROBE, str(missing_jar))
        check("installed pure Web offline doctor without credentials",
              [str(cli), "--protocol", "web", "doctor", "--offline"], predicates=lambda data: {
                  "web_mode": data.get("protocol_mode") == "web",
                  "signer_ready": data.get("signer_ready") is True,
                  "signer_not_executed": data.get("signer_executed") is False,
                  "java_not_required": data.get("java_required") is False,
                  "no_account_checked": data.get("account_checked") is False,
              })
        probe("installed pure Web signing and persisted mode without Java",
              WEB_PROBE, str(root / "synthetic-web-config.json"))

        resource_origin = root / "resource-origin"
        resource_origin.mkdir()
        artifact = resource_origin / "inert-synthetic.jar"
        artifact.write_bytes(b"offline fixture only; not a ZIP or executable JAR\n")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        reference = "managed:" + digest
        installed_jar = Path(env["XHH_SIGNER_HOME"]) / (digest + ".jar")
        check("installed launcher imports inert signer bytes",
              [str(cli), "signer", "install", str(artifact), "--sha256", digest, "--confirm"],
              predicates=lambda data: {"managed_reference": data.get("reference") == reference,
                                       "installed": data.get("installed") is True,
                                       "not_executed": data.get("executed") is False})
        moved_resources = root / "relocated-resource-origin"
        resource_origin.rename(moved_resources)
        checks.append({"check": "original synthetic resource directory moved",
                       "passed": not resource_origin.exists() and (moved_resources / artifact.name).is_file()})
        check("managed signer survives original resource move",
              [str(cli), "signer", "inspect", reference], predicates=lambda data: {
                  "artifact_verified": data.get("passed") is True,
                  "reference_matches": data.get("reference") == reference,
                  "digest_matches": data.get("sha256") == digest,
                  "user_store_resolution": data.get("resolved_path") == str(installed_jar),
                  "installed_bytes_match": installed_jar.is_file()
                  and hashlib.sha256(installed_jar.read_bytes()).hexdigest() == digest,
              })
        if installed_jar.is_file():
            installed_jar.write_bytes(b"tampered inert synthetic signer bytes\n")
            check("managed signer inspect rejects installed byte tampering",
                  [str(cli), "signer", "inspect", reference], expected=1, contains="SHA-256 mismatch")
            probe("managed signer tampering refused before Java discovery", TAMPER_PROBE, reference)
        else:
            checks.append({"check": "managed signer tampering acceptance", "passed": False,
                           "diagnostic": "synthetic artifact installation did not create a file"})
        checks.append({"check": "no account store created", "passed": not (root / "absent-store").exists()
                       and not (root / ".xhh_sdk").exists()})
        blocked = guard_log.read_text(encoding="ascii").splitlines() if guard_log.exists() else []
        checks.append({"check": "no JVM subprocess or network attempts", "passed": not blocked,
                       "blocked_events": blocked})

    report = {"scope": "offline_clean_install_and_disposable_origin_relocation",
              "wheel": wheel.name, "version": version,
              "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "archive_audit": audit, "checks": checks,
              "passed": all(item["passed"] for item in checks),
              "jar_executed": False, "live_requests": False,
              "web_validation_scope": "installed Python signer and fixture HTTP responses only",
              "original_repository_moved": False,
              "relocation_scope": "disposable wheel-origin and synthetic resource directories only",
              "public_publish_ready": False}
    (release / "install-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

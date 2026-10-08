"""Install the precompiled signer from your supported APK. No JDK or Maven."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = sibling("setup_runtime")
cli = sibling("xhh_cli")
Refused = runtime.Refused


def verify_embedded_lock(loader, lock):
    expected = {lock["resources"]["name"]: lock["dependencies"][lock["resources"]["name"]]}
    expected.update({name: pin for name, pin in lock["dependencies"].items() if name not in expected})
    text = "".join(f"{name}\t{pin['sha256']}\t{pin['bytes']}\n" for name, pin in expected.items())
    with zipfile.ZipFile(loader) as archive:
        if archive.read("META-INF/xhh-deps.tsv") != text.encode("ascii"):
            raise Refused("embedded_lock_mismatch")


def bind_account(alias, data_dir, bundle, java):
    from xhh_sdk.accounts import AccountStore
    try:
        store = AccountStore(runtime.reject_links(data_dir if data_dir else Path.home() / ".xhh_sdk"))
        current = store.get(alias)
        patch = {"signer_bundle": bundle, "java": str(java)}
        changed = any(current.config.get(key) != value for key, value in patch.items())
        if changed:
            store.configure(alias, patch)
        return {"requested": True, "bound": True, "changed": changed}
    except Exception as error:
        raise Refused("account_binding_failed") from error


def setup(args, receipt):
    if not args.confirm:
        raise Refused("confirmation_required")
    try:
        runtime.reject_links(cli.KIT_ROOT)
        cli.activate_runtime()
    except Exception as error:
        raise Refused("kit_integrity_failed") from error
    lock = runtime.validate_lock(cli.read_json(cli.KIT_ROOT / "references/signer-release.json"))
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise Refused("unsupported_platform")
    from xhh_sdk.signer_resources import prepare_resources
    from xhh_sdk.signer_bundle import install_bundle, resolve_bundle
    from xhh_sdk.signer import Signer
    home = Path(os.environ.get("XHH_SETUP_HOME", Path.home() / ".xhh_sdk/setup-cache")).expanduser()
    if not home.is_absolute():
        raise Refused("setup_home_must_be_absolute")
    runtime.reject_links(home)
    receipt["profile_id"] = lock["profile_id"]
    # The original SDK validates the entire APK before opening selected ZIP members.
    with tempfile.TemporaryDirectory(prefix="xhh-apk-import-") as temporary:
        resources = Path(temporary) / "resources"
        try:
            prepare_resources(args.apk, resources)
        except Exception as error:
            raise Refused("unsupported_apk") from error
        java, major, source = runtime.select_java(args.java, args.install_java, args.offline, home, lock)
        receipt["java"] = {"major": major, "source": source}
        cache = home / "downloads"
        loader = runtime.download(lock["bootstrap"], cache, args.offline)
        verify_embedded_lock(loader, lock)
        acquired = {}
        for key, artifact in lock["artifacts"].items():
            if key == "temurin-jre":
                continue
            path = runtime.download(artifact, cache, args.offline)
            acquired[artifact["name"]] = path
        archive = acquired[lock["artifacts"][lock["resources"]["artifact"]]["name"]]
        acquired[lock["resources"]["name"]] = runtime.resource_jar(lock, archive, cache)
        reference = install_bundle(resources, loader, loader_sha256=lock["bootstrap"]["sha256"])
        bundle = resolve_bundle(reference)
        receipt.update(bundle=reference, loader_sha256=lock["bootstrap"]["sha256"])
        runtime.install_dependencies(Path(bundle["directory"]), lock["dependencies"], acquired)
        vector = lock["selftest"]
        signer = Signer(bundle=reference, java=str(java), timeout=60,
                        **{key: vector[key] for key in ("identity", "imei", "device_info", "os_version", "app_version")})
        receipt["selftest"]["executed"] = True
        try:
            result = signer.sign(vector["path"], timestamp=vector["timestamp"])
        except Exception as error:
            raise Refused("selftest_failed") from error
        runtime.match_selftest(result, vector)
        receipt["selftest"]["matched"] = True
        if args.account:
            receipt["account_binding"] = bind_account(args.account, args.data_dir, reference, java)
    receipt.update(state="ready", reason="selftest_matched")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path, help="your supported APK, never uploaded")
    parser.add_argument("--confirm", action="store_true", help="authorize local import and synthetic signing")
    parser.add_argument("--account", help="existing explicit account alias to bind after selftest")
    parser.add_argument("--data-dir", type=Path, help="same account directory used by xhh_cli --data-dir")
    parser.add_argument("--java", help="explicit Java 17+ x64 executable")
    parser.add_argument("--install-java", action="store_true", help="allow private pinned JRE download if needed")
    parser.add_argument("--offline", action="store_true", help="refuse downloads; reverify cached artifacts")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    receipt = {"state": "refused", "reason": "setup_failed", "selftest": {"executed": False, "matched": False},
               "account_binding": {"requested": bool(args.account), "bound": False, "changed": False}}
    try:
        setup(args, receipt)
    except Refused as error:
        receipt["reason"] = str(error)
    except KeyboardInterrupt:
        receipt["reason"] = "interrupted"
    except Exception:
        receipt["reason"] = "setup_failed"
    print(json.dumps(receipt, ensure_ascii=False))
    if receipt["state"] != "ready":
        print("Setup refused. Check the reason, correct the input or cache, and retry the same command. "
              "For java_missing, select --java or explicitly allow --install-java.", file=sys.stderr)
    return 0 if receipt["state"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())

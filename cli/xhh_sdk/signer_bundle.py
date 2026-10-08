"""Content-addressed signer bundles: verified APK resources plus a loader JAR.

A bundle is the user-built half of the BYO-APK path. Installation copies the
prepared resources and the loader into the user's own store, keyed by a digest
over both, and hands back a `bundle:<sha256>` reference that account settings
can store. Nothing here executes Java, reads credentials or touches the
network; a bundle is only ever a local, digest-pinned pair of files.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from .exceptions import XhhSignerError
from .signer import _normalize_digest, _reject_links, _store_root, _verify_file
from .signer_resources import inspect_resources

BUNDLE_PREFIX = "bundle:"
SCHEMA_VERSION = 1
RESOURCE_DIR_NAME = "resources"
LOADER_NAME = "loader.jar"
MANIFEST_NAME = "bundle.json"


def _bundle_root() -> Path:
    override = os.environ.get("XHH_BUNDLE_HOME")
    root = Path(override) if override is not None else Path.home() / ".xhh_sdk" / "bundles"
    if not root.is_absolute():
        raise XhhSignerError("XHH_BUNDLE_HOME must be an absolute directory")
    _reject_links(root)
    return root.resolve()


def _bundle_path(root: Path, digest: str) -> Path:
    destination = root / digest
    _reject_links(destination)
    if not destination.resolve().is_relative_to(root):
        raise XhhSignerError("bundle path escapes its store")
    return destination


def _bundle_digest(resource_manifest: bytes, loader_digest: str, profile_id: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"xhh-signer-bundle\x00")
    digest.update(str(SCHEMA_VERSION).encode("ascii") + b"\x00")
    digest.update(profile_id.encode("utf-8") + b"\x00")
    digest.update(resource_manifest)
    digest.update(b"\x00" + loader_digest.encode("ascii"))
    return digest.hexdigest()


def _manifest(digest: str, profile_id: str, loader_digest: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_digest": digest,
        "profile_id": profile_id,
        "loader_sha256": loader_digest,
        "loader_name": LOADER_NAME,
        "resources": RESOURCE_DIR_NAME,
    }


def _publish(staging: Path, destination: Path) -> None:
    """Move a finished staging directory into place.

    Windows denies the rename while a scanner or indexer still holds a handle
    on the freshly written files, so retry briefly before giving up.
    """
    for attempt in range(10):
        try:
            staging.rename(destination)
            return
        except FileExistsError:
            shutil.rmtree(staging, ignore_errors=True)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1 * (attempt + 1))


def install_bundle(resources: str | Path, loader: str | Path, *, loader_sha256: str) -> str:
    """Verify and store a bundle, returning its `bundle:<sha256>` reference."""
    expected_loader = _normalize_digest(loader_sha256)
    source_resources = Path(resources).expanduser().absolute()
    source_loader = Path(loader).expanduser().absolute()
    try:
        _reject_links(source_loader)
        if not source_loader.is_file():
            raise XhhSignerError(f"loader jar not found: {source_loader}")
        report = inspect_resources(source_resources)
        _verify_file(source_loader, expected_loader)
        manifest_bytes = (source_resources / "manifest.json").read_bytes()
        digest = _bundle_digest(manifest_bytes, expected_loader, report["profile_id"])
        root = _bundle_root()
        root.mkdir(parents=True, exist_ok=True)
        destination = _bundle_path(root, digest)
        if destination.is_dir():
            resolve_bundle(BUNDLE_PREFIX + digest)
            return BUNDLE_PREFIX + digest
        staging = Path(tempfile.mkdtemp(prefix=".bundle-", dir=root))
        try:
            shutil.copytree(source_resources, staging / RESOURCE_DIR_NAME)
            shutil.copy2(source_loader, staging / LOADER_NAME)
            (staging / MANIFEST_NAME).write_text(
                json.dumps(_manifest(digest, report["profile_id"], expected_loader),
                           indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _publish(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        resolve_bundle(BUNDLE_PREFIX + digest)
        return BUNDLE_PREFIX + digest
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise XhhSignerError(f"cannot install signer bundle: {exc}") from exc


def resolve_bundle(reference: str | Path) -> dict:
    """Re-verify an installed bundle and return its loader and resource paths."""
    try:
        text = str(reference)
        if not text.startswith(BUNDLE_PREFIX):
            raise XhhSignerError("bundle reference must look like bundle:<sha256>")
        digest = _normalize_digest(text[len(BUNDLE_PREFIX):])
        directory = _bundle_path(_bundle_root(), digest)
        if not directory.is_dir():
            raise XhhSignerError(f"signer bundle not found: {text}")
        manifest_path = directory / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("schema_version") != SCHEMA_VERSION
                or manifest.get("bundle_digest") != digest
                or manifest.get("loader_name") != LOADER_NAME
                or manifest.get("resources") != RESOURCE_DIR_NAME):
            raise XhhSignerError("signer bundle manifest does not match this schema")
        loader = directory / LOADER_NAME
        loader_digest = _normalize_digest(str(manifest.get("loader_sha256")))
        if _verify_file(loader, loader_digest) != loader_digest:
            raise XhhSignerError("signer bundle loader digest mismatch")
        resources = directory / RESOURCE_DIR_NAME
        report = inspect_resources(resources)
        if report["profile_id"] != manifest.get("profile_id"):
            raise XhhSignerError("signer bundle profile does not match its manifest")
        return {
            "reference": text,
            "directory": str(directory),
            "loader": str(loader),
            "resources": str(resources),
            "loader_sha256": loader_digest,
            "profile_id": manifest["profile_id"],
            "signer_executed": False,
            "online_verified": False,
        }
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise XhhSignerError(f"cannot resolve signer bundle: {exc}") from exc

"""Drive a user-supplied request signer with arguments and JSON on stdout.

The legacy vendor lookup remains for compatibility, but this project never
ships a JAR. A digest pin verifies bytes, not publisher identity or safety.
The temporary working directory is housekeeping, not a security sandbox.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from .exceptions import XhhSignerError

VENDOR_JAR = Path(__file__).resolve().parent / "vendor" / "xiaoheihe-signer.jar"
FIELDS = {"_time", "nonce", "hkey", "_rnd"}
_CHILD_ENV_KEYS = {
    "PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT",
    "JAVA_HOME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TZ",
}


def _normalize_digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise XhhSignerError("signer SHA-256 must contain exactly 64 hexadecimal characters")
    return value.lower()


def _reject_links(path: Path) -> None:
    for entry in (*reversed(path.parents), path):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise XhhSignerError("managed signer path must not contain a symlink or reparse point")


def _store_root() -> Path:
    override = os.environ.get("XHH_SIGNER_HOME")
    root = Path(override) if override is not None else Path.home() / ".xhh_sdk" / "signers"
    if not root.is_absolute():
        raise XhhSignerError("XHH_SIGNER_HOME must be an absolute directory")
    _reject_links(root)
    return root.resolve()


def _managed_path(root: Path, digest: str) -> Path:
    destination = root / f"{digest}.jar"
    _reject_links(destination)
    if not destination.resolve().is_relative_to(root):
        raise XhhSignerError("managed signer path escapes its store")
    return destination


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise XhhSignerError(
            f"signer jar not found: {path}; set XHH_SIGNER_JAR "
            "or signer_jar in your config to a trusted local JAR")


def _verify_file(path: Path, expected: str | None = None) -> str:
    _require_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if expected is not None and actual != expected:
        raise XhhSignerError("signer SHA-256 mismatch; refusing to use JAR")
    return actual


def _select_jar(reference: str | Path | None, sha256: str | None = None
                ) -> tuple[str, Path, str | None]:
    selected = reference if reference is not None else os.environ.get("XHH_SIGNER_JAR", VENDOR_JAR)
    supplied = sha256 if sha256 is not None else os.environ.get("XHH_SIGNER_SHA256")
    pin = _normalize_digest(supplied) if supplied is not None else None
    if isinstance(selected, str) and selected.startswith("managed:"):
        digest = _normalize_digest(selected[len("managed:"):])
        if pin is not None and pin != digest:
            raise XhhSignerError("signer SHA-256 pin conflicts with managed reference")
        return f"managed:{digest}", _managed_path(_store_root(), digest), digest
    if not selected:
        raise XhhSignerError("invalid signer path; explicit signer reference must not be empty")
    path = Path(selected).expanduser().resolve()
    return str(path), path, pin


def install_signer(source: str | Path, *, sha256: str) -> str:
    """Import verified bytes without running Java or selecting any account."""
    digest = _normalize_digest(sha256)
    temporary: Path | None = None
    try:
        source_path = Path(source).expanduser().resolve()
        _require_file(source_path)
        root = _store_root()
        root.mkdir(parents=True, exist_ok=True)
        destination = _managed_path(root, digest)
        with source_path.open("rb") as reader:
            if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
                raise XhhSignerError("signer source must be a regular file")
            with tempfile.NamedTemporaryFile(prefix=".install-", suffix=".tmp", dir=root,
                                             delete=False) as writer:
                temporary = Path(writer.name)
                copied_digest = hashlib.sha256()
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(block)
                    copied_digest.update(block)
                if copied_digest.hexdigest() != digest:
                    raise XhhSignerError("signer SHA-256 mismatch; import refused")
                writer.flush()
                os.fsync(writer.fileno())
        destination = _managed_path(root, digest)
        try:
            # A hard link publishes complete bytes without replacing an existing file.
            os.link(temporary, destination)
        except FileExistsError:
            pass
        _reject_links(destination)
        _verify_file(destination, digest)
        return f"managed:{digest}"
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise XhhSignerError(f"cannot install signer: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise XhhSignerError(f"signer import cleanup failed: {exc}") from exc


def inspect_signer(reference: str | Path | None = None) -> dict:
    """Resolve and hash an artifact without Java, credentials, or network access."""
    try:
        selected, path, pin = _select_jar(reference)
        actual = _verify_file(path, pin)
        return {"reference": selected, "resolved_path": str(path), "sha256": actual, "passed": True}
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise XhhSignerError(f"cannot inspect signer: {exc}") from exc


def _bundle_request(resources: Path, path: str, timestamp: int, signer: "Signer") -> str:
    """Build the strict stdin request the public loader expects."""
    fields = (
        ("protocol", "1"),
        ("resource_dir", str(resources)),
        ("path", path),
        ("timestamp", str(timestamp)),
        ("identity", signer.identity),
        ("imei", signer.imei),
        ("device_info", signer.device_info),
        ("os_version", signer.os_version),
        ("app_version", signer.app_version),
    )
    return "".join(f"{key}={value}\n" for key, value in fields)


class Signer:
    """Produces the `_time/nonce/hkey/_rnd` quadruple for one request path.

    Parameters
    ----------
    jar:
        Local path or managed:<sha256>, then XHH_SIGNER_JAR, then the legacy
        vendor path. This package never ships the vendor JAR.
    sha256:
        Optional trusted digest pin, falling back to XHH_SIGNER_SHA256.
    identity / imei / device_info:
        Account and device binding. The device values must belong to the same
        account as the credentials; the platform checks the pairing.
    java:
        Java executable name or path (needs a JRE on PATH by default).
    timeout:
        Seconds allowed for one signing call.
    """

    def __init__(
        self,
        *,
        jar: str | Path | None = None,
        bundle: str | Path | None = None,
        sha256: str | None = None,
        identity: str,
        imei: str,
        device_info: str,
        os_version: str = "14",
        app_version: str = "1.3.385",
        java: str = "java",
        timeout: float = 120.0,
    ) -> None:
        self.bundle: dict | None = None
        self.resources: Path | None = None
        try:
            if bundle is not None:
                # Imported lazily: the bundle module re-uses the helpers above.
                from .signer_bundle import resolve_bundle
                self.bundle = resolve_bundle(bundle)
                self.reference = self.bundle["reference"]
                self.jar = Path(self.bundle["loader"])
                self.sha256 = self.bundle["loader_sha256"]
                self.resources = Path(self.bundle["resources"])
            else:
                self.reference, self.jar, self.sha256 = _select_jar(jar, sha256)
                _require_file(self.jar)
                if self.reference.startswith("managed:"):
                    _verify_file(self.jar, self.sha256)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            raise XhhSignerError("invalid signer path; set XHH_SIGNER_JAR to a readable JAR file") from exc
        self.identity = str(identity).strip()
        self.imei = str(imei).strip()
        self.device_info = str(device_info).strip()
        self.os_version = str(os_version).strip()
        self.app_version = str(app_version).strip()
        self.timeout = float(timeout)
        for name, value in (("identity", self.identity), ("imei", self.imei),
                            ("device_info", self.device_info),
                            ("os_version", self.os_version),
                            ("app_version", self.app_version)):
            if not value or any(c in value for c in "\r\n\x00"):
                raise XhhSignerError(f"{name} must be a non-empty single-line string")
            if any(c in value for c in "\\;"):
                raise XhhSignerError(f"{name} contains a character the loader rejects")
        java_path = shutil.which(java)
        if java_path is None and Path(java).is_file():
            java_path = java
        if java_path is None:
            raise XhhSignerError(
                f"java executable not found ({java!r}); install a JRE 17+ "
                "or pass java=<path>")
        self.java = str(Path(java_path).resolve())

    def sign(self, path: str, timestamp: int | None = None) -> dict[str, str]:
        """Sign `path` (must start with '/') for `timestamp` (default: now)."""
        if not path.startswith("/") or "?" in path or "#" in path or ".." in path:
            raise XhhSignerError(f"invalid signer path: {path!r}")
        clean = path.rstrip("/") + "/"
        import time as _time
        ts = int(timestamp if timestamp is not None else _time.time())
        env = {key: value for key, value in os.environ.items()
               if key.upper() in _CHILD_ENV_KEYS}
        env["HEYBOX_ID"] = self.identity
        env["HEYBOX_IMEI"] = self.imei
        try:
            if self.reference.startswith("managed:"):
                _reject_links(self.jar)
            if self.sha256 is not None:
                _verify_file(self.jar, self.sha256)
            with tempfile.TemporaryDirectory(prefix="xhh-signer-") as workdir:
                env.update(TMP=workdir, TEMP=workdir, TMPDIR=workdir)
                if self.resources is not None:
                    command = [self.java, f"-Djava.io.tmpdir={workdir}", "-jar", str(self.jar)]
                    payload: str | None = _bundle_request(self.resources, clean, ts, self)
                else:
                    command = [self.java, f"-Djava.io.tmpdir={workdir}", "-jar", str(self.jar),
                               clean, str(ts), self.identity, self.imei]
                    payload = None
                proc = subprocess.run(
                    command, input=payload,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=self.timeout, check=False, env=env,
                    shell=False, cwd=workdir,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
        except subprocess.TimeoutExpired as exc:
            raise XhhSignerError("signer timed out") from exc
        except OSError as exc:
            raise XhhSignerError(f"signer failed to start: {exc}") from exc
        if proc.returncode != 0:
            raise XhhSignerError(f"signer exited {proc.returncode}")
        matches = re.findall(r"(?m)^\s*(\{[^\r\n]*\})\s*$", proc.stdout)
        if not matches:
            raise XhhSignerError("signer produced no JSON line")
        try:
            out = json.loads(matches[-1])
        except ValueError as exc:
            raise XhhSignerError("signer output is not valid JSON") from exc
        if not isinstance(out, dict) or not FIELDS <= set(out):
            raise XhhSignerError(f"signer output missing fields: {sorted(FIELDS - set(out))}")
        if str(out["_time"]) != str(ts):
            raise XhhSignerError("signer echoed a different timestamp")
        result = {key: str(out[key]) for key in FIELDS}
        if any(not v or any(c in v for c in "\r\n\x00") for v in result.values()):
            raise XhhSignerError("signer produced an unsafe field value")
        return result

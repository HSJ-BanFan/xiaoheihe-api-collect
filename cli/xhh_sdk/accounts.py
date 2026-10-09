"""Explicit account selection with current-user Windows DPAPI storage."""
from __future__ import annotations

import base64
import ctypes as C
from ctypes import wintypes as W
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

from .config import XhhConfig
from .exceptions import XhhConfigError

_CONFIG_KEYS = {"java", "signer_jar", "signer_bundle", "imei", "device_info",
                "app_version", "os_version", "timeout", "protocol_mode"}
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10))}


@dataclass
class ManagedAccount:
    alias: str
    identity: str
    pkey: str | None = field(repr=False)
    config: dict
    revision: str
    risk_token: str | None = field(default=None, repr=False)


class _Blob(C.Structure):
    _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]


def _function(dll, name, args, result):
    function = getattr(dll, name)
    function.argtypes, function.restype = args, result
    return function


def _windows():
    if sys.platform != "win32":
        raise XhhConfigError("Managed accounts require Windows DPAPI; no plaintext fallback")
    return C.WinDLL("kernel32", use_last_error=True)


def _free(pointer):
    _function(_windows(), "LocalFree", [W.HLOCAL], W.HLOCAL)(C.cast(pointer, W.HLOCAL))


def _dpapi(data: bytes, *, decrypt=False) -> bytes:
    _windows()
    dll = C.WinDLL("crypt32", use_last_error=True)
    name = "CryptUnprotectData" if decrypt else "CryptProtectData"
    description_type = C.POINTER(W.LPWSTR) if decrypt else W.LPCWSTR
    function = _function(dll, name, [C.POINTER(_Blob), description_type, C.POINTER(_Blob),
        C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(_Blob)], W.BOOL)
    buffer = C.create_string_buffer(data)
    source = _Blob(len(data), C.cast(buffer, C.POINTER(C.c_ubyte)))
    target = _Blob()
    if not function(C.byref(source), None, None, None, None, 1, C.byref(target)):
        raise XhhConfigError("Credential protection failed")
    try:
        return C.string_at(target.data, target.size)
    finally:
        _free(target.data)


def _restrict_directory(path: Path):
    # Protected owner-rights DACL is inherited by all newly created store files.
    dll = C.WinDLL("advapi32", use_last_error=True)
    convert = _function(dll, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
        [W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.POINTER(W.DWORD)], W.BOOL)
    set_security = _function(dll, "SetFileSecurityW", [W.LPCWSTR, W.DWORD, C.c_void_p], W.BOOL)
    descriptor = C.c_void_p()
    if not convert("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)", 1, C.byref(descriptor), None):
        raise XhhConfigError("Private directory protection failed")
    try:
        if not set_security(str(path), 0x80000004, descriptor):
            raise XhhConfigError("Private directory protection failed")
    finally:
        _free(descriptor)


def _alias(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", value) or value.upper() in _RESERVED:
        raise XhhConfigError("Invalid account alias")
    return value.casefold()


def _identity(value, *, optional=False):
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,32}", value):
        raise XhhConfigError("Account identity must be numeric")
    return value


def _cookie(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 33 or ord(c) > 126 or c == ";" for c in value):
        raise XhhConfigError("Invalid account session cookie")


def _config(values):
    if not isinstance(values, dict) or values.keys() - _CONFIG_KEYS:
        raise XhhConfigError("Unsupported account configuration")
    for key, value in values.items():
        if key == "protocol_mode":
            valid = value in ("app", "web")
        elif key == "timeout":
            valid = type(value) in (float, int) and 0 < value <= 120 and math.isfinite(value)
        elif key == "signer_jar" and value is None:
            valid = True
        else:
            valid = isinstance(value, str) and bool(value.strip()) and not any(c in value for c in "\r\n\x00;")
        if not valid:
            raise XhhConfigError("Invalid account configuration value")
    return dict(values)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _public(account, **extra):
    identity = account.identity
    masked = identity[:2] + "*" * (len(identity) - 4) + identity[-2:] if len(identity) > 4 else "*" * len(identity)
    return {"alias": account.alias, "identity_masked": masked,
            "authenticated": bool(account.pkey), "state": "logged_in" if account.pkey else "needs_login",
            "storage": "windows-dpapi", "protocol_mode": account.config.get("protocol_mode", "app"),
            **extra}


class AccountStore:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()

    @contextmanager
    def _locked(self):
        kernel = _windows()
        create = _function(kernel, "CreateMutexW", [C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE)
        wait = _function(kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)
        release = _function(kernel, "ReleaseMutex", [W.HANDLE], W.BOOL)
        close = _function(kernel, "CloseHandle", [W.HANDLE], W.BOOL)
        digest = hashlib.sha256(str(self.root.resolve()).casefold().encode()).hexdigest()
        handle = create(None, False, "Global\\xhh-sdk-accounts-" + digest)
        if not handle:
            raise XhhConfigError("Account store lock unavailable")
        acquired = False
        try:
            acquired = wait(handle, 30000) in (0, 0x80)
            if not acquired:
                raise XhhConfigError("Account store is busy")
            for path in (self.root, self.root / "accounts.json"):
                if path.exists() and path.lstat().st_file_attributes & 0x400:
                    raise XhhConfigError("Account store cannot use reparse points")
            yield
        except XhhConfigError:
            raise
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            raise XhhConfigError("Account store operation failed") from None
        finally:
            if acquired:
                release(handle)
            close(handle)

    def _read(self):
        path = self.root / "accounts.json"
        if not path.exists():
            return {}
        try:
            document = json.loads(path.read_bytes(), object_pairs_hook=_object)
            if not isinstance(document, dict) or set(document) != {"schema_version", "accounts"} or type(document["schema_version"]) is not int or document["schema_version"] != 1 or not isinstance(document["accounts"], dict):
                raise ValueError()
            accounts = {}
            for key, sealed in document["accounts"].items():
                if not isinstance(sealed, dict) or sealed.get("protection") != "windows-dpapi":
                    raise ValueError()
                raw = _dpapi(base64.b64decode(sealed["value"], validate=True), decrypt=True)
                value = json.loads(raw, object_pairs_hook=_object)
                account = ManagedAccount(**value)
                if key != _alias(account.alias) or not isinstance(account.identity, str) or not re.fullmatch(r"[0-9a-f]{32}", account.revision):
                    raise ValueError()
                _identity(account.identity, optional=account.pkey is None)
                _config(account.config)
                if account.pkey is not None:
                    _cookie(account.pkey)
                accounts[key] = account
            return accounts
        except (XhhConfigError, OSError, ValueError, TypeError, KeyError):
            raise XhhConfigError("Account store is corrupt or unreadable; it was not reset") from None

    def _write(self, accounts):
        document = {"schema_version": 1, "accounts": {key: {
            "protection": "windows-dpapi", "value": base64.b64encode(_dpapi(json.dumps({
                "alias": item.alias, "identity": item.identity, "pkey": item.pkey,
                "config": item.config, "revision": item.revision,
                "risk_token": item.risk_token}).encode())).decode()}
            for key, item in accounts.items()}}
        self.root.mkdir(parents=True, exist_ok=True)
        _restrict_directory(self.root)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as stream:
                name = stream.name
                json.dump(document, stream, ensure_ascii=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.root / "accounts.json")
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def _find(self, accounts, key):
        if key not in accounts:
            raise XhhConfigError("Account not found")
        return accounts[key]

    def add(self, alias: str, *, identity: str | None = None) -> dict:
        key, identity = _alias(alias), _identity(identity, optional=True)
        with self._locked():
            accounts = self._read()
            if key in accounts:
                raise XhhConfigError("Account alias already exists")
            account = ManagedAccount(alias, identity, None, {}, uuid.uuid4().hex)
            accounts[key] = account
            self._write(accounts)
            return _public(account, changed=True)

    def list(self) -> list[dict]:
        with self._locked():
            return [_public(a) for _, a in sorted(self._read().items())]

    def get(self, alias: str) -> ManagedAccount:
        key = _alias(alias)
        with self._locked():
            return self._find(self._read(), key)

    def _change(self, alias, change):
        key = _alias(alias)
        with self._locked():
            accounts = self._read()
            account = self._find(accounts, key)
            change(account)
            account.revision = uuid.uuid4().hex
            self._write(accounts)
            return _public(account, changed=True)

    def configure(self, alias: str, values: dict) -> dict:
        values = _config(values)
        return self._change(alias, lambda account: account.config.update(values))

    def save_login(self, alias: str, *, pkey: str, identity: str, expected_revision: str,
                   protocol_mode: str = "app") -> dict:
        _cookie(pkey)
        identity = _identity(identity)
        mode = _config({"protocol_mode": protocol_mode})
        def update(account):
            if account.revision != expected_revision:
                raise XhhConfigError("Account changed during login; start login again")
            if account.identity and account.identity != identity:
                raise XhhConfigError("Login identity does not match the bound account")
            account.identity, account.pkey = identity, pkey
            account.config.update(mode)
        return self._change(alias, update)

    def logout(self, alias: str) -> dict:
        return self._change(alias, lambda account: setattr(account, "pkey", None))

    def set_risk_token(self, alias: str, token: str) -> dict:
        """Store the device anti-fraud token (sent as the x_xhh_tokenid cookie)."""
        if not isinstance(token, str) or not token.strip() or any(c in token for c in "\r\n\x00;"):
            raise XhhConfigError("Invalid risk token")
        return self._change(alias, lambda account: setattr(account, "risk_token", token.strip()))

    def remove(self, alias: str) -> dict:
        key = _alias(alias)
        with self._locked():
            accounts = self._read()
            account = self._find(accounts, key)
            del accounts[key]
            self._write(accounts)
            return {"alias": account.alias, "changed": True, "removed": True}

    def get_config(self, alias: str) -> XhhConfig:
        account = self.get(alias)
        if not account.pkey:
            raise XhhConfigError("Account is not logged in; run account login")
        try:
            config = XhhConfig(pkey=account.pkey, heybox_id=account.identity, **account.config)
            config.validate()
            return config
        except (XhhConfigError, TypeError, ValueError):
            raise XhhConfigError("Invalid managed account configuration") from None

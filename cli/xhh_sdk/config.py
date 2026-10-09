"""Client configuration: credentials + device binding + endpoints.

Credentials can come from the environment (XHH_PKEY / XHH_HEYBOX_ID /
XHH_IMEI / XHH_DEVICE_INFO) or from a JSON config file. The file stores the
session cookie value (`pkey`), which is a credential: keep it out of git.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import XhhConfigError

DEFAULT_API_BASE = "https://api.xiaoheihe.cn"
DEFAULT_WEB_ORIGIN = "https://www.xiaoheihe.cn"
DEFAULT_APP_VERSION = "1.3.385"
DEFAULT_OS_VERSION = "14"
DEFAULT_DEVICE = "25102RKBEC"


@dataclass
class XhhConfig:
    """Everything the client needs to sign and send requests."""

    pkey: str
    heybox_id: str
    imei: str = DEFAULT_DEVICE
    device_info: str = DEFAULT_DEVICE
    api_base: str = DEFAULT_API_BASE
    web_origin: str = DEFAULT_WEB_ORIGIN
    app_version: str = DEFAULT_APP_VERSION
    os_version: str = DEFAULT_OS_VERSION
    signer_jar: str | None = None
    signer_bundle: str | None = None
    java: str = "java"
    timeout: float = 30.0
    user_agent_app: str = (
        "Mozilla/5.0 (Linux; Android 14; 25102RKBEC Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36")
    user_agent_web: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    extra: dict = field(default_factory=dict)
    protocol_mode: str = "app"

    def validate(self) -> None:
        if self.protocol_mode not in ("app", "web"):
            raise XhhConfigError("protocol_mode must be app or web")
        for name, value in (("pkey", self.pkey), ("heybox_id", self.heybox_id),
                            ("imei", self.imei), ("device_info", self.device_info)):
            if not isinstance(value, str) or not value.strip():
                raise XhhConfigError(f"{name} is required and must be a non-empty string")
            if any(c in value for c in "\r\n\x00;"):
                raise XhhConfigError(f"{name} contains an illegal character")
        if not str(self.heybox_id).isdigit():
            raise XhhConfigError("heybox_id must be numeric")
        if not self.api_base.startswith("https://"):
            raise XhhConfigError("api_base must be an https:// URL")
        if not 0 < float(self.timeout) <= 120:
            raise XhhConfigError("timeout must be within (0, 120]")

    @property
    def cookie_app(self) -> str:
        """Cookie for signed (app) requests."""
        return (f"pkey={self.pkey}; heybox_id={self.heybox_id}; "
                f"x_pkey={self.pkey}; x_heybox_id={self.heybox_id}")

    @property
    def cookie_web(self) -> str:
        """Cookie for signed Web API calls and unsigned upload requests."""
        name = "user_pkey" if self.protocol_mode == "web" else "pkey"
        return f"{name}={self.pkey}; user_heybox_id={self.heybox_id};"

    @classmethod
    def from_env(cls) -> "XhhConfig":
        """Build from XHH_* environment variables."""
        pkey = os.environ.get("XHH_PKEY", "")
        heybox_id = os.environ.get("XHH_HEYBOX_ID", "")
        if not pkey or not heybox_id:
            raise XhhConfigError(
                "set XHH_PKEY and XHH_HEYBOX_ID (optionally XHH_IMEI, "
                "XHH_DEVICE_INFO, XHH_SIGNER_JAR, XHH_JAVA)")
        device = os.environ.get("XHH_DEVICE_INFO", DEFAULT_DEVICE)
        config = cls(
            pkey=pkey,
            heybox_id=heybox_id,
            imei=os.environ.get("XHH_IMEI", device),
            device_info=device,
            api_base=os.environ.get("XHH_API_BASE", DEFAULT_API_BASE),
            signer_jar=os.environ.get("XHH_SIGNER_JAR"),
            java=os.environ.get("XHH_JAVA", "java"),
            protocol_mode=os.environ.get("XHH_PROTOCOL_MODE", "app"),
        )
        config.validate()
        return config

    @classmethod
    def from_file(cls, path: str | Path) -> "XhhConfig":
        """Build from a JSON file containing user-supplied credentials."""
        file = Path(path)
        try:
            raw = json.loads(file.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise XhhConfigError(f"config file unreadable: {file}") from exc
        except ValueError as exc:
            raise XhhConfigError(f"config file is not valid JSON: {file}") from exc
        if not isinstance(raw, dict):
            raise XhhConfigError("config file must contain a JSON object")
        known = {k: v for k, v in raw.items()
                 if k in cls.__dataclass_fields__ and k != "extra"}
        unknown = {k: v for k, v in raw.items() if k not in cls.__dataclass_fields__}
        try:
            config = cls(**known)
            config.extra.update(unknown)
            config.validate()
        except (TypeError, ValueError, AttributeError):
            raise XhhConfigError("invalid configuration; required fields or types are incorrect") from None
        return config

    def save(self, path: str | Path) -> Path:
        """Persist to a JSON file (chmod 600 on POSIX)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pkey": self.pkey,
            "heybox_id": self.heybox_id,
            "imei": self.imei,
            "device_info": self.device_info,
            "api_base": self.api_base,
            "app_version": self.app_version,
            "os_version": self.os_version,
            "signer_jar": self.signer_jar,
            "signer_bundle": self.signer_bundle,
            "java": self.java,
            "protocol_mode": self.protocol_mode,
        }
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

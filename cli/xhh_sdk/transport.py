"""HTTP transport: explicit App/Web signing, session-aware uploads, and COS PUT.

Three transports, matching the verified contract:

* `signed_request` selects App or Web signing from the configured protocol.
* `web_request` uses Creator signing for Web sessions and cookie-only App uploads.
* `put_cos` — Tencent COS V5 signed PUT of the raw bytes.

Error mapping is centralized: 发帖频率过快 -> XhhRateLimitError, login
required -> XhhAuthError, everything else non-ok -> XhhAPIError.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import XhhConfig
from .exceptions import (
    XhhAPIError,
    XhhAuthError,
    XhhConfigError,
    XhhRateLimitError,
    XhhTransportError,
)
from .signer import Signer
from .web_signer import sign_web_request

_RATE_LIMIT_MARK = "发帖频率过快"
_SESSION_FIELDS = frozenset({"pkey", "user_pkey", "x_pkey", "heybox_id",
                             "user_heybox_id", "x_heybox_id"})
_WEB_PROTECTED_QUERY = _SESSION_FIELDS | frozenset({
    "_time", "nonce", "hkey", "_rnd", "version", "os_type", "x_os_type",
    "app", "x_app", "x_client_type", "x_client_version", "channel", "imei", "device_info",
})


def _hmac_sha1(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha1).digest()


def cos_authorization(secret_id: str, secret_key: str, method: str, path: str,
                      *, host: str, start: int, end: int) -> str:
    """Tencent COS V5 signature.

    The signKey is the HEX TEXT of the first HMAC digest, not its raw bytes;
    raw bytes produce SignatureDoesNotMatch even with an identical StringToSign.
    """
    key_time = f"{start};{end}"
    sign_key = _hmac_sha1(secret_key.encode(), key_time.encode()).hex().encode()
    header_string = f"host={urllib.parse.quote(host, safe='')}"
    http_string = f"{method.lower()}\n{path}\n\n{header_string}\n"
    sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
    signature = hmac.new(sign_key, string_to_sign.encode(), hashlib.sha1).hexdigest()
    return (f"q-sign-algorithm=sha1&q-ak={secret_id}"
            f"&q-sign-time={key_time}&q-key-time={key_time}"
            f"&q-header-list=host&q-url-param-list=&q-signature={signature}")


class Transport:
    """Owns the HTTP calls and the signer for one account."""

    def __init__(self, config: XhhConfig, signer: Signer | None = None) -> None:
        config.validate()
        self.config = config
        self._signer = signer

    @property
    def signer(self) -> Signer:
        """Resolve signer resources only when a signed operation needs them."""
        if self._signer is None:
            self._signer = Signer(
                jar=self.config.signer_jar,
                bundle=self.config.signer_bundle,
                identity=self.config.heybox_id,
                imei=self.config.imei,
                device_info=self.config.device_info,
                os_version=self.config.os_version,
                app_version=self.config.app_version,
                java=self.config.java,
                timeout=max(60.0, self.config.timeout * 2),
            )
        return self._signer

    @signer.setter
    def signer(self, signer: Signer | None) -> None:
        self._signer = signer

    # -- helpers -----------------------------------------------------------
    def _app_query(self, path: str) -> dict:
        sig = self.signer.sign(path)
        return {
            "os_type": "Android", "x_os_type": "Android",
            "x_client_type": "mobile", "os_version": self.config.os_version,
            "version": self.config.app_version, "build": "1093",
            "channel": "heybox_google", "x_app": "heybox",
            "time_zone": "Asia/Shanghai", "dw": "360", "netmode": "wifi",
            "imei": self.config.imei, "device_info": self.config.device_info,
            "heybox_id": self.config.heybox_id,
            **{k: v for k, v in sig.items() if k != "path"},
        }

    def _open(self, request: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as r:
                return r.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise XhhAuthError(
                    "platform rejected the session (login required or expired)") from exc
            raise XhhAPIError(f"HTTP {exc.code}", status=f"HTTP_{exc.code}") from exc
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                socket.timeout, ConnectionError, OSError) as exc:
            raise XhhTransportError(f"request failed: {exc}") from exc

    def _decode(self, body: bytes) -> dict:
        if len(body) > 4 * 1024 * 1024:
            raise XhhAPIError("response too large")
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise XhhAPIError("response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise XhhAPIError("response is not a JSON object")
        return data

    @staticmethod
    def _check_status(data: dict) -> None:
        status = data.get("status")
        msg = str(data.get("msg") or "")
        if status in ("ok", "success"):
            return
        if status in ("login", "relogin"):
            raise XhhAuthError("platform says: login required (请登录后使用该功能)")
        if _RATE_LIMIT_MARK in msg:
            raise XhhRateLimitError(f"platform throttled the action: {msg}")
        raise XhhAPIError(f"platform returned status={status!r} msg={msg!r}",
                          status=str(status or ""))

    @classmethod
    def _checked_response(cls, path: str, data: dict) -> dict:
        # Creator metadata is the one observed endpoint without an envelope.
        if (path.rstrip("/") == "/bbs/app/api/topic/index"
                and not {"status", "msg", "error", "code"}.intersection(data)
                and all(isinstance(data.get(key), list) for key in
                        ("post_article_plan", "post_pic_link_plan", "extra_declaration_choice"))
                and isinstance(data.get("topics_list_v2"), dict)):
            return {"status": "ok", "result": data}
        cls._check_status(data)
        return data

    # -- protocol selection ------------------------------------------------
    def signed_request(self, path: str, *, query: dict | None = None,
                       payload: dict | None = None,
                       extra_cookies: dict | None = None) -> dict:
        """Use the selected protocol once, without cross-protocol retries."""
        if self.config.protocol_mode == "web":
            return self.web_signed_request(path, query=query, payload=payload,
                                           extra_cookies=extra_cookies)
        return self._app_signed_request(path, query=query, payload=payload,
                                        extra_cookies=extra_cookies)

    # -- app (signed) ------------------------------------------------------
    def _app_signed_request(self, path: str, *, query: dict | None = None,
                            payload: dict | None = None,
                            extra_cookies: dict | None = None) -> dict:
        """Signed GET (payload None) or POST (form-encoded payload).

        ``extra_cookies`` adds device-context cookies the Android client also
        sends, notably ``x_xhh_tokenid`` (the anti-fraud device token). Values
        must be plain cookie atoms; a stray ``;`` would forge a new cookie.
        """
        protected = {"heybox_id", "imei", "device_info", "_time", "nonce", "hkey", "_rnd",
                     "pkey", "x_pkey", "x_heybox_id"}
        if protected.intersection(query or {}):
            raise XhhConfigError("query cannot override protected account or signature fields")
        params = {**self._app_query(path), **(query or {})}
        url = self.config.api_base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
        cookie = self.config.cookie_app
        for name, value in (extra_cookies or {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", name) or not value:
                raise XhhConfigError("invalid extra cookie name or value")
            if any(ord(c) < 33 or ord(c) > 126 or c == ";" for c in str(value)):
                raise XhhConfigError("invalid extra cookie value")
            cookie += f"; {name}={value}"
        headers = {
            "User-Agent": self.config.user_agent_app,
            "Referer": self.config.api_base + "/",
            "Cookie": cookie,
            "Accept": "application/json",
        }
        data = None
        method = "GET"
        if payload is not None:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            method = "POST"
        body = self._open(urllib.request.Request(url, data=data, headers=headers,
                                                 method=method))
        parsed = self._decode(body)
        return self._checked_response(path, parsed)

    # -- session-aware upload POST ----------------------------------------
    def web_request(self, path: str, payload: dict) -> dict:
        """Upload POST: Creator signing for Web sessions, legacy cookie-only for App."""
        if self.config.protocol_mode == "web":
            return self.web_signed_request(path, payload=payload)
        origin = self.config.web_origin
        url = self.config.api_base.rstrip("/") + path
        headers = {
            "User-Agent": self.config.user_agent_web,
            "Referer": origin + "/",
            "Origin": origin,
            "Cookie": self.config.cookie_web,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        body = self._open(urllib.request.Request(url, data=data, headers=headers,
                                                 method="POST"))
        parsed = self._decode(body)
        self._check_status(parsed)
        return parsed

    def web_signed_request(self, path: str, *, query: dict | None = None,
                           payload: dict | None = None,
                           method: str | None = None,
                           extra_cookies: dict | None = None) -> dict:
        """Pure-Python Web signing; payload selects POST unless GET/POST is explicit."""
        if not isinstance(path, str) or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+/?", path):
            raise XhhConfigError("Web request path must be an API route without query or fragment")
        if path.split("/")[1] in ("chat_group", "chatroom"):
            raise XhhConfigError("group and chatroom requests require an App session")
        if _WEB_PROTECTED_QUERY.intersection(query or {}):
            raise XhhConfigError("query cannot override protected Web account, signature or channel fields")
        req_method = method if method is not None else ("POST" if payload is not None else "GET")
        if req_method not in ("GET", "POST"):
            raise XhhConfigError("Web request method must be GET or POST")
        if req_method == "GET" and payload is not None:
            raise XhhConfigError("Web GET requests cannot carry a payload")
        cookie = self.config.cookie_web
        for name, value in (extra_cookies or {}).items():
            if name in _SESSION_FIELDS:
                raise XhhConfigError("extra cookies cannot override protected session fields")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", name) or not value:
                raise XhhConfigError("invalid extra cookie name or value")
            if any(ord(c) < 33 or ord(c) > 126 or c == ";" for c in str(value)):
                raise XhhConfigError("invalid extra cookie value")
            cookie += f" {name}={value};"
        quad = sign_web_request(path)
        params = {
            "os_type": "web",
            "app": "heybox",
            "x_client_type": "weboutapp",
            "x_client_version": "",
            "x_os_type": "Windows",
            "x_app": "heybox",
            "heybox_id": self.config.heybox_id,
            **{key: value for key, value in quad.items() if key != "_rnd"},
            **(query or {}),
        }
        origin = self.config.web_origin
        url = self.config.api_base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
        headers = {
            "User-Agent": self.config.user_agent_web,
            "Referer": origin + "/",
            "Origin": origin,
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
        }
        data = urllib.parse.urlencode(payload).encode("utf-8") if payload is not None else None
        if req_method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = self._open(urllib.request.Request(url, data=data, headers=headers, method=req_method))
        parsed = self._decode(body)
        return self._checked_response(path, parsed)

    # -- COS ---------------------------------------------------------------
    def put_cos(self, endpoint: str, key: str, data: bytes, *,
                secret_id: str, secret_key: str, session_token: str,
                mime: str) -> None:
        """PUT the object bytes with a V5 signature for the addressed host."""
        host = urllib.parse.urlsplit(endpoint).hostname or ""
        now = int(time.time())
        authorization = cos_authorization(secret_id, secret_key, "put", key,
                                          host=host, start=now - 60, end=now + 3600)
        headers = {
            "Authorization": authorization,
            "x-cos-security-token": session_token,
            "Content-Type": mime,
            "Content-Length": str(len(data)),
            "User-Agent": self.config.user_agent_web,
        }
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(endpoint, data=data, headers=headers,
                                           method="PUT"),
                    timeout=max(120.0, self.config.timeout)) as r:
                r.read(1024)
        except urllib.error.HTTPError as exc:
            raise XhhAPIError(f"COS upload rejected: HTTP {exc.code}",
                              status=f"HTTP_{exc.code}") from exc
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                socket.timeout, ConnectionError, OSError) as exc:
            raise XhhTransportError(f"COS upload failed: {exc}") from exc

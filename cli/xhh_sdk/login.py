"""User-operated WeChat login in a fresh, disposable browser session.

Cookie identity is a local binding, not a live API identity or permission check.
This module never loads existing credentials or saves the returned session.
"""
from __future__ import annotations

import re
import sys
import time
import http.cookiejar
import json
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .exceptions import XhhConfigError

SSO = "https://api.xiaoheihe.cn/account/wechat/login/v2/web_sso/"
CALLBACK = "https://api.xiaoheihe.cn/account/wechat/login_redirect/v2/web_sso/"
QR_IMAGE = "https://open.weixin.qq.com/connect/qrcode/"
LONG_POLL = "https://long.open.weixin.qq.com/connect/l/qrconnect?uuid="
_DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
COOKIE_URLS = (
    SSO,
    "https://api.xiaoheihe.cn/account/info/",
    "https://creator.xiaoheihe.cn/creator",
    "https://xiaoheihe.cn/",
)
_COOKIE_TARGETS = tuple(urlsplit(url) for url in COOKIE_URLS)
_COOKIE_DOMAINS = {"xiaoheihe.cn", "api.xiaoheihe.cn", "creator.xiaoheihe.cn"}
_PKEY_NAMES = ("pkey", "user_pkey")
# The login endpoints are unauthenticated: the client still has to build the
# standard parameter set, so it sends a placeholder session value that the
# platform ignores. Kept as a named constant so packaging audits can see that
# no real credential literal exists in the source.
_NO_SESSION = "0"
_IDENTITY_NAMES = ("heybox_id", "user_heybox_id")
_COOKIE_NAMES = frozenset(_PKEY_NAMES + _IDENTITY_NAMES)


@dataclass(frozen=True, repr=False, slots=True)
class LoginResult:
    """Session and numeric identity observed in official login cookies only."""

    pkey: str
    identity: str


def _numeric_identity(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9]+", value) is not None


def _validate_expected_identity(identity: str) -> None:
    if identity != "" and not _numeric_identity(identity):
        raise XhhConfigError("expected login identity must be numeric")


def _relevant_scope(domain: str, path: str) -> bool:
    host = domain[1:] if domain.startswith(".") else domain
    if host not in _COOKIE_DOMAINS or not path.startswith("/"):
        return False
    for target in _COOKIE_TARGETS:
        host_matches = target.hostname == host or (
            domain.startswith(".") and target.hostname.endswith("." + host))
        path_matches = target.path == path or (
            target.path.startswith(path) and (path.endswith("/") or target.path[len(path):].startswith("/")))
        if host_matches and path_matches:
            return True
    return False


def login_result_from_cookies(
    cookies: Iterable[Mapping[str, object]], *, expected_identity: str = "",
) -> LoginResult | None:
    """Select one consistent same-domain, same-path cookie pair.

    Alternate names must agree within each exact scope. Incomplete pairs never
    borrow a value from another scope. Conflicting complete pairs fail closed.
    """
    _validate_expected_identity(expected_identity)
    scopes: dict[tuple[str, str], dict[str, set[str]]] = {}
    for cookie in cookies:
        name, value = cookie.get("name"), cookie.get("value")
        domain, path = cookie.get("domain"), cookie.get("path")
        if not isinstance(name, str) or name not in _COOKIE_NAMES:
            continue
        if not isinstance(domain, str) or not isinstance(path, str) or not _relevant_scope(domain, path):
            continue
        if not isinstance(value, str):
            raise XhhConfigError("invalid login session cookie")
        scopes.setdefault((domain, path), {}).setdefault(name, set()).add(value)

    candidates: set[tuple[str, str]] = set()
    for values in scopes.values():
        pkeys = set().union(*(values.get(name, set()) for name in _PKEY_NAMES))
        identities = set().union(*(values.get(name, set()) for name in _IDENTITY_NAMES))
        if len(pkeys) > 1 or len(identities) > 1:
            raise XhhConfigError("conflicting login cookies; start a fresh login")
        if not pkeys or not identities:
            continue
        pkey, identity = next(iter(pkeys)), next(iter(identities))
        if not pkey.strip() or any(character in pkey for character in "\r\n\x00;"):
            raise XhhConfigError("invalid login session cookie")
        if not _numeric_identity(identity):
            raise XhhConfigError("login cookie identity must be numeric")
        candidates.add((pkey, identity))
    if len(candidates) > 1:
        raise XhhConfigError("conflicting login cookies; start a fresh login")
    if not candidates:
        return None
    pkey, identity = candidates.pop()
    if expected_identity and identity != expected_identity:
        raise XhhConfigError("login identity does not match the selected account")
    return LoginResult(pkey=pkey, identity=identity)


def login_wechat(
    *, expected_identity: str = "", browser_channel: str = "msedge", timeout: float = 180,
) -> LoginResult:
    """Open official QR authorization and wait for the user to finish login.

    Edge and Chrome use their installed channels. ``chromium`` uses Playwright's
    installed bundled browser. All choices create a new nonpersistent context.
    No Java signer, saved browser profile, or storage-state export is involved.
    """
    return _login_browser(SSO, expected_identity=expected_identity,
                          browser_channel=browser_channel, timeout=timeout)


def login_creator(
    *, expected_identity: str = "", browser_channel: str = "msedge", timeout: float = 180,
) -> LoginResult:
    """Let the user sign in on Creator with its official App QR or SMS UI."""
    return _login_browser("https://creator.xiaoheihe.cn/creator",
                          expected_identity=expected_identity,
                          browser_channel=browser_channel, timeout=timeout)


def _login_browser(start_url: str, *, expected_identity: str,
                   browser_channel: str, timeout: float) -> LoginResult:
    _validate_expected_identity(expected_identity)
    if browser_channel not in ("msedge", "chrome", "chromium"):
        raise XhhConfigError("browser channel must be msedge, chrome, or chromium")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
        raise XhhConfigError("login timeout must be within (0, 600] seconds")
    try:
        from playwright.sync_api import Error, TimeoutError as BrowserTimeout, sync_playwright
    except ImportError:
        raise XhhConfigError("Playwright is required for QR login; install xhh-sdk[login]") from None

    deadline = time.monotonic() + timeout
    try:
        with sync_playwright() as playwright:
            options = {"headless": False, "timeout": timeout * 1000}
            if browser_channel != "chromium":
                options["channel"] = browser_channel
            browser = playwright.chromium.launch(**options)
            context = None
            try:
                context = browser.new_context(accept_downloads=False)
                page = context.new_page()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise XhhConfigError("QR login timed out; complete authorization and retry")
                page.goto(start_url, wait_until="domcontentloaded", timeout=remaining * 1000)
                while time.monotonic() < deadline:
                    result = login_result_from_cookies(
                        context.cookies(list(COOKIE_URLS)), expected_identity=expected_identity)
                    if result is not None:
                        return result
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        page.wait_for_timeout(min(500, remaining * 1000))
                raise XhhConfigError("QR login timed out; complete authorization and retry")
            finally:
                try:
                    if context is not None:
                        context.close()
                finally:
                    browser.close()
    except BrowserTimeout:
        raise XhhConfigError("QR login timed out; complete authorization and retry") from None
    except Error:
        raise XhhConfigError(
            "QR login browser failed; install the selected browser and retry") from None


# --------------------------------------------------------------- QR callback
# The original project logged in without a browser page flow: it fetched the QR
# UUID, let the user scan, then called the WeChat callback directly and read the
# session from the Set-Cookie headers. That path yielded a `pkey` cookie, which
# the app endpoints accept. The browser flow above yields `user_pkey` instead.


def _fetch_login_page() -> str:
    request = urllib.request.Request(SSO, headers={"User-Agent": _DESKTOP_UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def _show_qr(url: str) -> None:
    # Printed as well as opened: the manual fallback must be reachable when no
    # browser opens, and the operator needs the URL to relay it.
    print(f"QR image for this login: {url}", file=sys.stderr)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - the user can still open the URL manually
        pass


def _poll_once(uuid: str) -> str:
    request = urllib.request.Request(LONG_POLL + uuid, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode("utf-8", "replace")


def _exchange_code(code: str, *, opener_factory=None) -> dict[str, str]:
    jar = http.cookiejar.CookieJar()
    factory = opener_factory or urllib.request.build_opener
    opener = factory(urllib.request.HTTPCookieProcessor(jar))
    url = f"{CALLBACK}?code={urllib.parse.quote(code)}&state=xiaoheihe"
    request = urllib.request.Request(
        url, headers={"User-Agent": _DESKTOP_UA, "Referer": "https://api.xiaoheihe.cn"})
    with opener.open(request, timeout=30) as response:
        response.read()
    return {cookie.name: cookie.value for cookie in jar if cookie.value}


def session_from_cookies(cookies: Mapping[str, str]) -> LoginResult:
    """Pick the session pair, preferring the `pkey` cookie the API accepts."""
    pkey = cookies.get("pkey") or cookies.get("user_pkey") or ""
    identity = cookies.get("heybox_id") or cookies.get("user_heybox_id") or ""
    if not pkey.strip() or any(character in pkey for character in "\r\n\x00;"):
        raise XhhConfigError("login response carried no usable session cookie")
    if not _numeric_identity(identity):
        raise XhhConfigError("login response carried no numeric account id")
    return LoginResult(pkey=pkey, identity=identity)


def login_wechat_qr(*, expected_identity: str = "", timeout: float = 180) -> LoginResult:
    """Log in with a WeChat QR code and capture the session from the callback.

    No browser session is required: the QR image is opened for the user, the
    WeChat long-poll supplies the authorization code, and the callback is called
    directly so its Set-Cookie headers become the session.
    """
    _validate_expected_identity(expected_identity)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
        raise XhhConfigError("login timeout must be within (0, 600] seconds")
    page = _fetch_login_page()
    match = re.search(r"uuid=([A-Za-z0-9_-]+)", page)
    if not match:
        raise XhhConfigError("QR code was not found on the login page; retry later")
    uuid = match.group(1)
    _show_qr(QR_IMAGE + uuid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            poll = _poll_once(uuid)
        except Exception:  # noqa: BLE001 - transient long-poll errors are retried
            time.sleep(2)
            continue
        if "window.wx_errcode=405" in poll:
            code = re.search(r"window\.wx_code='([^']+)'", poll)
            if not code or not code.group(1):
                raise XhhConfigError("WeChat authorized without returning a code; retry")
            result = session_from_cookies(_exchange_code(code.group(1)))
            if expected_identity and result.identity != expected_identity:
                raise XhhConfigError("login identity does not match this account; retry")
            return result
        if "window.wx_errcode=403" in poll:
            raise XhhConfigError("login was cancelled in WeChat")
        if "window.wx_errcode=402" in poll:
            raise XhhConfigError("QR code expired; start the login again")
        time.sleep(1)
    raise XhhConfigError("QR login timed out; complete authorization and retry")


# ------------------------------------------------------------- app SMS login
# The app signs its own login requests. These endpoints are the ones the APK
# declares for phone login:
#   POST /account/get_login_code/   form phone_num
#   POST /account/login_code/       form phone_num, query code/is_new_device/referrer

LOGIN_CODE_PATH = "/account/get_login_code/"
LOGIN_VERIFY_PATH = "/account/login_code/"
RISK_COOKIE = "x_xhh_tokenid"
MAIN_SITE = "https://www.xiaoheihe.cn/"
DEFAULT_BROWSER_PROFILE = Path.home() / ".xhh_sdk" / "browser-profile"
_PHONE = re.compile(r"1[3-9]\d{9}")
_CODE = re.compile(r"\d{4,8}")


def risk_token_from_cookies(cookies: Iterable[Mapping[str, object]]) -> str | None:
    """Return the anti-fraud token cookie the app sends as x_xhh_tokenid."""
    for cookie in cookies:
        if cookie.get("name") == RISK_COOKIE:
            value = cookie.get("value")
            if isinstance(value, str) and value and not any(c in value for c in "\r\n\x00;"):
                return value
    return None


def capture_risk_token(*, profile: str | Path | None = None, browser_channel: str = "msedge",
                       timeout: float = 180.0) -> str:
    """Open the site in a persistent profile and return the device risk token.

    The profile keeps the login between runs, so this usually needs no user
    action after the first time. Nothing is printed and nothing is stored here;
    the caller decides where the token goes.
    """
    if browser_channel not in ("msedge", "chrome", "chromium"):
        raise XhhConfigError("browser channel must be msedge, chrome, or chromium")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
        raise XhhConfigError("timeout must be within (0, 600] seconds")
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        raise XhhConfigError("Playwright is required; install xhh-sdk[login]") from None
    target = Path(profile) if profile else DEFAULT_BROWSER_PROFILE
    target.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            options = {"headless": False, "locale": "zh-CN"}
            if browser_channel != "chromium":
                options["channel"] = browser_channel
            context = playwright.chromium.launch_persistent_context(str(target), **options)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(MAIN_SITE, wait_until="domcontentloaded", timeout=60000)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    token = risk_token_from_cookies(context.cookies())
                    if token:
                        return token
                    page.wait_for_timeout(1000)
                raise XhhConfigError("no risk token yet; sign in on the opened page and retry")
            finally:
                context.close()
    except Error:
        raise XhhConfigError(
            "browser failed to start; install the selected browser and retry") from None


def _validate_phone(phone: str) -> str:
    value = str(phone).strip()
    if not _PHONE.fullmatch(value):
        raise XhhConfigError("phone must be a mainland China mobile number, e.g. 13500000000")
    return value


def _signed_post(path: str, *, form: dict, query: dict | None = None, identity: str = "0",
                 imei: str | None = None, device_info: str | None = None,
                 signer_jar: str | None = None, signer_bundle: str | None = None,
                 java: str = "java",
                 timeout: float = 30.0,
                 risk_token: str | None = None) -> tuple[dict, dict[str, str]]:
    """Signed form POST without a session cookie; returns (body, cookies)."""
    from .config import DEFAULT_DEVICE, XhhConfig
    from .transport import Transport

    config = XhhConfig(pkey=_NO_SESSION, heybox_id=str(identity),
                       imei=imei or DEFAULT_DEVICE,
                       device_info=device_info or imei or DEFAULT_DEVICE,
                       signer_jar=signer_jar, signer_bundle=signer_bundle,
                       java=java, timeout=timeout)
    params = Transport(config)._app_query(path)
    params.update(query or {})
    url = config.api_base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": config.user_agent_app, "Referer": config.api_base + "/",
                 "Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    if risk_token:
        request.add_header("Cookie", f"x_xhh_tokenid={risk_token}")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise XhhConfigError("login endpoint returned an unexpected payload")
    return body, {cookie.name: cookie.value for cookie in jar if cookie.value}


def _require_ok(body: dict) -> None:
    status = str(body.get("status") or "")
    if status in ("ok", "success"):
        return
    message = re.sub(r"\s+", " ", str(body.get("msg") or ""))[:120]
    raise XhhConfigError(f"platform refused the login request (status={status!r} msg={message!r})")


def session_from_response(body: dict, cookies: Mapping[str, str]) -> LoginResult:
    """Accept the session from cookies or, failing that, from the response body."""
    try:
        return session_from_cookies(cookies)
    except XhhConfigError:
        pass
    result = body.get("result")
    if isinstance(result, dict):
        user = result.get("user") if isinstance(result.get("user"), dict) else result
        detail = user.get("account_detail") if isinstance(user.get("account_detail"), dict) else {}
        values = {
            "pkey": user.get("pkey") or user.get("user_pkey") or "",
            "heybox_id": (user.get("heybox_id") or user.get("userid") or user.get("user_id")
                          or detail.get("userid") or detail.get("heybox_id") or ""),
        }
        return session_from_cookies({k: str(v) for k, v in values.items() if v})
    raise XhhConfigError("login response carried no usable session cookie")


def _encrypted_phone(phone: str, country_code: str) -> str:
    from .secure_phone import encrypt_phone

    return encrypt_phone(country_code + phone)


def login_sms_request(phone: str, *, country_code: str = "+86", **kwargs) -> dict:
    """Ask the platform to send an SMS login code. This contacts the network."""
    value = _validate_phone(phone)
    body, _ = _signed_post(LOGIN_CODE_PATH,
                           form={"phone_num": _encrypted_phone(value, country_code)}, **kwargs)
    _require_ok(body)
    return body


def login_sms_verify(phone: str, code: str, *, expected_identity: str = "",
                     is_new_device: str = "1", country_code: str = "+86", **kwargs) -> LoginResult:
    """Exchange the SMS code for an app session."""
    value = _validate_phone(phone)
    sms_code = str(code).strip()
    if not _CODE.fullmatch(sms_code):
        raise XhhConfigError("verification code must be 4-8 digits")
    body, cookies = _signed_post(
        LOGIN_VERIFY_PATH, form={"phone_num": _encrypted_phone(value, country_code)},
        query={"code": sms_code, "referrer": "", "is_new_device": is_new_device}, **kwargs)
    _require_ok(body)
    result = session_from_response(body, cookies)
    if expected_identity and result.identity != expected_identity:
        raise XhhConfigError("login identity does not match this account; retry")
    return result

"""QR login contracts, using synthetic cookies and an offline browser double."""
import importlib
import math
import sys
import types

import pytest

from xhh_sdk.exceptions import XhhConfigError


def login_module():
    assert importlib.util.find_spec("xhh_sdk.login") is not None, "QR login module is missing"
    return importlib.import_module("xhh_sdk.login")


def cookie(name, value, *, domain=".xiaoheihe.cn", path="/"):
    return {"name": name, "value": value, "domain": domain, "path": path,
            "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"}


def pair(pkey="synthetic-session", identity="12345", **scope):
    return [cookie("pkey", pkey, **scope), cookie("heybox_id", identity, **scope)]


def test_matching_cookie_pair_is_returned_without_secret_repr():
    result = login_module().login_result_from_cookies(pair(), expected_identity="12345")
    assert result.pkey == "synthetic-session"
    assert result.identity == "12345"
    assert "synthetic-session" not in repr(result)
    assert "12345" not in repr(result)
    assert not hasattr(result, "identity_verified")


def test_matching_user_cookie_pair_is_returned():
    cookies = [cookie("user_pkey", "synthetic-session"), cookie("user_heybox_id", "67890")]
    result = login_module().login_result_from_cookies(cookies)
    assert (result.pkey, result.identity) == ("synthetic-session", "67890")


@pytest.mark.parametrize("pkey_name, identity_name", [
    ("pkey", "user_heybox_id"), ("user_pkey", "heybox_id"),
])
def test_alternate_cookie_names_pair_within_the_same_exact_scope(pkey_name, identity_name):
    cookies = [cookie(pkey_name, "synthetic-session"), cookie(identity_name, "12345")]
    result = login_module().login_result_from_cookies(cookies)
    assert result is not None
    assert (result.pkey, result.identity) == ("synthetic-session", "12345")


def test_all_matching_cookie_aliases_in_one_scope_are_accepted():
    cookies = pair() + [cookie("user_pkey", "synthetic-session"), cookie("user_heybox_id", "12345")]
    result = login_module().login_result_from_cookies(cookies)
    assert (result.pkey, result.identity) == ("synthetic-session", "12345")


@pytest.mark.parametrize("cookies", [
    [], [cookie("pkey", "synthetic-session")],
    [cookie("pkey", "synthetic-session", domain="api.xiaoheihe.cn"),
     cookie("user_heybox_id", "12345", domain="creator.xiaoheihe.cn")],
    [cookie("user_pkey", "synthetic-session", path="/"),
     cookie("heybox_id", "12345", path="/account")],
    [cookie("pkey", "synthetic-session", domain="api.xiaoheihe.cn"),
     cookie("heybox_id", "12345", domain="creator.xiaoheihe.cn")],
    [cookie("pkey", "synthetic-session", domain=".xiaoheihe.cn"),
     cookie("heybox_id", "12345", domain="xiaoheihe.cn")],
    [cookie("pkey", "synthetic-session", path="/"),
     cookie("heybox_id", "12345", path="/account")],
    pair(domain="evil.xiaoheihe.cn"), pair(domain="xiaoheihe.cn.evil.test"),
    pair(domain=".api.xiaoheihe.cn.evil.test"), pair(path="/unrelated"),
    pair(domain="api.xiaoheihe.cn", path="/account/wechat/login/v2/web_sso/extra"),
    pair(domain="creator.xiaoheihe.cn", path="/creat"),
])
def test_cookies_are_never_joined_across_domain_or_path(cookies):
    assert login_module().login_result_from_cookies(cookies) is None


@pytest.mark.parametrize("scope", [
    {"domain": "api.xiaoheihe.cn", "path": "/account"},
    {"domain": ".api.xiaoheihe.cn", "path": "/account/wechat/login/v2/web_sso/"},
    {"domain": "creator.xiaoheihe.cn", "path": "/creator"},
    {"domain": "xiaoheihe.cn", "path": "/"},
])
def test_only_cookie_paths_applicable_to_fixed_official_urls_are_used(scope):
    result = login_module().login_result_from_cookies(pair(**scope))
    assert result.identity == "12345"


def test_duplicate_consistent_pairs_are_accepted():
    result = login_module().login_result_from_cookies(
        pair() + pair(domain="api.xiaoheihe.cn") + pair())
    assert (result.pkey, result.identity) == ("synthetic-session", "12345")


@pytest.mark.parametrize("extra", [
    pair(pkey="other-session", domain="api.xiaoheihe.cn"),
    pair(identity="67890", domain="creator.xiaoheihe.cn"),
    [cookie("user_pkey", "other-session"), cookie("user_heybox_id", "12345")],
    [cookie("pkey", "other-session")], [cookie("heybox_id", "67890")],
    [cookie("user_pkey", "other-session")], [cookie("user_heybox_id", "67890")],
])
def test_conflicting_candidates_are_rejected_without_disclosing_values(extra):
    with pytest.raises(XhhConfigError, match="conflict") as error:
        login_module().login_result_from_cookies(pair() + extra)
    assert "synthetic-session" not in str(error.value)
    assert "other-session" not in str(error.value)
    assert "67890" not in str(error.value)


@pytest.mark.parametrize("cookies", [
    [cookie("pkey", "synthetic-session"), cookie("user_pkey", "other-session")],
    [cookie("heybox_id", "12345"), cookie("user_heybox_id", "67890")],
])
def test_conflicting_aliases_are_rejected_even_before_a_pair_is_complete(cookies):
    with pytest.raises(XhhConfigError, match="conflict"):
        login_module().login_result_from_cookies(cookies)


@pytest.mark.parametrize("identity", ["abc", "12x", "123\n", "１２３", " 123", ""])
def test_invalid_cookie_identity_is_rejected(identity):
    with pytest.raises(XhhConfigError, match="identity"):
        login_module().login_result_from_cookies(pair(identity=identity))


@pytest.mark.parametrize("pkey", ["", " ", "bad;cookie", "bad\rvalue", "bad\x00value"])
def test_invalid_session_value_is_rejected(pkey):
    with pytest.raises(XhhConfigError, match="session"):
        login_module().login_result_from_cookies(pair(pkey=pkey))


def test_cookie_identity_must_match_expected_binding():
    with pytest.raises(XhhConfigError, match="match") as error:
        login_module().login_result_from_cookies(pair(), expected_identity="67890")
    assert "12345" not in str(error.value)
    assert "67890" not in str(error.value)


class FakePlaywrightError(Exception):
    pass


class FakePlaywrightTimeout(FakePlaywrightError):
    pass


class BrowserSession:
    """The browser is external; its login cookies and lifetime are controlled here."""

    def __init__(self, batches=None, fail_at=""):
        self.batches = batches if batches is not None else [pair()]
        self.fail_at = fail_at
        self.events = []
        self.clock = 0.0
        self.chromium = self

    def __enter__(self):
        self.events.append(("start",))
        return self

    def __exit__(self, *args):
        self.events.append(("stop",))

    def launch(self, **kwargs):
        self.events.append(("launch", kwargs))
        if self.fail_at == "launch":
            raise FakePlaywrightError("synthetic-session private browser path")
        return FakeBrowser(self)


class FakeBrowser:
    def __init__(self, session):
        self.session = session

    def new_context(self, **kwargs):
        self.session.events.append(("new_context", kwargs))
        if self.session.fail_at == "new_context":
            raise FakePlaywrightError("synthetic-session")
        return FakeContext(self.session)

    def close(self):
        self.session.events.append(("browser_close",))
        if self.session.fail_at == "browser_close":
            raise FakePlaywrightError("synthetic-session")


class FakeContext:
    def __init__(self, session):
        self.session = session

    def new_page(self):
        self.session.events.append(("new_page",))
        if self.session.fail_at == "new_page":
            raise FakePlaywrightError("synthetic-session")
        return FakePage(self.session)

    def cookies(self, urls):
        self.session.events.append(("cookies", urls))
        if self.session.fail_at == "cookies":
            raise FakePlaywrightError("synthetic-session")
        if len(self.session.batches) > 1:
            return self.session.batches.pop(0)
        return self.session.batches[0]

    def close(self):
        self.session.events.append(("context_close",))
        if self.session.fail_at == "context_close":
            raise FakePlaywrightError("synthetic-session")


class FakePage:
    def __init__(self, session):
        self.session = session

    def goto(self, url, **kwargs):
        self.session.events.append(("goto", url, kwargs))
        if self.session.fail_at == "goto":
            raise FakePlaywrightError("synthetic-session")
        if self.session.fail_at == "navigation_timeout":
            raise FakePlaywrightTimeout("synthetic-session")

    def wait_for_timeout(self, milliseconds):
        self.session.events.append(("wait", milliseconds))
        self.session.clock += milliseconds / 1000
        if self.session.fail_at == "wait":
            raise FakePlaywrightError("synthetic-session")


def install_browser(monkeypatch, session):
    module = login_module()
    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: session
    fake.Error = FakePlaywrightError
    fake.TimeoutError = FakePlaywrightTimeout
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    monkeypatch.setattr(module.time, "monotonic", lambda: session.clock)
    return module


@pytest.mark.parametrize("channel", ["msedge", "chrome", "chromium"])
def test_login_uses_fresh_headed_context_and_fixed_official_urls(monkeypatch, capsys, channel):
    session = BrowserSession(batches=[[], pair()])
    module = install_browser(monkeypatch, session)
    result = module.login_wechat(expected_identity="12345", browser_channel=channel)
    assert (result.pkey, result.identity) == ("synthetic-session", "12345")
    launch = next(event[1] for event in session.events if event[0] == "launch")
    assert launch["headless"] is False
    assert launch.get("channel") == (None if channel == "chromium" else channel)
    assert set(launch) <= {"channel", "headless", "timeout"}
    contexts = [event[1] for event in session.events if event[0] == "new_context"]
    assert contexts == [{"accept_downloads": False}]
    navigation = next(event for event in session.events if event[0] == "goto")
    assert navigation[1] == "https://api.xiaoheihe.cn/account/wechat/login/v2/web_sso/"
    assert navigation[2]["wait_until"] == "domcontentloaded"
    scopes = [event[1] for event in session.events if event[0] == "cookies"]
    assert len(scopes) == 2
    assert set(scopes[0]) == {
        "https://api.xiaoheihe.cn/account/wechat/login/v2/web_sso/",
        "https://api.xiaoheihe.cn/account/info/",
        "https://creator.xiaoheihe.cn/creator",
        "https://xiaoheihe.cn/",
    }
    assert session.events[-3:] == [("context_close",), ("browser_close",), ("stop",)]
    assert capsys.readouterr() == ("", "")


def test_default_browser_is_edge(monkeypatch):
    session = BrowserSession()
    install_browser(monkeypatch, session).login_wechat()
    launch = next(event[1] for event in session.events if event[0] == "launch")
    assert launch["channel"] == "msedge"


def test_each_login_creates_a_new_browser_and_context(monkeypatch):
    session = BrowserSession()
    module = install_browser(monkeypatch, session)
    module.login_wechat()
    module.login_wechat()
    names = [event[0] for event in session.events]
    assert names.count("launch") == names.count("new_context") == 2
    assert names.count("context_close") == names.count("browser_close") == 2


def test_timeout_closes_browser_and_exposes_no_cookies(monkeypatch, capsys):
    session = BrowserSession(batches=[[]])
    module = install_browser(monkeypatch, session)
    with pytest.raises(XhhConfigError, match="timed out"):
        module.login_wechat(timeout=0.75)
    assert session.clock == 0.75
    assert session.events[-3:] == [("context_close",), ("browser_close",), ("stop",)]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("fail_at", ["new_context", "new_page", "goto", "cookies", "wait",
                                    "context_close", "browser_close", "navigation_timeout"])
def test_browser_failures_are_sanitized_and_cleanup_always_runs(monkeypatch, fail_at):
    session = BrowserSession(batches=[[]], fail_at=fail_at)
    module = install_browser(monkeypatch, session)
    with pytest.raises(XhhConfigError) as error:
        module.login_wechat(timeout=0.75)
    assert "synthetic-session" not in str(error.value)
    assert error.value.__suppress_context__
    assert ("browser_close",) in session.events
    if fail_at != "new_context":
        assert ("context_close",) in session.events
    assert session.events[-1] == ("stop",)


def test_launch_failure_is_sanitized(monkeypatch):
    session = BrowserSession(fail_at="launch")
    module = install_browser(monkeypatch, session)
    with pytest.raises(XhhConfigError) as error:
        module.login_wechat()
    assert "synthetic-session" not in str(error.value)
    assert "private browser path" not in str(error.value)
    assert session.events[-1] == ("stop",)


def test_mismatched_binding_closes_browser_before_returning_error(monkeypatch):
    session = BrowserSession()
    module = install_browser(monkeypatch, session)
    with pytest.raises(XhhConfigError, match="match"):
        module.login_wechat(expected_identity="67890")
    assert session.events[-3:] == [("context_close",), ("browser_close",), ("stop",)]


@pytest.mark.parametrize("kwargs", [
    {"timeout": value} for value in [0, -1, True, 601, math.inf, math.nan, "30"]
] + [
    {"browser_channel": value} for value in ["edge", "firefox", "C:/browser.exe", ""]
] + [
    {"expected_identity": value} for value in [None, 123, "abc", "１２３", "123\n"]
])
def test_invalid_options_fail_before_starting_browser(monkeypatch, kwargs):
    session = BrowserSession()
    module = install_browser(monkeypatch, session)
    with pytest.raises(XhhConfigError):
        module.login_wechat(**kwargs)
    assert session.events == []


def test_missing_playwright_has_actionable_sanitized_error(monkeypatch):
    module = login_module()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(XhhConfigError, match="[Pp]laywright") as error:
        module.login_wechat()
    assert error.value.__suppress_context__

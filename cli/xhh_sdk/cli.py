"""Command-line interface: `xhh-sdk <command>`.

Commands:
    init        write a config template to ~/.xhh_sdk/config.json
    doctor      environment check (java, jar, config, signer)
    verify      live smoke test (signer + one readback)
    call        signed GET against the historical GET allowlist
    upload      upload image files, print CDN URLs
    drafts      list the draft box
    posts       list the account's own posts
    read        read back one post
    comments    read a post's comment floors
    sub-comments read replies under one floor comment
    my-comments list the account's own comments
    delete      delete a post (asks for --yes)
    publish     create a post from a JSON spec (draft by default)
    comment     comment on an own post (needs --confirm)
    reply       reply in a thread on an own post (needs --confirm)
    delete-comment  delete an own comment (needs --confirm)
    favourite / unfavourite  reversible single-post save (needs --confirm)
    follow-topic / unfollow-topic  reversible topic follow (needs --confirm)
    canary      comment public-visibility probe on an own post (needs --confirm)
    topic-feeds / hashtag-feed  hot-ordered feed reads
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .client import XhhClient
from .config import XhhConfig
from .exceptions import XhhAuthError, XhhConfigError, XhhError
from .payload import Post

DEFAULT_CONFIG = Path.home() / ".xhh_sdk" / "config.json"


def _account_store(args):
    from .accounts import AccountStore
    return AccountStore(Path(args.data_dir) if args.data_dir else Path.home() / ".xhh_sdk")


def _load(args) -> XhhConfig:
    if args.account:
        return _account_store(args).get_config(args.account)
    if args.config:
        return XhhConfig.from_file(args.config)
    if args.env:
        return XhhConfig.from_env()
    raise XhhConfigError("select --account ALIAS, or explicitly use --config FILE / --env")


def _offline_doctor(args) -> int:
    from .signer import inspect_signer

    report = {"offline": True, "signer_executed": False, "signer_ready": False,
              "java_present": False, "account_checked": False}
    try:
        config = _load(args) if (args.account or args.config or args.env) else None
        report["account_checked"] = config is not None
        java = config.java if config else "java"
        report["java_present"] = bool(shutil.which(java) or Path(java).is_file())
        if config is not None and config.signer_bundle:
            from .signer_bundle import resolve_bundle
            report["artifact"] = resolve_bundle(config.signer_bundle)
        else:
            report["artifact"] = inspect_signer(config.signer_jar if config else None)
        report["signer_ready"] = True
    except XhhError as exc:
        report["error"] = str(exc)
    _print(report)
    return 0 if report["signer_ready"] and report["java_present"] else 1


def _redact(data, secret: str | None = None):
    if isinstance(data, dict):
        return {key: "[REDACTED]" if isinstance(value, (str, int)) and not isinstance(value, bool)
                and any(word in str(key).lower()
                        for word in ("pkey", "cookie", "token", "secret", "password", "authorization"))
                else _redact(value, secret) for key, value in data.items()}
    if isinstance(data, (tuple, list)):
        return [_redact(value, secret) for value in data]
    if isinstance(data, str) and secret:
        return data.replace(secret, "[REDACTED]")
    return data


def _print(data, *, secret: str | None = None) -> None:
    print(json.dumps(_redact(data, secret), ensure_ascii=False, indent=2))


def _account_view(account) -> dict:
    return {"alias": account.alias, "identity_masked": _mask_identity(account.identity),
            "authenticated": bool(account.pkey), "state": "logged_in" if account.pkey else "needs_login",
            "storage": "windows-dpapi", "session_valid": "not_checked", "api_identity_verified": False,
            "risk_token_present": bool(getattr(account, "risk_token", None))}


def _mask_identity(identity: str) -> str:
    return "***" + identity[-2:] if len(identity) > 4 else "*" * len(identity)


def _identity_matches(data: dict, expected: str) -> bool:
    identities = set()
    for container in (data, data.get("user"), data.get("account_detail")):
        if not isinstance(container, dict):
            continue
        for key in ("heybox_id", "userid", "user_id", "id"):
            value = container.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).isdigit():
                identities.add(str(value))
    return identities == {expected}


def _manage_account(args) -> int:
    if args.account or args.config or args.env:
        print("account commands take their own alias; do not combine credential selectors", file=sys.stderr)
        return 2
    action = args.account_action
    if action in {"login", "logout", "remove", "configure", "risk-token"} and not args.confirm:
        print("refusing account change without --confirm", file=sys.stderr)
        return 2
    try:
        store = _account_store(args)
        if action == "list":
            _print({"accounts": store.list(), "session_valid": "not_checked"})
        elif action == "add":
            _print(store.add(args.alias, identity=args.identity))
        elif action == "configure":
            values = {}
            for pair in args.set:
                if "=" not in pair:
                    raise XhhConfigError("settings must use KEY=VALUE")
                key, value = pair.split("=", 1)
                if key in values:
                    raise XhhConfigError("duplicate configuration key")
                if key == "timeout":
                    try:
                        value = float(value)
                    except ValueError:
                        raise XhhConfigError("timeout must be numeric") from None
                values[key] = value
            _print(store.configure(args.alias, values))
        elif action == "login":
            account = store.get(args.alias)
            if args.method == "qr":
                from .login import login_wechat_qr as login_impl
                print(f"Scan the QR image that opens in your browser for alias {account.alias}; "
                      "confirm it is the intended account.", file=sys.stderr)
                result = login_impl(expected_identity=account.identity, timeout=args.timeout)
            elif args.method == "sms":
                from .login import login_sms_request, login_sms_verify
                if not args.phone:
                    raise XhhConfigError("--phone is required for --method sms")
                identity = args.identity or account.identity
                if not identity:
                    raise XhhConfigError("--identity is required for an unbound alias")
                risk_token = (args.risk_token or os.environ.get("XHH_RISK_TOKEN", "")
                              or account.risk_token or "")
                if not risk_token:
                    raise XhhConfigError(
                        "no risk token: run `account risk-token ALIAS --confirm` first, "
                        "or pass --risk-token / set XHH_RISK_TOKEN")
                options = {"imei": account.config.get("imei"), "device_info": account.config.get("device_info"),
                           "signer_jar": account.config.get("signer_jar"),
                           "signer_bundle": account.config.get("signer_bundle"),
                           "java": account.config.get("java", "java"),
                           "identity": identity, "risk_token": risk_token}
                if args.code:
                    result = login_sms_verify(args.phone, args.code,
                                              expected_identity=account.identity, **options)
                else:
                    body = login_sms_request(args.phone, **options)
                    _print({"status": body.get("status"), "code_sent": True,
                            "next": f"rerun with --code <sms code> to finish logging in {account.alias}"})
                    return 0
            else:
                from .login import login_wechat as login_impl
                print(f"Opening official login for alias {account.alias}; confirm the intended account.",
                      file=sys.stderr)
                result = login_impl(expected_identity=account.identity,
                                    browser_channel=args.browser, timeout=args.timeout)
            saved = store.save_login(args.alias, pkey=result.pkey, identity=result.identity,
                                     expected_revision=account.revision)
            report = {**saved, "api_identity_verified": False, "session_valid": "not_checked",
                      "browser_session_persisted": False, "login_method": args.method}
            # A stored session is not a usable one: verify it with an app-signed
            # read and never report a rejected session as logged in.
            try:
                data = XhhClient(store.get_config(args.alias)).account_info()
            except XhhAuthError:
                report.update(state="expired", session_valid=False)
            except XhhError as exc:
                report.update(state="rejected", session_valid=False, reason=str(exc)[:120])
            else:
                verified = _identity_matches(data, result.identity)
                report.update(state="verified" if verified else "identity_unverified",
                              session_valid=bool(verified), api_identity_verified=verified)
            _print(report)
            return 0 if report["api_identity_verified"] else 1
        elif action in {"logout", "remove"}:
            result = store.logout(args.alias) if action == "logout" else store.remove(args.alias)
            _print({**result, "server_session_revoked": False, "browser_session_persisted": False})
        elif action == "risk-token":
            from .login import capture_risk_token
            print(f"Opening the site for alias {args.alias}; sign in if it asks.", file=sys.stderr)
            token = capture_risk_token(browser_channel=args.browser, timeout=args.timeout)
            _print({**store.set_risk_token(args.alias, token), "risk_token_present": True})
        elif action == "status":
            account = store.get(args.alias)
            report = _account_view(account)
            if args.online:
                if not account.pkey:
                    _print(report)
                    return 1
                config = store.get_config(args.alias)
                try:
                    data = XhhClient(config).account_info()
                except XhhAuthError:
                    _print({**report, "state": "expired", "session_valid": False})
                    return 1
                except XhhError:
                    _print({**report, "state": "check_failed", "session_valid": "unknown"})
                    return 1
                if store.get(args.alias).revision != account.revision:
                    _print({**report, "state": "account_changed", "session_valid": "unknown"})
                    return 1
                verified = _identity_matches(data, account.identity)
                report.update(api_identity_verified=verified,
                              session_valid=True if verified else "unknown",
                              state="verified" if verified else "identity_unverified")
                _print(report)
                return 0 if verified else 1
            _print(report)
        return 0
    except XhhError as exc:
        print(f"account error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(
        prog="xhh-sdk", description="Unofficial xiaoheihe creation/upload SDK (research use only)")
    parser.add_argument("--version", action="version", version=f"xhh-sdk {__version__}")
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument("--account", help="explicit managed account alias for this operation")
    selectors.add_argument("--config", help="explicit legacy credential file (no automatic fallback)")
    selectors.add_argument("--env", action="store_true", help="explicitly use XHH_* legacy credentials")
    parser.add_argument("--data-dir", help="managed account directory (default: ~/.xhh_sdk)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_account = sub.add_parser("account", help="manage isolated Windows DPAPI accounts")
    actions = p_account.add_subparsers(dest="account_action", required=True)
    actions.add_parser("list", help="list aliases, without network or secret output")
    p_add = actions.add_parser("add", help="create an alias without credentials")
    p_add.add_argument("alias")
    p_add.add_argument("--identity", help="optional expected numeric account ID")
    p_status = actions.add_parser("status", help="local state; --online checks API identity")
    p_status.add_argument("alias")
    p_status.add_argument("--online", action="store_true")
    p_login = actions.add_parser("login", help="open official WeChat QR login in a fresh browser")
    p_login.add_argument("alias")
    p_login.add_argument("--browser", choices=["msedge", "chrome", "chromium"], default="msedge")
    p_login.add_argument("--method", choices=["qr", "browser", "sms"], default="qr",
                         help="qr/browser: WeChat web SSO (yields a web session the app API "
                              "rejected with status=relogin when tested 2026-10-08); "
                              "sms: app session from a phone code (verified working)")
    p_login.add_argument("--phone", help="mobile number for --method sms")
    p_login.add_argument("--code", help="SMS code for --method sms; omit to send a new code")
    p_login.add_argument("--identity", help="numeric account id used to sign --method sms requests")
    p_login.add_argument("--risk-token", help="x_xhh_tokenid value from a logged-in browser session")
    p_login.add_argument("--timeout", type=float, default=180)
    p_login.add_argument("--confirm", action="store_true")
    for action in ("logout", "remove"):
        p = actions.add_parser(action, help="local account change, does not revoke server sessions")
        p.add_argument("alias")
        p.add_argument("--confirm", action="store_true")
    p_configure = actions.add_parser("configure", help="set nonsecret signer/device settings")
    p_configure.add_argument("alias")
    p_configure.add_argument("--set", action="append", required=True, metavar="KEY=VALUE")
    p_configure.add_argument("--confirm", action="store_true")
    p_risk = actions.add_parser("risk-token",
                                help="open the site and store the device anti-fraud token")
    p_risk.add_argument("alias")
    p_risk.add_argument("--browser", choices=["msedge", "chrome", "chromium"], default="msedge")
    p_risk.add_argument("--timeout", type=float, default=180)
    p_risk.add_argument("--confirm", action="store_true")

    sub.add_parser("init", help="write a config template")
    p_doctor = sub.add_parser("doctor", help="environment check; --offline never executes the signer")
    p_doctor.add_argument("--offline", action="store_true", help="check artifact bytes and Java discovery only")
    p_signer = sub.add_parser("signer", help="manage local signer artifacts without executing Java")
    signer_actions = p_signer.add_subparsers(dest="signer_action", required=True)
    p_install = signer_actions.add_parser("install", help="copy digest-verified bytes into user storage")
    p_install.add_argument("source", type=Path)
    p_install.add_argument("--sha256", required=True)
    p_install.add_argument("--confirm", action="store_true")
    p_inspect = signer_actions.add_parser("inspect", help="inspect a selected signer without Java")
    p_inspect.add_argument("reference", nargs="?")
    p_prepare = signer_actions.add_parser("prepare-apk", help="extract verified local APK resources; no Java or network")
    p_prepare.add_argument("apk", type=Path)
    p_prepare.add_argument("--out", type=Path, required=True)
    p_prepare.add_argument("--confirm", action="store_true")
    p_resources = signer_actions.add_parser("inspect-resources", help="verify extracted resources without Java")
    p_resources.add_argument("directory", type=Path)
    p_apk = signer_actions.add_parser(
        "inspect-apk", help="diagnose whether an APK can supply the pinned resources")
    p_apk.add_argument("apk", type=Path)
    p_bundle = signer_actions.add_parser(
        "bundle-install", help="store verified resources plus a loader JAR as one bundle")
    p_bundle.add_argument("--resources", type=Path, required=True)
    p_bundle.add_argument("--loader", type=Path, required=True)
    p_bundle.add_argument("--loader-sha256", required=True)
    p_bundle.add_argument("--confirm", action="store_true")
    p_bundle_inspect = signer_actions.add_parser(
        "bundle-inspect", help="re-verify an installed bundle without Java")
    p_bundle_inspect.add_argument("reference")
    p_selftest = signer_actions.add_parser(
        "selftest", help="run one local signature with explicit values; no network or credentials")
    p_selftest.add_argument("reference", help="bundle:<sha256>, managed:<sha256> or a local JAR")
    p_selftest.add_argument("--identity", required=True, help="app identity used for this test")
    p_selftest.add_argument("--imei", required=True, help="device imei used for this test")
    p_selftest.add_argument("--device-info", required=True, help="device model used for this test")
    p_selftest.add_argument("--os-version", default="14")
    p_selftest.add_argument("--app-version", default="1.3.385")
    p_selftest.add_argument("--path", default="/account/info")
    p_selftest.add_argument("--timestamp", type=int, default=1700000000)
    sub.add_parser("verify", help="live smoke test")
    p_catalog = sub.add_parser("catalog", help="offline interface purposes and historical evidence")
    p_catalog.add_argument("--search", default="", help="filter routes, purposes or commands")
    p_catalog.add_argument("--route", help="show one exact route, including review status")
    p_catalog.add_argument("--json", action="store_true", help="machine-readable catalog")
    p_catalog.add_argument("--group", action="store_true",
                           help="list the App-only group/community routes instead")

    p_call = sub.add_parser("call", help="signed request using the historical GET allowlist")
    p_call.add_argument("route", help="e.g. /account/info")
    p_call.add_argument("--query", action="append", default=[],
                        metavar="K=V", help="query parameter (repeatable)")

    from .groups import numeric_id, limit_value, offset_value
    p_group = sub.add_parser("group", help="read-only App group commands")
    group_sub = p_group.add_subparsers(dest="group_action", required=True)
    group_sub.add_parser("list", help="list groups joined by this account")
    members = group_sub.add_parser("members", help="read one page of group members")
    members.add_argument("group_id", type=numeric_id)
    members.add_argument("--offset", type=offset_value, default=0)
    members.add_argument("--limit", type=limit_value, default=20)
    messages = group_sub.add_parser("messages", help="read one page of group messages")
    messages.add_argument("group_id", type=numeric_id)
    messages.add_argument("--last-msg-id", type=numeric_id, default="0")
    messages.add_argument("--limit", type=limit_value, default=20)

    p_upload = sub.add_parser("upload", help="upload images")
    p_upload.add_argument("files", nargs="+")
    p_upload.add_argument("--confirm", action="store_true")

    sub.add_parser("drafts", help="list drafts")
    sub.add_parser("posts", help="list own posts")

    p_read = sub.add_parser("read", help="read one post")
    p_read.add_argument("link_id")

    p_comments = sub.add_parser("comments", help="read a post's comment floors")
    p_comments.add_argument("link_id")
    p_comments.add_argument("--page", type=int, default=1)
    p_comments.add_argument("--limit", type=int, default=50)
    p_comments.add_argument("--sort", choices=["hot", "time_aes", "time_desc"])

    p_sub = sub.add_parser("sub-comments",
                           help="read replies under one floor comment")
    p_sub.add_argument("root_comment_id")
    p_sub.add_argument("--lastval", default=None)

    p_myc = sub.add_parser("my-comments",
                           help="list the account's own comments")
    p_myc.add_argument("--offset", type=int, default=0)
    p_myc.add_argument("--limit", type=int, default=20)

    p_delete = sub.add_parser("delete", help="delete a post")
    p_delete.add_argument("link_id")
    p_delete.add_argument("--yes", action="store_true", help="confirm deletion")
    p_delete.add_argument("--confirm", action="store_true", help="confirm deletion")

    p_publish = sub.add_parser("publish", help="create a post from JSON")
    p_publish.add_argument("spec", help="JSON file or '-' for stdin")
    p_publish.add_argument("--publish", action="store_true",
                           help="publish for real (default: save as draft)")
    p_publish.add_argument("--confirm", action="store_true", help="confirm draft or public write")

    p_comment = sub.add_parser("comment", help="comment on an own post")
    p_comment.add_argument("link_id")
    p_comment.add_argument("text")
    p_comment.add_argument("--cy", action="store_true", help="mark as CY")
    p_comment.add_argument("--confirm", action="store_true",
                           help="confirm this live write")

    p_reply = sub.add_parser("reply",
                             help="reply in a thread on an own post")
    p_reply.add_argument("link_id")
    p_reply.add_argument("root_id")
    p_reply.add_argument("reply_id")
    p_reply.add_argument("text")
    p_reply.add_argument("--confirm", action="store_true")

    p_delc = sub.add_parser("delete-comment", help="delete an own comment")
    p_delc.add_argument("link_id")
    p_delc.add_argument("comment_id")
    p_delc.add_argument("--confirm", action="store_true")

    p_fav = sub.add_parser("favourite", help="favourite one post")
    p_fav.add_argument("link_id")
    p_fav.add_argument("--folder-id", default=None)
    p_fav.add_argument("--confirm", action="store_true")

    p_unfav = sub.add_parser("unfavourite", help="remove one post from favourites")
    p_unfav.add_argument("link_id")
    p_unfav.add_argument("--confirm", action="store_true")

    p_follow = sub.add_parser("follow-topic", help="follow one topic")
    p_follow.add_argument("topic_id")
    p_follow.add_argument("--confirm", action="store_true")

    p_unfollow = sub.add_parser("unfollow-topic", help="unfollow one topic")
    p_unfollow.add_argument("topic_id")
    p_unfollow.add_argument("--confirm", action="store_true")

    p_canary = sub.add_parser(
        "canary", help="comment public-visibility probe on an own post")
    p_canary.add_argument("link_id")
    p_canary.add_argument("--wait", type=int, default=20,
                          help="seconds before the second visibility check")
    p_canary.add_argument("--confirm", action="store_true")

    p_topic = sub.add_parser("topic-feeds",
                             help="hot-ordered posts in a topic")
    p_topic.add_argument("topic_id")
    p_topic.add_argument("--offset", type=int, default=0)
    p_topic.add_argument("--limit", type=int, default=20)

    p_hashtag = sub.add_parser("hashtag-feed",
                               help="hot-ordered posts with one hashtag")
    p_hashtag.add_argument("hashtag_id")
    p_hashtag.add_argument("--name", required=True, help="hashtag name")
    p_hashtag.add_argument("--offset", type=int, default=0)
    p_hashtag.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)

    if args.command == "signer":
        if args.account or args.config or args.env:
            print("signer commands do not select or modify accounts", file=sys.stderr)
            return 2
        if args.signer_action == "install" and not args.confirm:
            print("refusing signer installation without --confirm", file=sys.stderr)
            return 2
        if args.signer_action == "prepare-apk" and not args.confirm:
            print("refusing APK preparation without --confirm", file=sys.stderr)
            return 2
        if args.signer_action == "bundle-install" and not args.confirm:
            print("refusing bundle installation without --confirm", file=sys.stderr)
            return 2
        from .signer import install_signer, inspect_signer
        try:
            if args.signer_action == "install":
                reference = install_signer(args.source, sha256=args.sha256)
                _print({"reference": reference, "installed": True, "executed": False})
            elif args.signer_action == "prepare-apk":
                from .signer_resources import prepare_resources
                _print(prepare_resources(args.apk, args.out))
            elif args.signer_action == "inspect-resources":
                from .signer_resources import inspect_resources
                _print(inspect_resources(args.directory))
            elif args.signer_action == "inspect-apk":
                from .signer_resources import inspect_apk
                report = inspect_apk(args.apk)
                _print(report)
                return 0 if report["supported"] else 1
            elif args.signer_action == "bundle-install":
                from .signer_bundle import install_bundle
                reference = install_bundle(args.resources, args.loader,
                                           loader_sha256=args.loader_sha256)
                _print({"reference": reference, "installed": True, "executed": False})
            elif args.signer_action == "bundle-inspect":
                from .signer_bundle import resolve_bundle
                _print(resolve_bundle(args.reference))
            elif args.signer_action == "selftest":
                from .signer import Signer
                options = {
                    "identity": args.identity,
                    "imei": args.imei,
                    "device_info": args.device_info,
                    "os_version": args.os_version,
                    "app_version": args.app_version,
                }
                if args.reference.startswith("bundle:"):
                    signer = Signer(bundle=args.reference, **options)
                else:
                    signer = Signer(jar=args.reference, **options)
                signature = signer.sign(args.path, args.timestamp)
                _print({"reference": args.reference, "path": args.path,
                        "signer_executed": True, "online_request_sent": False,
                        "signature": signature})
            else:
                _print(inspect_signer(args.reference))
            return 0
        except XhhError as exc:
            print(f"signer error: {exc}", file=sys.stderr)
            return 1

    if args.command == "doctor" and args.offline:
        return _offline_doctor(args)

    if args.command == "account":
        return _manage_account(args)

    if args.command == "catalog":
        from .catalog import display, select
        try:
            data = select(search=args.search, route=args.route, group=args.group)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print(data) if args.json else print(display(data))
        return 0

    writes = {"upload", "publish", "delete", "comment", "reply", "delete-comment",
              "favourite", "unfavourite", "follow-topic", "unfollow-topic", "canary"}
    if args.command in writes and not (getattr(args, "confirm", False) or
                                      (args.command == "delete" and args.yes)):
        print("refusing live write without --confirm", file=sys.stderr)
        return 2

    if args.command == "init":
        if DEFAULT_CONFIG.exists():
            print(f"config already exists: {DEFAULT_CONFIG}")
            return 1
        template = {
            "pkey": "<your session cookie pkey>",
            "heybox_id": "<your numeric heybox id>",
            "imei": "25102RKBEC",
            "device_info": "25102RKBEC",
        }
        DEFAULT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_CONFIG.write_text(json.dumps(template, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(f"wrote template: {DEFAULT_CONFIG}")
        print("legacy mode: fill it in, then run xhh-sdk --config <path> doctor; prefer account login")
        return 0

    try:
        config = _load(args)
    except XhhError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        print("use `xhh-sdk account add ALIAS`, then `account login ALIAS --confirm`", file=sys.stderr)
        return 2

    try:
        client = XhhClient(config)
        def emit(data):
            _print(data, secret=config.pkey)
        if args.command == "group":
            cookies = None
            if args.account:
                account = _account_store(args).get(args.account)
                if account.identity != config.heybox_id or account.pkey != config.pkey:
                    raise XhhConfigError("account changed while preparing group request")
                if account.risk_token:
                    cookies = {"x_xhh_tokenid": account.risk_token}
            if args.group_action == "list":
                result = client.group_list(cookies=cookies)
            elif args.group_action == "members":
                result = client.group_members(args.group_id, offset=args.offset,
                                               limit=args.limit, cookies=cookies)
            else:
                result = client.group_messages(args.group_id, last_msg_id=args.last_msg_id,
                                                limit=args.limit, cookies=cookies)
            emit(result)
            return 0
        if args.command == "doctor":
            signer_jar = client.transport.signer.jar
            report = {"config": "ok", "identity_masked": _mask_identity(config.heybox_id),
                      "signer_jar": str(signer_jar), "jar_present": signer_jar.is_file(),
                      "sha256_pinned": client.transport.signer.sha256 is not None,
                      "java": config.java, "api_base": config.api_base}
            try:
                client.transport.signer.sign("/bbs/app/link/tree")
                report["signer"] = "ok"
            except XhhError as exc:
                report["signer"] = f"failed: {exc}"
            emit(report)
            return 0 if report.get("signer") == "ok" and report["jar_present"] else 1
        if args.command == "verify":
            emit(client.verify())
            return 0
        if args.command == "call":
            query = {}
            for pair in args.query:
                if "=" not in pair:
                    print(f"bad --query (want K=V): {pair}", file=sys.stderr)
                    return 2
                key, value = pair.split("=", 1)
                query[key] = value
            emit(client.call(args.route, query=query or None))
            return 0
        if args.command == "upload":
            emit([client.upload(f) for f in args.files])
            return 0
        if args.command == "drafts":
            emit(client.drafts())
            return 0
        if args.command == "posts":
            emit(client.my_posts())
            return 0
        if args.command == "read":
            emit(client.read_post(args.link_id))
            return 0
        if args.command == "comments":
            emit(client.comment_thread(args.link_id, page=args.page,
                                         limit=args.limit, sort=args.sort))
            return 0
        if args.command == "sub-comments":
            emit(client.sub_comments(args.root_comment_id,
                                       lastval=args.lastval))
            return 0
        if args.command == "my-comments":
            emit(client.my_comments(offset=args.offset, limit=args.limit))
            return 0
        if args.command == "delete":
            if not (args.yes or args.confirm):
                print("refusing without --yes", file=sys.stderr)
                return 2
            emit(client.delete(args.link_id))
            return 0
        if args.command == "publish":
            raw = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
            spec = json.loads(raw)
            post = Post(
                title=spec.get("title", ""), content=spec.get("content", ""),
                content_format=spec.get("content_format", "html"),
                hashtags=spec.get("hashtags", []),
                topic_ids=[str(t) for t in spec.get("topic_ids", [])],
                images=spec.get("images", []),
                cover_url=spec.get("cover_url"),
                post_type=str(spec.get("post_type", "1")),
                visibility=spec.get("visibility"),
                original=bool(spec.get("original", True)),
                draft=not args.publish,
            )
            emit(client.publish(post, confirm=args.publish))
            return 0
        if args.command == "comment":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            emit(client.comment(args.link_id, args.text, is_cy=args.cy,
                                  confirm=True))
            return 0
        if args.command == "reply":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            emit(client.reply(args.link_id, args.root_id, args.reply_id,
                                args.text, confirm=True))
            return 0
        if args.command == "delete-comment":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            emit(client.delete_comment(args.link_id, args.comment_id,
                                         confirm=True))
            return 0
        if args.command == "favourite":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            emit(client.favourite(args.link_id, folder_id=args.folder_id,
                                    confirm=True))
            return 0
        if args.command == "unfavourite":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            emit(client.unfavourite(args.link_id, confirm=True))
            return 0
        if args.command == "follow-topic":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            emit(client.follow_topic(args.topic_id, confirm=True))
            return 0
        if args.command == "unfollow-topic":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            emit(client.unfollow_topic(args.topic_id, confirm=True))
            return 0
        if args.command == "canary":
            if not args.confirm:
                print("refusing without --confirm", file=sys.stderr)
                return 2
            marker = "【xhh-sdk canary】临时评论，自动删除"
            created = client.comment(args.link_id, marker, confirm=True)
            comment_id = str(created.get("comment_id") or "")
            if not comment_id:
                print("error: canary comment returned no id", file=sys.stderr)
                return 1
            try:
                def visible() -> bool:
                    return any(
                        str(node.get("commentid")) == comment_id
                        for floor in client.comment_thread(args.link_id,
                                                           sort="time_desc")
                        for node in [floor["root"], *floor["replies"]])

                at_once = visible()
                time.sleep(min(max(args.wait, 0), 120))
                after_wait = visible()
                emit({"link_id": args.link_id, "comment_id": comment_id,
                        "public_at_once": at_once,
                        "public_after_wait": after_wait,
                        "verdict": "PUBLIC" if after_wait else "NOT_PUBLIC"})
                return 0
            finally:
                client.delete_comment(args.link_id, comment_id, confirm=True)
        if args.command == "topic-feeds":
            data = client.transport.signed_request(
                "/bbs/app/topic/feeds",
                query={"topic_id": str(args.topic_id),
                       "offset": str(args.offset), "limit": str(args.limit),
                       "h_src": ""})
            emit(data.get("result") or {})
            return 0
        if args.command == "hashtag-feed":
            data = client.transport.signed_request(
                "/bbs/app/hashtag/link/list",
                query={"hashtag_id": str(args.hashtag_id), "hashtag_name": args.name,
                       "offset": str(args.offset), "limit": str(args.limit),
                       "h_src": ""})
            emit(data.get("result") or {})
            return 0
    except XhhError as exc:
        print(f"error: {_redact(str(exc), config.pkey)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

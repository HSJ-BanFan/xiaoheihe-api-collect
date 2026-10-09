"""Guarded publishing through the unchanged portable CLI; no MCP or secrets store."""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("publisher_cli", Path(__file__).with_name("xhh_cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)
Refused = cli.Refused
FIELDS = {"title", "content", "content_format", "hashtags", "topic_ids", "images", "post_type", "original",
          "post_plan", "extra_declaration"}
PLAN_FIELDS = {"schema_version", "account", "mode", "spec", "media", "cli_version", "wheel_sha256",
               "kit_version", "runtime_manifest_sha256", "approval_sha256"}
MAX_MEDIA_BYTES = 20 * 1024 * 1024


def validate_spec(spec: object) -> dict:
    if not isinstance(spec, dict) or set(spec) - FIELDS:
        raise Refused("unsupported_spec_fields")
    defaults = {"title": "", "content": "", "content_format": "text", "hashtags": [],
                "topic_ids": [], "images": [], "post_type": "1", "original": True}
    result = {**defaults, **spec}
    for field in ("title", "content", "content_format", "post_type"):
        if type(result[field]) is not str:
            raise Refused("invalid_spec_type")
    if not result["content"].strip() or "\x00" in result["content"] or "\x00" in result["title"]:
        raise Refused("invalid_content")
    if result["content_format"] not in {"text", "html"} or result["post_type"] not in {"1", "3"}:
        raise Refused("unsupported_content_format_or_post_type")
    if type(result["original"]) is not bool:
        raise Refused("invalid_original")
    post_plan = result.get("post_plan")
    if post_plan is not None and (
            type(post_plan) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", post_plan)):
        raise Refused("invalid_post_plan")
    declaration = result.get("extra_declaration")
    if declaration is not None and (type(declaration) is not int or declaration not in (1, 2, 3)):
        raise Refused("invalid_extra_declaration")
    for field in ("post_plan", "extra_declaration"):
        if result.get(field) is None:
            result.pop(field, None)
    for field in ("hashtags", "topic_ids", "images"):
        if not isinstance(result[field], list) or any(type(v) is not str or not v.strip() or "\x00" in v for v in result[field]):
            raise Refused("invalid_spec_list")
    if any(not re.fullmatch(r"[0-9]+", value) for value in result["topic_ids"]):
        raise Refused("invalid_topic_id")
    if result["content_format"] == "html" and re.search(
        r"<\s*(?:img|video|audio|source|iframe|object|embed|svg|script|style|link)\b|\b(?:src|srcset|background)\s*=|url\s*\(",
        result["content"], re.I,
    ):
        raise Refused("embedded_media_requires_original_cli")
    return result


def check_identity(account: str, mode: str) -> None:
    if type(account) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", account):
        raise Refused("explicit_account_required")
    if mode not in {"draft", "public"}:
        raise Refused("invalid_mode")


def local_bytes(path: Path) -> bytes:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise Refused("media_symlink")
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
            raise Refused("missing_empty_or_oversized_media")
        raw = path.read_bytes()
    except OSError as exc:
        raise Refused("media_unreadable") from exc
    if not 0 < len(raw) <= MAX_MEDIA_BYTES:
        raise Refused("missing_empty_or_oversized_media")
    return raw


def validate_image(raw: bytes, suffix: str) -> None:
    from xhh_sdk.client import image_dimensions
    valid_header = (
        suffix == ".png" and raw.startswith(b"\x89PNG\r\n\x1a\n")
        or suffix in {".jpg", ".jpeg"} and raw.startswith(b"\xff\xd8")
        or suffix == ".gif" and raw.startswith((b"GIF87a", b"GIF89a"))
    )
    dimensions = image_dimensions(raw) if valid_header else None
    if not dimensions or min(dimensions) < 1:
        raise Refused("unsupported_or_invalid_image")


def render(spec: dict, mode: str) -> dict:
    from xhh_sdk.payload import Post
    try:
        values = {**spec, "images": ["https://example.invalid/frozen/" + str(i) for i in range(len(spec["images"]))]}
        return Post(**values, draft=mode == "draft").build()
    except Exception as exc:
        raise Refused("post_validation_failed") from exc


def write_json(path: Path, value: dict, *, exclusive=False) -> None:
    with path.open("xb" if exclusive else "wb") as stream:
        stream.write(cli.canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def plan(spec_path: Path, account: str, mode: str, operation: Path) -> dict:
    check_identity(account, mode)
    spec_path, operation = Path(spec_path), Path(operation)
    spec = validate_spec(cli.read_json(spec_path))
    blobs = []
    media = []
    for index, ref in enumerate(spec["images"]):
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", ref) or ref.startswith(("\\\\", "//")):
            raise Refused("local_images_required")
        source = Path(ref)
        if not source.is_absolute():
            source = spec_path.parent / source
        raw = local_bytes(source)
        suffix = source.suffix.lower()
        name = f"media/{index:04d}{suffix}"
        blobs.append(raw)
        media.append({"path": name, "sha256": cli.digest(raw), "bytes": len(raw)})
    cli.activate_runtime()
    for descriptor, raw in zip(media, blobs):
        validate_image(raw, Path(descriptor["path"]).suffix)
    spec["images"] = [item["path"] for item in media]
    render(spec, mode)
    frozen = {
        "schema_version": 1, "account": account, "mode": mode, "spec": spec, "media": media,
        "cli_version": cli.CLI_VERSION, "wheel_sha256": cli.WHEEL_SHA256, "kit_version": cli.KIT_VERSION,
        "runtime_manifest_sha256": cli.digest((cli.KIT_ROOT / "kit-manifest.json").read_bytes()),
    }
    frozen["approval_sha256"] = cli.digest(cli.canonical(frozen))
    try:
        operation.mkdir(parents=False, exist_ok=False, mode=0o700)
    except OSError as exc:
        raise Refused("operation_must_be_new") from exc
    if media:
        (operation / "media").mkdir(mode=0o700)
    for descriptor, raw in zip(media, blobs):
        (operation / descriptor["path"]).write_bytes(raw)
    write_json(operation / "plan.json", frozen, exclusive=True)
    return frozen


def snapshot(operation: Path) -> tuple[dict, list[bytes]]:
    operation = Path(operation)
    if operation.is_symlink() or any(parent.is_symlink() for parent in operation.parents):
        raise Refused("operation_symlink")
    cli.activate_runtime()
    frozen = cli.read_json(operation / "plan.json")
    if not isinstance(frozen, dict) or set(frozen) != PLAN_FIELDS or type(frozen["schema_version"]) is not int or frozen["schema_version"] != 1:
        raise Refused("invalid_plan")
    approval = frozen["approval_sha256"]
    if approval != cli.digest(cli.canonical({key: value for key, value in frozen.items() if key != "approval_sha256"})):
        raise Refused("plan_hash_mismatch")
    check_identity(frozen["account"], frozen["mode"])
    if (frozen["cli_version"] != cli.CLI_VERSION or frozen["kit_version"] != cli.KIT_VERSION
            or frozen["wheel_sha256"] != cli.WHEEL_SHA256
            or frozen["runtime_manifest_sha256"] != cli.digest((cli.KIT_ROOT / "kit-manifest.json").read_bytes())):
        raise Refused("plan_runtime_mismatch")
    spec = validate_spec(frozen["spec"])
    if spec != frozen["spec"] or type(frozen["media"]) is not list or len(frozen["media"]) != len(spec["images"]):
        raise Refused("invalid_plan_media")
    blobs = []
    for index, descriptor in enumerate(frozen["media"]):
        if not isinstance(descriptor, dict) or set(descriptor) != {"path", "sha256", "bytes"}:
            raise Refused("invalid_plan_media")
        ref = descriptor["path"]
        if type(ref) is not str or not re.fullmatch(r"media/" + f"{index:04d}" + r"\.(png|jpg|jpeg|gif)", ref) or spec["images"][index] != ref:
            raise Refused("invalid_plan_media")
        raw = local_bytes(operation / ref)
        if type(descriptor["bytes"]) is not int or len(raw) != descriptor["bytes"] or cli.digest(raw) != descriptor["sha256"]:
            raise Refused("media_hash_mismatch")
        validate_image(raw, Path(ref).suffix)
        blobs.append(raw)
    render(spec, frozen["mode"])
    return frozen, blobs


def show(operation: Path) -> dict:
    return snapshot(operation)[0]


def run_cli(argv: list[str], *, input_text=None) -> tuple[int, object]:
    child = subprocess.run(
        [sys.executable, "-I", str(cli.KIT_ROOT / "scripts" / "xhh_cli.py"), *argv],
        input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    try:
        data = json.loads(child.stdout)
    except ValueError:
        data = None
    return child.returncode, data


def receipt_for(frozen: dict, state: str, reason: str, link_id=None, readback=None) -> dict:
    result = {"state": state, "approval_sha256": frozen["approval_sha256"], "reason": reason}
    if link_id is not None:
        result.update(link_id=link_id, url="https://www.xiaoheihe.cn/app/bbs/link/" + link_id)
    if readback is not None:
        result["readback"] = readback
    return result


def valid_link(value: object) -> str | None:
    if type(value) in {int, str} and re.fullmatch(r"[0-9]{1,30}", str(value)):
        return str(value)
    return None


def upload_inline_images(outgoing: dict, account: str, mode: str) -> dict:
    if not outgoing["images"]:
        return outgoing
    code, uploads = run_cli(["--account", account, "upload", *outgoing["images"], "--confirm"])
    if code != 0 or not isinstance(uploads, list) or len(uploads) != len(outgoing["images"]):
        raise Refused("invalid_upload_result")
    content = json.loads(render(outgoing, mode)["text"])[0]["text"]
    for image in uploads:
        if not isinstance(image, dict):
            raise Refused("invalid_upload_result")
        url, width, height = image.get("url"), image.get("width"), image.get("height")
        if type(url) is not str or re.search(r"[\s\\\x00-\x1f\x7f]", url):
            raise Refused("invalid_upload_url")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not re.fullmatch(r"imgheybox[0-9]*\.max-c\.com", parsed.netloc)
                or not parsed.path.startswith("/") or parsed.fragment):
            raise Refused("invalid_upload_url")
        if type(width) is not int or type(height) is not int or min(width, height) < 1:
            raise Refused("invalid_upload_dimensions")
        content += f'<p><img src="{html.escape(url, quote=True)}" data-width="{width}" data-height="{height}" /></p>'
    return {**outgoing, "content": content, "content_format": "html", "images": []}


def submit(operation: Path, approval: str, confirm: bool) -> dict:
    if not confirm:
        raise Refused("confirmation_required")
    operation = Path(operation)
    frozen, _ = snapshot(operation)
    if approval != frozen["approval_sha256"]:
        raise Refused("approval_mismatch")
    if (operation / "attempt.json").exists():
        raise Refused("already_attempted_reconcile_only")
    try:
        code, account = run_cli(["account", "status", frozen["account"], "--online"])
    except Exception as exc:
        raise Refused("account_preflight_failed") from exc
    if (code != 0 or not isinstance(account, dict) or account.get("state") != "verified"
            or account.get("api_identity_verified") is not True or account.get("session_valid") is not True):
        raise Refused("account_not_verified")
    if (account.get("protocol_mode") == "web" and frozen["mode"] == "public"
            and not frozen["spec"]["topic_ids"]):
        raise Refused("web_public_community_required")
    fresh, blobs = snapshot(operation)
    if fresh["approval_sha256"] != approval:
        raise Refused("approval_mismatch")
    with tempfile.TemporaryDirectory(prefix="xhh-publish-", ignore_cleanup_errors=True) as temporary:
        outgoing = {**fresh["spec"], "images": []}
        for descriptor, raw in zip(fresh["media"], blobs):
            path = Path(temporary) / Path(descriptor["path"]).name
            path.write_bytes(raw)
            outgoing["images"].append(str(path))
        try:
            write_json(operation / "attempt.json", {"schema_version": 1, "approval_sha256": approval}, exclusive=True)
        except FileExistsError as exc:
            raise Refused("already_attempted_reconcile_only") from exc
        result = receipt_for(fresh, "outcome_unknown", "publish_attempt_reserved_inspect_own_posts_or_drafts")
        write_json(operation / "receipt.json", result)
        argv = ["--account", fresh["account"], "publish", "-", "--confirm"]
        if fresh["mode"] == "public":
            argv.append("--publish")
        try:
            outgoing = upload_inline_images(outgoing, fresh["account"], fresh["mode"])
            code, data = run_cli(argv, input_text=json.dumps(outgoing, ensure_ascii=False))
            link_id = valid_link(data.get("link_id")) if isinstance(data, dict) else None
            if code == 0 and link_id is not None:
                result = receipt_for(fresh, "acknowledged", "creation_ack_only_readback_required", link_id)
            else:
                result = receipt_for(fresh, "outcome_unknown", "publish_result_unknown_inspect_own_posts_or_drafts")
        except Exception:
            result = receipt_for(fresh, "outcome_unknown", "publish_result_unknown_inspect_own_posts_or_drafts")
        try:
            write_json(operation / "receipt.json", result)
        except OSError:
            return receipt_for(fresh, "outcome_unknown", "receipt_storage_failed_reconcile_before_any_new_attempt")
        return result


def reconcile(operation: Path) -> dict:
    operation = Path(operation)
    frozen = show(operation)
    if not (operation / "attempt.json").is_file():
        raise Refused("no_publish_attempt")
    attempt = cli.read_json(operation / "attempt.json")
    if not isinstance(attempt, dict) or attempt.get("approval_sha256") != frozen["approval_sha256"]:
        raise Refused("attempt_mismatch")
    try:
        saved = cli.read_json(operation / "receipt.json")
    except Refused:
        saved = {}
    if not isinstance(saved, dict) or saved.get("approval_sha256") != frozen["approval_sha256"]:
        saved = {}
    link_id = valid_link(saved.get("link_id"))
    if link_id is None:
        return receipt_for(frozen, "outcome_unknown", "no_link_id_inspect_own_posts_or_drafts_no_retry")
    readback = {"own_listing_match": False, "title_match": False, "description_match": False,
                "full_content_verified": False, "public_visibility_verified": False}
    try:
        code, entries = run_cli(["--account", frozen["account"], "drafts" if frozen["mode"] == "draft" else "posts"])
        if code == 0 and isinstance(entries, list):
            matching = [item for item in entries if isinstance(item, dict) and valid_link(item.get("linkid")) == link_id]
            if len(matching) == 1:
                item = matching[0]
                expected = render(frozen["spec"], frozen["mode"])
                readback["own_listing_match"] = True
                readback["title_match"] = item.get("title") == expected["title"]
                readback["description_match"] = item.get("description") == expected["desc"]
                readback["draft_flag_match"] = type(item.get("draft")) is int and item["draft"] == (1 if frozen["mode"] == "draft" else 0)
    except Exception:
        pass
    result = receipt_for(frozen, "acknowledged", "readback_partial_full_content_and_public_visibility_unverified", link_id, readback)
    write_json(operation / "receipt.json", result)
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused("invalid_arguments")


def main(argv=None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = Parser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    prepare = actions.add_parser("plan")
    prepare.add_argument("spec", type=Path)
    prepare.add_argument("--account", required=True)
    prepare.add_argument("--mode", choices=("draft", "public"), required=True)
    prepare.add_argument("--out", type=Path, required=True)
    for action in ("show", "submit", "reconcile"):
        command = actions.add_parser(action)
        command.add_argument("operation", type=Path)
        if action == "submit":
            command.add_argument("--approval", required=True)
            command.add_argument("--confirm", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.command == "plan":
            frozen = plan(args.spec, args.account, args.mode, args.out)
            result = receipt_for(frozen, "prepared", "local_snapshot_only")
        elif args.command == "show":
            result = show(args.operation)
        elif args.command == "submit":
            result = submit(args.operation, args.approval, args.confirm)
        else:
            result = reconcile(args.operation)
    except Refused as exc:
        result = {"state": "refused", "reason": str(exc)}
    except Exception:
        result = {"state": "refused", "reason": "local_operation_failed"}
    print(json.dumps(result, ensure_ascii=False))
    return {"refused": 2, "outcome_unknown": 3}.get(result.get("state"), 0)


if __name__ == "__main__":
    raise SystemExit(main())

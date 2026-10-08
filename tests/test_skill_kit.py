import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_skill_kit.py"
WHEEL = ROOT / "cli" / "dist" / "standalone-7-clean" / "xhh_sdk-0.5.0rc4+standalone.7-py3-none-any.whl"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
UPLOADED = {"url": "https://imgheybox.max-c.com/synthetic.png", "width": 1, "height": 1}


def run(*args, cwd=None):
    return subprocess.run([sys.executable, "-I", *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")


def test_build_entrypoint_exists():
    assert BUILDER.is_file(), "portable skill kit builder is not implemented"


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    if not BUILDER.exists():
        pytest.skip("builder not implemented")
    out = tmp_path_factory.mktemp("kit-build") / "output"
    result = run(BUILDER, "--wheel", WHEEL, "--out", out)
    assert result.returncode == 0, result.stdout + result.stderr
    return out / "xiaoheihe-publisher"


@pytest.fixture
def facade(kit):
    old_modules = {name: module for name, module in sys.modules.items()
                   if name == "xhh_sdk" or name.startswith("xhh_sdk.")}
    old_path = sys.path[:]
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("publisher_under_test", kit / "scripts" / "xhh_publish.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in tuple(sys.modules):
        if name == "xhh_sdk" or name.startswith("xhh_sdk."):
            del sys.modules[name]
    sys.modules.update(old_modules)
    sys.path[:] = old_path
    sys.dont_write_bytecode = old_bytecode


def source(tmp_path, **updates):
    (tmp_path / "pixel.png").write_bytes(PNG)
    spec = {"title": "Fixture", "content": "Only synthetic text", "content_format": "text",
            "hashtags": ["fixture"], "images": ["pixel.png"]}
    spec.update(updates)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def prepared(facade, tmp_path, mode="draft"):
    operation = tmp_path / "operation"
    plan = facade.plan(source(tmp_path), "synthetic-test", mode, operation)
    return operation, plan


def test_deterministic_and_exact_wheel_members(kit, tmp_path):
    out = tmp_path / "second"
    result = run(BUILDER, "--wheel", WHEEL, "--out", out)
    assert result.returncode == 0, result.stderr
    archive = "xhh-publisher-kit-0.1.0rc1.zip"
    assert (out / archive).read_bytes() == (kit.parent / archive).read_bytes()
    manifest = json.loads((kit / "kit-manifest.json").read_text())
    with zipfile.ZipFile(WHEEL) as wheel:
        for member in wheel.namelist():
            actual = (kit / "runtime" / member).read_bytes()
            assert actual == wheel.read(member)
            assert manifest["files"]["runtime/" + member] == hashlib.sha256(actual).hexdigest()
    assert not list(kit.rglob("*.whl"))


def test_wrong_wheel_rejected_without_output(tmp_path):
    wheel = tmp_path / "wrong.whl"
    wheel.write_bytes(b"not the approved wheel")
    out = tmp_path / "output"
    result = run(BUILDER, "--wheel", wheel, "--out", out)
    assert result.returncode == 2
    assert not out.exists()


def test_moved_isolated_kit_uses_pinned_cli_and_renderer(kit, tmp_path):
    moved = tmp_path / "moved"
    shutil.copytree(kit, moved)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    result = run(moved / "scripts" / "xhh_cli.py", "--version", cwd=unrelated)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "xhh-sdk 0.5.0rc4+standalone.7"
    result = run(moved / "scripts" / "xhh_publish.py", "plan", source(tmp_path),
                 "--account", "synthetic-test", "--mode", "draft", "--out", tmp_path / "op", cwd=unrelated)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["state"] == "prepared"
    result = run(moved / "scripts" / "xhh_publish.py", "show", tmp_path / "op", cwd=unrelated)
    assert result.returncode == 0
    assert json.loads(result.stdout)["spec"]["content"] == "Only synthetic text"


def test_plan_and_show_keep_unicode_in_real_isolated_process(kit, tmp_path):
    text = "\u6d4b\u8bd5\u53d1\u5e16\U0001f680"
    result = run(kit / "scripts" / "xhh_publish.py", "plan",
                 source(tmp_path, title=text, content=text),
                 "--account", "synthetic-test", "--mode", "draft", "--out", tmp_path / "op")
    assert result.returncode == 0, result.stdout + result.stderr
    result = run(kit / "scripts" / "xhh_publish.py", "show", tmp_path / "op")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["spec"]["content"] == text


def test_original_cli_reads_unicode_stdin_before_any_upload(kit, tmp_path):
    config = tmp_path / "synthetic.json"
    config.write_text(json.dumps({
        "pkey": "<synthetic-test-session>", "heybox_id": "12345",
        "api_base": "https://example.invalid",
    }), encoding="utf-8")
    missing = tmp_path / "\u6d4b\u8bd5.png"
    payload = {"content": "\u6d4b\u8bd5\U0001f680", "content_format": "text", "images": [str(missing)]}
    result = subprocess.run(
        [sys.executable, "-I", str(kit / "scripts" / "xhh_cli.py"),
         "--config", str(config), "publish", "-", "--confirm"],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True,
        text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 1
    assert "media file missing or empty" in result.stderr
    assert str(missing) in result.stderr


@pytest.mark.parametrize("change", ["runtime", "extra", "source"])
def test_tampering_refused_before_import(kit, tmp_path, change):
    moved = tmp_path / "moved"
    shutil.copytree(kit, moved)
    path = {"runtime": "runtime/xhh_sdk/payload.py", "source": "references/setup.md",
            "extra": "runtime/xhh_sdk/unknown.py"}[change]
    with (moved / path).open("ab") as stream:
        stream.write(b"\n# changed\n")
    result = run(moved / "scripts" / "xhh_cli.py", "--version")
    assert result.returncode == 2
    assert "xhh-sdk 0." not in result.stdout


@pytest.mark.parametrize("updates", [
    {"content": ""}, {"images": ["missing.png"]}, {"images": ["https://example.invalid/p.png"]},
    {"mode": "public"}, {"draft": False}, {"original": "false"}, {"hashtags": "tag"},
    {"topic_ids": [True]}, {"post_type": 1}, {"content_format": "markdown"},
    {"content": '<img src="https://example.invalid/p.png">', "content_format": "html"},
])
def test_invalid_spec_never_dispatches_or_creates_operation(facade, tmp_path, monkeypatch, updates):
    monkeypatch.setattr(facade, "run_cli", lambda *a, **k: pytest.fail("unexpected CLI invocation"))
    with pytest.raises(facade.Refused):
        facade.plan(source(tmp_path, **updates), "synthetic-test", "draft", tmp_path / "op")
    assert not (tmp_path / "op").exists()


def test_plan_freezes_bytes_and_approval_binds_media(facade, tmp_path):
    op, plan = prepared(facade, tmp_path)
    (tmp_path / "pixel.png").write_bytes(b"source later changed")
    assert facade.show(op) == plan
    frozen = op / plan["media"][0]["path"]
    assert frozen.read_bytes() == PNG
    frozen.write_bytes(b"snapshot changed")
    with pytest.raises(facade.Refused):
        facade.show(op)


@pytest.mark.parametrize("confirm,approval", [(False, "valid"), (True, "stale")])
def test_missing_approval_never_reads_account(facade, tmp_path, monkeypatch, confirm, approval):
    op, plan = prepared(facade, tmp_path)
    monkeypatch.setattr(facade, "run_cli", lambda *a, **k: pytest.fail("unexpected account access"))
    with pytest.raises(facade.Refused):
        facade.submit(op, plan["approval_sha256"] if approval == "valid" else "0" * 64, confirm)
    assert not (op / "attempt.json").exists()


@pytest.mark.parametrize("mode", ["draft", "public"])
def test_submit_dispatches_real_cli_shape_once_and_sanitizes(facade, tmp_path, monkeypatch, mode):
    op, plan = prepared(facade, tmp_path, mode)
    calls = []

    def transport(argv, *, input_text=None):
        calls.append(argv)
        if "status" in argv:
            return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}
        assert (op / "attempt.json").is_file()
        if "upload" in argv:
            assert argv[:3] == ["--account", "synthetic-test", "upload"]
            assert argv[-1] == "--confirm"
            assert Path(argv[3]).read_bytes() == PNG
            return 0, [UPLOADED]
        assert argv[:4] == ["--account", "synthetic-test", "publish", "-"]
        assert "--confirm" in argv
        assert ("--publish" in argv) == (mode == "public")
        outgoing = json.loads(input_text)
        assert outgoing["images"] == []
        assert outgoing["content_format"] == "html"
        assert outgoing["content"] == ('<p>Only synthetic text</p><p><img src="https://imgheybox.max-c.com/synthetic.png" '
                                       'data-width="1" data-height="1" /></p>')
        return 0, {"link_id": "123", "url": "https://example.invalid/private-token", "draft": mode == "draft",
                   "payload": {"secret": "MUST-NOT-LEAK"}}

    monkeypatch.setattr(facade, "run_cli", transport)
    receipt = facade.submit(op, plan["approval_sha256"], True)
    assert receipt["state"] == "acknowledged"
    assert receipt["link_id"] == "123"
    assert "MUST-NOT-LEAK" not in json.dumps(receipt)
    assert "example.invalid" not in json.dumps(receipt)
    with pytest.raises(facade.Refused):
        facade.submit(op, plan["approval_sha256"], True)
    assert len(calls) == 3


def test_online_identity_must_be_verified(facade, tmp_path, monkeypatch):
    op, plan = prepared(facade, tmp_path)
    monkeypatch.setattr(facade, "run_cli", lambda *a, **k: (0, {"state": "identity_unverified"}))
    with pytest.raises(facade.Refused):
        facade.submit(op, plan["approval_sha256"], True)
    assert not (op / "attempt.json").exists()


@pytest.mark.parametrize("failed_command", ["upload", "publish"])
def test_post_start_failure_is_unknown_and_never_retryable(facade, tmp_path, monkeypatch, failed_command):
    op, plan = prepared(facade, tmp_path)

    def transport(argv, **kwargs):
        if "status" in argv:
            return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}
        if "upload" in argv and failed_command == "publish":
            return 0, [UPLOADED]
        raise TimeoutError("private stderr MUST-NOT-LEAK")

    monkeypatch.setattr(facade, "run_cli", transport)
    receipt = facade.submit(op, plan["approval_sha256"], True)
    assert receipt["state"] == "outcome_unknown"
    assert "MUST-NOT-LEAK" not in json.dumps(receipt)
    monkeypatch.setattr(facade, "run_cli", lambda *a, **k: pytest.fail("no link must not dispatch"))
    assert facade.reconcile(op)["state"] == "outcome_unknown"
    with pytest.raises(facade.Refused):
        facade.submit(op, plan["approval_sha256"], True)


def test_reconcile_does_not_upgrade_creation_ack_to_public(facade, tmp_path, monkeypatch):
    op, plan = prepared(facade, tmp_path, "public")
    responses = iter([(0, {"state": "verified", "api_identity_verified": True, "session_valid": True}),
                      (0, [UPLOADED]),
                      (0, {"link_id": "123", "draft": False})])
    monkeypatch.setattr(facade, "run_cli", lambda *a, **k: next(responses))
    facade.submit(op, plan["approval_sha256"], True)
    calls = []

    def read_only(argv, **kwargs):
        calls.append(argv)
        assert "publish" not in argv
        return 0, {"result": {"link": {"linkid": "123", "title": "Fixture"}}} if "read" in argv else []

    monkeypatch.setattr(facade, "run_cli", read_only)
    receipt = facade.reconcile(op)
    assert receipt["state"] == "acknowledged"
    assert receipt["readback"]["public_visibility_verified"] is False
    assert calls


def test_plan_change_during_online_preflight_prevents_publish(facade, tmp_path, monkeypatch):
    op, plan = prepared(facade, tmp_path)

    def transport(argv, **kwargs):
        assert "status" in argv
        (op / plan["media"][0]["path"]).write_bytes(b"changed during status")
        return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}

    monkeypatch.setattr(facade, "run_cli", transport)
    with pytest.raises(facade.Refused):
        facade.submit(op, plan["approval_sha256"], True)
    assert not (op / "attempt.json").exists()


def test_two_submitters_cannot_publish_twice(facade, tmp_path, monkeypatch):
    op, plan = prepared(facade, tmp_path)
    barrier = Barrier(2)
    writes = []

    def transport(argv, **kwargs):
        if "status" in argv:
            barrier.wait(timeout=10)
            return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}
        if "upload" in argv:
            return 0, [UPLOADED]
        writes.append(argv)
        return 0, {"link_id": "123", "draft": True}

    def submit():
        try:
            return facade.submit(op, plan["approval_sha256"], True)["state"]
        except facade.Refused:
            return "refused"

    monkeypatch.setattr(facade, "run_cli", transport)
    with ThreadPoolExecutor(max_workers=2) as executor:
        states = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(states) == ["acknowledged", "refused"]
    assert len(writes) == 1


def test_receipt_storage_failure_after_dispatch_stays_unknown(facade, tmp_path, monkeypatch):
    op, plan = prepared(facade, tmp_path)
    writes = []
    original_write = facade.write_json

    def storage(path, value, **kwargs):
        if writes and Path(path).name == "receipt.json":
            raise OSError("simulated full disk")
        return original_write(path, value, **kwargs)

    def transport(argv, **kwargs):
        if "status" in argv:
            return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}
        if "upload" in argv:
            return 0, [UPLOADED]
        writes.append(argv)
        return 0, {"link_id": "123", "draft": True}

    monkeypatch.setattr(facade, "write_json", storage)
    monkeypatch.setattr(facade, "run_cli", transport)
    assert facade.submit(op, plan["approval_sha256"], True)["state"] == "outcome_unknown"
    assert (op / "attempt.json").is_file()


def test_malformed_media_checked_before_original_renderer(facade, tmp_path, monkeypatch):
    path = source(tmp_path)
    (tmp_path / "pixel.png").write_bytes(b"not an image")
    monkeypatch.setattr(facade, "render", lambda *a, **k: pytest.fail("renderer called for invalid media"))
    with pytest.raises(facade.Refused):
        facade.plan(path, "synthetic-test", "draft", tmp_path / "operation")


def test_original_cli_gets_real_publish_arguments_and_renders(facade, tmp_path, monkeypatch, capsys):
    facade.cli.activate_runtime()
    from xhh_sdk import cli as original
    from xhh_sdk.client import XhhClient
    from xhh_sdk.config import XhhConfig

    config = XhhConfig(pkey="<placeholder-session>", heybox_id="10000")
    submitted = []

    class Transport:
        def signed_request(self, route, **kwargs):
            submitted.append((route, kwargs["payload"]))
            return {"result": {"link_id": "123"}}

    client = XhhClient(config, transport=Transport())
    monkeypatch.setattr(original, "_load", lambda args: config)
    monkeypatch.setattr(original, "XhhClient", lambda _: client)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({"content": "<literal>", "content_format": "text"})))
    assert original.main(["--account", "synthetic-test", "publish", "-", "--confirm", "--publish"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["link_id"] == "123"
    assert submitted[0][0] == "/bbs/app/api/link/post"
    assert submitted[0][1]["draft"] == "0"
    assert json.loads(submitted[0][1]["text"])[0]["text"] == "<p>&lt;literal&gt;</p>"


def test_reconcile_matches_real_draft_fields_conservatively(facade, tmp_path, monkeypatch):
    op, plan = prepared(facade, tmp_path)
    responses = iter([(0, {"state": "verified", "api_identity_verified": True, "session_valid": True}),
                      (0, [UPLOADED]),
                      (0, {"link_id": "123", "draft": True}),
                      (0, [{"linkid": 123, "draft": 1, "title": "Fixture", "description": "Only synthetic text", "imgs": []}])])
    monkeypatch.setattr(facade, "run_cli", lambda *a, **k: next(responses))
    facade.submit(op, plan["approval_sha256"], True)
    receipt = facade.reconcile(op)
    assert receipt["state"] == "acknowledged"
    assert receipt["readback"] == {"own_listing_match": True, "title_match": True,
                                   "description_match": True, "draft_flag_match": True,
                                   "full_content_verified": False, "public_visibility_verified": False}


def test_unknown_source_member_fails_builder(kit, tmp_path):
    checkout = tmp_path / "checkout"
    shutil.copytree(ROOT / "skill-kit", checkout / "skill-kit")
    (checkout / "scripts").mkdir()
    shutil.copy2(BUILDER, checkout / "scripts" / BUILDER.name)
    (checkout / "skill-kit" / "xiaoheihe-publisher" / "unreviewed.txt").write_text("not shipped")
    out = tmp_path / "output"
    result = run(checkout / "scripts" / BUILDER.name, "--wheel", WHEEL, "--out", out)
    assert result.returncode == 2
    assert not out.exists()


@pytest.mark.parametrize("uploads", [
    None, {}, [], [UPLOADED, UPLOADED], [None],
    [{**UPLOADED, "url": "http://imgheybox.max-c.com/a.png"}],
    [{**UPLOADED, "url": "https://imgheybox.max-c.com.evil.invalid/a.png"}],
    [{**UPLOADED, "url": "https://user:secret@imgheybox.max-c.com/a.png"}],
    [{**UPLOADED, "url": "https://imgheybox.max-c.com:443/a.png"}],
    [{**UPLOADED, "url": "https://imgheybox.max-c.com/a.png\n"}],
    [{**UPLOADED, "width": True}], [{**UPLOADED, "width": "1"}],
    [{**UPLOADED, "height": 0}], [{**UPLOADED, "height": -1}],
])
def test_invalid_upload_result_never_publishes_or_retries(facade, tmp_path, monkeypatch, uploads):
    op, plan = prepared(facade, tmp_path)
    calls = []

    def transport(argv, **kwargs):
        calls.append(argv)
        if "status" in argv:
            return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}
        assert "publish" not in argv
        assert (op / "attempt.json").is_file()
        return 0, uploads

    monkeypatch.setattr(facade, "run_cli", transport)
    result = facade.submit(op, plan["approval_sha256"], True)
    assert result["state"] == "outcome_unknown"
    assert len(calls) == 2
    assert calls[1][2] == "upload"
    assert "imgheybox" not in json.dumps(result)
    with pytest.raises(facade.Refused):
        facade.submit(op, plan["approval_sha256"], True)
    assert len(calls) == 2


def test_multiple_inline_images_escape_urls_and_preserve_original_renderer(facade, tmp_path, monkeypatch):
    op = tmp_path / "operation"
    plan = facade.plan(source(tmp_path, content='<literal> & "text"', images=["pixel.png", "pixel.png"]),
                       "synthetic-test", "draft", op)
    calls = []

    def transport(argv, *, input_text=None):
        calls.append(argv)
        if "status" in argv:
            return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}
        if "upload" in argv:
            assert len(argv[3:-1]) == 2
            assert all(Path(path).read_bytes() == PNG for path in argv[3:-1])
            return 0, [{**UPLOADED, "url": 'https://imgheybox.max-c.com/a.png?x=1&y="quoted"'}, UPLOADED]
        outgoing = json.loads(input_text)
        assert outgoing["content"].startswith("<p>&lt;literal&gt; &amp; &quot;text&quot;</p>")
        assert 'src="https://imgheybox.max-c.com/a.png?x=1&amp;y=&quot;quoted&quot;"' in outgoing["content"]
        assert outgoing["content"].count("<img ") == 2
        assert outgoing["images"] == []
        return 0, {"link_id": "123", "draft": True}

    monkeypatch.setattr(facade, "run_cli", transport)
    assert facade.submit(op, plan["approval_sha256"], True)["state"] == "acknowledged"
    assert len(calls) == 3


def test_text_only_submit_does_not_upload(facade, tmp_path, monkeypatch):
    op = tmp_path / "operation"
    plan = facade.plan(source(tmp_path, images=[]), "synthetic-test", "draft", op)

    def transport(argv, *, input_text=None):
        if "status" in argv:
            return 0, {"state": "verified", "api_identity_verified": True, "session_valid": True}
        assert "upload" not in argv
        assert json.loads(input_text)["content_format"] == "text"
        return 0, {"link_id": "123", "draft": True}

    monkeypatch.setattr(facade, "run_cli", transport)
    assert facade.submit(op, plan["approval_sha256"], True)["state"] == "acknowledged"

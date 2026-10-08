"""Unit tests for the live-evidence half of the release gate.

The fixtures here are synthetic records that exercise the validator only.
They are not live results and never feed a gate report.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BINDING = {"wheel_sha256": "a" * 64, "loader_sha256": "b" * 64, "apk_sha256": "c" * 64}


def evidence_module():
    path = SCRIPTS / "gate_evidence.py"
    assert path.is_file(), "gate_evidence.py is missing"
    spec = importlib.util.spec_from_file_location("gate_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def account_assertions():
    return [
        {"alias": "private-one", "identity_matches_own": True,
         "identity_matches_other": False, "drafts_read": "ok"},
        {"alias": "private-two", "identity_matches_own": True,
         "identity_matches_other": False, "drafts_read": "ok"},
    ]


def completed_record(module, tmp_path, *, generated_at=None, binding=None, **overrides):
    record = module.template(binding or BINDING)
    record["generated_at"] = generated_at or datetime.now(timezone.utc).isoformat()
    record["authorized_by"] = "synthetic-authorization-fixture"
    record["account"] = {"alias": "synthetic", "identity_masked": "***23",
                         "fresh_bootstrap": True}
    for entry in record["features"]:
        entry["status"] = "passed"
        entry["command"] = f"synthetic command for {entry['name']}"
        entry["readback"] = "synthetic readback"
        entry["evidence"] = "synthetic-evidence.json"
        if entry["name"] in {"upload", "creator", "interaction"}:
            entry["cleanup"] = "synthetic removal verified"
    aliases = account_assertions()
    linked = tmp_path / "multi-account.json"
    linked.write_text(json.dumps({"aliases": aliases}), encoding="utf-8")
    record["multi_account"] = {
        "readback": "two account identities and drafts verified",
        "aliases": aliases,
        "evidence": {"path": linked.name,
                     "sha256": hashlib.sha256(linked.read_bytes()).hexdigest()},
    }
    record.update(overrides)
    return record


def validate_record(module, record, tmp_path, **kwargs):
    return module.validate(record, BINDING, evidence_path=tmp_path / "live.json", **kwargs)


def test_template_alone_never_validates():
    module = evidence_module()
    problems = module.validate(module.template(BINDING), BINDING,
                               evidence_path=Path("live.json"))
    assert problems
    assert any("fresh-login" in problem or "generated_at" in problem for problem in problems)


def test_completed_record_validates(tmp_path):
    module = evidence_module()
    assert validate_record(module, completed_record(module, tmp_path), tmp_path) == []


def test_stale_and_future_records_are_rejected(tmp_path):
    module = evidence_module()
    now = datetime.now(timezone.utc)
    stale = completed_record(module, tmp_path, generated_at=(now - timedelta(days=30)).isoformat())
    assert any("stale" in problem for problem in validate_record(module, stale, tmp_path, now=now))
    future = completed_record(module, tmp_path, generated_at=(now + timedelta(days=3)).isoformat())
    assert any("future" in problem for problem in validate_record(module, future, tmp_path, now=now))


def test_artifact_binding_must_match(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path)
    record["artifact_binding"]["wheel_sha256"] = "d" * 64
    problems = validate_record(module, record, tmp_path)
    assert any("wheel_sha256" in problem for problem in problems)


def test_missing_or_unfinished_features_are_rejected(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path)
    record["features"] = [entry for entry in record["features"] if entry["name"] != "upload"]
    problems = validate_record(module, record, tmp_path)
    assert any("live_feature.upload.missing" in problem for problem in problems)
    unfinished = completed_record(module, tmp_path)
    unfinished["features"][0]["status"] = "not run"
    assert any("live_feature." in problem and ".status" in problem
               for problem in validate_record(module, unfinished, tmp_path))


def test_readback_and_cleanup_are_required(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path)
    for entry in record["features"]:
        if entry["name"] == "interaction":
            entry["cleanup"] = ""
    assert any(".cleanup:" in problem for problem in validate_record(module, record, tmp_path))
    record = completed_record(module, tmp_path)
    for entry in record["features"]:
        if entry["name"] == "app-read":
            entry["readback"] = ""
    assert any(".readback:" in problem for problem in validate_record(module, record, tmp_path))


def test_authorization_and_bootstrap_are_required(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path, authorized_by="")
    assert any("fresh_login.authorization" in problem
               for problem in validate_record(module, record, tmp_path))
    record = completed_record(module, tmp_path)
    record["account"]["fresh_bootstrap"] = False
    assert any("fresh_login.bootstrap" in problem
               for problem in validate_record(module, record, tmp_path))


def test_unverified_items_keep_the_gate_closed(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path, failed_or_unverified=["group writes"])
    assert any("online_acceptance.unverified" in problem
               for problem in validate_record(module, record, tmp_path))


def test_two_account_evidence_rejects_duplicates_and_cross_identity(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path)
    record["multi_account"]["aliases"][1]["alias"] = "private-one"
    linked = tmp_path / "multi-account.json"
    linked.write_text(json.dumps({"aliases": record["multi_account"]["aliases"]}),
                      encoding="utf-8")
    record["multi_account"]["evidence"]["sha256"] = hashlib.sha256(
        linked.read_bytes()).hexdigest()
    record["multi_account"]["aliases"][0]["identity_matches_other"] = True
    problems = validate_record(module, record, tmp_path)
    assert any("duplicate_alias" in problem for problem in problems)
    assert any("cross_identity" in problem for problem in problems)
    assert all("private-one" not in problem for problem in problems)


def test_two_account_link_requires_matching_digest_and_aliases(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path)
    linked = tmp_path / "multi-account.json"
    linked.write_text(json.dumps({"aliases": account_assertions()[:-1]}), encoding="utf-8")
    assert any("evidence_hash_mismatch" in problem
               for problem in validate_record(module, record, tmp_path))
    record["multi_account"]["evidence"]["sha256"] = hashlib.sha256(
        linked.read_bytes()).hexdigest()
    assert any("alias_mismatch" in problem
               for problem in validate_record(module, record, tmp_path))


def test_two_account_link_rejects_missing_files_and_path_escape(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path)
    record["multi_account"]["evidence"]["path"] = "missing.json"
    assert any("evidence_missing" in problem
               for problem in validate_record(module, record, tmp_path))
    record["multi_account"]["evidence"]["path"] = "../outside.json"
    assert any("evidence_path_escape" in problem
               for problem in validate_record(module, record, tmp_path))


def test_two_account_evidence_rejects_failed_draft_readback(tmp_path):
    module = evidence_module()
    record = completed_record(module, tmp_path)
    record["multi_account"]["aliases"][0]["drafts_read"] = "failed"
    problems = validate_record(module, record, tmp_path)
    assert any("multi_account.draft_read" in problem for problem in problems)


def test_ready_report_has_no_blocking_items():
    gate = gate_module()
    live = {"provided": True, "valid": True, "problems": []}
    rights = {"provided": True, "valid": True, "problems": []}
    assert gate.build_open_items(True, live, rights) == []
    blocked = gate.build_open_items(False, {**live, "valid": False}, rights)
    assert blocked and all(item["blocking"] for item in blocked)
    assert {item["item"] for item in blocked} == {
        "local package checks", "fresh login", "online functional parity"}
    rights_blocked = gate.build_open_items(True, live, {**rights, "valid": False})
    assert [item["item"] for item in rights_blocked] == ["rights and licence review"]


def gate_module():
    path = SCRIPTS / "release_gate.py"
    spec = importlib.util.spec_from_file_location("release_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_live_status_requires_a_complete_record(tmp_path):
    evidence = evidence_module()
    gate = gate_module()
    template_path = tmp_path / "live-evidence-template.json"
    template_path.write_text("{}", encoding="utf-8")

    missing = gate.live_status(None, BINDING, template_path)
    assert missing["valid"] is False and missing["problems"]

    placeholder = tmp_path / "placeholder.json"
    placeholder.write_text(json.dumps(evidence.template(BINDING)), encoding="utf-8")
    assert gate.live_status(placeholder, BINDING, template_path)["valid"] is False

    complete = tmp_path / "complete.json"
    complete.write_text(json.dumps(completed_record(evidence, tmp_path)), encoding="utf-8")
    status = gate.live_status(complete, BINDING, template_path)
    assert status["valid"] is True and status["problems"] == []


def test_loader_choice_requires_exactly_one_source():
    gate = gate_module()

    class Args:
        loader = Path("loader.jar")
        build_loader = False
        loader_repo = None
        prepare_deps = False

    args = Args()
    assert gate.loader_choice(args) == "supplied"
    args.loader = None
    args.build_loader = True
    with pytest.raises(SystemExit):
        gate.loader_choice(args)
    args.loader_repo = Path("repo")
    assert gate.loader_choice(args) == "built"
    args.loader_repo = None
    args.prepare_deps = True
    assert gate.loader_choice(args) == "built"
    args.loader_repo = Path("repo")
    with pytest.raises(SystemExit):
        gate.loader_choice(args)
    args.loader_repo = None
    args.prepare_deps = False
    args.loader = Path("loader.jar")
    with pytest.raises(SystemExit):
        gate.loader_choice(args)
    args.build_loader = False
    args.prepare_deps = True
    args.loader = None
    with pytest.raises(SystemExit):
        gate.loader_choice(args)


def rights_record(module, digest, **overrides):
    record = module.rights_template()
    record.update({"reviewed_by": "synthetic-reviewer",
                   "reviewed_at": datetime.now(timezone.utc).isoformat(),
                   "license": "CC-BY-NC-4.0",
                   "redistribution_allowed": True,
                   "third_party_reviewed": True,
                   "distributed_assets": [
                       {"path": "docs/assets/cover.svg", "sha256": digest,
                        "license": "CC-BY-4.0", "attribution": "NOTICE.md",
                        "redistributable": True}]})
    record.update(overrides)
    return record


def test_rights_review_template_never_validates():
    module = evidence_module()
    assert module.validate_rights(module.rights_template())


def reviewed_assets(tmp_path, payload=b"<svg/>"):
    target = tmp_path / "docs" / "assets" / "cover.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_rights_review_accepts_only_a_complete_decision(tmp_path):
    module = evidence_module()
    digest = reviewed_assets(tmp_path)
    assert module.validate_rights(rights_record(module, digest), repository=tmp_path) == []
    assert any("license" in problem
               for problem in module.validate_rights(
                   rights_record(module, digest, license=""), repository=tmp_path))
    assert any("redistribution" in problem
               for problem in module.validate_rights(
                   rights_record(module, digest, redistribution_allowed=False), repository=tmp_path))
    assert any("third-party" in problem
               for problem in module.validate_rights(
                   rights_record(module, digest, third_party_reviewed=False), repository=tmp_path))
    assert any("who decided" in problem
               for problem in module.validate_rights(
                   rights_record(module, digest, reviewed_by=""), repository=tmp_path))


def test_rights_review_must_cover_every_repository_asset(tmp_path):
    module = evidence_module()
    digest = reviewed_assets(tmp_path)
    extra = tmp_path / "docs" / "assets" / "later-addition.png"
    extra.write_bytes(b"not-reviewed")
    problems = module.validate_rights(rights_record(module, digest), repository=tmp_path)
    assert any(problem.startswith("distributed_assets.unlisted:") for problem in problems)


def test_rights_review_detects_a_changed_asset(tmp_path):
    module = evidence_module()
    digest = reviewed_assets(tmp_path)
    (tmp_path / "docs" / "assets" / "cover.svg").write_bytes(b"<svg>replaced</svg>")
    problems = module.validate_rights(rights_record(module, digest), repository=tmp_path)
    assert any(problem.startswith("distributed_assets.drift:") for problem in problems)


def test_rights_review_cannot_drop_the_asset_check(tmp_path):
    module = evidence_module()
    digest = reviewed_assets(tmp_path)
    problems = module.validate_rights(rights_record(module, digest))
    assert any("distributed_assets.unchecked" in problem for problem in problems)
    problems = module.validate_rights(rights_record(module, digest, distributed_assets=[]),
                                      repository=tmp_path)
    assert any("distributed_assets.unlisted:" in problem for problem in problems)


def test_rights_review_rejects_an_uncleared_asset(tmp_path):
    module = evidence_module()
    digest = reviewed_assets(tmp_path)
    record = rights_record(module, digest)
    record["distributed_assets"][0]["redistributable"] = False
    problems = module.validate_rights(record, repository=tmp_path)
    assert any("redistributable" in problem for problem in problems)


def test_wheel_metadata_body_is_compared_ignoring_line_endings():
    gate = gate_module()
    metadata = "Metadata-Version: 2.4\r\nName: xhh-sdk\r\n\r\n# Title\r\n\r\nbody line\r\n"
    assert gate._metadata_body(metadata) == "# Title\n\nbody line"
    assert gate._normalized("a\r\n\r\nb\r\n") == "a\n\nb"

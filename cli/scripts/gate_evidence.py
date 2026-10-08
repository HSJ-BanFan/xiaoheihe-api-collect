"""Validate the live half of the first-release gate.

The local gate proves that a public build signs correctly. It cannot prove that
a fresh user can log in and that the documented functions still work, because
that needs an authorized account and live calls. This module turns that live
run into a machine-checked record: `release_gate.py` only reports
`release_ready: true` when a record exists, matches the artifacts under test,
is recent enough, and carries a readback for every required feature.

A record is written by the tester after running the authorized flow. This
module never performs the flow and never invents results.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA_VERSION = 2
MAX_AGE_DAYS = 14

# Each entry is (feature, needs_cleanup). Cleanup applies to anything that
# changed or created state on the platform.
REQUIRED_FEATURES = (
    ("fresh-login", False),
    ("account-read", False),
    ("app-read", False),
    ("upload", True),
    ("creator", True),
    ("interaction", True),
)
ARTIFACT_KEYS = ("wheel_sha256", "loader_sha256", "apk_sha256")


def template(binding: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "",
        "authorized_by": "",
        "artifact_binding": {key: binding.get(key, "") for key in ARTIFACT_KEYS},
        "account": {"alias": "", "identity_masked": "", "fresh_bootstrap": False},
        "features": [
            {"name": name, "status": "not run", "command": "",
             "readback": "", "cleanup": "" if needs_cleanup else "not applicable",
             "evidence": ""}
            for name, needs_cleanup in REQUIRED_FEATURES
        ],
        "multi_account": {
            "readback": "",
            "aliases": [],
            "evidence": {"path": "", "sha256": ""},
        },
        "failed_or_unverified": [],
    }


def _parse_time(value: str) -> datetime:
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _problem(problems: list[str], code: str, message: str) -> None:
    problems.append(f"{code}: {message}")


def _validate_aliases(entries: object, code: str, problems: list[str]) -> set[str]:
    if not isinstance(entries, list):
        _problem(problems, f"{code}.aliases_type", "alias assertions are not a list")
        return set()
    if len(entries) != 2:
        _problem(problems, f"{code}.alias_count", "exactly two alias assertions are required")
    aliases: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            _problem(problems, f"{code}.alias_entry", "alias assertion is not an object")
            continue
        alias = entry.get("alias")
        if not isinstance(alias, str) or not alias.strip():
            _problem(problems, f"{code}.alias_missing", "alias label is missing")
            continue
        normalized = alias.casefold()
        if normalized in aliases:
            _problem(problems, f"{code}.duplicate_alias", "alias labels must be unique")
        aliases.add(normalized)
        if entry.get("identity_matches_own") is not True:
            _problem(problems, f"{code}.own_identity", "own-identity readback did not pass")
        if entry.get("identity_matches_other") is not False:
            _problem(problems, f"{code}.cross_identity", "cross-identity readback did not reject")
        if entry.get("drafts_read") != "ok":
            _problem(problems, f"{code}.draft_read", "own-draft readback did not pass")
    return aliases


def _validate_multi_account(section: object, evidence_path: str | Path,
                            problems: list[str]) -> None:
    if not isinstance(section, dict):
        _problem(problems, "multi_account.missing", "two-account evidence is missing")
        return
    if not str(section.get("readback", "")).strip():
        _problem(problems, "multi_account.readback", "two-account readback summary is missing")
    embedded = _validate_aliases(section.get("aliases"), "multi_account", problems)

    reference = section.get("evidence")
    if not isinstance(reference, dict):
        _problem(problems, "multi_account.evidence_shape",
                 "linked evidence must include a path and SHA-256")
        return
    raw_path = reference.get("path")
    expected_digest = reference.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        _problem(problems, "multi_account.evidence_path", "linked evidence path is missing")
        return
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        _problem(problems, "multi_account.evidence_sha256",
                 "linked evidence SHA-256 is missing or malformed")
        return

    record_dir = Path(evidence_path).resolve().parent
    candidate = Path(raw_path)
    try:
        target = (candidate if candidate.is_absolute() else record_dir / candidate).resolve()
        target.relative_to(record_dir)
    except (OSError, RuntimeError, ValueError):
        _problem(problems, "multi_account.evidence_path_escape",
                 "linked evidence is outside the live-record directory")
        return
    if not target.exists():
        _problem(problems, "multi_account.evidence_missing", "linked evidence is not a file")
        return
    try:
        target = target.resolve(strict=True)
        if not target.is_file():
            raise OSError
        contents = target.read_bytes()
    except (OSError, RuntimeError):
        _problem(problems, "multi_account.evidence_read", "linked evidence could not be read")
        return
    actual_digest = hashlib.sha256(contents).hexdigest()
    if actual_digest != expected_digest:
        _problem(problems, "multi_account.evidence_hash_mismatch",
                 "linked evidence SHA-256 does not match")
        return
    try:
        linked = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _problem(problems, "multi_account.evidence_json", "linked evidence is not valid JSON")
        return
    if not isinstance(linked, dict):
        _problem(problems, "multi_account.evidence_object", "linked evidence is not an object")
        return
    linked_aliases = _validate_aliases(linked.get("aliases"), "linked_multi_account", problems)
    if embedded != linked_aliases:
        _problem(problems, "multi_account.alias_mismatch",
                 "embedded and linked alias sets do not agree")


def validate(record: dict, binding: dict, *, evidence_path: str | Path,
             now: datetime | None = None,
             max_age_days: int = MAX_AGE_DAYS) -> list[str]:
    """Return a list of problems; an empty list means the record is usable."""
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["live_evidence.object: live evidence is not a JSON object"]
    if record.get("schema_version") != SCHEMA_VERSION:
        _problem(problems, "live_evidence.schema", "schema_version is not supported")
    if not str(record.get("authorized_by", "")).strip():
        _problem(problems, "fresh_login.authorization", "the live run has no authorization record")
    try:
        generated = _parse_time(record.get("generated_at", ""))
    except ValueError:
        _problem(problems, "live_evidence.generated_at", "generated_at is not an ISO timestamp")
        generated = None
    if generated is not None:
        reference = now or datetime.now(timezone.utc)
        if generated > reference + timedelta(days=1):
            _problem(problems, "live_evidence.generated_at", "timestamp is in the future")
        if reference - generated > timedelta(days=max_age_days):
            _problem(problems, "live_evidence.stale",
                     f"evidence is older than {max_age_days} days")
    recorded = record.get("artifact_binding") or {}
    if not isinstance(recorded, dict):
        recorded = {}
        _problem(problems, "artifact_binding.shape", "artifact binding is not an object")
    for key in ARTIFACT_KEYS:
        expected = str(binding.get(key, ""))
        actual = str(recorded.get(key, ""))
        if not expected:
            _problem(problems, f"artifact_binding.{key}", "gate run has no digest to bind against")
        elif actual != expected:
            _problem(problems, f"artifact_binding.{key}",
                     "live evidence digest does not match the artifact under test")
    account = record.get("account") or {}
    if not isinstance(account, dict) or not str(account.get("alias", "")).strip():
        _problem(problems, "fresh_login.alias", "live evidence does not name the account alias")
    if not isinstance(account, dict) or account.get("fresh_bootstrap") is not True:
        _problem(problems, "fresh_login.bootstrap", "fresh login bootstrap did not pass")
    seen = {}
    features = record.get("features")
    if not isinstance(features, list):
        features = []
        _problem(problems, "live_feature.list", "feature evidence is not a list")
    for entry in features:
        if not isinstance(entry, dict):
            _problem(problems, "live_feature.entry", "feature entry is not an object")
            continue
        name = str(entry.get("name", ""))
        if name in seen:
            _problem(problems, f"live_feature.{name}.duplicate", "feature entry is duplicated")
        seen[name] = entry
    for name, needs_cleanup in REQUIRED_FEATURES:
        entry = seen.get(name)
        if entry is None:
            _problem(problems, f"live_feature.{name}.missing", "required feature evidence is missing")
            continue
        if entry.get("status") != "passed":
            _problem(problems, f"live_feature.{name}.status", "feature is not marked passed")
        for field in ("command", "readback", "evidence"):
            if not str(entry.get(field, "")).strip():
                _problem(problems, f"live_feature.{name}.{field}", f"feature has no {field}")
        if needs_cleanup and not str(entry.get("cleanup", "")).strip():
            _problem(problems, f"live_feature.{name}.cleanup", "feature has no cleanup record")
    if record.get("failed_or_unverified"):
        _problem(problems, "online_acceptance.unverified",
                 "live evidence still lists failed or unverified items")
    _validate_multi_account(record.get("multi_account"), evidence_path, problems)
    return problems


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# Asset types the repository distributes. The rights review must name each one
# with its digest, so the decision is bound to files instead of to prose.
RIGHTS_SCHEMA_VERSION = 2
ASSET_SUFFIXES = frozenset({".svg", ".png", ".jpg", ".jpeg", ".gif", ".pdf"})
GENERATED_DIRS = frozenset({
    ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", "build", "dist",
})


def find_assets(root: Path) -> dict[str, str]:
    """Map every distributed asset under `root` to its SHA-256."""
    assets: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        parts = path.relative_to(root).parts
        if set(parts) & GENERATED_DIRS or any(part.endswith(".egg-info") for part in parts):
            continue
        if path.suffix.lower() in ASSET_SUFFIXES:
            assets[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return assets


def rights_template() -> dict:
    return {
        "schema_version": RIGHTS_SCHEMA_VERSION,
        "reviewed_by": "",
        "reviewed_at": "",
        "license": "",
        "redistribution_allowed": False,
        "third_party_reviewed": False,
        "distributed_assets": [
            {"path": "", "sha256": "", "license": "", "attribution": "",
             "redistributable": False},
        ],
        "notes": "",
    }


def _validate_asset(entry: object, index: int, problems: list[str]) -> tuple[str, str] | None:
    code = f"distributed_assets[{index}]"
    if not isinstance(entry, dict):
        _problem(problems, f"{code}.shape", "asset entry is not an object")
        return None
    path = entry.get("path")
    digest = entry.get("sha256")
    if not isinstance(path, str) or not path.strip():
        _problem(problems, f"{code}.path", "asset path is missing")
        return None
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in path or ":" in path:
        _problem(problems, f"{code}.path", "asset path is not repository-relative")
        return None
    if candidate.suffix.lower() not in ASSET_SUFFIXES:
        _problem(problems, f"{code}.path", "asset path is not a distributed asset type")
        return None
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        _problem(problems, f"{code}.sha256", "asset digest is missing or malformed")
        return None
    if not str(entry.get("license", "")).strip():
        _problem(problems, f"{code}.license", "asset licence is missing")
    if not str(entry.get("attribution", "")).strip():
        _problem(problems, f"{code}.attribution", "asset attribution is missing")
    if entry.get("redistributable") is not True:
        _problem(problems, f"{code}.redistributable", "asset is not cleared for redistribution")
    return path, digest


def _validate_asset_list(record: dict, repository: Path | None, problems: list[str]) -> int:
    """Check the recorded assets against the checkout they describe."""
    entries = record.get("distributed_assets")
    if not isinstance(entries, list):
        _problem(problems, "distributed_assets.shape", "asset list is not an array")
        return 0
    recorded: dict[str, str] = {}
    for index, entry in enumerate(entries):
        parsed = _validate_asset(entry, index, problems)
        if parsed is None:
            continue
        path, digest = parsed
        if path in recorded:
            _problem(problems, "distributed_assets.duplicate", "asset is listed twice")
            continue
        recorded[path] = digest
    if repository is None:
        _problem(problems, "distributed_assets.unchecked",
                 "the review could not be checked against the repository contents")
        return len(recorded)
    present = find_assets(repository)
    for path in sorted(set(present) - set(recorded)):
        _problem(problems, f"distributed_assets.unlisted:{path}",
                 "repository asset is not covered by the review")
    for path in sorted(set(recorded) - set(present)):
        _problem(problems, f"distributed_assets.missing:{path}",
                 "recorded asset is not in the repository")
    for path in sorted(set(recorded) & set(present)):
        if recorded[path] != present[path]:
            _problem(problems, f"distributed_assets.drift:{path}",
                     "recorded asset digest does not match the checkout")
    return len(recorded)


def validate_rights(record: dict, *, now: datetime | None = None,
                    repository: Path | None = None) -> list[str]:
    """The distribution gate: no wording here may be inferred from the code."""
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["rights review is not a JSON object"]
    if record.get("schema_version") != RIGHTS_SCHEMA_VERSION:
        problems.append("rights review schema_version is not supported")
    if not str(record.get("reviewed_by", "")).strip():
        problems.append("rights review does not name who decided")
    try:
        reviewed = _parse_time(record.get("reviewed_at", ""))
    except ValueError:
        problems.append("rights review reviewed_at is not an ISO timestamp")
    else:
        reference = now or datetime.now(timezone.utc)
        if reviewed > reference + timedelta(days=1):
            problems.append("rights review reviewed_at is in the future")
    if not str(record.get("license", "")).strip():
        problems.append("rights review does not name the chosen license")
    if record.get("redistribution_allowed") is not True:
        problems.append("rights review does not allow redistribution")
    if record.get("third_party_reviewed") is not True:
        problems.append("rights review has not covered the third-party components")
    _validate_asset_list(record, repository, problems)
    return problems

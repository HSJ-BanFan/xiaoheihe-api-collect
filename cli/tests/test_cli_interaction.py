"""Offline CLI tests: confirm gates and command surface (no network)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SDK = Path(__file__).resolve().parents[1]


@pytest.fixture()
def dummy_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "pkey": "dummy", "heybox_id": "12345",
        "imei": "DEVICE", "device_info": "DEVICE",
    }), encoding="utf-8")
    return path


def run_cli(config: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "xhh_sdk.cli", "--config", str(config), *args],
        cwd=SDK, capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_help_lists_interaction_commands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "xhh_sdk.cli", "--help"],
        cwd=SDK, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0
    for command in ("comments", "comment", "reply", "delete-comment",
                    "favourite", "follow-topic", "canary", "topic-feeds",
                    "hashtag-feed"):
        assert command in result.stdout


@pytest.mark.parametrize("args", [
    ("comment", "1", "hi"),
    ("reply", "1", "10", "10", "hi"),
    ("delete-comment", "1", "10"),
    ("favourite", "1"),
    ("unfavourite", "1"),
    ("follow-topic", "7214"),
    ("unfollow-topic", "7214"),
    ("canary", "1"),
])
def test_write_commands_require_confirm(dummy_config: Path,
                                        args: tuple[str, ...]) -> None:
    result = run_cli(dummy_config, *args)
    assert result.returncode == 2
    assert "--confirm" in result.stderr

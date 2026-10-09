import hashlib
import json
import sys

import pytest

from xhh_sdk import cli


def test_signer_install_refuses_without_confirm_before_account_or_file_access(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load", lambda _: pytest.fail("account access"))
    assert cli.main(["signer", "install", "missing.jar", "--sha256", "0" * 64]) == 2
    assert "--confirm" in capsys.readouterr().err


def test_install_then_inspect_survives_original_resource_move(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XHH_SIGNER_HOME", str(tmp_path / "private-runtime"))
    monkeypatch.setattr(cli, "_load", lambda _: pytest.fail("account access"))
    source = tmp_path / "from-case.jar"
    source.write_bytes(b"synthetic inert artifact")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert cli.main(["signer", "install", str(source), "--sha256", digest, "--confirm"]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["reference"] == "managed:" + digest
    assert installed["executed"] is False
    source.rename(tmp_path / "case-moved.jar")
    assert cli.main(["signer", "inspect", installed["reference"]]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["passed"] is True
    assert checked["sha256"] == digest


def test_offline_doctor_reports_missing_resource_without_client(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("XHH_SIGNER_JAR", str(tmp_path / "missing.jar"))
    monkeypatch.setattr(cli, "_load", lambda _: pytest.fail("implicit account access"))
    monkeypatch.setattr(cli, "XhhClient", lambda _: pytest.fail("client construction"))
    assert cli.main(["doctor", "--offline"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["offline"] is True
    assert report["signer_ready"] is False
    assert report["signer_executed"] is False


def test_offline_doctor_checks_explicit_config_without_running_signer(tmp_path, monkeypatch, capsys):
    from xhh_sdk.config import XhhConfig
    source = tmp_path / "external.jar"
    source.write_bytes(b"synthetic external artifact")
    config = XhhConfig(pkey="<synthetic-session>", heybox_id="12345", signer_jar=str(source))
    monkeypatch.setattr(cli, "_load", lambda _: config)
    monkeypatch.setattr(cli, "XhhClient", lambda _: pytest.fail("client construction"))
    monkeypatch.setattr("shutil.which", lambda _: str(tmp_path / "java"))
    assert cli.main(["--config", "synthetic-config.json", "doctor", "--offline"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["signer_ready"] and report["java_present"]
    assert not report["signer_executed"]
    assert config.pkey not in json.dumps(report)


@pytest.mark.skipif(sys.platform != "win32", reason="Managed account integration requires Windows DPAPI")
def test_managed_configuration_preserves_account_fields(tmp_path):
    from xhh_sdk.accounts import AccountStore
    store = AccountStore(tmp_path / "accounts")
    store.add("synthetic", identity="12345")
    account = store.get("synthetic")
    store.save_login("synthetic", pkey="<synthetic-session>", identity="12345",
                     expected_revision=account.revision)
    store.configure("synthetic", {"imei": "synthetic-device", "device_info": "synthetic-model"})
    store.set_risk_token("synthetic", "synthetic-risk-value")
    before = store.get("synthetic")
    store.configure("synthetic", {"signer_jar": "managed:" + "a" * 64})
    after = store.get("synthetic")
    assert (before.identity, before.pkey, before.risk_token) == (after.identity, after.pkey, after.risk_token)
    assert {k: v for k, v in after.config.items() if k != "signer_jar"} == before.config
    assert store.get_config("synthetic").signer_jar == "managed:" + "a" * 64


def test_explicit_empty_environment_reference_does_not_use_vendor(tmp_path, monkeypatch):
    from xhh_sdk import signer
    from xhh_sdk.exceptions import XhhSignerError
    vendor = tmp_path / "vendor.jar"
    vendor.write_bytes(b"synthetic")
    monkeypatch.setattr(signer, "VENDOR_JAR", vendor)
    monkeypatch.setenv("XHH_SIGNER_JAR", "")
    with pytest.raises(XhhSignerError, match="empty"):
        signer.inspect_signer()


def test_offline_doctor_returns_safe_error_for_malformed_config(tmp_path, capsys):
    source = tmp_path / "bad-config.json"
    source.write_text('{}', encoding="utf-8")
    assert cli.main(["--config", str(source), "doctor", "--offline"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["offline"] is True
    assert result["error"] == "invalid configuration; required fields or types are incorrect"

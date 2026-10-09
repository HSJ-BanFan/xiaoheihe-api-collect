"""Managed accounts use real Windows DPAPI, only with temporary test data."""
import base64
import json
import os
import subprocess
import sys

import pytest

from xhh_sdk import accounts
from xhh_sdk.exceptions import XhhConfigError


@pytest.fixture
def store(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Real DPAPI requires Windows")
    return accounts.AccountStore(tmp_path / "private")


def login(store, alias="one", identity="123456789", pkey="test-only-cookie-one"):
    return store.save_login(alias, identity=identity, pkey=pkey,
                            expected_revision=store.get(alias).revision)


def test_empty_listing_creates_no_private_directory(store):
    assert store.list() == []
    assert not store.root.exists()


def test_records_roundtrip_isolated_encrypted_and_publicly_redacted(store):
    store.add("one", identity="123456789")
    store.add("two")
    store.configure("one", {"imei": "test-device-one", "timeout": 12})
    login(store)
    login(store, "two", "987654321", "test-only-cookie-two")
    data = (store.root / "accounts.json").read_bytes()
    for secret in (b"test-only-cookie-one", b"test-only-cookie-two", b"123456789",
                   b"987654321", b"test-device-one"):
        assert secret not in data
    assert json.loads(data)["schema_version"] == 1
    restored = accounts.AccountStore(store.root)
    assert restored.get_config("one").pkey == "test-only-cookie-one"
    assert restored.get_config("two").pkey == "test-only-cookie-two"
    assert restored.get_config("one").imei == "test-device-one"
    public = restored.list()
    assert public[0] == {"alias": "one", "identity_masked": "12*****89",
                         "authenticated": True, "state": "logged_in",
                         "storage": "windows-dpapi", "protocol_mode": "app"}
    rendered = json.dumps(public) + repr(restored.get("one"))
    assert "test-only-cookie" not in rendered
    assert "test-device-one" not in json.dumps(public)


@pytest.mark.parametrize("alias", ["", "../x", "a/b", "a\\b", "a.", "a b", "_a",
                                    "CON", "nul", "LPT1", "com9", "a" * 33])
def test_bad_aliases_are_rejected_without_creating_store(store, alias):
    with pytest.raises(XhhConfigError):
        store.add(alias)
    assert not store.root.exists()


def test_case_collisions_rejected_and_lookup_is_case_insensitive(store):
    store.add("Alice")
    with pytest.raises(XhhConfigError):
        store.add("alice")
    assert store.get("ALICE").alias == "Alice"
    assert len(store.list()) == 1


def test_identity_binding_and_logout_preserve_configuration(store):
    store.add("one", identity="123456789")
    store.configure("one", {"imei": "test-device-one"})
    with pytest.raises(XhhConfigError):
        login(store, identity="987654321")
    login(store)
    before = store.get("one").revision
    store.logout("one")
    result = store.get("one")
    assert (result.identity, result.pkey, result.config) == (
        "123456789", None, {"imei": "test-device-one", "protocol_mode": "app"})
    assert result.revision != before
    assert store.list()[0]["state"] == "needs_login"


def test_each_alias_uses_its_own_device_profile(store):
    store.add("one", identity="11111")
    store.add("two", identity="22222")
    login(store, "one", "11111", "synthetic-one")
    login(store, "two", "22222", "synthetic-two")
    store.configure("one", {"imei": "device-one", "device_info": "model-one"})
    store.configure("two", {"imei": "device-two", "device_info": "model-two"})

    first = store.get_config("one")
    second = store.get_config("two")
    assert (first.heybox_id, first.imei, first.device_info) == (
        "11111", "device-one", "model-one")
    assert (second.heybox_id, second.imei, second.device_info) == (
        "22222", "device-two", "model-two")


@pytest.mark.parametrize("action", ["logout", "configure", "remove_recreate", "other_login"])
def test_stale_login_cannot_overwrite_newer_state(store, action):
    store.add("one")
    old = store.get("one").revision
    if action == "remove_recreate":
        store.remove("one")
        store.add("one")
    elif action == "other_login":
        login(store)
    elif action == "configure":
        store.configure("one", {"timeout": 15})
    else:
        store.logout("one")
    with pytest.raises(XhhConfigError):
        store.save_login("one", identity="123456789", pkey="stale-test-cookie",
                         expected_revision=old)
    assert store.get("one").pkey != "stale-test-cookie"


@pytest.mark.parametrize("values", [{"pkey": "test-secret"}, {"heybox_id": "123"},
    {"api_base": "https://invalid.example"}, {"extra": {}}, {"timeout": 0},
    {"timeout": float("nan")}, {"timeout": True}, {"java": []}, {"imei": "a;b"}])
def test_config_rejects_bad_keys_and_values_without_mutation(store, values):
    store.add("one")
    before = store.get("one").revision
    with pytest.raises(XhhConfigError) as caught:
        store.configure("one", values)
    assert "test-secret" not in str(caught.value)
    assert store.get("one").revision == before


@pytest.mark.parametrize("pkey,identity", [("", "123"), ("a;b", "123"),
    ("a\nb", "123"), ("a\x00b", "123"), ("test", "abc"), ("test", "\x123")])
def test_login_validation_rejects_bad_credentials(store, pkey, identity):
    store.add("one")
    with pytest.raises(XhhConfigError):
        login(store, pkey=pkey, identity=identity)
    assert store.get("one").pkey is None


@pytest.mark.parametrize("data", [b"", b"{", b"null", b'{"schema_version":2,"accounts":{}}',
    b'{"schema_version":1,"accounts":{},"accounts":{}}',
    b'{"schema_version":1,"accounts":{"one":{"protection":"plaintext","value":"test"}}}'])
def test_corrupt_store_fails_closed_and_is_not_replaced(store, data):
    store.add("one")
    file = store.root / "accounts.json"
    file.write_bytes(data)
    with pytest.raises(XhhConfigError):
        store.list()
    with pytest.raises(XhhConfigError):
        store.add("two")
    assert file.read_bytes() == data


def test_damaged_dpapi_blob_fails_closed(store):
    store.add("one")
    file = store.root / "accounts.json"
    document = json.loads(file.read_text())
    document["accounts"]["one"]["value"] = "YWJjZA=="
    file.write_text(json.dumps(document))
    with pytest.raises(XhhConfigError):
        store.get("one")


def test_no_legacy_or_environment_credential_fallback(store, monkeypatch):
    monkeypatch.setenv("XHH_PKEY", "test-only-ambient-cookie")
    monkeypatch.setenv("XHH_HEYBOX_ID", "123456789")
    store.add("one")
    with pytest.raises(XhhConfigError, match="not logged in"):
        store.get_config("one")
    login(store)
    monkeypatch.setenv("XHH_API_BASE", "https://invalid.example")
    assert store.get_config("one").api_base == "https://api.xiaoheihe.cn"


def test_atomic_replace_failure_preserves_previous_store(store, monkeypatch):
    store.add("one")
    before = (store.root / "accounts.json").read_bytes()
    def fail_replace(*args):
        raise OSError("test-only-sensitive-path")
    monkeypatch.setattr(accounts.os, "replace", fail_replace)
    with pytest.raises(XhhConfigError) as caught:
        store.add("two")
    assert "test-only-sensitive-path" not in str(caught.value)
    assert (store.root / "accounts.json").read_bytes() == before
    assert sorted(p.name for p in store.root.iterdir()) == ["accounts.json"]


def test_separate_processes_do_not_lose_account_additions(store):
    code = "from pathlib import Path; from xhh_sdk.accounts import AccountStore; import sys; AccountStore(Path(sys.argv[1])).add(sys.argv[2])"
    processes = [subprocess.Popen([sys.executable, "-c", code, str(store.root), f"user{i}"],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(8)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, (stdout, stderr)
    assert {row["alias"] for row in store.list()} == {f"user{i}" for i in range(8)}


def test_non_windows_fails_closed_before_creating_store(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts.sys, "platform", "linux")
    store = accounts.AccountStore(tmp_path / "private")
    with pytest.raises(XhhConfigError, match="Windows DPAPI"):
        store.add("one")
    assert not store.root.exists()


def test_null_identity_in_encrypted_record_is_rejected(store):
    store.add("one")
    file = store.root / "accounts.json"
    document = json.loads(file.read_text())
    record = {"alias": "one", "identity": None, "pkey": None,
              "config": {}, "revision": store.get("one").revision}
    document["accounts"]["one"]["value"] = base64.b64encode(
        accounts._dpapi(json.dumps(record).encode())).decode()
    file.write_text(json.dumps(document))
    with pytest.raises(XhhConfigError):
        store.get("one")


def test_oversized_timeout_is_a_sanitized_configuration_error(store):
    store.add("one")
    with pytest.raises(XhhConfigError):
        store.configure("one", {"timeout": 10 ** 1000})


def test_directory_and_file_have_only_protected_owner_and_system_access(store):
    store.add("one")
    command = "$ErrorActionPreference='Stop'; $a=Get-Acl -LiteralPath $env:XHH_TEST_ACL_PATH; [pscustomobject]@{Protected=$a.AreAccessRulesProtected; Rules=@($a.Access | ForEach-Object { [pscustomobject]@{Sid=$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value; Inherited=$_.IsInherited; Rights=$_.FileSystemRights.ToString()} })} | ConvertTo-Json -Depth 4"
    environment = {k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"}
    for path in (store.root, store.root / "accounts.json"):
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                env={**environment, "XHH_TEST_ACL_PATH": str(path)},
                                text=True, capture_output=True, check=True)
        acl = json.loads(result.stdout)
        assert {rule["Sid"] for rule in acl["Rules"]} == {"S-1-3-4", "S-1-5-18"}
        assert all("FullControl" in rule["Rights"] for rule in acl["Rules"])
        if path == store.root:
            assert acl["Protected"] is True
        else:
            assert all(rule["Inherited"] for rule in acl["Rules"])

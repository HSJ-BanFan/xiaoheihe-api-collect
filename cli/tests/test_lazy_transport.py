"""Unsigned client operations must not require a signer or a Java runtime."""
import json
import subprocess
import urllib.parse
from unittest.mock import Mock

import pytest

from xhh_sdk.client import XhhClient
from xhh_sdk.config import XhhConfig
from xhh_sdk.exceptions import XhhConfigError, XhhSignerError
from xhh_sdk.transport import Transport
import xhh_sdk.signer as signer_module
import xhh_sdk.transport as transport_module


@pytest.fixture
def unsigned_config(tmp_path, monkeypatch):
    def forbidden_runtime(*args, **kwargs):
        pytest.fail("unsigned or missing-resource request attempted Java discovery/execution")

    monkeypatch.setattr(signer_module.shutil, "which", forbidden_runtime)
    monkeypatch.setattr(subprocess, "run", forbidden_runtime)
    return XhhConfig(
        pkey="synthetic-session", heybox_id="123456",
        imei="synthetic-device", device_info="synthetic-device",
        api_base="https://api.invalid", web_origin="https://web.invalid",
        signer_jar=str(tmp_path / "missing-signer.jar"),
        java=str(tmp_path / "missing-java.exe"),
    )


@pytest.mark.parametrize("factory", [Transport, XhhClient])
def test_construct_without_signer_resources(unsigned_config, factory):
    instance = factory(unsigned_config)
    assert instance.config is unsigned_config


def test_construction_still_validates_config(unsigned_config):
    unsigned_config.pkey = ""
    with pytest.raises(XhhConfigError, match="pkey is required"):
        Transport(unsigned_config)


def test_web_request_without_jar_or_java(unsigned_config, monkeypatch):
    transport = Transport(unsigned_config)
    open_request = Mock(return_value=b'{"status":"ok","result":{"alive":true}}')
    monkeypatch.setattr(transport, "_open", open_request)

    result = transport.web_request("/synthetic/heartbeat", {"keys": "[]"})

    assert result["result"] == {"alive": True}
    request = open_request.call_args.args[0]
    assert request.get_method() == "POST"
    assert request.full_url == "https://api.invalid/synthetic/heartbeat"
    assert request.get_header("Cookie") == unsigned_config.cookie_web
    assert urllib.parse.parse_qs(request.data.decode()) == {"keys": ["[]"]}


class CosResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return b""


def test_cos_put_without_jar_or_java(unsigned_config, monkeypatch):
    transport = Transport(unsigned_config)
    open_request = Mock(return_value=CosResponse())
    monkeypatch.setattr(transport_module.urllib.request, "urlopen", open_request)

    transport.put_cos(
        "https://cos.invalid/synthetic.bin", "/synthetic.bin", b"synthetic-media",
        secret_id="synthetic-id", secret_key="synthetic-key",
        session_token="synthetic-token", mime="application/octet-stream",
    )

    request = open_request.call_args.args[0]
    assert request.get_method() == "PUT"
    assert request.data == b"synthetic-media"
    assert request.get_header("Authorization").startswith("q-sign-algorithm=sha1&")


def test_client_upload_four_steps_without_signer(unsigned_config, tmp_path, monkeypatch):
    client = XhhClient(unsigned_config)
    media = tmp_path / "synthetic.bin"
    media.write_bytes(b"synthetic-media")
    monkeypatch.setattr(client, "_image_info", lambda path, data: {
        "name": path.name, "mimetype": "application/octet-stream", "fsize": len(data),
    })
    steps = []
    responses = {
        "info": {"keys": ["/synthetic.bin"], "bucket": "synthetic-123", "region": "ap-shanghai"},
        "token": {"credentials": {
            "tmpSecretId": "synthetic-id", "tmpSecretKey": "synthetic-key",
            "sessionToken": "synthetic-token",
        }},
        "callback": {"preview_urls": ["https://cdn.invalid/synthetic.bin"]},
    }

    def mock_web(request):
        step = urllib.parse.urlsplit(request.full_url).path.split("/")[-2]
        steps.append(step)
        assert request.get_method() == "POST"
        assert request.get_header("Cookie") == unsigned_config.cookie_web
        return json.dumps({"status": "ok", "result": responses[step]}).encode()

    def mock_cos(request, **kwargs):
        steps.append("cos")
        assert request.get_method() == "PUT"
        assert request.data == media.read_bytes()
        return CosResponse()

    monkeypatch.setattr(client.transport, "_open", mock_web)
    monkeypatch.setattr(transport_module.urllib.request, "urlopen", mock_cos)

    result = client.upload(media)

    assert steps == ["info", "token", "cos", "callback"]
    assert result["url"] == "https://cdn.invalid/synthetic.bin"
    assert result["key"] == "/synthetic.bin"
    assert result["bytes"] == len(b"synthetic-media")


def test_missing_signer_fails_before_network(unsigned_config, monkeypatch):
    transport = Transport(unsigned_config)
    open_request = Mock(side_effect=AssertionError("signed request reached network"))
    monkeypatch.setattr(transport, "_open", open_request)

    with pytest.raises(XhhSignerError, match="signer jar not found"):
        transport.signed_request("/synthetic/signed")

    open_request.assert_not_called()


def test_signer_initialization_retries_failure_and_caches_success(unsigned_config, monkeypatch):
    injected = Mock()
    factory = Mock(side_effect=[XhhSignerError("synthetic unavailable"), injected])
    monkeypatch.setattr(transport_module, "Signer", factory)
    transport = Transport(unsigned_config)
    factory.assert_not_called()

    with pytest.raises(XhhSignerError, match="synthetic unavailable"):
        _ = transport.signer

    assert transport.signer is injected
    assert transport.signer is injected
    assert factory.call_count == 2
    factory.assert_called_with(
        jar=unsigned_config.signer_jar, bundle=unsigned_config.signer_bundle,
        identity=unsigned_config.heybox_id,
        imei=unsigned_config.imei, device_info=unsigned_config.device_info,
        os_version=unsigned_config.os_version, app_version=unsigned_config.app_version,
        java=unsigned_config.java, timeout=max(60.0, unsigned_config.timeout * 2),
    )


def test_injected_falsey_signer_and_setter_preserve_identity(unsigned_config, monkeypatch):
    class FalseySigner:
        def __bool__(self):
            return False

        def sign(self, path):
            return {"_time": "1", "nonce": "synthetic", "hkey": "synthetic", "_rnd": "1"}

    injected = FalseySigner()
    factory = Mock(side_effect=AssertionError("injected signer was replaced"))
    monkeypatch.setattr(transport_module, "Signer", factory)
    transport = Transport(unsigned_config, signer=injected)
    monkeypatch.setattr(transport, "_open", Mock(return_value=b'{"status":"ok"}'))

    assert transport.signer is injected
    assert transport.signed_request("/synthetic/signed") == {"status": "ok"}
    replacement = FalseySigner()
    transport.signer = replacement
    assert transport.signer is replacement
    factory.assert_not_called()

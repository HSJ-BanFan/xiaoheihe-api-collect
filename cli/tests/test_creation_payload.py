"""Strict optional creation metadata, with no runtime or network dependency."""
import pytest

from xhh_sdk.exceptions import XhhConfigError
from xhh_sdk.payload import Post


@pytest.mark.parametrize("plan", ["article", "metadata-plan_2", "A" * 64])
@pytest.mark.parametrize("declaration", [1, 2, 3])
def test_creation_metadata_serializes_without_losing_values(plan, declaration):
    payload = Post(content="synthetic", post_plan=plan, extra_declaration=declaration).build()
    assert payload["post_plan"] == plan
    assert payload["extra_declaration"] == str(declaration)


def test_absent_creation_metadata_is_omitted():
    payload = Post(content="synthetic", post_plan=None, extra_declaration=None).build()
    assert "post_plan" not in payload
    assert "extra_declaration" not in payload


@pytest.mark.parametrize("plan", [True, False, 1, [], {}, "", " ", "a b", "a/b",
                                  "a;other=1", "a\n", "A" * 65, "\u6587\u7ae0"])
def test_creation_plan_refuses_malformed_keys_without_coercion(plan):
    with pytest.raises(XhhConfigError, match="post_plan"):
        Post(content="synthetic", post_plan=plan).build()


@pytest.mark.parametrize("declaration", [True, False, 0, -1, 4, "1", "", 1.0, [], {}])
def test_creation_declaration_refuses_unknown_values_and_non_ints(declaration):
    with pytest.raises(XhhConfigError, match="extra_declaration"):
        Post(content="synthetic", extra_declaration=declaration).build()


def test_invalid_creation_metadata_refuses_before_upload(monkeypatch):
    from xhh_sdk.client import XhhClient
    from xhh_sdk.config import XhhConfig

    client = XhhClient(XhhConfig(pkey="<synthetic-session>", heybox_id="12345"))
    monkeypatch.setattr(client, "upload", lambda *_: pytest.fail("invalid metadata uploaded an image"))
    with pytest.raises(XhhConfigError, match="extra_declaration"):
        client.publish(Post(content="synthetic", images=["local.png"], extra_declaration=True))


def test_web_public_post_requires_community_before_upload(monkeypatch):
    from xhh_sdk.client import XhhClient
    from xhh_sdk.config import XhhConfig

    client = XhhClient(XhhConfig(pkey="<synthetic-session>", heybox_id="12345", protocol_mode="web"))
    monkeypatch.setattr(client, "upload", lambda *_: pytest.fail("missing community uploaded an image"))
    with pytest.raises(XhhConfigError, match="community"):
        client.publish(Post(content="synthetic", images=["local.png"], draft=False), confirm=True)


@pytest.mark.parametrize("topic_ids", [
    None, "123", 123, ("123",), {}, [""], [" "], ["123", ""],
    [True], [False], [0], [-1], [1.5], [[]], ["0"], ["01"], ["-1"],
    ["123\n"], ["\uff11\uff12\uff13"], ["1" * 31], [10 ** 30],
])
def test_web_public_rejects_malformed_communities_before_upload(monkeypatch, topic_ids):
    from xhh_sdk.client import XhhClient
    from xhh_sdk.config import XhhConfig

    client = XhhClient(XhhConfig(pkey="<synthetic-session>", heybox_id="12345", protocol_mode="web"))
    monkeypatch.setattr(client, "upload", lambda *_: pytest.fail("invalid community uploaded an image"))
    monkeypatch.setattr(client.transport, "signed_request", lambda *a, **k: pytest.fail("invalid community submitted"))
    with pytest.raises(XhhConfigError, match="community"):
        client.publish(Post(content="synthetic", images=["local.png"], topic_ids=topic_ids,
                            draft=False), confirm=True)


@pytest.mark.parametrize("topic_ids", [[1], ["123"], [1, "123"], ["1" * 30], [10 ** 29]])
def test_web_public_preserves_valid_string_and_integer_communities(monkeypatch, topic_ids):
    from xhh_sdk.client import XhhClient
    from xhh_sdk.config import XhhConfig

    client = XhhClient(XhhConfig(pkey="<synthetic-session>", heybox_id="12345", protocol_mode="web"))
    submitted = []
    def respond(path, **kwargs):
        submitted.append(kwargs["payload"])
        return {"status": "ok", "link_id": 123}
    monkeypatch.setattr(client.transport, "signed_request", respond)
    result = client.publish(Post(content="synthetic", topic_ids=topic_ids, draft=False), confirm=True)
    assert result["link_id"] == "123"
    assert submitted[0]["topic_ids"] == ",".join(str(value) for value in topic_ids)

"""Offline tests for the interaction mixin: guards, payloads, read parsing.

No network. A fake transport records every request so the tests can prove
that refused calls never reach the transport at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xhh_sdk import XhhClient, XhhConfig  # noqa: E402
from xhh_sdk.exceptions import XhhConfigError  # noqa: E402

ME = "12345678"


class FakeTransport:
    def __init__(self, responses=None):
        self.calls: list[dict] = []
        self.responses = dict(responses or {})

    def signed_request(self, path, *, query=None, payload=None):
        self.calls.append({"path": path, "query": dict(query or {}),
                           "payload": dict(payload) if payload else None})
        value = self.responses.get(path, {"status": "ok", "result": {}})
        if isinstance(value, list):
            value = value.pop(0) if value else {"status": "ok", "result": {}}
        if isinstance(value, Exception):
            raise value
        return value


def make_client(fake: FakeTransport) -> XhhClient:
    config = XhhConfig(pkey="p", heybox_id=ME, imei="X", device_info="X")
    return XhhClient(config, transport=fake)


def node(comment_id: str, author: str, text: str = "x") -> dict:
    return {"commentid": comment_id, "userid": author, "text": text}


def tree_response(*, owner: str = ME, floors=None, is_favour: int = 0) -> dict:
    return {"status": "ok", "result": {
        "link": {"linkid": "1", "userid": owner, "is_favour": is_favour},
        "comments": floors or [],
    }}


def floors(*nodes: dict) -> list:
    return [{"comment": list(nodes)}]


def calls_to(fake: FakeTransport, path: str) -> list[dict]:
    return [c for c in fake.calls if c["path"] == path]


WRITE_CALLS = [
    ("comment", ("1", "hi")),
    ("reply", ("1", "10", "10", "hi")),
    ("delete_comment", ("1", "10")),
    ("favourite", ("1",)),
    ("unfavourite", ("1",)),
    ("follow_topic", ("7214",)),
    ("unfollow_topic", ("7214",)),
]


class TestConfirmGuards:
    @pytest.mark.parametrize("name,args", WRITE_CALLS)
    def test_confirm_required_and_no_call_leaks(self, name, args):
        fake = FakeTransport()
        client = make_client(fake)
        with pytest.raises(XhhConfigError):
            getattr(client, name)(*args)
        assert fake.calls == []


class TestReads:
    def test_comment_thread_flattens_floors(self):
        fake = FakeTransport({"/bbs/app/link/tree": tree_response(
            floors=floors(node("10", ME), node("11", "777")))})
        client = make_client(fake)
        thread = client.comment_thread("1")
        assert thread[0]["root"]["commentid"] == "10"
        assert [n["commentid"] for n in thread[0]["replies"]] == ["11"]
        query = calls_to(fake, "/bbs/app/link/tree")[0]["query"]
        assert query["limit"] == "50" and query["page"] == "1"

    def test_comment_thread_sort_passthrough(self):
        fake = FakeTransport({"/bbs/app/link/tree": tree_response()})
        make_client(fake).comment_thread("1", sort="time_desc", limit=10)
        query = calls_to(fake, "/bbs/app/link/tree")[0]["query"]
        assert query == {"link_id": "1", "page": "1", "limit": "10",
                         "sort_filter": "time_desc"}

    def test_topic_follow_state_found_and_absent(self):
        fake = FakeTransport({"/bbs/app/topic/search": {"status": "ok", "result": {
            "topics": [{"children": [{"topic_id": 7214, "is_follow": 1}]}]}}})
        client = make_client(fake)
        assert client.topic_follow_state("7214", "盒友杂谈") == {
            "topic_id": "7214", "found": True, "is_follow": 1}
        assert client.topic_follow_state("9", "盒友杂谈")["found"] is False


class TestComment:
    def test_comment_on_own_post_payload(self):
        fake = FakeTransport({
            "/bbs/app/link/tree": tree_response(),
            "/bbs/app/comment/create": {"status": "ok", "commentid": "555"},
        })
        client = make_client(fake)
        result = client.comment("1", "hello", confirm=True)
        assert result["comment_id"] == "555"
        create = calls_to(fake, "/bbs/app/comment/create")[0]
        assert create["payload"] == {"link_id": "1", "text": "hello",
                                     "imgs": "", "is_cy": "0"}
        assert create["query"] == {"h_src": ""}
        assert fake.calls[0]["path"] == "/bbs/app/link/tree"

    def test_comment_refuses_foreign_post(self):
        fake = FakeTransport({"/bbs/app/link/tree": tree_response(owner="777")})
        client = make_client(fake)
        with pytest.raises(XhhConfigError):
            client.comment("1", "hello", confirm=True)
        assert calls_to(fake, "/bbs/app/comment/create") == []

    @pytest.mark.parametrize("text", ["", "   ", "x" * 1001])
    def test_comment_text_validation(self, text):
        fake = FakeTransport()
        client = make_client(fake)
        with pytest.raises(XhhConfigError):
            client.comment("1", text, confirm=True)
        assert fake.calls == []

    def test_comment_is_cy_flag(self):
        fake = FakeTransport({
            "/bbs/app/link/tree": tree_response(),
            "/bbs/app/comment/create": {"status": "ok", "commentid": "1"},
        })
        make_client(fake).comment("1", "hi", is_cy=True, confirm=True)
        assert calls_to(fake, "/bbs/app/comment/create")[0]["payload"]["is_cy"] == "1"


class TestReply:
    def test_reply_payload_includes_thread_ids(self):
        fake = FakeTransport({
            "/bbs/app/link/tree": tree_response(
                floors=floors(node("10", "777"), node("11", ME))),
            "/bbs/app/comment/create": {"status": "ok", "commentid": "12"},
        })
        result = make_client(fake).reply("1", "10", "11", "reply", confirm=True)
        assert result["comment_id"] == "12"
        payload = calls_to(fake, "/bbs/app/comment/create")[0]["payload"]
        assert payload["root_id"] == "10" and payload["reply_id"] == "11"

    def test_reply_to_floor_itself_allowed(self):
        fake = FakeTransport({
            "/bbs/app/link/tree": tree_response(floors=floors(node("10", "777"))),
            "/bbs/app/comment/create": {"status": "ok", "commentid": "11"},
        })
        make_client(fake).reply("1", "10", "10", "reply", confirm=True)
        assert calls_to(fake, "/bbs/app/comment/create")

    def test_reply_unknown_root_rejected(self):
        fake = FakeTransport({"/bbs/app/link/tree": tree_response()})
        with pytest.raises(XhhConfigError):
            make_client(fake).reply("1", "10", "10", "reply", confirm=True)
        assert calls_to(fake, "/bbs/app/comment/create") == []


class TestDeleteComment:
    def test_delete_own_comment_seen_in_tree(self):
        fake = FakeTransport({"/bbs/app/link/tree": tree_response(
            floors=floors(node("77", ME)))})
        result = make_client(fake).delete_comment("1", "77", confirm=True)
        assert result["deleted"] is True
        assert calls_to(fake, "/bbs/app/comment/delete")[0]["payload"] == {
            "comment_id": "77"}

    def test_delete_foreign_comment_refused(self):
        fake = FakeTransport({
            "/bbs/app/link/tree": tree_response(floors=floors(node("77", "777"))),
            "/bbs/app/profile/bbs/comment/list": {"status": "ok", "result": []},
        })
        with pytest.raises(XhhConfigError):
            make_client(fake).delete_comment("1", "77", confirm=True)
        assert calls_to(fake, "/bbs/app/comment/delete") == []

    def test_delete_uses_own_comment_list_as_fallback(self):
        fake = FakeTransport({
            "/bbs/app/link/tree": tree_response(),  # not on the first pages
            "/bbs/app/profile/bbs/comment/list": {"status": "ok", "result": [
                {"comment_id": 99, "link": {"id": 1}}]},
        })
        make_client(fake).delete_comment("1", "99", confirm=True)
        assert calls_to(fake, "/bbs/app/comment/delete")[0]["payload"] == {
            "comment_id": "99"}

    def test_delete_fallback_checks_link(self):
        fake = FakeTransport({
            "/bbs/app/link/tree": tree_response(),
            "/bbs/app/profile/bbs/comment/list": {"status": "ok", "result": [
                {"comment_id": 99, "link": {"id": 2}}]},
        })
        with pytest.raises(XhhConfigError):
            make_client(fake).delete_comment("1", "99", confirm=True)


class TestFavourites:
    def test_favourite_and_unfavourite_payloads(self):
        fake = FakeTransport({"/bbs/app/link/tree": tree_response()})
        client = make_client(fake)
        client.favourite("1", folder_id="42", confirm=True)
        client.unfavourite("1", confirm=True)
        add, remove = calls_to(fake, "/bbs/app/link/favour")
        assert add["payload"] == {"link_id": "1", "favour_type": "1",
                                  "folder_id": "42"}
        assert add["query"] == {"h_src": ""}
        assert remove["payload"] == {"link_id": "1", "favour_type": "2"}

    def test_favourite_without_folder_omits_field(self):
        fake = FakeTransport({"/bbs/app/link/tree": tree_response()})
        make_client(fake).favourite("1", confirm=True)
        payload = calls_to(fake, "/bbs/app/link/favour")[0]["payload"]
        assert "folder_id" not in payload


class TestTopicFollow:
    def test_follow_topic_checks_existence_then_writes(self):
        fake = FakeTransport({"/bbs/app/topic/list_infos": {"status": "ok", "result": {
            "topic_infos": [{"topic_id": 7214}]}}})
        result = make_client(fake).follow_topic("7214", confirm=True)
        assert result["following"] is True
        assert calls_to(fake, "/bbs/app/profile/follow/topic")[0]["payload"] == {
            "topic_id": "7214"}

    def test_follow_topic_unknown_rejected(self):
        fake = FakeTransport({"/bbs/app/topic/list_infos": {"status": "ok",
                                                           "result": {}}})
        with pytest.raises(XhhConfigError):
            make_client(fake).follow_topic("9", confirm=True)
        assert calls_to(fake, "/bbs/app/profile/follow/topic") == []

    def test_unfollow_topic_has_no_existence_precondition(self):
        fake = FakeTransport()
        result = make_client(fake).unfollow_topic("7214", confirm=True)
        assert result["following"] is False
        assert fake.calls == [{"path": "/bbs/app/profile/follow/topic/cancel",
                               "query": {}, "payload": {"topic_id": "7214"}}]

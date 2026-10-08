"""Offline tests: no network, no live credentials required.

Run:  python -m pytest tests/ -q     (from the sdk/ directory)
"""
from __future__ import annotations

import json
import struct
import sys
import urllib.parse
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xhh_sdk import XhhConfig, Post, cos_authorization, plain_text
from xhh_sdk.client import XhhClient, image_dimensions
from xhh_sdk.exceptions import XhhConfigError, XhhSignerError
from xhh_sdk.payload import _text_to_html
from xhh_sdk.signer import Signer


# --------------------------------------------------------------------- config
class TestConfig:
    def test_valid_config(self):
        c = XhhConfig(pkey="p", heybox_id="12345678")
        c.validate()

    def test_missing_pkey_rejected(self):
        with pytest.raises(XhhConfigError):
            XhhConfig(pkey="", heybox_id="12345678").validate()

    def test_non_numeric_id_rejected(self):
        with pytest.raises(XhhConfigError):
            XhhConfig(pkey="p", heybox_id="abc").validate()

    def test_cookie_headers(self):
        c = XhhConfig(pkey="tok", heybox_id="123")
        assert c.cookie_app == "pkey=tok; heybox_id=123; x_pkey=tok; x_heybox_id=123"
        assert c.cookie_web == "pkey=tok; user_heybox_id=123;"

    def test_from_file_roundtrip(self, tmp_path):
        c = XhhConfig(pkey="tok", heybox_id="42", imei="X", device_info="X")
        path = c.save(tmp_path / "config.json")
        loaded = XhhConfig.from_file(path)
        assert loaded.pkey == "tok" and loaded.heybox_id == "42"

    def test_from_file_rejects_garbage(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(XhhConfigError):
            XhhConfig.from_file(bad)


# --------------------------------------------------------------------- payload
class TestPayload:
    def test_text_converted_to_html(self):
        post = Post(title="t", content="line1\nline2", content_format="text")
        payload = post.build()
        blocks = json.loads(payload["text"])
        assert "<p>line1</p><p>line2</p>" in blocks[0]["text"]

    def test_draft_flag_always_written(self):
        assert Post(title="t", content="x").build()["draft"] == "1"
        assert Post(title="t", content="x", draft=False).build()["draft"] == "0"

    def test_hashtags_get_hash_prefix(self):
        payload = Post(title="t", content="x", hashtags=["工具", "#效率"]).build()
        assert json.loads(payload["hashtags"]) == ["#工具", "#效率"]

    def test_view_limit_only_for_articles(self):
        dynamic = Post(title="t", content="x", visibility="3").build()
        assert "view_limit" not in dynamic
        article = Post(title="t", content="x", visibility="3", post_type="3").build()
        assert article["view_limit"] == "3"

    def test_cover_promotes_to_article(self):
        payload = Post(title="t", content="x", cover_url="https://x/y.png").build()
        assert payload["post_type"] == "3"
        assert payload["thumb"] == "https://x/y.png"

    def test_edit_fields(self):
        payload = Post(title="t", content="x", edit_link_id="123").build()
        assert payload["edit"] == "1" and payload["link_id"] == "123"

    def test_local_image_rejected_at_build(self):
        with pytest.raises(XhhConfigError):
            Post(title="t", content="x", images=["local.png"]).build()

    def test_https_image_becomes_block(self):
        payload = Post(title="t", content="x",
                       images=["https://img.example/a.png"]).build()
        blocks = json.loads(payload["text"])
        assert {"type": "img", "url": "https://img.example/a.png"} in blocks

    def test_empty_post_rejected(self):
        with pytest.raises(XhhConfigError):
            Post(title="", content="   ").build()

    def test_words_count_counts_plain_text(self):
        payload = Post(title="t", content="<p>你好世界</p>").build()
        assert payload["words_count"] == "4"

    def test_plain_text_strips_tags(self):
        assert plain_text("<p>a<br>b</p>") == "a\nb\n"


# -------------------------------------------------------------------- cos sign
class TestCosSignature:
    def test_signkey_is_hex_text(self):
        # The signKey must be the hex TEXT of the first digest; this is the
        # defect class that silently breaks COS uploads.
        import hashlib
        import hmac
        secret, key_time = "SECRET", "100;200"
        raw = hmac.new(secret.encode(), key_time.encode(), hashlib.sha1).digest()
        auth = cos_authorization("id", secret, "put", "/k.png",
                                 host="h.example.com", start=100, end=200)
        assert "q-sign-algorithm=sha1" in auth
        assert "q-ak=id" in auth
        assert "q-sign-time=100;200" in auth
        assert "q-header-list=host" in auth

    def test_http_string_layout(self):
        import hashlib
        import hmac
        import urllib.parse
        host = "b.cos.ap-shanghai.myqcloud.com"
        auth = cos_authorization("id", "SECRET", "put", "/k.png", host=host,
                                 start=1, end=2)
        key_time = "1;2"
        sign_key = hmac.new(b"SECRET", key_time.encode(), hashlib.sha1).hexdigest().encode()
        hdr = f"host={urllib.parse.quote(host, safe='')}"
        http_string = f"put\n/k.png\n\n{hdr}\n"
        s2s = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
        expected = hmac.new(sign_key, s2s.encode(), hashlib.sha1).hexdigest()
        assert f"q-signature={expected}" in auth


# ---------------------------------------------------------------------- signer
class TestSigner:
    def test_rejects_bad_path(self):
        with pytest.raises(XhhSignerError):
            Signer(identity="1", imei="X", device_info="X").sign("no-slash")

    def test_rejects_missing_jar(self):
        with pytest.raises(XhhSignerError):
            Signer(jar="/nonexistent.jar", identity="1", imei="X", device_info="X")

    def test_rejects_empty_identity(self):
        with pytest.raises(XhhSignerError):
            Signer(identity="", imei="X", device_info="X")


# --------------------------------------------------------------------- browse
class _RecordingTransport:
    """Captures calls; never touches the network."""

    def __init__(self, result=None):
        self.calls = []
        self._result = result if result is not None else {"result": {}}

    def signed_request(self, path, *, query=None, payload=None):
        self.calls.append({"path": path, "query": query, "payload": payload})
        return self._result


class TestBrowse:
    def _client(self, result=None):
        from xhh_sdk import XhhClient
        t = _RecordingTransport(result)
        return XhhClient(XhhConfig(pkey="p", heybox_id="1"), transport=t), t

    def test_hot_news_hits_verified_path(self):
        client, t = self._client()
        client.hot_news(limit=5)
        assert t.calls[0]["path"] == "/bbs/app/hot_news/main_list"
        assert t.calls[0]["query"]["limit"] == "5"

    def test_search_hot_words_returns_list(self):
        client, t = self._client({"result": {"hot_words": [{"word": "x"}]}})
        words = client.search_hot_words()
        assert words == [{"word": "x"}]

    def test_followers_uses_config_identity(self):
        client, t = self._client()
        client.followers(limit=10)
        assert t.calls[0]["query"]["userid"] == "1"

    def test_fav_folders_parses_folder_list(self):
        client, t = self._client({"result": {"folders": [{"name": "f"}]}})
        assert client.fav_folders() == [{"name": "f"}]

    def test_game_leaderboard_rejects_unknown_game(self):
        client, _ = self._client()
        with pytest.raises(ValueError):
            client.game_leaderboard("lol")

    def test_game_leaderboard_builds_path(self):
        client, t = self._client()
        client.game_leaderboard("dota2", offset=0)
        assert t.calls[0]["path"] == "/game/dota2/get_player_leaderboards"

    def test_notifications_returns_list(self):
        client, t = self._client({"result": {"list": [1, 2, 3]}})
        assert client.notifications() == [1, 2, 3]

    def test_result_helper_tolerates_missing_result(self):
        client, _ = self._client({"status": "ok"})
        assert client.account_info() == {}

    def test_topic_list_infos_joins_ids(self):
        client, t = self._client()
        client.topic_list_infos(["1", "2"])
        assert t.calls[0]["query"]["topic_ids"] == "1,2"

    def test_all_browse_methods_are_get_only(self):
        """Every browse method must issue a GET (payload=None)."""
        client, t = self._client({"result": {}})
        for name in ("hot_news", "feeds_banner", "story_mode_list",
                     "search_hot_words", "hashtag_ranking", "topic_categories",
                     "followers", "following", "profile_preference",
                     "fav_folders", "account_info", "account_state",
                     "game_all_recommend", "game_developers",
                     "notifications", "link_labels", "forbid_reason",
                     "image_editor_stickers", "feedback_list", "max_tag_list"):
            getattr(client, name)()
        assert all(c["payload"] is None for c in t.calls), \
            "a browse method issued a POST payload"
        assert all(c["path"].startswith(("/bbs/", "/account/", "/game/"))
                   for c in t.calls)


# ----------------------------------------------------------------- generic call
class TestGenericCall:
    def _client(self, result=None):
        from xhh_sdk import XhhClient
        t = _RecordingTransport(result)
        return XhhClient(XhhConfig(pkey="p", heybox_id="1"), transport=t), t

    def test_call_accepts_verified_route(self):
        client, t = self._client()
        client.call("/account/info")
        assert t.calls[0]["path"] == "/account/info"
        assert t.calls[0]["payload"] is None

    def test_call_passes_query(self):
        client, t = self._client()
        client.call("/game/release_calendar/game_list", query={"limit": "5"})
        assert t.calls[0]["query"]["limit"] == "5"

    def test_call_rejects_unverified_route(self):
        client, _ = self._client()
        with pytest.raises(XhhConfigError):
            client.call("/totally/not/verified")

    def test_call_rejects_write_route(self):
        client, _ = self._client()
        with pytest.raises(XhhConfigError):
            client.call("/bbs/app/api/link/post")

    def test_call_rejects_safety_excluded(self):
        client, _ = self._client()
        with pytest.raises(XhhConfigError):
            client.call("/bbs/app/profile/friend/del")

    def test_snapshot_sorted_and_unique(self):
        from xhh_sdk.routes import VERIFIED_READ_ROUTES as routes
        assert list(routes) == sorted(set(routes))
        assert all(r.startswith("/") for r in routes)


# ------------------------------------------------------------ media metadata
def png(width: int = 3, height: int = 5) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload)))

    rows = b"".join(b"\x00" + b"\x10\x20\x30" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


class TestImageDimensions:
    def test_png(self):
        assert image_dimensions(png(7, 11)) == (7, 11)

    def test_gif(self):
        data = b"GIF89a" + (64).to_bytes(2, "little") + (32).to_bytes(2, "little") + b"\x00" * 4
        assert image_dimensions(data) == (64, 32)

    def test_jpeg_scan_finds_the_frame_header(self):
        segment = b"\xff\xe0" + (16).to_bytes(2, "big") + b"\x00" * 14
        frame = (b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
                 + (600).to_bytes(2, "big") + (800).to_bytes(2, "big") + b"\x03" + b"\x00" * 9)
        assert image_dimensions(b"\xff\xd8" + segment + frame) == (800, 600)

    def test_unknown_format_returns_none(self):
        assert image_dimensions(b"synthetic-media") is None

    def test_upload_info_carries_dimensions_without_pillow(self, tmp_path, monkeypatch):
        """The platform rejects an allocation whose file entry has no size."""
        from xhh_sdk import transport as transport_module

        media = tmp_path / "synthetic.png"
        media.write_bytes(png(4, 9))
        client = XhhClient(XhhConfig(pkey="synthetic-pkey", heybox_id="12345678"))
        sent: list[dict] = []

        class Response:
            def __init__(self, body: bytes):
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=None):
                return self._body

        def urlopen(request, **kwargs):
            body = request.data.decode() if request.data else ""
            path = urllib.parse.urlsplit(request.full_url).path
            if path.endswith("/upload/info/v2"):
                sent.append(dict(urllib.parse.parse_qsl(body)))
                result = {"keys": ["/synthetic.png"], "bucket": "synthetic-123"}
            elif path.endswith("/upload/token/v2"):
                result = {"credentials": {"tmpSecretId": "i", "tmpSecretKey": "k",
                                          "sessionToken": "t"}}
            else:
                result = {"preview_urls": ["https://cdn.invalid/synthetic.png"]}
            return Response(json.dumps({"status": "ok", "result": result}).encode())

        monkeypatch.setattr(transport_module.urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(transport_module.Transport, "put_cos",
                            lambda *args, **kwargs: None)
        client.upload(media)

        file_info = json.loads(sent[0]["file_infos"])[0]
        assert (file_info["width"], file_info["height"]) == (4, 9)
        assert file_info["fsize"] == media.stat().st_size


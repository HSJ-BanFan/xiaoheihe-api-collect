"""High-level client: one method per verified interface.

Read-only methods are safe to call any time. The two write methods that can
publish (`publish`) require `confirm=True` when `draft=False`, so a typo can
never publish to the platform by accident.

    from xhh_sdk import XhhClient, Post, XhhConfig

    client = XhhClient(XhhConfig.from_file("~/.xhh_sdk/config.json"))
    media = client.upload("cover.png")              # -> CDN URL
    post = client.publish(Post(
        title="标题", content="<p>正文</p>",
        hashtags=["工具"], images=[media["url"]],
    ))                                               # draft by default
    post = client.publish(Post(..., draft=False), confirm=True)   # publishes
    client.delete(post["link_id"])
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from .browse import BrowseMixin
from .config import XhhConfig
from .exceptions import XhhAPIError, XhhConfigError
from .interaction import InteractionMixin
from .groups import GroupMixin
from .payload import Post
from .routes import call as _call_route
from .transport import Transport

MAX_MEDIA_BYTES = 32 * 1024 * 1024

# The platform rejects an upload allocation whose file entry has no dimensions
# ("file information missing"), so read them here rather than depend on an
# optional imaging library.
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height for PNG, JPEG or GIF, or None when unknown."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        index = 2
        while index + 4 <= len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker == 0xFF:
                index += 1
                continue
            if marker == 0x01 or 0xD0 <= marker <= 0xD9:
                index += 2
                continue
            length = int.from_bytes(data[index + 2:index + 4], "big")
            if length < 2:
                return None
            if marker in _SOF_MARKERS and index + 9 <= len(data):
                height = int.from_bytes(data[index + 5:index + 7], "big")
                width = int.from_bytes(data[index + 7:index + 9], "big")
                return width, height
            index += 2 + length
    return None


class XhhClient(GroupMixin, InteractionMixin, BrowseMixin):
    """Unofficial client for the xiaoheihe creation/upload/browse interfaces.

    Creation methods (upload/publish/edit/delete) live here; browse-domain
    reads (feeds/search/profile/account/game/notify) come from BrowseMixin;
    comment/favourite/topic-follow methods come from InteractionMixin and
    require ``confirm=True`` for every write.
    """

    def __init__(self, config: XhhConfig, *, transport: Transport | None = None) -> None:
        config.validate()
        self.config = config
        self.transport = transport or Transport(config)

    # ------------------------------------------------------------------ upload
    def _image_info(self, path: Path, data: bytes) -> dict:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        info = {"name": path.name, "mimetype": mime, "fsize": len(data)}
        size = None
        try:
            from PIL import Image  # optional dependency
        except ImportError:
            pass
        else:
            try:
                with Image.open(path) as image:
                    size = (image.width, image.height)
            except (OSError, ValueError) as exc:
                raise XhhConfigError(f"not a readable image: {path}") from exc
        size = size or image_dimensions(data)
        if not size or min(size) < 1:
            raise XhhConfigError(
                f"cannot read image dimensions: {path}; "
                "use PNG, JPEG or GIF, or install Pillow")
        info["width"], info["height"] = size
        return info

    def upload(self, file: str | Path, *, scope: str = "bbs",
               need_cache: int = 1) -> dict:
        """Upload one image; returns {url, key, bucket, region, bytes, ...}.

        Four-step web flow: info -> token -> COS PUT -> callback.
        """
        path = Path(file)
        if not path.is_file() or path.stat().st_size == 0:
            raise XhhConfigError(f"media file missing or empty: {path}")
        data = path.read_bytes()
        if len(data) > MAX_MEDIA_BYTES:
            raise XhhConfigError(f"media exceeds {MAX_MEDIA_BYTES} bytes")
        info = self._image_info(path, data)
        mime = str(info["mimetype"])

        allocated = self.transport.web_request(
            "/bbs/app/api/qcloud/cos/upload/info/v2",
            {"file_infos": json.dumps([info], ensure_ascii=False),
             "scope": scope, "need_cache": need_cache},
        ).get("result")
        if not isinstance(allocated, dict) or not allocated.get("keys"):
            raise XhhAPIError("upload/info/v2 returned no key")
        key = str(allocated["keys"][0])
        bucket = str(allocated["bucket"])
        region = str(allocated.get("region") or "ap-shanghai")

        granted = self.transport.web_request(
            "/bbs/app/api/qcloud/cos/upload/token/v2",
            {"bucket": bucket, "keys": json.dumps([key]),
             "mimetypes": json.dumps([mime])},
        ).get("result")
        creds = granted.get("credentials") if isinstance(granted, dict) else None
        if not isinstance(creds, dict):
            raise XhhAPIError("upload/token/v2 returned no credentials")

        bucket_id = bucket.split("-")[-1]
        if bucket_id in {"76572233", "26734588", "89370810"}:
            host = f"{bucket}.cos.accelerate.myqcloud.com"
        else:
            host = f"{bucket}.cos.{region}.myqcloud.com"
        endpoint = f"https://{host}{key}"
        self.transport.put_cos(
            endpoint, key, data,
            secret_id=creds["tmpSecretId"], secret_key=creds["tmpSecretKey"],
            session_token=creds["sessionToken"], mime=mime)

        registered = self.transport.web_request(
            "/bbs/app/api/qcloud/cos/upload/callback/v2",
            {"is_finished": "true", "keys": json.dumps([key])},
        ).get("result")
        previews = registered.get("preview_urls") if isinstance(registered, dict) else None
        url = (str(previews[0]) if isinstance(previews, list) and previews
               else f"https://imgheybox.max-c.com{key}")
        return {"url": url, "key": key, "bucket": bucket, "region": region,
                "bytes": len(data), "width": info.get("width"),
                "height": info.get("height"), "file": str(path)}

    def heartbeat(self, keys: list[str]) -> dict:
        """Keep multipart upload keys alive (web, unsigned)."""
        return self.transport.web_request(
            "/bbs/app/api/qcloud/cos/upload/heartbeat",
            {"keys": json.dumps(keys)}).get("result", {})

    def copy_image_by_url(self, target_url: str, *, watermark: str | None = None) -> dict:
        """Re-host an external image on the platform CDN (signed)."""
        query = {"target_url": target_url}
        if watermark is not None:
            query["watermark"] = watermark
        return self.transport.signed_request(
            "/bbs/app/api/qcloud/cos/copy/image/by/url", query=query).get("result", {})

    # ------------------------------------------------------------------ post
    def publish(self, post: Post, *, confirm: bool = False,
                upload_local: bool = True) -> dict:
        """Create/update a post.

        Draft posts (the default) go straight through. Publishing for real
        (post.draft=False) requires confirm=True; local image paths in
        post.images are uploaded first when upload_local is True.
        """
        if not post.draft and not confirm:
            raise XhhConfigError(
                "post.draft=False publishes for real; pass confirm=True to proceed")
        if upload_local:
            resolved: list[str] = []
            for image in post.images:
                ref = str(image)
                if ref.startswith("https://"):
                    resolved.append(ref)
                else:
                    resolved.append(self.upload(ref)["url"])
            post = Post(**{**post.__dict__, "images": resolved})
        payload = post.build()
        result = self.transport.signed_request("/bbs/app/api/link/post",
                                               payload=payload).get("result", {})
        if not isinstance(result, dict) or not result.get("link_id"):
            raise XhhAPIError("link/post returned no link_id")
        return {"link_id": str(result["link_id"]),
                "url": f"https://www.xiaoheihe.cn/app/bbs/link/{result['link_id']}",
                "draft": post.draft, "payload": payload}

    def edit(self, link_id: str, post: Post, *, confirm: bool = False) -> dict:
        """Edit an existing post (body updates; title behavior is inconsistent)."""
        if not post.draft and not confirm:
            raise XhhConfigError("editing with draft=False requires confirm=True")
        post = Post(**{**post.__dict__, "edit_link_id": str(link_id)})
        return self.publish(post, confirm=confirm)

    def delete(self, link_id: str) -> dict:
        """Delete a draft or published post (change/status?status=0)."""
        self.transport.signed_request("/bbs/app/link/change/status",
                                      query={"status": "0", "link_id": str(link_id)})
        return {"link_id": str(link_id), "deleted": True}

    # ---------------------------------------------------------------- read
    def read_post(self, link_id: str, *, page: int = 1,
                  limit: int = 50) -> dict:
        """Full post tree (comments + link).

        ``limit`` is required for the server to return comment floors: probes
        showed the same comment read back as an empty list without it.
        """
        return self.transport.signed_request(
            "/bbs/app/link/tree",
            query={"link_id": str(link_id), "page": str(page),
                   "limit": str(limit)})

    def read_post_v2(self, link_id: str, *, page: int = 1,
                     limit: int = 50) -> dict:
        """Compact post tree {link, comment}."""
        return self.transport.signed_request(
            "/bbs/app/link/tree/v2",
            query={"link_id": str(link_id), "page": str(page),
                   "limit": str(limit)})

    def edit_info(self, link_id: str) -> dict:
        """Current editable state of a post (title, text, hashtags, topics...)."""
        result = self.transport.signed_request(
            "/bbs/app/link/edit/info", query={"link_id": str(link_id)}).get("result")
        return result.get("link", {}) if isinstance(result, dict) else {}

    def drafts(self, *, offset: int = 0, limit: int = 20) -> list[dict]:
        """Draft box list."""
        result = self.transport.signed_request(
            "/bbs/app/link/drafts",
            query={"offset": str(offset), "limit": str(limit)}).get("result")
        return result.get("links", []) if isinstance(result, dict) else []

    def my_posts(self, *, offset: int = 0, limit: int = 20,
                 userid: str | None = None) -> list[dict]:
        """The account's own posts (top-level post_links)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/user/link/list",
            query={"userid": userid or self.config.heybox_id,
                   "offset": str(offset), "limit": str(limit)})
        return data.get("post_links", []) or []

    def permission(self) -> dict:
        """Posting-related permission flags for the account."""
        return self.transport.signed_request(
            "/bbs/app/api/user/permission").get("result", {})

    # ------------------------------------------------------------- discovery
    def search_hashtags(self, q: str, *, only_hashtag: bool = True) -> list[dict]:
        """Search hashtags (and topics) by keyword."""
        result = self.transport.signed_request(
            "/bbs/app/api/post_editor/topic_selection/search",
            query={"q": q, "only_hashtag": "1" if only_hashtag else "0"},
        ).get("result")
        return result.get("search_result", []) if isinstance(result, dict) else []

    def topic_selection(self) -> dict:
        """Editor topic selector initial lists (hashtag_list, topic_list)."""
        return self.transport.signed_request(
            "/bbs/app/api/post_editor/topic_selection/index").get("result", {})

    def topic_index(self, *, link_id: str | None = None) -> dict:
        """Topic aggregation page data."""
        query = {"is_post": "1", "post_tab": "1", "is_new_style": "1", "type": "list"}
        if link_id:
            query["link_id"] = str(link_id)
        return self.transport.signed_request(
            "/bbs/app/api/topic/index", query=query).get("result", {})

    def emojis(self) -> dict:
        """Emoji catalog (note: emoji_groups is empty server-side)."""
        return self.transport.signed_request(
            "/bbs/app/api/emojis/list").get("result", {})

    def search(self, q: str, *, search_type: str = "link", offset: int = 0,
               limit: int = 20) -> dict:
        """General search (search_type: game | link | user ...)."""
        return self.transport.signed_request(
            "/bbs/app/api/general/search/v1",
            query={"q": q, "search_type": search_type,
                   "request_source": "edit_link", "offset": str(offset),
                   "limit": str(limit)}).get("result", {})

    # ----------------------------------------------------------------- misc
    def call(self, route: str, *, query: dict | None = None,
             payload: dict | None = None) -> dict:
        """Signed request against any verified read-only route.

        The gate lives in xhh_sdk.routes: only routes in the live-verified
        snapshot are accepted; anything else raises XhhConfigError.

            client.call("/account/info")
            client.call("/game/release_calendar/game_list", query={"limit": "5"})
        """
        return _call_route(self, route, query=query, payload=payload)

    def verify(self) -> dict:
        """Health check: signs one request and lists drafts (account-agnostic).

        Returns {"ok": True, "signer": ..., "drafts": n} on success; raises
        otherwise. Connectivity + credentials + signer smoke test.
        """
        sig = self.transport.signer.sign("/bbs/app/link/tree")
        if not {"_time", "nonce", "hkey", "_rnd"} <= set(sig):
            raise XhhAPIError("signer did not produce the expected fields")
        drafts = self.drafts(limit=1)
        return {"ok": True, "signer": "ok", "drafts": len(drafts)}

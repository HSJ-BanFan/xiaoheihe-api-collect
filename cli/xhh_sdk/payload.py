"""Payload construction for /bbs/app/api/link/post.

Mirrors the editor contract recovered from the SPA bundle (and verified live):

* `text` is a JSON string of blocks: [{"type":"html","text":...}, {"type":"img",...}]
* `hashtags` is a JSON string array; the editor submits them WITH the leading #
  (the server strips it on storage)
* `topic_ids` is a comma-separated string
* `view_limit` is only meaningful for post_type=3 (articles); sending it on a
  dynamic post (post_type=1) gets "异常的访问权限"
* `draft` must be explicit: "0" publishes for real, "1" only saves a draft.
  This builder always writes it, so a forgotten flag can never publish.
"""
from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field

from .exceptions import XhhConfigError


def _text_to_html(text: str) -> str:
    """Convert plain text to simple paragraph HTML."""
    parts = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        parts.append(f"<p>{_html.escape(line) if line else '<br>'}</p>")
    return "".join(parts)


def plain_text(markup: str) -> str:
    """Strip tags for desc/words_count, matching the editor's approach."""
    markup = re.sub(r"<br\s*/?>", "\n", markup, flags=re.I)
    markup = re.sub(r"</(?:p|h[1-6]|li|blockquote|div)>", "\n", markup, flags=re.I)
    return _html.unescape(re.sub(r"<[^>]+>", "", markup))


@dataclass
class Post:
    """One post draft destined for link/post.

    `content` may be HTML (default) or plain text. `images` accepts local
    paths or already-uploaded https URLs; https URLs go straight into the
    body, local paths are uploaded first by the client when you call
    `client.publish(..., upload_local=True)`.
    """

    title: str = ""
    content: str = ""
    content_format: str = "html"          # "html" | "text"
    hashtags: list[str] = field(default_factory=list)
    topic_ids: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    cover_url: str | None = None
    post_type: str = "1"                  # "1" dynamic | "3" article
    visibility: str | None = None         # "0" public "1".."3" private (article only)
    original: bool = True
    draft: bool = True                    # safe default: never publishes implicitly
    edit_link_id: str | None = None

    def build(self) -> dict:
        """Return the form payload for link/post."""
        content = self.content
        if self.content_format == "text":
            content = _text_to_html(content)
        if not content.strip():
            raise XhhConfigError("content is required")

        # Normalize hashtags: keep exactly one leading # on submission.
        tags: list[str] = []
        seen: set[str] = set()
        for raw in self.hashtags:
            tag = str(raw).strip().strip("#").strip()
            if tag and tag.casefold() not in seen:
                tags.append(f"#{tag}")
                seen.add(tag.casefold())

        # Append explicit images as body blocks (after the html block).
        blocks: list[dict] = [{"type": "html", "text": content.strip()}]
        for image in self.images:
            ref = str(image)
            if ref.startswith("http://") or ref.startswith("https://"):
                blocks.append({"type": "img", "url": ref})
            else:
                raise XhhConfigError(
                    f"images must be uploaded URLs at build time, got: {ref!r}")

        body = plain_text(content).replace("\n", " ").strip()
        payload: dict = {
            "title": self.title.strip(),
            "desc": body[:100],
            "link_tag": "1",
            "post_type": self.post_type,
            "draft": "1" if self.draft else "0",
            "text": json.dumps(blocks, ensure_ascii=False),
            "words_count": str(len(plain_text(content).strip())),
        }
        if tags:
            payload["hashtags"] = json.dumps(tags, ensure_ascii=False)
        if self.topic_ids:
            payload["topic_ids"] = ",".join(str(t) for t in self.topic_ids)
        if self.original:
            payload["original"] = "1"
            payload["declaration"] = "原创首发"
        if self.cover_url:
            payload["thumb"] = self.cover_url
            payload["post_type"] = "3"
        if self.visibility is not None and payload["post_type"] == "3":
            # view_limit is only valid for articles; on a dynamic post it
            # triggers 异常的访问权限 and masks the real result.
            payload["view_limit"] = str(self.visibility)
        if self.edit_link_id:
            payload["edit"] = "1"
            payload["link_id"] = str(self.edit_link_id)
        if not payload["title"] and not payload["words_count"].strip("0"):
            raise XhhConfigError("post needs a title or non-empty content")
        return payload

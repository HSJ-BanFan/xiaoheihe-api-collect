"""Community-interaction domain (v1): comments, favourites, topic follows.

Deliberately narrow, own-account scope:

* read a post's comment thread and the account's own comment list;
* comment on the account's OWN post and reply inside its threads;
* delete the account's OWN comments (ownership is proven by reading the
  thread / own-comment list before the write);
* favourite / unfavourite one explicitly named post (reversible);
* follow / unfollow one explicitly named topic (reversible).

Every write method requires ``confirm=True`` and validates its target against
the server before writing. There are no batch methods and no loops over
targets: one call, one explicit target, one state observation.

Contract evidence: APK decompilation (``/bbs/app/comment/create|delete``,
``/bbs/app/link/favour`` with ``favour_type=1|2``, ``/bbs/app/profile/
follow/topic[/cancel]``) plus the live verification recorded in the case
``reports/interaction-api-v1.md``.
"""
from __future__ import annotations

from typing import Any

from .exceptions import XhhAPIError, XhhConfigError

COMMENT_MAX_CHARS = 1000


def _comment_id(node: dict) -> str:
    for key in ("commentid", "comment_id", "id"):
        value = node.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _comment_author(node: dict) -> str:
    value = node.get("userid")
    if value in (None, ""):
        user = node.get("user")
        if isinstance(user, dict):
            value = user.get("userid")
    return "" if value in (None, "") else str(value)


def _validate_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise XhhConfigError("comment text must be a non-empty string")
    if len(text) > COMMENT_MAX_CHARS:
        raise XhhConfigError(
            f"comment text exceeds {COMMENT_MAX_CHARS} characters")
    return text


def _find_topic(tree: Any, topic_id: str) -> dict | None:
    """Depth-first search for a topic dict by id in a nested structure."""
    if isinstance(tree, dict):
        if str(tree.get("topic_id")) == topic_id:
            return tree
        for value in tree.values():
            found = _find_topic(value, topic_id)
            if found is not None:
                return found
    elif isinstance(tree, list):
        for item in tree:
            found = _find_topic(item, topic_id)
            if found is not None:
                return found
    return None


class InteractionMixin:
    """Comments, favourites, topic follows — with write guards."""

    # Provided by the concrete client that mixes this in.
    transport: Any
    config: Any

    # ----------------------------------------------------------------- reads
    def post_state(self, link_id: str) -> dict:
        """Server state of one post: owner, favourite flag, comment count."""
        data = self.transport.signed_request(
            "/bbs/app/link/tree",
            query={"link_id": str(link_id), "page": "1"})
        result = data.get("result")
        link = result.get("link") if isinstance(result, dict) else None
        if not isinstance(link, dict) or not link:
            raise XhhAPIError(f"link/tree returned no link for {link_id}")
        return link

    def comment_thread(self, link_id: str, *, page: int = 1, limit: int = 50,
                       sort: str | None = None) -> list[dict]:
        """Comment floors of one post: [{"root": node, "replies": [...]}].

        ``limit`` is always sent: the same comment reads back as an empty
        floor list when the parameter is omitted (observed 2026-10-04).
        """
        query = {"link_id": str(link_id), "page": str(page),
                 "limit": str(limit)}
        if sort:
            query["sort_filter"] = sort
        data = self.transport.signed_request(
            "/bbs/app/link/tree", query=query)
        result = data.get("result")
        floors = result.get("comments") if isinstance(result, dict) else None
        if not isinstance(floors, list):
            return []
        out: list[dict] = []
        for floor in floors:
            nodes = floor.get("comment") if isinstance(floor, dict) else None
            if not isinstance(nodes, list) or not nodes:
                continue
            root = nodes[0] if isinstance(nodes[0], dict) else {}
            replies = [n for n in nodes[1:] if isinstance(n, dict)]
            out.append({"root": root, "replies": replies})
        return out

    def sub_comments(self, root_comment_id: str, *, lastval: str | None = None,
                    hide_cy: str = "0") -> dict:
        """Replies under one floor comment (paged by ``lastval``)."""
        query = {"root_comment_id": str(root_comment_id), "h_src": "",
                 "hide_cy": hide_cy}
        if lastval is not None:
            query["lastval"] = str(lastval)
        result = self.transport.signed_request(
            "/bbs/app/comment/sub/comments", query=query).get("result")
        return result if isinstance(result, dict) else {}

    def my_comments(self, *, offset: int = 0, limit: int = 20,
                    only_cy: str = "0") -> list[dict]:
        """Comments authored by this account (newest first)."""
        result = self.transport.signed_request(
            "/bbs/app/profile/bbs/comment/list",
            query={"userid": str(self.config.heybox_id), "offset": str(offset),
                   "limit": str(limit), "only_cy": only_cy}).get("result")
        return [c for c in result if isinstance(c, dict)] \
            if isinstance(result, list) else []

    def topic_follow_state(self, topic_id: str, keyword: str) -> dict:
        """Follow state of one topic via topic search (server-observed).

        The search response omits ``is_follow`` when the account does not
        follow the topic; presence with value 1 means followed.
        """
        result = self.transport.signed_request(
            "/bbs/app/topic/search", query={"q": keyword}).get("result")
        node = _find_topic(result, str(topic_id))
        if node is None:
            return {"topic_id": str(topic_id), "found": False,
                    "is_follow": 0}
        try:
            state = int(node.get("is_follow") or 0)
        except (TypeError, ValueError):
            state = 0
        return {"topic_id": str(topic_id), "found": True, "is_follow": state}

    # ---------------------------------------------------------------- guards
    @staticmethod
    def _require_confirm(action: str, confirm: bool) -> None:
        if not confirm:
            raise XhhConfigError(
                f"{action} writes to the live account; pass confirm=True")

    def _link(self, link_id: str) -> dict:
        return self.post_state(link_id)

    def _assert_own_post(self, link_id: str) -> dict:
        link = self._link(link_id)
        owner = str(link.get("userid") or "")
        if not owner:
            user = link.get("user")
            owner = str(user.get("userid") or "") if isinstance(user, dict) else ""
        if owner != str(self.config.heybox_id):
            raise XhhConfigError(
                f"refusing to write on link {link_id}: owner is {owner or 'unknown'}, "
                "this SDK only writes on the configured account's own posts")
        return link

    def _owns_comment(self, link_id: str, comment_id: str) -> bool:
        """Prove the comment belongs to this account on this post."""
        target = str(comment_id)
        me = str(self.config.heybox_id)
        for page in (1, 2):
            for floor in self.comment_thread(link_id, page=page):
                for node in [floor["root"], *floor["replies"]]:
                    if _comment_id(node) == target and _comment_author(node) == me:
                        return True
        offset = 0
        for _ in range(4):  # bounded scan of the account's own comments
            batch = self.my_comments(offset=offset, limit=50)
            if not batch:
                break
            for node in batch:
                if _comment_id(node) != target:
                    continue
                link = node.get("link")
                link_ref = str(link.get("id") or "") if isinstance(link, dict) else ""
                if not link_ref or link_ref == str(link_id):
                    return True
            offset += len(batch)
        return False

    # ---------------------------------------------------------------- writes
    def comment(self, link_id: str, text: str, *, is_cy: bool = False,
                confirm: bool = False) -> dict:
        """Post a top-level comment on the account's own post.

        Note (observed 2026-10-04): a new comment is immediately visible in
        the author's own comment list, but its public-tree visibility is
        asynchronous (not visible within ~4 minutes in verification).
        """
        self._require_confirm("comment()", confirm)
        body = _validate_text(text)
        self._assert_own_post(link_id)
        data = self.transport.signed_request(
            "/bbs/app/comment/create",
            query={"h_src": ""},
            payload={"link_id": str(link_id), "text": body, "imgs": "",
                     "is_cy": "1" if is_cy else "0"})
        return {"comment_id": self._created_comment_id(data) or None,
                "link_id": str(link_id), "text": body, "is_cy": bool(is_cy),
                "raw": data}

    def reply(self, link_id: str, root_id: str, reply_id: str, text: str, *,
              confirm: bool = False) -> dict:
        """Reply to a comment in a thread on the account's own post.

        ``root_id`` is the floor comment that starts the thread; ``reply_id``
        is the exact comment being replied to (pass ``root_id`` to reply to
        the floor comment itself). Both must be visible on the first thread
        page, which is where the SDK proves the target before writing — a
        just-created comment that has not yet surfaced publicly cannot be
        used here yet. Public visibility of the reply itself is asynchronous.
        """
        self._require_confirm("reply()", confirm)
        body = _validate_text(text)
        self._assert_own_post(link_id)
        floors = self.comment_thread(link_id, page=1)
        floor = next((f for f in floors
                      if _comment_id(f["root"]) == str(root_id)), None)
        if floor is None:
            raise XhhConfigError(
                f"root_id {root_id} is not a floor comment on link {link_id} "
                "(first page)")
        if str(reply_id) != str(root_id) and not any(
                _comment_id(node) == str(reply_id) for node in floor["replies"]):
            raise XhhConfigError(
                f"reply_id {reply_id} is not visible in that thread's first page; "
                "fetch more replies and retry")
        data = self.transport.signed_request(
            "/bbs/app/comment/create",
            query={"h_src": ""},
            payload={"link_id": str(link_id), "text": body, "imgs": "",
                     "root_id": str(root_id), "reply_id": str(reply_id),
                     "is_cy": "0"})
        return {"comment_id": self._created_comment_id(data) or None,
                "link_id": str(link_id), "root_id": str(root_id),
                "reply_id": str(reply_id), "text": body, "raw": data}

    def delete_comment(self, link_id: str, comment_id: str, *,
                       confirm: bool = False) -> dict:
        """Delete one of the account's own comments on a post."""
        self._require_confirm("delete_comment()", confirm)
        if not self._owns_comment(link_id, comment_id):
            raise XhhConfigError(
                f"refusing to delete comment {comment_id}: not proven to belong "
                f"to this account on link {link_id} (v1 deletes own comments only)")
        self.transport.signed_request(
            "/bbs/app/comment/delete",
            payload={"comment_id": str(comment_id)})
        return {"comment_id": str(comment_id), "link_id": str(link_id),
                "deleted": True}

    def favourite(self, link_id: str, *, folder_id: str | None = None,
                  confirm: bool = False) -> dict:
        """Favourite one explicitly named post (favour_type=1)."""
        self._require_confirm("favourite()", confirm)
        self._link(link_id)  # must exist
        payload = {"link_id": str(link_id), "favour_type": "1"}
        if folder_id is not None:
            payload["folder_id"] = str(folder_id)
        data = self.transport.signed_request(
            "/bbs/app/link/favour", query={"h_src": ""}, payload=payload)
        return {"link_id": str(link_id), "favour_type": "1",
                "folder_id": str(folder_id) if folder_id is not None else None,
                "raw": data}

    def unfavourite(self, link_id: str, *, confirm: bool = False) -> dict:
        """Remove one post from favourites (favour_type=2)."""
        self._require_confirm("unfavourite()", confirm)
        self._link(link_id)  # must exist
        data = self.transport.signed_request(
            "/bbs/app/link/favour", query={"h_src": ""},
            payload={"link_id": str(link_id), "favour_type": "2"})
        return {"link_id": str(link_id), "favour_type": "2", "raw": data}

    def follow_topic(self, topic_id: str, *, confirm: bool = False) -> dict:
        """Follow one topic."""
        self._require_confirm("follow_topic()", confirm)
        infos = self.transport.signed_request(
            "/bbs/app/topic/list_infos",
            query={"topic_ids": str(topic_id)}).get("result")
        topic_infos = infos.get("topic_infos") if isinstance(infos, dict) else None
        if not isinstance(topic_infos, list) or not topic_infos:
            raise XhhConfigError(f"topic {topic_id} was not found")
        self.transport.signed_request(
            "/bbs/app/profile/follow/topic",
            payload={"topic_id": str(topic_id)})
        return {"topic_id": str(topic_id), "following": True}

    def unfollow_topic(self, topic_id: str, *, confirm: bool = False) -> dict:
        """Unfollow one topic (cleanup path; no existence precondition)."""
        self._require_confirm("unfollow_topic()", confirm)
        self.transport.signed_request(
            "/bbs/app/profile/follow/topic/cancel",
            payload={"topic_id": str(topic_id)})
        return {"topic_id": str(topic_id), "following": False}

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _created_comment_id(data: dict) -> str:
        value = data.get("commentid")
        if value not in (None, ""):
            return str(value)
        result = data.get("result")
        if isinstance(result, dict):
            comment = result.get("comment")
            if isinstance(comment, dict):
                return _comment_id(comment)
        return ""

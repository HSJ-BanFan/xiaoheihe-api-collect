"""Named read-only App group contracts; no experimental write routes."""
from __future__ import annotations

import re

from .exceptions import XhhAPIError, XhhConfigError


def numeric_id(value):
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,30}", text):
        raise ValueError("expected a non-negative decimal identifier")
    return text


def offset_value(value):
    value = int(value)
    if value < 0:
        raise ValueError("offset must be non-negative")
    return value


def limit_value(value):
    value = int(value)
    if not 1 <= value <= 100:
        raise ValueError("limit must be within 1..100")
    return value


class GroupMixin:
    def group_list(self, *, cookies=None):
        body = self.transport.signed_request("/chat_group/my_list", extra_cookies=cookies)
        result = body.get("result")
        rows = result.get("my_chat_groups") if isinstance(result, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict)
                                            or not row.get("chat_group_id") for row in rows):
            raise XhhAPIError("group list response has no valid my_chat_groups list")
        return rows

    def _group_read(self, route, group_id, params, cookies):
        try:
            group_id = numeric_id(group_id)
        except ValueError as exc:
            raise XhhConfigError(str(exc)) from None
        if group_id not in {str(row["chat_group_id"]) for row in self.group_list(cookies=cookies)}:
            raise XhhConfigError("group membership could not be confirmed for the selected account")
        body = self.transport.signed_request(route, query={"chat_group_id": group_id, **params},
                                             extra_cookies=cookies)
        result = body.get("result")
        if not isinstance(result, dict):
            raise XhhAPIError("group response has no result object")
        return result

    def group_members(self, group_id, *, offset=0, limit=20, cookies=None):
        try:
            params = {"offset": str(offset_value(offset)), "limit": str(limit_value(limit))}
        except (ValueError, TypeError) as exc:
            raise XhhConfigError(str(exc)) from None
        return self._group_read("/chat_group/user/list", group_id, params, cookies)

    def group_messages(self, group_id, *, last_msg_id="0", limit=20, cookies=None):
        try:
            params = {"last_msg_id": numeric_id(last_msg_id), "limit": str(limit_value(limit))}
        except (ValueError, TypeError) as exc:
            raise XhhConfigError(str(exc)) from None
        return self._group_read("/chatroom/v2/chat_group_msg/list", group_id, params, cookies)

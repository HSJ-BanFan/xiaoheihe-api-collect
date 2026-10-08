"""Browse-domain endpoints (feeds, search, profile, account, game, notify).

All methods here hit endpoints verified live on 2026-10-04 (outcome=ok in
route_inventory/batch_verify_results.json). Read-only by construction: every
call is a signed GET; none of these endpoints mutate state.

The mixin expects `self.transport.signed_request(path, query=...)` — provided
by the XhhClient that mixes it in.
"""
from __future__ import annotations

from typing import Any


def _result(data: dict) -> dict:
    result = data.get("result")
    return result if isinstance(result, dict) else {}


def _list(data: dict, *keys: str) -> list:
    result = data.get("result")
    if not isinstance(result, dict):
        return []
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []


class BrowseMixin:
    """Feeds, search, profile, account, game and notification reads."""

    # Provided by the concrete client that mixes this in.
    transport: Any
    config: Any

    # ------------------------------------------------------------- feeds
    def hot_news(self, *, offset: int = 0, limit: int = 20) -> dict:
        """Hot-news main list (/bbs/app/hot_news/main_list)."""
        return _result(self.transport.signed_request(
            "/bbs/app/hot_news/main_list",
            query={"offset": str(offset), "limit": str(limit)}))

    def feeds_banner(self) -> dict:
        """Community feed banners (/bbs/app/feeds/banner)."""
        return _result(self.transport.signed_request("/bbs/app/feeds/banner"))

    def story_mode_list(self, *, offset: int = 0, limit: int = 20) -> list:
        """Story-mode entries (/bbs/app/story_mode/list)."""
        data = self.transport.signed_request(
            "/bbs/app/story_mode/list",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "links", "list")

    # ------------------------------------------------------------ search
    def search_hot_words(self) -> list:
        """Search hot words (/bbs/app/api/search/hot_words)."""
        data = self.transport.signed_request("/bbs/app/api/search/hot_words")
        return _list(data, "hot_words", "words")

    def search_suggestions(self, q: str) -> dict:
        """Search suggestions v2 (/bbs/app/api/search/suggestion/v2)."""
        return _result(self.transport.signed_request(
            "/bbs/app/api/search/suggestion/v2", query={"q": q}))

    def search_topic(self, q: str) -> dict:
        """Topic search (/bbs/app/api/search/topic)."""
        return _result(self.transport.signed_request(
            "/bbs/app/api/search/topic", query={"q": q}))

    def search_found(self, q: str) -> dict:
        """Search discovery page (/bbs/app/api/search/found)."""
        return _result(self.transport.signed_request(
            "/bbs/app/api/search/found", query={"q": q}))

    # ----------------------------------------------------------- hashtag
    def hashtag_ranking(self) -> dict:
        """Hashtag ranking (/bbs/app/hashtag/ranking)."""
        return _result(self.transport.signed_request("/bbs/app/hashtag/ranking"))

    def hashtag_search(self, q: str) -> dict:
        """Hashtag search (/bbs/app/hashtag/search)."""
        return _result(self.transport.signed_request(
            "/bbs/app/hashtag/search", query={"q": q}))

    def hashtag_template_center(self) -> dict:
        """Hashtag template center (/bbs/app/hashtag/template/center)."""
        return _result(self.transport.signed_request(
            "/bbs/app/hashtag/template/center"))

    # ------------------------------------------------------------ topics
    def topic_categories(self) -> dict:
        """Topic categories (/bbs/app/topic/categories)."""
        return _result(self.transport.signed_request("/bbs/app/topic/categories"))

    def topic_search(self, q: str) -> dict:
        """Topic search (/bbs/app/topic/search)."""
        return _result(self.transport.signed_request(
            "/bbs/app/topic/search", query={"q": q}))

    def topic_list_infos(self, topic_ids: list[str]) -> dict:
        """Topic info by ids (/bbs/app/topic/list_infos)."""
        return _result(self.transport.signed_request(
            "/bbs/app/topic/list_infos",
            query={"topic_ids": ",".join(str(t) for t in topic_ids)}))

    def topic_sub_categories(self, topic_id: str) -> dict:
        """Sub-categories of one topic (/bbs/app/topic/sub/categories/v2)."""
        return _result(self.transport.signed_request(
            "/bbs/app/topic/sub/categories/v2", query={"topic_id": str(topic_id)}))

    # ----------------------------------------------------------- profile
    def followers(self, *, offset: int = 0, limit: int = 20,
                  userid: str | None = None) -> list:
        """Follower list (/bbs/app/profile/follower/list)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/follower/list",
            query={"userid": userid or self.config.heybox_id,
                   "offset": str(offset), "limit": str(limit)})
        return _list(data, "followers", "list", "users")

    def following(self, *, offset: int = 0, limit: int = 20,
                  userid: str | None = None) -> list:
        """Following list (/bbs/app/profile/following/list)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/following/list",
            query={"userid": userid or self.config.heybox_id,
                   "offset": str(offset), "limit": str(limit)})
        return _list(data, "following", "list", "users")

    def following_simple(self, *, userid: str | None = None) -> list:
        """Lightweight following list (/bbs/app/profile/following/simple_list)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/following/simple_list",
            query={"userid": userid or self.config.heybox_id})
        return _list(data, "following", "list", "users")

    def relations(self, *, userid: str | None = None) -> dict:
        """Relation summary for a user (/bbs/app/profile/relations)."""
        return _result(self.transport.signed_request(
            "/bbs/app/profile/relations",
            query={"userid": userid or self.config.heybox_id}))

    def profile_preference(self) -> dict:
        """Profile preference settings (/bbs/app/profile/preference)."""
        return _result(self.transport.signed_request("/bbs/app/profile/preference"))

    def profile_privacy_settings(self) -> dict:
        """Privacy settings (/bbs/app/profile/privacy/settings)."""
        return _result(self.transport.signed_request(
            "/bbs/app/profile/privacy/settings"))

    def profile_history_visit(self, *, offset: int = 0, limit: int = 20) -> list:
        """Visit history (/bbs/app/profile/history/visit)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/history/visit",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "list", "history")

    def profile_history_search(self, *, offset: int = 0, limit: int = 20) -> list:
        """Search history (/bbs/app/profile/history/search)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/history/search",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "list", "history")

    def subscribed_events(self, *, offset: int = 0, limit: int = 20) -> list:
        """Subscribed events (/bbs/app/profile/subscribed/events)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/subscribed/events",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "events", "list")

    def recommend_following(self, *, offset: int = 0, limit: int = 20) -> list:
        """Recommended users to follow (/bbs/app/profile/recommend/following)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/recommend/following",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "users", "list", "recommend")

    # ---------------------------------------------------------- fav (read)
    def fav_folders(self) -> list:
        """Favorite folders (/bbs/app/profile/fav/folders)."""
        data = self.transport.signed_request("/bbs/app/profile/fav/folders")
        result = data.get("result")
        if isinstance(result, dict):
            for key in ("folders", "folder_list", "list"):
                if isinstance(result.get(key), list):
                    return result[key]
        return []

    def fav_folder_links(self, folder_id: str, *, offset: int = 0,
                         limit: int = 20) -> list:
        """Links inside a favorite folder (/bbs/app/profile/fav/folder/v2/links)."""
        data = self.transport.signed_request(
            "/bbs/app/profile/fav/folder/v2/links",
            query={"folder_id": str(folder_id), "offset": str(offset),
                   "limit": str(limit)})
        return _list(data, "links", "list")

    def fav_tab_list(self) -> dict:
        """Favorite tabs (/bbs/app/profile/fav/tab_list)."""
        return _result(self.transport.signed_request("/bbs/app/profile/fav/tab_list"))

    # ---------------------------------------------------------- account
    def account_info(self) -> dict:
        """Account overview (/account/info)."""
        return _result(self.transport.signed_request("/account/info"))

    def account_home(self) -> dict:
        """Account home v2 (/account/home_v2)."""
        return _result(self.transport.signed_request("/account/home_v2"))

    def account_state(self) -> dict:
        """Account state (/account/check_account_state)."""
        return _result(self.transport.signed_request("/account/check_account_state"))

    def account_games(self) -> list:
        """Owned game list (/account/game_list)."""
        data = self.transport.signed_request("/account/game_list")
        return _list(data, "games", "list")

    def account_game_infos(self, game_ids: list[str]) -> dict:
        """Game info by ids (/account/game_infos)."""
        return _result(self.transport.signed_request(
            "/account/game_infos",
            query={"game_ids": ",".join(str(g) for g in game_ids)}))

    def steam_friends(self) -> list:
        """Steam friends (/account/steam_friends_v2)."""
        data = self.transport.signed_request("/account/steam_friends_v2")
        return _list(data, "friends", "list")

    def user_group(self) -> dict:
        """User group info (/account/user_group)."""
        return _result(self.transport.signed_request("/account/user_group"))

    # ------------------------------------------------------------- game
    def game_leaderboard(self, game: str, **params) -> dict:
        """Player leaderboards for one game (apex/csgo/destiny2/dota2)."""
        allowed = {"apex", "csgo", "destiny2", "dota2"}
        if game not in allowed:
            raise ValueError(f"game must be one of {sorted(allowed)}")
        return _result(self.transport.signed_request(
            f"/game/{game}/get_player_leaderboards",
            query={k: str(v) for k, v in params.items()} or None))

    def game_all_recommend(self) -> dict:
        """All-game recommendations (/game/all_recommend/v2)."""
        return _result(self.transport.signed_request("/game/all_recommend/v2"))

    def game_similar(self, game_id: str) -> dict:
        """Similar games (/game/get_similar_games)."""
        return _result(self.transport.signed_request(
            "/game/get_similar_games", query={"game_id": str(game_id)}))

    def game_developers(self) -> dict:
        """Developer list (/game/developers)."""
        return _result(self.transport.signed_request("/game/developers"))

    # ----------------------------------------------------------- notify
    def notifications(self, *, offset: int = 0, limit: int = 20) -> list:
        """Notification list (/bbs/notify/list)."""
        data = self.transport.signed_request(
            "/bbs/notify/list", query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "list", "notifies", "notifications")

    def official_messages(self, *, offset: int = 0, limit: int = 20) -> list:
        """Official messages v2 (/bbs/notify/official_msg_v2/list)."""
        data = self.transport.signed_request(
            "/bbs/notify/official_msg_v2/list",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "list", "messages")

    def developer_messages(self, *, offset: int = 0, limit: int = 20) -> list:
        """Developer messages (/bbs/notify/developer_messages)."""
        data = self.transport.signed_request(
            "/bbs/notify/developer_messages",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "list", "messages")

    # ------------------------------------------------------ misc reads
    def link_labels(self) -> dict:
        """Post labels (/bbs/app/link/labels)."""
        return _result(self.transport.signed_request("/bbs/app/link/labels"))

    def forbid_reason(self) -> dict:
        """Forbid reasons (/bbs/app/api/get/forbid_reason)."""
        return _result(self.transport.signed_request("/bbs/app/api/get/forbid_reason"))

    def image_editor_stickers(self) -> dict:
        """Image-editor sticker list (/bbs/app/api/image_editor/sticker/list)."""
        return _result(self.transport.signed_request(
            "/bbs/app/api/image_editor/sticker/list"))

    def image_editor_typefaces(self) -> dict:
        """Image-editor typeface list (/bbs/app/api/image_editor/advance_typeface/list)."""
        return _result(self.transport.signed_request(
            "/bbs/app/api/image_editor/advance_typeface/list"))

    def feedback_list(self, *, offset: int = 0, limit: int = 20) -> list:
        """Feedback history (/bbs/app/feedback/list)."""
        data = self.transport.signed_request(
            "/bbs/app/feedback/list",
            query={"offset": str(offset), "limit": str(limit)})
        return _list(data, "list", "feedbacks")

    def max_tag_list(self) -> dict:
        """Max tag list (/bbs/app/max/tag_list)."""
        return _result(self.transport.signed_request("/bbs/app/max/tag_list"))

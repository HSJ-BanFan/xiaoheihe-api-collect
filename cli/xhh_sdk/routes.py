"""Generic read-only access to the historical route allowlist.

The snapshot records prior evidence, not current availability or freedom from
side effects. ``call`` refuses payloads and paths outside this exact allowlist.
Private research regeneration is intentionally not part of this package.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from .exceptions import XhhConfigError

# Routes that answered ok during probing but are semantically mutating or
# context-bound: excluded from the callable snapshot (defense in depth — the
# classifier incident showed why "it answered ok" is not proof of read-only).
SAFETY_EXCLUDED = (
    "/account/add_to_cart/push_state",
    "/bbs/app/profile/fav/folder/clean",
    "/bbs/app/profile/friend/del",
    # GET probe answered ok, but the endpoint is a POST setter taking
    # topic_ids; classifying it as a readable route was wrong.
    "/bbs/app/profile/topic/settings",
    "/game/mobile/get_auto_download_list",
    # Historical GET success conflicts with POST contracts or suggests
    # state changes. Quarantine until method and semantics are reviewed.
    "/account/check_account_state",
    "/account/manual_refresh_steam_screenshot",
    "/account/qr_redirect",
    "/account/resolve_clipboard",
    "/bbs/app/api/post_editor/topic_selection/index",
    "/bbs/app/api/recommend/feedback",
    "/account/refresh_steam_stats",
    "/account/getui/fix",
    "/bbs/app/link/steam/game/ignore_review",
)

# Historical allowlist. Update only with reviewed evidence and a new digest.
VERIFIED_READ_ROUTES: tuple[str, ...] = (
    "/account/ad/get_overall_ad_info",
    "/account/avatar/decoration/mall",
    "/account/check_white_url",
    "/account/cleared_game_list",
    "/account/client/animation",
    "/account/epic_game_list",
    "/account/following_list",
    "/account/friend_list_v2",
    "/account/game_infos",
    "/account/game_list",
    "/account/game_servers",
    "/account/get_ads_info_v2",
    "/account/get_async_js",
    "/account/get_auth_info",
    "/account/get_popup_tool_card",
    "/account/get_push_state_v2",
    "/account/get_qrcode_url",
    "/account/get_refreshing_state",
    "/account/get_white_hostnames",
    "/account/home_v2",
    "/account/info",
    "/account/my_comment_list",
    "/account/personal_profile/config/get",
    "/account/popup",
    "/account/popup_v2",
    "/account/privacy/recommend/switch/get",
    "/account/profile/editor/settings",
    "/account/psn_game_list",
    "/account/public_steam_settings",
    "/account/qr_state",
    "/account/recommend/block/list",
    "/account/steam_api_key/setting_page",
    "/account/steam_friends_v2",
    "/account/teen_mode/status",
    "/account/third_login/steam/get_authorize_url",
    "/account/tips_state",
    "/account/unlogin_stats",
    "/account/user_group",
    "/account/version_control_info",
    "/account/wechat/state",
    "/account/xbox_game_list",
    "/app/client/certificate",
    "/app/client/hot_fix",
    "/app/client/query_package_list",
    "/app/client/static",
    "/bbs/app/api/at/recent",
    "/bbs/app/api/at/search",
    "/bbs/app/api/emojis/list",
    "/bbs/app/api/general/search/v1",
    "/bbs/app/api/general/search/v1/web",
    "/bbs/app/api/get/forbid_reason",
    "/bbs/app/api/image_editor/advance_typeface/list",
    "/bbs/app/api/image_editor/module/tab_list",
    "/bbs/app/api/image_editor/sticker/list",
    "/bbs/app/api/post_editor/topic_selection/search",
    "/bbs/app/api/post_tools",
    "/bbs/app/api/search/found",
    "/bbs/app/api/search/hot_words",
    "/bbs/app/api/search/main_page/query_promote",
    "/bbs/app/api/search/suggestion/v2",
    "/bbs/app/api/search/topic",
    "/bbs/app/api/search/welcome_page",
    "/bbs/app/api/search/welcome_page/v2",
    "/bbs/app/api/static_resource",
    "/bbs/app/api/typeface",
    "/bbs/app/api/user/permission",
    "/bbs/app/feedback/faq/input_prompt",
    "/bbs/app/feedback/list",
    "/bbs/app/feeds/banner",
    "/bbs/app/hashtag/ranking",
    "/bbs/app/hashtag/search",
    "/bbs/app/hashtag/template/center",
    "/bbs/app/hot_news/main_list",
    "/bbs/app/link/drafts",
    "/bbs/app/link/favour/search",
    "/bbs/app/link/labels",
    "/bbs/app/max/tag_list",
    "/bbs/app/message/fold/list",
    "/bbs/app/message/notify/list",
    "/bbs/app/message/notify/user/rooms_setting",
    "/bbs/app/profile/bbs/comment/list_v2",
    "/bbs/app/profile/fav/folder/v2/links",
    "/bbs/app/profile/fav/folders",
    "/bbs/app/profile/fav/tab_list",
    "/bbs/app/profile/favour/list",
    "/bbs/app/profile/follower/list",
    "/bbs/app/profile/following/list",
    "/bbs/app/profile/following/simple_list",
    "/bbs/app/profile/forbid/history",
    "/bbs/app/profile/history/search",
    "/bbs/app/profile/history/visit",
    "/bbs/app/profile/post/limits",
    "/bbs/app/profile/preference",
    "/bbs/app/profile/privacy/settings",
    "/bbs/app/profile/recommend/following",
    "/bbs/app/profile/relations",
    "/bbs/app/profile/subscribed/events",
    "/bbs/app/story_mode/list",
    "/bbs/app/topic/categories",
    "/bbs/app/topic/list_infos",
    "/bbs/app/topic/search",
    "/bbs/app/topic/sub/categories/v2",
    "/bbs/app/user/discount_message_v2",
    "/bbs/app/user/preference/categories",
    "/bbs/app/user/preference/list",
    "/bbs/app/user/preference/search",
    "/bbs/notify/developer_messages",
    "/bbs/notify/list",
    "/bbs/notify/official_messages/list",
    "/bbs/notify/official_msg_v2/list",
    "/chat/message_setting",
    "/chat/stranger_messages",
    "/debugcenter/ab_test/data",
    "/debugcenter/tips_config/data",
    "/fast_test/get_demand_list",
    "/friend/inter_follow/list",
    "/friend/remark/map",
    "/friend/show_state",
    "/game/all_recommend/game_comments",
    "/game/all_recommend/v2",
    "/game/apex/get_player_leaderboards",
    "/game/comment/share_data",
    "/game/console/get_game_detail",
    "/game/console/switch/cassette/price_history",
    "/game/csgo/5e/get_player_leaderboards",
    "/game/csgo/b5/get_player_leaderboards",
    "/game/csgo/get_player_leaderboards",
    "/game/destiny2/get_player_leaderboards",
    "/game/developers",
    "/game/dota2/player/calendars",
    "/game/dota2/player/career_record",
    "/game/dota2/player/followed_match_list",
    "/game/dota2/player/hero_list",
    "/game/dota2/player/match_list",
    "/game/dota2/player/overview",
    "/game/dota2/player/teammates",
    "/game/epic/free_package_pick_up_failed_reason",
    "/game/game_compilation",
    "/game/get_meta_critic_detail",
    "/game/get_publisher_games",
    "/game/get_similar_games",
    "/game/get_wiki_share_info",
    "/game/header/2669320_it",
    "/game/header/916440_h",
    "/game/match/leagues",
    "/game/mini_app/data",
    "/game/mini_app/main_page",
    "/game/mini_app/menu_info",
    "/game/mini_app/recently_used",
    "/game/mini_app/search",
    "/game/mobile/android/app/white_list",
    "/game/mobile/device/get_list",
    "/game/mobile/get_collection_game_list",
    "/game/mobile/my/game_list",
    "/game/mobile/recommend",
    "/game/ow/achievements",
    "/game/ow/get_player_overview",
    "/game/ow/leaderboards",
    "/game/ow/ow_famous_player",
    "/game/ow/search",
    "/game/owned_game/hot_list",
    "/game/owned_game/menu",
    "/game/popup_window/list",
    "/game/popup_window/user_info",
    "/game/pubg/famous_player_list",
    "/game/pubg/get_player_leaderboards",
    "/game/pubg/get_player_overview",
    "/game/pubg/get_updating_state",
    "/game/pubg/search",
    "/game/pubg/weaspon/mastery/list",
    "/game/r6/get_player_leaderboards",
    "/game/rec_wall",
    "/game/release_calendar/filters",
    "/game/release_calendar/game_count",
    "/game/release_calendar/game_list",
    "/game/search",
    "/game/self_made_game_list/data/infos",
    "/game/speedtest/game_list",
    "/game/speedtest/get_download_url",
    "/game/speedtest/get_ip_location",
    "/game/speedtest/get_platform_list",
    "/game/speedtest/speed_test_rank",
    "/game/speedtest/speed_test_record",
    "/game/steam/comparison",
    "/game/steam/screenshot/list",
    "/game/steam_stats/data_usage",
    "/game/steam_stats/data_usage/map",
    "/game/steam_stats/server_stats",
    "/game/steam_stats/user_count",
    "/game/switch/jp/games/data",
    "/game/switch/other_versions",
    "/game/user_game_block/appid_list",
    "/game/user_game_block/block_game_list",
    "/game/user_game_block/game_list",
    "/game/xbox/v2/game_score_rank",
    "/heybox/open/user/is_certificated",
    "/infra/ip/location/info",
    "/mall/backpack/unusable_items",
    "/mall/backpack/usable_items",
    "/mall/cart/items",
    "/mall/cart/order/detail",
    "/mall/cart/order/get_type",
    "/mall/check_account/steam/prepare",
    "/mall/coupons",
    "/mall/header",
    "/mall/history_free_app",
    "/mall/list",
    "/mall/member/bulletin",
    "/mall/newcomer/notify",
    "/mall/order/cashier/available",
    "/mall/order/detail/v2",
    "/mall/orders",
    "/mall/physical/pca/detail",
    "/mall/physical/user/address",
    "/mall/sales",
    "/mall/search",
    "/mall/steam/wishlist/authorize_term/state",
    "/mall/trade/bargain/order/history",
    "/mall/trade/follows",
    "/mall/trade/home",
    "/mall/trade/list",
    "/mall/trade/order_detail",
    "/mall/trade/orders",
    "/mall/trade/sale/settings",
    "/mall/trade/sell/wait_deliver",
    "/mall/trade/steam_settings",
    "/mall/trade/tips_states",
    "/mall/trade/web/sale_skus",
    "/mall/trade/wechat/data",
    "/store/get_all_active_roll_room",
    "/store/get_order_progress",
    "/store/get_roll_items",
    "/store/hcoin/history",
    "/store/hosts_to_ip",
    "/store/roll/check_in_white_list",
    "/store/whish/list",
    "/task/list_v2",
    "/task/shared",
    "/task/sign_list",
    "/task/sign_v3/get_sign_state",
    "/wiki/get/article/related/link",
    "/wiki/get_wiki_infos",
    "/wiki/ranking",
)

_ROUTE_SET = frozenset(VERIFIED_READ_ROUTES)


def is_verified_read(route: str) -> bool:
    """True when `route` is in the retained historical GET allowlist."""
    return route.rstrip("/") in _ROUTE_SET


def call(client, route: str, *, query: dict | None = None,
         payload: dict | None = None) -> dict:
    """Signed GET against the retained historical allowlist.

    Refuses paths outside the allowlist and all payloads (XhhConfigError).
    Historical success does not prove absence of server-side effects.
    Returns the raw response dict.

        client.call("/account/info")
        client.call("/game/dota2/player/overview", query={"steam_id": "..."})
    """
    if payload is not None:
        raise XhhConfigError("read-only call() does not accept a payload")
    normalized = route.rstrip("/")
    if not is_verified_read(normalized):
        raise XhhConfigError(
            f"route not in the verified read-only snapshot: {route!r}. "
            "Updates require a reviewed package snapshot; private regeneration "
            "is not included in this distribution.")
    return client.transport.signed_request(
        normalized, query=query or None, payload=payload)


CATALOG_SHA256 = "dafd6a63423ea44fc7cd2eb6c1a9ccfddb0b3e07792ef651cf952e2c1d22beea"
ROUTES_SHA256 = "6ac5ce39ec5535cc0e386382b87e330500a3b31078ff84cd13b1abfa56d66483"


def check_snapshot() -> dict:
    """Check the shipped bytes and allowlist, without reading research files."""
    raw = Path(__file__).with_name("api_catalog.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("catalog snapshot SHA-256 mismatch")
    routes = tuple(VERIFIED_READ_ROUTES)
    if hashlib.sha256("\n".join(routes).encode("utf-8")).hexdigest() != ROUTES_SHA256:
        raise ValueError("route allowlist SHA-256 mismatch")
    if routes != tuple(sorted(set(routes))) or set(routes) & set(SAFETY_EXCLUDED):
        raise ValueError("route allowlist must be sorted, unique and exclude unsafe routes")
    catalog = json.loads(raw)
    if [row["route"] for row in catalog["routes"]] != list(routes):
        raise ValueError("catalog routes differ from the runtime allowlist")
    return {"routes": len(routes), "catalog_sha256": CATALOG_SHA256,
            "routes_sha256": ROUTES_SHA256, "scope": "offline_snapshot_integrity_only"}


def _main(argv: list[str]) -> int:
    if argv[1:] == ["--check"]:
        try:
            report = check_snapshot()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"snapshot integrity failed: {exc}", file=sys.stderr)
            return 1
        print(f"snapshot integrity verified: {report['routes']} routes")
        return 0
    print("Only --check is supported. Private research regeneration is not "
          "included; updates require a reviewed package snapshot.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))



"""Stable public facade for external API adapters.

Business modules import API functions from here. Protocol-specific request,
signing, response-normalization, retry, and timeout details live in
``glorybond.integrations``.
"""

from glorybond.integrations.ai import ai_api, ai_function, aliyun_web_search, deepseek_web_search, apimart_images_generate, ark_api, ark_images_generate
from glorybond.integrations.bilibili import BilibiliEsportsAPI, BilibiliVideoAPI, bilibili_esports_get_bytes, bilibili_esports_get_json, bilibili_get_user_card, bilibili_search_users, bilibili_search_videos_by_exact_author, bilibili_search_videos_by_mid
from glorybond.integrations.bili_media import BiliVideoError, download_bili_video, resolve_video_reference
from glorybond.integrations.steam import steam_api_recent_games, steam_api_user_status
from glorybond.integrations.service_health import service_health_http
from glorybond.integrations.qq_profiles import qq_avatar_bytes
from glorybond.integrations.aihot import aihot_latest_daily
from glorybond.integrations.x import x_get_user, x_get_posts, x_get_replies, x_username, x_get_media_bytes
from glorybond.integrations.tianyuanzhiyi import tianyuanzhiyi_hero_avatars_api, tianyuanzhiyi_matchup_api, tianyuanzhiyi_skin_votes_api, tianyuanzhiyi_skin_icons_api, tianyuanzhiyi_tier_api
from glorybond.integrations.wzry import WzryOfficialAPI, wzry_get_official, wzry_battle_image_bytes

__all__ = [
    "BiliVideoError", "download_bili_video", "resolve_video_reference",
    "service_health_http",
    "aihot_latest_daily",
    "x_get_user", "x_get_posts", "x_get_replies", "x_username", "x_get_media_bytes",
    "BilibiliEsportsAPI",
    "BilibiliVideoAPI",
    "WzryOfficialAPI",
    "ai_api",
    "ai_function",
    "aliyun_web_search",
    "deepseek_web_search",
    "apimart_images_generate",
    "ark_api",
    "ark_images_generate",
    "bilibili_esports_get_bytes",
    "bilibili_esports_get_json",
    "bilibili_get_user_card",
    "bilibili_search_users",
    "bilibili_search_videos_by_exact_author",
    "bilibili_search_videos_by_mid",
    "steam_api_recent_games",
    "steam_api_user_status",
    "qq_avatar_bytes",
    "tianyuanzhiyi_hero_avatars_api",
    "tianyuanzhiyi_matchup_api",
    "tianyuanzhiyi_skin_votes_api",
    "tianyuanzhiyi_skin_icons_api",
    "tianyuanzhiyi_tier_api",
    "wzry_get_official",
]

from glorybond.integrations.player_client import PlayerClientAdapter, PlayerClientRateLimited, player_client_artwork_api, player_client_error_info

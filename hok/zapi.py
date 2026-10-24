"""Stable public facade for external API adapters.

Business modules import API functions from here. Protocol-specific request,
signing, response-normalization, retry, and timeout details live in
``hok.api_adapters``.
"""

from .api_adapters.ai import (
    ai_api,
    ai_function,
    aliyun_web_search,
    deepseek_web_search,
    apimart_images_generate,
    ark_api,
    ark_images_generate,
)
from .api_adapters.bilibili import (
    BilibiliEsportsAPI,
    BilibiliVideoAPI,
    bilibili_esports_get_bytes,
    bilibili_esports_get_json,
    bilibili_get_user_card,
    bilibili_search_users,
    bilibili_search_videos_by_exact_author,
    bilibili_search_videos_by_mid,
)
from .api_adapters.steam import steam_api_recent_games, steam_api_user_status
from .api_adapters.service_health import service_health_http
from .api_adapters.qq_profiles import qq_avatar_bytes
from .api_adapters.aihot import aihot_latest_daily
from .api_adapters.x import x_get_user, x_get_posts, x_get_replies, x_username, x_get_media_bytes
from .api_adapters.tianyuanzhiyi import (
    tianyuanzhiyi_hero_avatars_api,
    tianyuanzhiyi_matchup_api,
    tianyuanzhiyi_skin_votes_api,
    tianyuanzhiyi_skin_icons_api,
    tianyuanzhiyi_tier_api,
)
from .api_adapters.wzry import WzryOfficialAPI, wzry_get_official

__all__ = [
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

from .api_adapters.player_client import PlayerClientAdapter, PlayerClientRateLimited

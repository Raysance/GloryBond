"""Hero-name helpers and Tianyuan tier image workflow."""

from .. import zapi, zfile
from ..zstatic import HeroList


def to_pinyin(value):
    from pypinyin import lazy_pinyin

    return "".join(lazy_pinyin(str(value))).lower()


def safe_hero_name(hero_id, default=None):
    if hero_id is None:
        return default or "未知英雄"
    hero_id = str(hero_id)
    return HeroList.get(hero_id, default or f"未知英雄({hero_id})")


def hero_tier_query_process():
    from ..tools.gen_hero_tier import generate_hero_tier_image

    tier_data = zapi.tianyuanzhiyi_tier_api()
    if not isinstance(tier_data, dict) or not tier_data.get("tiers"):
        raise Exception(f"hero_tier_query_error: empty response {tier_data!r}")
    avatar_bytes, missing_items = zfile.load_hero_tier_avatar_cache(
        tier_data["tiers"]
    )
    if missing_items:
        downloaded = zapi.tianyuanzhiyi_hero_avatars_api(missing_items)
        zfile.save_hero_tier_avatar_cache(missing_items, downloaded)
        avatar_bytes.update(downloaded)
    output_path = zfile.hero_tier_image_path()
    generate_hero_tier_image(
        tier_data,
        output_path,
        avatar_bytes=avatar_bytes,
    )
    return output_path

"""Honor-power hero and district resolution workflow."""

import math

from ..zstatic import *


def _zfunc_call(name, *args, **kwargs):
    from .. import zfunc

    return getattr(zfunc, name)(*args, **kwargs)


def _to_pinyin(*args, **kwargs):
    return _zfunc_call("_to_pinyin", *args, **kwargs)


def safe_hero_name(*args, **kwargs):
    return _zfunc_call("safe_hero_name", *args, **kwargs)


def wzry_get_official(*args, **kwargs):
    return _zfunc_call("wzry_get_official", *args, **kwargs)

def _honor_hero_from_query(query_text):
    hero_names = {}
    for hero_id, hero_name in HeroList.items():
        hero_names[hero_name] = hero_id
    for hero_id, hero_name in HeroName_replacements.items():
        hero_names[hero_name] = hero_id

    normalized_query = str(query_text).lower().replace(" ", "")
    for candidate_name in sorted(hero_names, key=len, reverse=True):
        if candidate_name in normalized_query:
            hero_id = hero_names[candidate_name]
            return hero_id, safe_hero_name(hero_id)

    query_pinyin = _to_pinyin(normalized_query)
    for candidate_name in sorted(hero_names, key=len, reverse=True):
        if _to_pinyin(candidate_name) in query_pinyin:
            hero_id = hero_names[candidate_name]
            return hero_id, safe_hero_name(hero_id)
    return None


def _honor_region_name_without_suffix(region_name):
    suffixes = (
        "特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区",
        "自治州", "自治县", "地区", "新区", "省", "市", "区", "县", "盟", "旗",
    )
    for suffix in suffixes:
        if region_name.endswith(suffix) and len(region_name) > len(suffix):
            return region_name[:-len(suffix)]
    return region_name


def _honor_district_entries(district_payload):
    roots = (district_payload.get("data") or {}).get("list") or []
    entries = [{
        "adcode": 156,
        "display_name": "全国",
        "aliases": {"全国", "国服"},
        "depth": 0,
    }]

    def visit(node, full_path, short_path):
        full_name = str(node.get("fullName") or "").strip()
        short_name = str(node.get("shortName") or full_name).strip()
        next_full_path = full_path + ([full_name] if full_name else [])
        next_short_path = short_path + ([short_name] if short_name else [])
        aliases = {full_name, short_name}
        path_variants = [next_full_path, next_short_path]
        for path in path_variants:
            for start_index in range(len(path)):
                suffix_path = path[start_index:]
                aliases.add("".join(suffix_path))
                aliases.add("".join(_honor_region_name_without_suffix(part) for part in suffix_path))
        aliases.add(_honor_region_name_without_suffix(full_name))
        aliases.add(_honor_region_name_without_suffix(short_name))
        entries.append({
            "adcode": int(node["adcode"]),
            "display_name": "".join(next_full_path),
            "aliases": {alias.replace(" ", "") for alias in aliases if len(alias.replace(" ", "")) >= 2},
            "depth": len(next_full_path),
        })
        for child in node.get("list") or []:
            visit(child, next_full_path, next_short_path)

    for root in roots:
        visit(root, [], [])
    return entries


def resolve_honor_district(region_query, district_payload=None):
    from ..zfile import read_honor_districts

    normalized_query = str(region_query or "").replace(" ", "").strip()
    if not normalized_query:
        return None, "缺少地区，请使用：#战力查询 英雄名 地区名"
    if district_payload is None:
        district_payload = read_honor_districts()

    matches = {}
    for entry in _honor_district_entries(district_payload):
        matched_aliases = [alias for alias in entry["aliases"] if alias in normalized_query]
        if not matched_aliases:
            continue
        best_alias = max(matched_aliases, key=len)
        candidate = dict(entry)
        candidate["match_score"] = (entry["depth"], len(best_alias))
        matches[entry["adcode"]] = candidate
    matched_entries = list(matches.values())
    if not matched_entries:
        return None, f"未找到地区：{region_query}"
    best_score = max(entry["match_score"] for entry in matched_entries)
    matched_entries = [entry for entry in matched_entries if entry["match_score"] == best_score]
    if len(matched_entries) > 1:
        choices = "、".join(entry["display_name"] for entry in matched_entries[:5])
        return None, f"地区名称不唯一，请使用完整地区名：{choices}"
    return matched_entries[0], None


def _honor_rank_percentile_points(rank_list):
    valid_ranks = []
    for fallback_rank_no, player_rank in enumerate(rank_list, 1):
        try:
            rank_value = int(player_rank.get("rankValue") or 0)
            rank_no = int(player_rank.get("rankNo") or fallback_rank_no)
        except (TypeError, ValueError):
            continue
        if rank_value > 0:
            valid_ranks.append({"rank_no": rank_no, "rank_value": rank_value})

    if not valid_ranks:
        return []

    points = []
    rank_count = len(valid_ranks)
    for percentage in (0, 25, 50, 100):
        if percentage == 0:
            index = 0
        else:
            index = math.ceil(rank_count * percentage / 100) - 1
        selected = valid_ranks[index]
        points.append({
            "percentage": percentage,
            "rank_no": selected["rank_no"],
            "rank_value": selected["rank_value"],
        })
    return points


def honor_power_query_process(realname, query_text):
    """Query one hero's honor threshold for an arbitrary configured district."""
    hero = _honor_hero_from_query(query_text)
    if not hero:
        return "未识别到英雄，请使用：#战力查询 英雄名 地区名"
    hero_id, hero_name = hero
    district, district_error = resolve_honor_district(query_text)
    if district_error:
        return district_error

    roleid = roleidlist[realname]
    rank_info = wzry_get_official(
        reqtype="honorranklist",
        roleid=roleid,
        heroid=hero_id,
        honor_adcode=district["adcode"],
    )

    rank_points = _honor_rank_percentile_points(rank_info.get("list") or [])
    lines = [f"【{hero_name}战力查询】", line_delim, district["display_name"]]
    if rank_points:
        lines.append(f"榜单人数 {len(rank_info.get('list') or [])}")
        for point in rank_points:
            lines.append(
                f"榜单 {point['percentage']}%  "
                f"第 {point['rank_no']} 名  战力 {point['rank_value']}"
            )
    else:
        lines.append("暂无荣耀排行数据")
    return "\n".join(lines)

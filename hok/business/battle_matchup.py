"""Hero-lineup matchup metrics and optional AI commentary."""

import re

from .. import zapi


def _runtime():
    from .. import zfunc

    return zfunc


def battle_matchup_composition(detail_list):
    composition = {}
    for player in detail_list:
        battle_records = player.get("battleRecords") or {}
        used_hero = battle_records.get("usedHero") or {}
        position = battle_records.get("position")
        hero_id = used_hero.get("heroId")
        try:
            position = int(position)
            hero_id = int(hero_id)
        except (TypeError, ValueError):
            continue
        if 0 <= position <= 4:
            composition[str(position)] = hero_id
    return composition


def hero_matchup_process(my_detail, op_detail, matchup_api=None):
    if matchup_api is None:
        matchup_api = zapi.tianyuanzhiyi_matchup_api
    my_heroes = battle_matchup_composition(my_detail)
    op_heroes = battle_matchup_composition(op_detail)
    if len(my_heroes) + len(op_heroes) < 2:
        return {"winRate": None, "sampleMatches": 0, "queryMode": "unavailable"}
    try:
        exact = matchup_api(my_heroes, op_heroes, days=30)
        exact_matches = int(exact.get("totalMatchesFound") or 0)
        if exact_matches:
            return {
                "winRate": float(exact.get("camp1WinRate") or 0),
                "sampleMatches": exact_matches,
                "queryMode": "exact",
                "queryCount": 1,
            }

        samples = []
        queried_pairs = 0
        for position in sorted(set(my_heroes) & set(op_heroes), key=int):
            queried_pairs += 1
            result = matchup_api(
                {position: my_heroes[position]},
                {position: op_heroes[position]},
                days=30,
            )
            match_count = int(result.get("totalMatchesFound") or 0)
            if match_count:
                samples.append((float(result.get("camp1WinRate") or 0), match_count))
        total_matches = sum(match_count for _, match_count in samples)
        if not total_matches:
            return {"winRate": None, "sampleMatches": 0, "queryMode": "lane_pairs", "queryCount": queried_pairs}
        weighted_rate = sum(rate * match_count for rate, match_count in samples) / total_matches
        return {
            "winRate": weighted_rate,
            "sampleMatches": total_matches,
            "queryMode": "lane_pairs",
            "queryCount": queried_pairs,
        }
    except Exception as error:
        _runtime().log_message(f"TIANYUAN_MATCHUP_ERROR: {repr(error)}")
        return {"winRate": None, "sampleMatches": 0, "queryMode": "error", "error": repr(error)}


_BATTLE_POSITION_NAMES = {
    0: "对抗路",
    1: "中路",
    2: "发育路",
    3: "打野",
    4: "游走",
}


def battle_lineup_items(detail_list):
    items = []
    for player in detail_list:
        battle_records = player.get("battleRecords") or {}
        used_hero = battle_records.get("usedHero") or {}
        try:
            position = int(battle_records.get("position"))
        except (TypeError, ValueError):
            position = -1
        hero_name = used_hero.get("heroName") or _runtime().safe_hero_name(used_hero.get("heroId"))
        items.append({"position": position, "heroName": hero_name})
    return items


def format_battle_lineup_ai_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if len(lines) > 1:
        return "\n".join(lines)
    sentences = [item.strip() for item in re.findall(r"[^。！？!?]+[。！？!?]?", text) if item.strip()]
    return "\n".join(sentences)


def battle_lineup_ai_process(my_lineup, op_lineup, ai_func=None):
    if ai_func is None:
        ai_func = _runtime().ai_parser

    def position_value(item):
        try:
            return int(item.get("position", -1))
        except (TypeError, ValueError):
            return -1

    def format_side(lineup):
        ordered = sorted(lineup, key=position_value)
        return "、".join(
            f"{_BATTLE_POSITION_NAMES.get(position_value(item), '未知分路')}{item.get('heroName') or '未知英雄'}"
            for item in ordered
        )

    context = f"我方：{format_side(my_lineup)}；对方：{format_side(op_lineup)}。"
    try:
        return format_battle_lineup_ai_text(ai_func([context], "battle_lineup"))
    except Exception as error:
        _runtime().log_message(f"BATTLE_LINEUP_AI_ERROR: {repr(error)}")
        return ""

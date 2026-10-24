"""Bounded, readable projections of standalone-client hero statistics."""

from math import isfinite


SCOPE_NAMES = {"all": "全部时间", "season": "本赛季", "year": "本年度"}


def _number(value):
    return value if type(value) in (int, float) and isfinite(value) and value >= 0 else None


def _number_text(value):
    return "—" if value is None else f"{value:,.0f}"


def hero_report(label, result, settings, hero_names):
    """Select by 5v5 games before rendering; never carry raw protocol fields."""
    heroes = result["heroes"]
    limit = max(1, min(20, int(settings["display_hero_limit"])))
    ordered = sorted(heroes, key=lambda row: (-(_number(row.get("games")) or 0), int(row["hero_id"])))
    rows = []
    for hero in ordered[:limit]:
        hero_id = str(hero["hero_id"])
        row = {key: _number(hero.get(key)) for key in (
            "games", "wins", "losses", "win_rate_percent", "fight_value", "highest_fight_value")}
        if not row["games"] or row["win_rate_percent"] is None or row["win_rate_percent"] > 100:
            row["win_rate_percent"] = None
        row.update(hero_id=hero_id, name=str(hero_names.get(hero_id) or hero.get("name") or f"英雄{hero_id}"))
        rows.append(row)
    scope = SCOPE_NAMES.get(result.get("scope"), "当前范围")
    summary = f"{label} · {scope}英雄\n5v5 · 按场次降序，展示 {len(rows)}/{len(heroes)} 个返回英雄。"
    hint = "查看单个英雄：#客户端 英雄详情 我 英雄名（将“我”替换为要查询的玩家）"
    text_rows = []
    for index, row in enumerate(rows, 1):
        rate = "—" if row["win_rate_percent"] is None else f"{row['win_rate_percent']:.1f}%"
        text_rows.append(f"{index}. {row['name']}：{_number_text(row['games'])}场，胜率{rate}，"
                         f"当前战力{_number_text(row['fight_value'])}，历史最高{_number_text(row['highest_fight_value'])}")
    text = "\n".join([summary, *text_rows, hint] if rows else [summary, "当前范围没有返回英雄数据。"])
    return {"label": str(label), "scope": scope, "rows": rows, "total": len(heroes),
            "summary": summary, "hint": hint, "text": text}

"""Whitelisted display models for the three in-game reference layouts."""

from .player_client import _number, _text

SCOPE_LABELS = {"season": "当前赛季", "year": "当前赛年", "all": "全部比赛"}
BRANCH_LABELS = {None: "全部", "top": "对抗路", "mid": "中路", "bot": "发育路", "jungle": "打野", "assist": "游走"}
MODE_LABELS = {"all": "所有游戏", "ranked": "5v5/排位赛", "matchmaking": "5v5/匹配", "peak": "巅峰赛", "entertainment": "娱乐模式"}
RADAR_KEYS = ("output", "kda", "development", "teamfight", "survival")
BADGE_TYPES = (1, 2, 3, 5, 4)


def radar_model(display):
    radar = (display or {}).get("radar") or {}
    values = radar.get("plot_ratios") or {}
    ratios = {key: _number(values.get(key)) for key in RADAR_KEYS}
    return ratios if all(value is not None and value <= 1 for value in ratios.values()) else None


def year_labels_model(data):
    if not isinstance(data, dict):
        return None
    return [_text(row.get("name")) or None for row in data.get("in_use", [])][:3]


def rank_model(data):
    if not isinstance(data, dict):
        return None
    ranked = data.get("ranked")
    if ranked not in (True, False):
        return None
    rank = _number(data.get("rank"))
    return {"ranked": ranked, "rank": rank, "title_type": data.get("title_type"),
            "text": (f"第{int(rank)}名" if rank is not None else "—") if ranked else "暂无排名"}


def branch_models(data):
    if not isinstance(data, dict) or data.get("by_score") is None:
        return None
    return [{"branch": row["branch"], "text": _text(row.get("text")) or None}
            for row in data["by_score"] if row.get("branch") in BRANCH_LABELS][:2]


def screen_report(kind, label, result, hero_names):
    # display has its own native denominators and must not be mixed with raw summary rows.
    display = result.get("display")
    source = display if isinstance(display, dict) else result
    values = {key: _number(source.get(key)) for key in (
        "games", "wins", "losses", "win_rate_percent", "mvp", "losing_mvp", "triple_kills",
        "quadra_kills", "penta_kills", "legendary")}
    values["highest_fight_value"] = _number(result.get("highest_fight_value"))
    if values["win_rate_percent"] is not None and values["win_rate_percent"] > 100:
        values["win_rate_percent"] = None
    if not isinstance(display, dict) and not values["games"]:
        values["win_rate_percent"] = None
    values["score"] = _number((display or {}).get("composite_score"))
    # Hero medal/MVP counts are separate native honor fields, not part of hero display.
    medals = (source if kind == "game" else result).get("medals") or {}
    values["medals"] = {key: _number(medals.get(key)) for key in ("top", "gold", "silver", "bronze")}
    if kind == "hero":
        values["mvp"] = _number(result.get("mvp"))
        values["losing_mvp"] = _number(result.get("losing_mvp"))
    values["radar"] = radar_model(display)
    scope = SCOPE_LABELS.get(result.get("scope"), "当前范围")
    hero_id = str(result.get("hero_id", ""))
    name = hero_names.get(hero_id, result.get("hero_name") or "未知英雄")
    title = name if kind == "hero" else "对战资料"
    missing = []
    for key, description in (("score", "综合得分"), ("radar", "雷达图"), ("games", "场次"),
                             ("win_rate_percent", "胜率"), ("mvp", "MVP")):
        if values[key] is None:
            missing.append(description)
    if any(value is None for value in values["medals"].values()):
        missing.append("部分奖牌计数")
    year_labels = year_labels_model(result.get("year_labels"))
    historical = result.get("historical_badges")
    by_type = {row["title_type"]: row for row in historical} if isinstance(historical, list) else {}
    badge_counts = [_number(by_type.get(key, {}).get("count")) for key in BADGE_TYPES]
    rank = rank_model(result.get("rank_badge"))
    if kind == "hero":
        if year_labels is None or any(value is None for value in year_labels):
            missing.append("赛年标签")
        if any(value is None for value in badge_counts):
            missing.append("历史徽章")
        if rank is None:
            missing.append("历史称号排名")
    notice = "暂缺：" + "、".join(missing) + "。" if missing else ""
    return {"kind": kind, "label": str(label), "title": title, "hero_id": hero_id,
            "scope": scope, "mode": MODE_LABELS.get(result.get("mode"), "全部比赛"),
            "branch": result.get("branch"), "values": values, "notice": notice,
            "year_labels": year_labels, "historical_badges": badge_counts, "rank_badge": rank,
            "text": f"{label} · {title} · {scope} · {BRANCH_LABELS.get(result.get('branch'), '全部')}" + ("\n" + notice if notice else "")}

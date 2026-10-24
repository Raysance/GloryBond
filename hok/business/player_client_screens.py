"""Whitelisted display models for the three in-game reference layouts."""

from .player_client import _number

SCOPE_LABELS = {"season": "当前赛季", "year": "当前赛年", "all": "全部比赛"}
BRANCH_LABELS = {None: "全部", "top": "对抗路", "mid": "中路", "bot": "发育路", "jungle": "打野", "assist": "游走"}
MODE_LABELS = {"all": "所有游戏", "ranked": "5v5/排位赛", "matchmaking": "5v5/匹配", "peak": "巅峰赛", "entertainment": "娱乐模式"}


def screen_report(kind, label, result, hero_names):
    values = {key: _number(result.get(key)) for key in (
        "games", "wins", "losses", "win_rate_percent", "mvp", "losing_mvp", "triple_kills",
        "quadra_kills", "penta_kills", "legendary", "highest_fight_value")}
    if not values["games"] or values["win_rate_percent"] is None or values["win_rate_percent"] > 100:
        values["win_rate_percent"] = None
    values["score"] = _number(result.get("display_score")) if kind == "hero" else None
    medals = result.get("medals") or {}
    values["medals"] = {key: _number(medals.get(key)) for key in ("top", "gold", "silver", "bronze")}
    scope = SCOPE_LABELS.get(result.get("scope"), "当前范围")
    hero_id = str(result.get("hero_id", ""))
    name = hero_names.get(hero_id, result.get("hero_name") or "未知英雄")
    title = name if kind == "hero" else "对战资料"
    missing = ["雷达图", "赛年标签、徽章图标及分路段位"]
    if values["score"] is None:
        missing.append("综合得分")
    for key, description in (("games", "场次"), ("win_rate_percent", "胜率"), ("mvp", "MVP")):
        if values[key] is None:
            missing.append(description)
    if any(value is None for value in values["medals"].values()):
        missing.append("部分奖牌计数")
    notice = "暂缺：" + "、".join(missing) + "。"
    if result.get("notice"):
        notice += result["notice"] + "。"
    if kind == "hero":
        notice += "插画使用默认形象。"
    return {"kind": kind, "label": str(label), "title": title, "hero_id": hero_id,
            "scope": scope, "mode": MODE_LABELS.get(result.get("mode"), "全部比赛"),
            "branch": result.get("branch"), "values": values, "notice": notice,
            "text": f"{label} · {title} · {scope} · {BRANCH_LABELS.get(result.get('branch'), '全部')}\n{notice}"}

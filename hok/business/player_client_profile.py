"""Whitelisted profile-card facts from one official-client profile response."""

from .player_client import _at, _number, _number_text, _text
from .player_client_screens import BRANCH_LABELS, screen_report
from .player_client_details import statistics_details, hero_details


def profile_report(label, result):
    profile = result.get("profile") or {}
    statistics = screen_report("game", label, result.get("statistics") or {}, {})
    values = {key: _number(profile.get(field)) for key, field in (
        ("level", "dwPvpLevel"), ("credit", "dwCreditValue"),
        ("achievement", "dwAchieveMentScore"), ("popularity", "ullPopularity"),
        ("king_marks", "dwWangZheCnt"))}
    for key, field in (("heroes", "dwTotalHeroNum"), ("skins", "dwTotalSkinNum")):
        values[key] = _number(_at(profile, "stMostUsedHero", field))
    peak = profile.get("stMasterMatchData") or {}
    values["peak"] = [_number(peak.get(field)) for field in (
        "iMasterMatchScore", "iMaxSeasonMasterMatchScore", "iMaxHistoryMasterMatchScore")]
    branches = {row["branch"]: row for row in (result.get("branches") or {}).get("branches") or []
                if isinstance(row, dict) and row.get("branch") in BRANCH_LABELS}
    branch_rows = [{"name": BRANCH_LABELS[key], "level": _number(branches.get(key, {}).get("level"))}
                   for key in ("top", "mid", "bot", "jungle", "assist")]
    name = _text(profile.get("szAcntName")) or "—"
    signature = _text(profile.get("szSignatureInfo"))
    summary = statistics["values"]
    rate = "—" if summary["win_rate_percent"] is None else f"{summary['win_rate_percent']:.1f}%"
    text = (f"{name} · 个人资料\n等级 {_number_text(values['level'])} · 信誉 {_number_text(values['credit'])}\n"
            f"英雄 {_number_text(values['heroes'])} · 皮肤 {_number_text(values['skins'])}\n"
            f"本赛季 {_number_text(summary['games'])} 场 · 胜率 {rate}\n"
            f"巅峰积分 {_number_text(values['peak'][0])}")
    return {"kind": "profile", "label": str(label), "name": name, "signature": signature,
            "title": "个人资料", "values": values, "statistics": summary,
            "branches": branch_rows, "text": text,
            "detail_sections": statistics_details(summary, result.get("statistics") or {})}


def statistics_report(label, result):
    label = _text(result.get("player_name")) or "—"
    report = screen_report("game", label, result, {})
    report["branch_label"] = "全部分路" if report["branch"] is None else BRANCH_LABELS[report["branch"]]
    report["detail_sections"] = statistics_details(report["values"], result)
    # The card carries its scope and filters; delivery adds no explanatory copy.
    title = f"{label} · {report['scope']} · {BRANCH_LABELS[report['branch']]}"
    values = report["values"]
    rate = "—" if values["win_rate_percent"] is None else f"{values['win_rate_percent']:.1f}%"
    report["text"] = (f"{title}\n{report['mode']}\n场次 {_number_text(values['games'])} · 胜率 {rate}\n"
                      f"综合得分 {'—' if values['score'] is None else format(values['score'], '.1f')}")
    return report


def hero_summary_report(result, hero_names, *, district_names=None):
    name = _text(result.get("player_name")) or "—"
    report = screen_report("hero", name, result, hero_names, district_names=district_names)
    report["branch_label"] = report["title"]
    counts = report["historical_badges"]
    report["honor_count"] = sum(counts) if all(value is not None for value in counts) else None
    report["detail_sections"] = hero_details(report["values"], result, district_names)
    values = report["values"]
    rate = "—" if values["win_rate_percent"] is None else f"{values['win_rate_percent']:.1f}%"
    report["text"] = (f"{name} · {report['title']} · {report['scope']}\n"
                      f"场次 {_number_text(values['games'])} · 胜率 {rate}\n"
                      f"综合得分 {'—' if values['score'] is None else format(values['score'], '.1f')}\n"
                      f"最高战力 {_number_text(values['highest_fight_value'])}\n"
                      f"历史称号 {(report['rank_badge'] or {}).get('text') or '—'}")
    return report

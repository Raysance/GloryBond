"""Whitelisted profile-card facts from one official-client profile response."""

from .player_client import _at, _number, _number_text, _text
from .player_client_screens import BRANCH_LABELS, screen_report


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
    name = _text(profile.get("szAcntName")) or str(label)
    signature = _text(profile.get("szSignatureInfo"))
    summary = statistics["values"]
    rate = "—" if summary["win_rate_percent"] is None else f"{summary['win_rate_percent']:.1f}%"
    text = (f"{name} · 个人资料\n等级 {_number_text(values['level'])} · 信誉 {_number_text(values['credit'])}\n"
            f"英雄 {_number_text(values['heroes'])} · 皮肤 {_number_text(values['skins'])}\n"
            f"本赛季 {_number_text(summary['games'])} 场 · 胜率 {rate}\n"
            f"巅峰积分 {_number_text(values['peak'][0])}")
    return {"kind": "profile", "label": str(label), "name": name, "signature": signature,
            "title": "个人资料", "values": values, "statistics": summary,
            "branches": branch_rows, "text": text}


def statistics_report(label, result):
    report = screen_report("game", label, result, {})
    report["branch_label"] = "全部分路" if report["branch"] is None else BRANCH_LABELS[report["branch"]]
    # The card carries its scope and filters; delivery adds no explanatory copy.
    title = f"{label} · {report['scope']} · {BRANCH_LABELS[report['branch']]}"
    values = report["values"]
    rate = "—" if values["win_rate_percent"] is None else f"{values['win_rate_percent']:.1f}%"
    report["text"] = (f"{title}\n{report['mode']}\n场次 {_number_text(values['games'])} · 胜率 {rate}\n"
                      f"综合得分 {'—' if values['score'] is None else format(values['score'], '.1f')}")
    return report

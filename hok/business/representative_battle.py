"""Representative-battle selection and query workflows."""

import traceback

from ..zstatic import representative_battle_rules
from ..zutil import log_message

def _build_representative_battle_text(best_battle, title_date):
    result_emoji = "🏆" if best_battle.get("Result") == "胜利" else "🏳️"
    lines = [
        f"【{title_date}代表性对局】",
        f"{best_battle['RepresentativeCategory']} {best_battle['RepScore']}/100",
        (
            f"{best_battle['nickname']} {best_battle['HeroName']} "
            f"{best_battle['Kill']}/{best_battle['Dead']}/{best_battle['Assist']} "
            f"{best_battle['MapName']} {result_emoji}"
        ),
    ]
    tags = "".join(best_battle.get("RawTags") or [])
    if tags:
        lines.append(tags)
    return "\n".join(lines)


def get_daily_representative_battle(target_date=None, candidates_only=False):
    """Select the day's most representative battle with a transparent score."""
    from .. import zfunc as _zfunc
    from ..ztime import time_sul
    from ..zfile import read_history_date
    from ..tools.representative_battle import ranking_key
    from ..tools.representative_battle import score_candidate
    from ..tools.representative_battle import validate_candidate

    use_today_title = target_date is None
    if target_date is None:
        target_date = time_sul().strftime("%Y-%m-%d")

    gameinfo = read_history_date(target_date)

    if not gameinfo:
        return [] if candidates_only else None

    candidates_by_game = {}
    candidate_perspectives = []
    filter_summary = {
        "scanned": 0,
        "official_map_rejected": 0,
        "rule_rejected": 0,
        "duplicate_perspectives": 0,
        "detail_available": 0,
    }

    for player_data in gameinfo:
        realname = player_data.get("key")
        nick = player_data.get("nickname", realname)
        details = player_data.get("details", [])
        roleid = player_data.get("roleid")
        for btl in details:
            filter_summary["scanned"] += 1
            if not _zfunc.check_btl_official_with_matching(btl.get("MapName", "")):
                filter_summary["official_map_rejected"] += 1
                continue

            eligible, rejected_reasons = validate_candidate(btl, representative_battle_rules)
            if not eligible:
                filter_summary["rule_rejected"] += 1
                continue

            gameseq = btl.get("GameSeq")
            try:
                battle_detail = _zfunc.fetch_battle(gameseq, roleid)
            except Exception:
                battle_detail = None

            scored = score_candidate(
                battle=btl,
                detail=battle_detail,
                roleid=roleid,
                rules=representative_battle_rules,
            )
            if scored["has_detail"]:
                filter_summary["detail_available"] += 1

            detail_factors = [item for item in scored["breakdown"] if item["source"] == "详情JSON"]
            detail_reason = detail_factors[0]["condition"] if detail_factors else ""

            btl_info = {
                "realname": realname,
                "nickname": nick,
                "roleid": roleid,
                "HeroName": btl.get("HeroName"),
                "Result": btl.get("Result"),
                "Grade": btl.get("GameGrade", 0),
                "Kill": btl.get("KillCnt", 0),
                "Dead": btl.get("DeadCnt", 0),
                "Assist": btl.get("AssistCnt", 0),
                "MapName": btl.get("MapName"),
                "GameSeq": gameseq,
                "GameTimeTimestamp": btl.get("GameTime_Timestamp", 0),
                "Duration": btl.get("Duration_Second", 0),
                "Others": btl.get("Others", ""),
                "Params": btl.get("Params") or {},
                "DetailReason": detail_reason,
                "Tags": "".join(scored["tags"][:3]),
                "RepScore": scored["score"],
                "RawTags": scored["tags"],
                "ScoreBreakdown": scored["breakdown"],
                "RepresentativeCategory": scored["representative_category"],
                "CategoryScores": scored["category_scores"],
                "CategoryBreakdowns": scored["category_breakdowns"],
                "DetailMetrics": scored["detail_metrics"],
                "HasDetail": scored["has_detail"],
                "RuleVersion": representative_battle_rules.get("version"),
                "RejectedReasons": rejected_reasons,
            }
            candidate_perspectives.append(btl_info)

            existing = candidates_by_game.get(str(gameseq))
            if existing:
                filter_summary["duplicate_perspectives"] += 1
            if not existing or ranking_key(btl_info) > ranking_key(existing):
                candidates_by_game[str(gameseq)] = btl_info

    if candidates_only:
        return candidate_perspectives

    all_battles = list(candidates_by_game.values())
    if not all_battles:
        return None

    all_battles.sort(key=ranking_key, reverse=True)
    best_btl = all_battles[0]
    filter_summary["eligible_unique_battles"] = len(all_battles)
    best_btl["FilterSummary"] = filter_summary
    best_btl["RankingKey"] = list(ranking_key(best_btl))

    title_date = "今日" if use_today_title else target_date
    match_info = _build_representative_battle_text(best_btl, title_date)

    btl_img = None
    try:
        params = best_btl.get("Params") or {}
        _, btl_img, _ = _zfunc.btldetail_process(
            gameSvrId=params.get("gameSvrId", 0),
            relaySvrId=params.get("relaySvrId", 0),
            gameseq=best_btl["GameSeq"],
            pvptype=params.get("pvptype", 0),
            roleid=best_btl["roleid"],
            gen_image=True,
        )
    except Exception:
        log_message(f"GET_REP_BATTLE_DETAIL_ERROR: {traceback.format_exc()}")

    best_btl["AiCommentary"] = None
    try:
        enriched = _zfunc.ai_parser([match_info], "best_battle")
        if enriched and "Error" not in enriched:
            best_btl["AiCommentary"] = enriched
    except Exception:
        pass
    return match_info, btl_img, best_btl


def representative_battle_query_impl(query_text):
    """Return the public representative-battle payload without debug details."""
    from ..ztime import parse_representative_battle_date

    target_date = parse_representative_battle_date(query_text)
    from .. import zfunc as _zfunc

    representative_result = _zfunc.get_daily_representative_battle(target_date=target_date)
    if not representative_result:
        return {
            "target_date": target_date,
            "found": False,
            "text": None,
            "image_path": None,
        }
    if not isinstance(representative_result, (list, tuple)) or len(representative_result) < 2:
        raise Exception(
            "representative_battle_query_impl_error: "
            f"target_date={target_date} result={representative_result!r}"
        )
    return {
        "target_date": target_date,
        "found": True,
        "text": representative_result[0],
        "image_path": representative_result[1],
        "commentary": representative_result[2].get("AiCommentary"),
    }


def _build_representative_category_leader_text(category_label, candidate):
    result_emoji = "🏆" if candidate.get("Result") == "胜利" else "🏳️"
    category_score = (candidate.get("CategoryScores") or {}).get(category_label, 0)
    return (
        f"{category_label} {category_score}/100\n"
        f"{candidate.get('nickname') or '未知玩家'} "
        f"{candidate.get('HeroName') or '未知英雄'} "
        f"{candidate.get('Kill', 0)}/{candidate.get('Dead', 0)}/{candidate.get('Assist', 0)} "
        f"{candidate.get('MapName') or '未知地图'} {result_emoji}"
    )


def get_representative_battle_category_leaders(target_date):
    """Return the top battle perspective for each category without rich output."""
    from ..tools.representative_battle import category_ranking_key

    from .. import zfunc as _zfunc

    candidates = _zfunc.get_daily_representative_battle(target_date=target_date, candidates_only=True)
    if not candidates:
        return []

    category_labels = [
        representative_battle_rules["categories"][category_key]["label"]
        for category_key in ("good", "bad", "extreme")
    ]
    leaders = []
    for category_label in category_labels:
        candidates_by_game = {}
        for candidate in candidates:
            game_key = str(candidate.get("GameSeq"))
            existing = candidates_by_game.get(game_key)
            if (
                existing is None
                or category_ranking_key(candidate, category_label)
                > category_ranking_key(existing, category_label)
            ):
                candidates_by_game[game_key] = candidate
        leader = max(
            candidates_by_game.values(),
            key=lambda candidate: category_ranking_key(candidate, category_label),
        )
        leaders.append({
            "category": category_label,
            "score": (leader.get("CategoryScores") or {}).get(category_label, 0),
            "candidate": leader,
            "text": _build_representative_category_leader_text(category_label, leader),
        })
    return leaders


def representative_battle_range_debug_impl(query_text):
    """Build a text-only three-category leader report for an inclusive date range."""
    from ..ztime import inclusive_date_strings
    from ..ztime import parse_representative_battle_date_range

    start_date, end_date = parse_representative_battle_date_range(query_text)
    day_reports = []
    for target_date in inclusive_date_strings(start_date, end_date):
        from .. import zfunc as _zfunc
        leaders = _zfunc.get_representative_battle_category_leaders(target_date)
        if leaders:
            day_text = f"【{target_date}】\n" + "\n".join(leader["text"] for leader in leaders)
        else:
            day_text = f"【{target_date}】\n暂无对局"
        day_reports.append(day_text)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "day_reports": day_reports,
    }

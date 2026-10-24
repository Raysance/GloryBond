"""Normalize client-only matches into the existing battle-list persistence contract."""

import hashlib

from .. import ztime


def client_battles(result, player, settings):
    """An exact UID/world match is mandatory; nicknames never establish identity."""
    rows, seen = [], set()
    for match in result.get("matches", []):
        own = [p for p in match.get("players", []) if
               str(p.get("uid")) == str(player["uid"]) and
               str(p.get("logic_world_id")) == str(player["logic_world_id"])]
        if len(own) != 1:
            continue
        own = own[0]
        start, duration = match.get("start_time"), match.get("duration_seconds")
        if type(start) is not int or start <= 0 or type(duration) is not int or duration < 0:
            continue
        identity = (match.get("desk_id"), match.get("desk_sequence"), start, match.get("map_id"))
        if identity in seen:
            continue
        seen.add(identity)
        # Negative, stable int64 IDs cannot collide with the camp's positive game sequences.
        sequence = -(int.from_bytes(hashlib.blake2b(repr(identity).encode(), digest_size=8).digest(), "big") % (2**63-1) or 1)
        end = start + duration
        camp, winning = own.get("camp"), match.get("winning_camp")
        outcome = 1 if camp and winning and camp == winning else 2 if camp and winning else 0
        missing = [name for name, value in (("评分", None), ("段位变化", None),
                   ("击杀", own.get("kills")), ("死亡", own.get("deaths")), ("助攻", own.get("assists"))) if value is None]
        rows.append(dict(gameSeq=sequence, dtEventTime=str(end),
            gametime=ztime.epoch_to_text(end, "%H:%M", "Asia/Shanghai"),
            heroId=own.get("hero_id"), heroIcon=settings["hero_avatar_url_template"].format(hero_id=own.get("hero_id", 0)),
            mapName={"ranked": "排位赛", "matchmaking": "匹配赛", "peak": "巅峰赛"}.get(
                match.get("mode"), match.get("mode_name") or "其他模式"),
            killcnt=own.get("kills") or 0, deadcnt=own.get("deaths") or 0, assistcnt=own.get("assists") or 0,
            gameresult=outcome, gradeGame=0, gradeMissing=True, usedTime=duration,
            roleJobName="", stars=-1, newMasterMatchScore=-1, oldMasterMatchScore=-1,
            detailUrl="", clientOnly=True, clientMatch=match, clientMissing=missing,
            clientDeskSequence=match.get("desk_sequence"), clientStartTime=start,
            selectedSkillIds=own.get("selected_skill_ids"), AcntCamp=camp,
            teamNum=own.get("premade_size"), mvpcnt=0, losemvp=0,
            skill={}, evaluateUrl="", evaluateUrlV2="", evaluateUrlV3="", mvpUrlV3=""))
    return rows


def merge_battles(camp, client, *, tolerance_seconds):
    """Keep camp originals intact; use a unique strict fallback for differing IDs."""
    rows = [dict(row) for row in camp]
    added = 0
    for candidate in client:
        duplicates = [row for row in rows if
            str(row.get("gameSeq")) == str(candidate["gameSeq"]) or
            (not row.get("clientOnly") and str(row.get("gameSeq")) == str(candidate.get("clientDeskSequence"))
             and str(row.get("heroId")) == str(candidate.get("heroId"))
             and abs(int(row["dtEventTime"]) - int(candidate["dtEventTime"])) <= tolerance_seconds)]
        if not duplicates:
            duplicates = [row for row in rows if not row.get("clientOnly") and
                str(row.get("heroId")) == str(candidate.get("heroId")) and
                all(row.get(k) == candidate.get(k) for k in ("killcnt", "deadcnt", "assistcnt")) and
                abs(int(row.get("usedTime", 0)) - candidate["usedTime"]) <= tolerance_seconds and
                abs(int(row["dtEventTime"]) - int(candidate["dtEventTime"])) <= tolerance_seconds]
        if len(duplicates) == 1:
            duplicates[0]["clientMatch"] = candidate["clientMatch"]
            duplicates[0]["sources"] = ["camp", "player_client"]
        else:
            rows.append(candidate)
            added += 1
    return sorted(rows, key=lambda row: int(row["dtEventTime"]), reverse=True), added

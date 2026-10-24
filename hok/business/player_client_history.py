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
            clientPlayer={"uid": str(player["uid"]), "logic_world_id": player["logic_world_id"]},
            clientDeskSequence=match.get("desk_sequence"), clientStartTime=start,
            selectedSkillIds=own.get("selected_skill_ids"), AcntCamp=camp,
            teamNum=own.get("premade_size"), mvpcnt=0, losemvp=0,
            skill={}, evaluateUrl="", evaluateUrlV2="", evaluateUrlV3="", mvpUrlV3=""))
    return rows


def camp_battle_detail(row, player, *, roleid, userid, identities, hero_names, settings):
    """Project available client fields into the camp detail contract without mixing IDs."""
    if roleid is None or userid is None:
        raise ValueError("camp target identity is unavailable")
    match = row["clientMatch"]
    target = (str(player["uid"]), str(player["logic_world_id"]))
    players = match.get("players", [])
    own = [p for p in players if (str(p.get("uid")), str(p.get("logic_world_id"))) == target]
    if len(own) != 1:
        raise ValueError("client battle target identity is not unique")
    roles = []
    for item in players:
        identity = (str(item.get("uid")), str(item.get("logic_world_id")))
        known = {"role_id": roleid, "user_id": userid} if identity == target else identities.get(identity, {})
        hero_id = item.get("hero_id")
        stats = {dest: item.get(source) for dest, source in {
            "killCnt": "kills", "deadCnt": "deaths", "assistCnt": "assists", "money": "gold",
            "heroLevel": "hero_level", "totalHeroHurtCnt": "hero_damage", "totalHurtCnt": "enemy_damage",
            "totalBeheroHurtCnt": "damage_taken_from_enemies", "totalBehurtCnt": "total_damage_taken_raw",
            "healCnt": "healing", "buildingDamage": "tower_damage", "monsterCoin": "monster_gold",
            "killSoldier": "last_hits"}.items()}
        stats.update(gradeGame=None, mvp=None, nativeScore=item.get("score_raw"),
                     nativeNewScore=item.get("new_score_raw"), nativeControl=item.get("control_raw"),
                     honorFlags=item.get("honor_flags"))
        participation = item.get("panels", {}).get("team", {}).get("participation", {}).get("ratio")
        stats["joinGamePercent"] = participation
        equipment = [{"equipId": e["dwEquipID"], "count": e.get("bCnt"), "equipName": "", "equipIcon": ""}
                     for e in item.get("equipment") or [] if isinstance(e, dict) and e.get("dwEquipID")]
        roles.append({"basicInfo": {"roleId": str(known["role_id"]) if known.get("role_id") else None,
                "userId": str(known["user_id"]) if known.get("user_id") else None,
                "roleName": item.get("name") or "未知玩家", "roleIcon": "", "acntCamp": item.get("camp"),
                "clientUid": str(item.get("uid")), "clientWorldId": item.get("logic_world_id"),
                "isMe": identity == target},
            "battleStats": stats,
            "battleRecords": {"usedHero": {"heroId": hero_id,
                "heroName": hero_names.get(str(hero_id)) or item.get("hero_name") or "未知英雄",
                "heroIcon": settings["hero_avatar_url_template"].format(hero_id=hero_id)},
                "usedSkin": {}, "finalEquips": equipment, "skill": {},
                "selectedSkillIds": item.get("selected_skill_ids")},
            "heroBehavior": {}, "dataBehavior": []})

    def team(camp):
        members = [p["battleStats"] for p in roles if p["basicInfo"]["acntCamp"] == camp]
        totals = {key: sum(p[key] for p in members) if members and all(p[key] is not None for p in members)
                  else None for key in ("killCnt", "deadCnt", "assistCnt", "money")}
        return {**totals, "acntCamp": camp, "gameResult": match.get("winning_camp") == camp
                if match.get("winning_camp") in (1, 2) else None,
                "banHeros": [], "pickHeros": [], "moneyTrend": []}

    owner = next(p for p in roles if p["basicInfo"]["isMe"])
    basic, stats = owner["basicInfo"], owner["battleStats"]
    start, duration = match["start_time"], match["duration_seconds"]
    return {"source": "player_client", "gameSeq": str(row["gameSeq"]),
        "head": {**{key: basic[key] for key in ("roleId", "userId", "roleName", "roleIcon", "acntCamp")},
            **{key: stats[key] for key in ("killCnt", "deadCnt", "assistCnt", "gradeGame")},
            "heroId": own[0].get("hero_id"), "heroName": owner["battleRecords"]["usedHero"]["heroName"],
            "mapName": row["mapName"], "gameResult": row["gameresult"] == 1 if row["gameresult"] else None},
        "battle": {"gameType": match.get("game_type"), "mapName": row["mapName"], "usedTime": duration,
            "startTime": ztime.epoch_to_text(start, "%m-%d %H:%M", "Asia/Shanghai"),
            "dtEventTime": ztime.epoch_to_text(start + duration, "%m-%d %H:%M", "Asia/Shanghai")},
        "redTeam": team(2), "blueTeam": team(1),
        "redRoles": [p for p in roles if p["basicInfo"]["acntCamp"] == 2],
        "blueRoles": [p for p in roles if p["basicInfo"]["acntCamp"] == 1],
        "otherRoles": [p for p in roles if p["basicInfo"]["acntCamp"] not in (1, 2)]}


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

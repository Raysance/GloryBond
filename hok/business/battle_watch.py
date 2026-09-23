"""Strict watch-battle response conversion."""


def _required_int(value, field_name):
    if value is None:
        raise ValueError(f"missing required field: {field_name}")
    return int(value)


def _camp_from_detail_url(url):
    if not isinstance(url, str) or "?" not in url:
        raise ValueError("missing required field: battleInfo.battleDetailUrl")
    query = url.split("?", 1)[1]
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = value
    if "acntCamp" not in params:
        raise ValueError("missing required field: acntCamp in battleDetailUrl")
    return int(params["acntCamp"])


def _is_authorized(raw_player):
    role_id = _required_int(raw_player["roleId"], "roleId")
    user_id = _required_int(raw_player["userId"], "userId")
    role_name = raw_player["roleInfo"]["roleName"]
    return role_id != 0 and user_id != 0 and role_name != "未授权游戏信息"


def _convert_player(raw_player):
    return {
        "basicInfo": {
            "roleId": _required_int(raw_player["roleId"], "roleId"),
            "userId": _required_int(raw_player["userId"], "userId"),
            "roleName": raw_player["roleInfo"]["roleName"],
            "isGameAuth": _is_authorized(raw_player),
        },
        "heroBehavior": {
            "winNum": _required_int(raw_player["win"], "win"),
            "loseNum": _required_int(raw_player["lost"], "lost"),
            "avgScore": "8.0",
            "winRate": raw_player["winRate"],
        },
        "battleRecords": {
            "usedHero": {
                "heroName": raw_player["heroName"],
                "heroIcon": raw_player["heroIcon"],
            }
        },
        "battleStats": {
            "fightPower": _required_int(
                raw_player["heroFightValue"],
                "heroFightValue",
            ),
        },
    }


def watchbattleinfo_to_coplayer_res(watchbattle_json, roleid=None, game_result=None):
    if not isinstance(watchbattle_json, dict):
        raise TypeError("watchbattle_json must be dict")

    source = (
        watchbattle_json["data"]
        if "data" in watchbattle_json
        else watchbattle_json
    )
    battle_info = source["battleInfo"] if "battleInfo" in source else source
    if not isinstance(battle_info, dict):
        raise TypeError("battle_info must be dict")

    camp1 = battle_info["camp1"]
    camp2 = battle_info["camp2"]
    red_roles = [_convert_player(player) for player in camp1]
    blue_roles = [_convert_player(player) for player in camp2]
    target_roleid = (
        int(roleid)
        if roleid is not None
        else int(battle_info["roleInfo"]["roleId"])
    )

    head_camp = None
    for player in camp1:
        if int(player["roleId"]) == target_roleid:
            head_camp = 1
            break
    if head_camp is None:
        for player in camp2:
            if int(player["roleId"]) == target_roleid:
                head_camp = 2
                break
    if head_camp is None:
        head_camp = _camp_from_detail_url(battle_info["battleDetailUrl"])

    return {
        "head": {"acntCamp": int(head_camp), "gameResult": True},
        "redTeam": {"acntCamp": 1},
        "redRoles": red_roles,
        "blueRoles": blue_roles,
    }

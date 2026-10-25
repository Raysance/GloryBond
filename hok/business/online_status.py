"""Concurrent Honor of Kings and Steam online-status aggregation."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from ..zstatic import confs, player_client_config, roleidlist, steam_userlist, userlist


def _zfunc_call(name, *args, **kwargs):
    from .. import zfunc

    return getattr(zfunc, name)(*args, **kwargs)


def _client_online_report():
    """Read one fresh friend snapshot, keeping only configured main players."""
    from .player_client import _text
    from ..ztime import elapsed_minutes_text

    bindings = player_client_config.get("players", {})
    allowed = {(str(bindings[key]["uid"]), str(bindings[key]["logic_world_id"])): bindings[key]
               for key in userlist if key in bindings}
    if not allowed:
        return {"online_cnt": 0, "text": ""}
    snapshot = _zfunc_call("player_client_query", "friend_states")
    if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
        raise ValueError("Incomplete client friend snapshot")
    games, teams, idle, seen = {}, [], [], set()
    for state in snapshot["players"]:
        ref = state.get("player") or {}
        identity = str(ref.get("uid")), str(ref.get("logic_world_id"))
        if identity not in allowed or identity in seen:
            continue
        if state.get("online") is not True or state.get("hidden") is True:
            continue
        seen.add(identity)
        name = _text(state.get("name")) or _text(allowed[identity].get("nickname"))
        mode = _text((state.get("current_mode") or {}).get("name"))
        members, capacity = state.get("current_team_members"), state.get("team_capacity")
        size = ""
        if type(members) is int and members > 0:
            size = f"{members}/{capacity}" if type(capacity) is int and capacity >= members else f"{members}人"
        party = {1: "单排", 2: "双排", 3: "三排", 5: "五排"}.get(state.get("ranked_party_size"), "")
        player = {"name": name, "mode": mode, "size": size, "party": party,
                  "hero": _text(state.get("hero_name")), "elapsed": state.get("game_elapsed_seconds")}
        if state.get("is_in_game") is True:
            battle = state.get("battle_id") or {}
            values = tuple(battle.get(key) for key in ("relay_entity", "desk_id", "creation_sequence"))
            # A missing identity must never merge unrelated games, even at the same time.
            known_battle = all(type(v) is int and 0 <= v < 2**32 for v in values) and any(values)
            key = ("battle", *values) if known_battle else ("player", *identity)
            games.setdefault(key, []).append(player)
        elif state.get("game_state") in {"team", "waiting_multiplayer"} or state.get("game_substate") in {"room_or_team", "match_queue"}:
            teams.append(player)
        else:
            idle.append(player)

    if not seen:
        return {"online_cnt": 0, "text": ""}
    message = f"在线 {len(seen)} 人\n─────────────\n"
    for players in games.values():
        first = players[0]
        common_party = (first["party"], first["size"]) if first["party"] and all(
            (p["party"], p["size"]) == (first["party"], first["size"]) for p in players) else None
        mode = next((p["mode"] for p in players if p["mode"]), "")
        header = ["🎮", mode, *(common_party or ())]
        message += " ".join(value for value in header if value)
        elapsed = [p["elapsed"] for p in players if type(p["elapsed"]) is int and p["elapsed"] >= 0]
        if elapsed:
            message += "  " + elapsed_minutes_text(max(elapsed))
        message += "\n"
        for player in players:
            fields = [player["name"], player["hero"]]
            if not common_party:
                fields.extend((player["party"], player["size"]))
            message += "   • " + "  ".join(value for value in fields if value) + "\n"
        message += "\n"
    if teams or idle:
        if games:
            message += "─────────────\n"
        for player in teams:
            context = " ".join(value for value in (player["mode"], player["size"]) if value)
            message += f"👥 {player['name']}" + ("  " + context if context else "") + "\n"
        for player in idle:
            message += f"💤 {player['name']}\n"
    return {"online_cnt": len(seen), "text": message.rstrip("\n")}


def online_process(*, use_client=True):
    from ..zapi import steam_api_user_status

    def process_user(realname):
        userid = userlist[realname]
        roleid = roleidlist[realname]
        errors = []
        try:
            profile = _zfunc_call(
                "wzry_get_official",
                reqtype="profile",
                userid=userid,
                roleid=roleid,
            )
        except Exception as error:
            errors.append(
                _zfunc_call(
                    "_build_traversal_error",
                    "online.profile",
                    realname,
                    {"reqtype": "profile", "userid": userid, "roleid": roleid},
                    error,
                )
            )
            return {
                "online_cnt": 0,
                "battle_info": None,
                "nickname": "",
                "errors": errors,
            }

        online_count = 0
        battle_info = None
        nickname = ""
        for role_info in profile["roleList"]:
            if not role_info["gameOnline"]:
                continue
            if not nickname:
                nickname = role_info["roleName"]
            online_count += 1
            params = {
                "reqtype": "btlist",
                "userid": userid,
                "roleid": roleid,
                "roleName": role_info.get("roleName"),
                "shortRoleJobName": role_info.get("shortRoleJobName"),
            }
            try:
                battle_list = _zfunc_call(
                    "wzry_get_official",
                    reqtype="btlist",
                    userid=userid,
                    roleid=roleid,
                )
            except Exception as error:
                errors.append(
                    _zfunc_call(
                        "_build_traversal_error",
                        "online.btlist",
                        realname,
                        params,
                        error,
                    )
                )
                if not battle_info:
                    battle_info = {
                        "battleId": None,
                        "job": role_info.get("shortRoleJobName", ""),
                        "mapName": None,
                        "heroName": None,
                        "duration": None,
                    }
                continue

            if battle_list["isGaming"]:
                battle_info = {
                    "battleId": battle_list["gaming"].get("battleId", ""),
                    "job": role_info["shortRoleJobName"],
                    "mapName": battle_list["gaming"]["mapName"],
                    "heroName": _zfunc_call(
                        "safe_hero_name",
                        battle_list["gaming"].get("heroId"),
                    ),
                    "duration": battle_list["gaming"]["duration"],
                }
            else:
                battle_info = {
                    "battleId": None,
                    "job": role_info["shortRoleJobName"],
                    "mapName": None,
                    "heroName": None,
                    "duration": None,
                }
        return {
            "online_cnt": online_count,
            "battle_info": battle_info,
            "nickname": nickname,
            "errors": errors,
        }

    def process_steam_user(steam_id):
        return steam_api_user_status(confs["Steam"]["api_key"], steam_id)

    total_online_count = 0
    battle_groups = {}
    idle_users = []
    steam_online_users = []
    traversal_errors = []
    client_message, client_failed = "", False
    workers = (1 if use_client else len(userlist)) + len(steam_userlist)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_to_user = {executor.submit(_client_online_report): ("client", "player_client")} if use_client else {
            executor.submit(process_user, realname): ("wzry", realname)
            for realname in userlist
        }
        for realname, steam_id in steam_userlist.items():
            future_to_user[executor.submit(process_steam_user, steam_id)] = (
                "steam",
                realname,
            )

        for future in as_completed(future_to_user):
            request_type, realname = future_to_user[future]
            if request_type == "client":
                try:
                    result = future.result()
                    total_online_count = result["online_cnt"]
                    client_message = result["text"]
                except Exception as error:
                    from ..zapi import player_client_error_info

                    client_failed = True
                    traversal_errors.append(_zfunc_call("_build_traversal_error", "online.player_client",
                        realname, {}, RuntimeError(str(player_client_error_info(error)))))
            elif request_type == "wzry":
                try:
                    result = future.result()
                except Exception as error:
                    traversal_errors.append(
                        _zfunc_call(
                            "_build_traversal_error",
                            "online.wzry_future",
                            realname,
                            {
                                "userid": userlist.get(realname),
                                "roleid": roleidlist.get(realname),
                            },
                            error,
                        )
                    )
                    continue
                traversal_errors.extend(result.get("errors", []))
                if not result or result["online_cnt"] <= 0:
                    continue
                total_online_count += result["online_cnt"]
                battle_info = result["battle_info"]
                if battle_info and battle_info["battleId"]:
                    battle_id = battle_info["battleId"]
                    battle_groups.setdefault(battle_id, []).append(
                        {"name": result["nickname"], "info": battle_info}
                    )
                elif battle_info:
                    idle_users.append(
                        {"name": result["nickname"], "job": battle_info["job"]}
                    )
            elif request_type == "steam":
                steam_id = steam_userlist.get(realname)
                try:
                    result = future.result()
                    if result:
                        state = result.get("personastate", 0)
                        game = result.get("gameextrainfo", "")
                        if state > 0 or game:
                            steam_online_users.append(
                                {
                                    "name": result.get("personaname", realname),
                                    "game": game,
                                    "state": state,
                                }
                            )
                except Exception as error:
                    traversal_errors.append(
                        _zfunc_call(
                            "_build_traversal_error",
                            "online.steam_status",
                            realname,
                            {"steam_id": steam_id},
                            error,
                        )
                    )

    message = ""
    if total_online_count or steam_online_users:
        if total_online_count and use_client:
            message += client_message
        elif total_online_count:
            message += f"在线 {total_online_count} 人\n─────────────\n"
            for players in battle_groups.values():
                map_name = players[0]["info"]["mapName"]
                duration = players[0]["info"]["duration"]
                message += f"🎮 {map_name}  {duration}min\n"
                for player in players:
                    info = player["info"]
                    message += (
                        f"   • {player['name']} {info['job']}  {info['heroName']}\n"
                    )
                message += "\n"
            if idle_users:
                if battle_groups:
                    message += "─────────────\n"
                for user in idle_users:
                    message += f"💤 {user['name']}  {user['job']}\n"
        if steam_online_users:
            if total_online_count:
                message = message.rstrip("\n") + "\n\n"
            message += f"Steam 在线 {len(steam_online_users)} 人\n─────────────\n"
            for user in steam_online_users:
                if user.get("game"):
                    message += f"🎮 {user['name']}  {user['game']}\n"
                else:
                    message += f"💤 {user['name']}  在线\n"
        message = message.rstrip("\n")
    else:
        message = "在线查询暂时失败" if client_failed else "🐟🐟无人在线"

    error_report = _zfunc_call(
        "format_traversal_error_report",
        "在线遍历",
        traversal_errors,
    )
    return message, error_report

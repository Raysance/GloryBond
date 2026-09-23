"""Concurrent Honor of Kings and Steam online-status aggregation."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from ..zstatic import confs, roleidlist, steam_userlist, userlist


def _zfunc_call(name, *args, **kwargs):
    from .. import zfunc

    return getattr(zfunc, name)(*args, **kwargs)


def online_process():
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
    workers = len(userlist) + len(steam_userlist)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_to_user = {
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
            if request_type == "wzry":
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
        if total_online_count:
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
        message = "🐟🐟无人在线"

    error_report = _zfunc_call(
        "format_traversal_error_report",
        "在线遍历",
        traversal_errors,
    )
    return message, error_report

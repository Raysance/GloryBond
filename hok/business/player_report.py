"""Single-player current and historical battle-report workflow."""

import re

from .. import zdynamic as dmc
from ..zfile import (
    list_history_dates_descending,
    read_history_date,
    read_personal_history,
    web_history_json_path,
    write_daily_history_export,
    writerl,
)
from ..zstatic import (
    fin,
    namenick,
    record_begin_date,
    roleidlist,
    serr,
    userlist,
)


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def extract_single_history_query(text):
    if "昨天" in text or "昨日" in text:
        return [1, [1]]
    if "前天" in text:
        return [1, [2]]
    range_match = re.search(r"(\d+)-(\d+)$", text)
    if range_match:
        return [2, [int(range_match.group(1)), int(range_match.group(2))]]
    day_match = re.search(r"(\d+)$", text)
    if day_match:
        return [1, [int(day_match.group(1))]]
    return [0, []]


def single_process(received_message):
    from ..ztime import (
        calc_gap,
        current_timestamp,
        stamp_to_time,
        str_to_time,
        time_delta,
        time_r,
        time_r_delta,
        time_sul,
        time_to_str,
    )

    message = ""
    poke_names = []
    gameinfo = []
    ai_feedback = "$" not in received_message
    battle_exists = True
    show_map_count_total = False
    last_official_battle_params = None
    matching_name = _zfunc_attr("extract_name")(received_message)

    if not matching_name:
        message += "没有提到玩家名字哦"
    else:
        last_request = dmc.LastSingleRequestTime.get(matching_name, stamp_to_time(0))
        if calc_gap(time_r(), last_request) < 5:
            return None
        dmc.LastSingleRequestTime[matching_name] = time_r()

        exhibit_date = str(time_sul().strftime("%m-%d"))
        web_artifacts = _zfunc_attr("WebArtifacts")
        filename_hashed = web_artifacts.make_hash(round(current_timestamp() * 1000000))
        website_path = web_history_json_path(filename_hashed)
        history_query = extract_single_history_query(received_message)
        battle_visible = True

        if history_query[0] == 1:
            ai_feedback = False
            show_map_count_total = True
            traceback_count = history_query[1][0]
            traceback_date = str(time_r_delta(traceback_count).strftime("%Y-%m-%d"))
            exhibit_date = str(time_r_delta(traceback_count).strftime("%m-%d"))
            available_dates = set(list_history_dates_descending())
            if traceback_date not in available_dates:
                traceback_date = str(record_begin_date)
            histories = read_history_date(traceback_date)
            gameinfo = [
                history
                for history in histories
                if history["id"] == userlist[matching_name]
            ][0]
            if "roleid" not in gameinfo:
                gameinfo["roleid"] = str(roleidlist[gameinfo["key"]])
            if "visible" not in gameinfo:
                gameinfo["visible"] = True
            try:
                personal_payload = read_personal_history(
                    traceback_date,
                    userlist[matching_name],
                )
                if not personal_payload:
                    raise FileNotFoundError(
                        f"personal snapshot missing: {traceback_date}/{userlist[matching_name]}"
                    )
                writerl(website_path, personal_payload)
            except Exception:
                exhibit_date += " 链接失效"
            website_link = web_artifacts.history_route_link(
                filename_hashed,
                "single_oneday",
            )
        elif history_query[0] == 2:
            ai_feedback = False
            show_map_count_total = True
            lost_info_dates = []
            traceback_from, traceback_to = history_query[1]
            if traceback_from < traceback_to:
                traceback_to, traceback_from = traceback_from, traceback_to
            traceback_date_from = time_r_delta(traceback_from)
            traceback_date_to = time_r_delta(traceback_to)
            available_dates = set(list_history_dates_descending())
            if traceback_date_from.strftime("%Y-%m-%d") not in available_dates:
                traceback_date_from = str_to_time(record_begin_date)
            if traceback_date_to.strftime("%Y-%m-%d") not in available_dates:
                traceback_date_to = str_to_time(record_begin_date)

            raw_gameinfo = []
            scan_date = traceback_date_from
            while scan_date <= traceback_date_to:
                scan_date_text = scan_date.strftime("%Y-%m-%d")
                if scan_date_text in available_dates:
                    histories = read_history_date(scan_date_text)
                    matching_history = next(
                        (
                            history
                            for history in histories
                            if history["key"] == matching_name
                        ),
                        None,
                    )
                    if matching_history:
                        raw_gameinfo.append(matching_history)
                    else:
                        lost_info_dates.append(scan_date.strftime("%m-%d"))
                scan_date = time_delta(scan_date, 1)
            lost_info = (
                f"(Lost {' '.join(lost_info_dates)})" if lost_info_dates else ""
            )
            exhibit_date = (
                f"{traceback_date_from.strftime('%m-%d')} - "
                f"{traceback_date_to.strftime('%m-%d')} {lost_info}"
            )
            writerl(website_path, raw_gameinfo)
            gameinfo = _zfunc_attr("merge_crossday_gamedata")(raw_gameinfo)
            website_link = web_artifacts.history_route_link(
                filename_hashed,
                "single_period",
                extra={
                    "DateFrom": traceback_date_from.strftime("%m-%d"),
                    "DateTo": traceback_date_to.strftime("%m-%d"),
                },
            )
        else:
            gameinfo = _zfunc_attr("wzry_data")(
                matching_name,
                website_path,
                sync_battle_visibility=True,
            )
            today_sul_date = str(time_sul().strftime("%Y-%m-%d"))
            current_history = read_history_date(today_sul_date) or []
            current_history = [
                item for item in current_history if item.get("key") != matching_name
            ]
            current_history.append(gameinfo)
            write_daily_history_export(today_sul_date, current_history)

            battle_visible = gameinfo["visible"]
            if gameinfo["details"]:
                for item in gameinfo["details"][::-1]:
                    if _zfunc_attr("check_btl_official_with_matching")(
                        item["MapName"]
                    ):
                        last_official_battle_params = item["Params"]
                        break
                if last_official_battle_params:
                    dmc.LastBtlParams = last_official_battle_params
                    dmc.LastBtlRoleId = roleidlist[matching_name]
                    dmc.LastBtlMsgTime = time_to_str(time_r())
                    dmc.LastBtlMsgStatus = True
            if gameinfo["gaming_info"]:
                dmc.spoiler_cache = {
                    "time": current_timestamp(),
                    "realname": matching_name,
                    "battleID": gameinfo["gaming_info"]["battle_id"],
                }
            website_link = web_artifacts.history_route_link(
                filename_hashed,
                "single_oneday",
            )

        gameinfo["btl_aver"] = _zfunc_attr("calculate_official_battle_average")(
            gameinfo.get("details", [])
        )
        gameinfo["btl_contribute_aver"] = _zfunc_attr(
            "calculate_official_battle_contribution_average"
        )(
            gameinfo.get("details", []),
            gameinfo.get("roleid", roleidlist[matching_name]),
        )

        win_content = (
            "\n".join(
                [
                    f"              -{map_name}WIN：{map_count[0]} "
                    f"{f' / {map_count[1]}' if show_map_count_total else ''}"
                    for map_name, map_count in gameinfo["map_cnt"].items()
                ]
            )
            + "\n"
        )
        analyses = _zfunc_attr("Analyses")
        expert_hero_info = analyses.get_expert_hero(userlist[matching_name])
        if matching_name not in expert_hero_info:
            expert_hero_content = ""
        else:
            hero_values = expert_hero_info[matching_name][0]
            expert_hero_content = (
                f"最拿手英雄：{list(hero_values.keys())[0]},"
                f"拿手程度：{list(hero_values.values())[0]}\n"
            )
        gaming_content = ""
        if gameinfo["gaming_info"]:
            gaming = gameinfo["gaming_info"]
            gaming_content = (
                f"👀{namenick[matching_name]}正在{gaming['map_name']}中玩"
                f"{gaming['hero_name']}，{gaming['duration_minute']}分钟前开局，快去看看。\n\n"
            )
        if gameinfo["visible"] and "排位" in gameinfo["map_cnt"]:
            star_up_content = f"      相比前一天 +⭐: {gameinfo['star_up']}\n"
        else:
            star_up_content = ""
        if gameinfo["visible"] and "巅峰" in gameinfo["map_cnt"]:
            peak_up_content = "      相比前一天 巅峰分: \n"
            for score in gameinfo["peak_up"]:
                peak_up_content += f"             {score[0]} --> {score[1]}\n"
        else:
            peak_up_content = ""

        if battle_visible:
            message += (
                f"{gaming_content}"
                f"🚩{gameinfo['nickname']}({exhibit_date})的战报:\n"
                f"        场次：{gameinfo['today_num']}\n"
                f"{win_content}"
                f"        平均评分: "
                f"{gameinfo['btl_aver'] if gameinfo['btl_aver'] != fin else serr}\n"
                f"        平均贡献: {gameinfo.get('btl_contribute_aver', 0):.2f}\n"
                f"      当前段位: {gameinfo['rank_name']} {gameinfo['rank_star']}⭐\n"
                f"{star_up_content}{peak_up_content}"
            )
            message += website_link + "\n\n"
            if gameinfo["today_num"] == 0:
                ai_feedback = False
                battle_exists = False
            poke_names.append(gameinfo["nickname"])
            ai_gameinfo = []
            allowed_keys = {
                "GameTime",
                "HeroName",
                "MapName",
                "StarAfterGame",
                "PeakGradeAfterGame",
                "PeakGradeBeforeGame",
                "KillCnt",
                "DeadCnt",
                "AssistCnt",
                "Result",
                "GameGrade",
                "Duration_Second",
                "Others",
            }
            for detail in gameinfo["details"]:
                ai_gameinfo.append(
                    {
                        key: value
                        for key, value in detail.items()
                        if key in allowed_keys and value != -1
                    }
                )
            if ai_feedback:
                message += _zfunc_attr("ai_parser")(
                    [str(ai_gameinfo), message, received_message],
                    "single_player",
                ) + "\n"
        else:
            message += (
                f"{gaming_content}"
                f"🚩{gameinfo['nickname']}({exhibit_date})的战报:\n"
                "              -战绩不可见\n"
                f"      当前段位: {gameinfo['rank_name']} {gameinfo['rank_star']}⭐\n"
                f"{star_up_content}{peak_up_content}"
            )

    return [
        message,
        poke_names,
        battle_exists,
        last_official_battle_params,
        roleidlist[matching_name],
    ]

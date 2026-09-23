"""Group ranking aggregation and presentation."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from ..zfile import write_daily_history_export, write_web_history_payload
from ..zstatic import namenick, roleidlist, userlist


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def rnk_process(rcv_msg, caller=None, show_zero=True, show_analyze=False, debug=False):
    from ..ztime import current_timestamp, time_r, time_sul

    if caller is None:
        caller = ""
    now_time = str(time_r().strftime("%Y-%m-%d %H:%M:%S"))
    today_sul_date = str(time_sul().strftime("%Y-%m-%d"))
    web_artifacts = _zfunc_attr("WebArtifacts")
    filename_hashed = web_artifacts.make_hash(round(current_timestamp() * 1000000))
    website_link = web_artifacts.history_route_link(
        filename_hashed,
        "all",
        caller=caller,
        time_text=now_time,
    )
    traversal_errors = []

    def visit_wzry_data(realname):
        try:
            game_data = _zfunc_attr("wzry_data")(realname=realname)
            return {"data": game_data, "error": None}
        except Exception as error:
            params = {
                "realname": realname,
                "calls": [
                    {
                        "reqtype": "btlist",
                        "userid": userlist.get(realname),
                        "roleid": roleidlist.get(realname),
                    },
                    {
                        "reqtype": "profile",
                        "userid": userlist.get(realname),
                        "roleid": roleidlist.get(realname),
                    },
                ],
            }
            return {
                "data": None,
                "error": _zfunc_attr("_build_traversal_error")(
                    "rank.wzry_data",
                    realname,
                    params,
                    error,
                ),
            }

    gameinfo = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        future_to_name = {
            executor.submit(visit_wzry_data, realname): realname
            for realname in userlist
        }
        for future in as_completed(future_to_name):
            realname = future_to_name[future]
            try:
                result = future.result()
            except Exception as error:
                traversal_errors.append(
                    _zfunc_attr("_build_traversal_error")(
                        "rank.future",
                        realname,
                        {
                            "realname": realname,
                            "calls": [
                                {
                                    "reqtype": "btlist",
                                    "userid": userlist.get(realname),
                                    "roleid": roleidlist.get(realname),
                                },
                                {
                                    "reqtype": "profile",
                                    "userid": userlist.get(realname),
                                    "roleid": roleidlist.get(realname),
                                },
                            ],
                        },
                        error,
                    )
                )
                continue
            if result.get("error"):
                traversal_errors.append(result["error"])
            if result.get("data") is not None:
                gameinfo.append(result["data"])

    format_errors = _zfunc_attr("format_traversal_error_report")
    if not gameinfo:
        _zfunc_attr("log_message")("ERROR: 王者荣耀数据源错误")
        return [
            str(time_r().strftime("%Y-%m-%d %H:%M"))
            + "\n\n王者荣耀数据源错误，暂无可用排行数据",
            [],
            format_errors("排行遍历", traversal_errors),
        ]

    write_daily_history_export(today_sul_date, gameinfo)
    if not show_zero:
        gameinfo = [item for item in gameinfo if item["today_num"] != 0]
    sorted_star = sorted(gameinfo, key=lambda item: item["star_up"], reverse=True)
    sorted_battle = sorted(gameinfo, key=lambda item: item["today_num"], reverse=True)
    web_payload = [
        {key: value for key, value in item.items() if key != "key"}
        for item in sorted_star
    ]
    write_web_history_payload(filename_hashed, web_payload)
    message = str(time_r().strftime("%Y-%m-%d %H:%M")) + "\n"
    if not gameinfo or sorted_battle[0]["today_num"] == 0:
        message += "\n今日还没有战绩哦"
        return [message, [], format_errors("排行遍历", traversal_errors)]

    if show_analyze:
        analyses = _zfunc_attr("Analyses")
        extreme_data = analyses.get_extreme_data()
        benefit_data = analyses.get_benefit_data()
        message += "\n近5天最高最低评分：\n"
        message += (
            "      ↑"
            + namenick[extreme_data[3]]
            + "的"
            + extreme_data[5]
            + "："
            + str(extreme_data[1])
            + "分\n"
        )
        message += (
            "      ↓"
            + namenick[extreme_data[2]]
            + "的"
            + extreme_data[4]
            + "："
            + str(extreme_data[0])
            + "分\n"
        )
        message += "机制受益受害者 ：\n"
        message += f"      {namenick[benefit_data[0]]}：{benefit_data[2]}\n"
        message += f"      {namenick[benefit_data[1]]}：{benefit_data[3]}\n\n"

    message += "--- 上分榜 ---\n"
    top_point = sorted_star[0]["nickname"] if sorted_star[0]["star_up"] > 0 else ""
    bottom_point = sorted_star[-1]["nickname"] if sorted_star[-1]["star_up"] < 0 else ""
    if top_point:
        message += f"今日上分最佳👆：{top_point}\n"
    if bottom_point:
        message += f"今日掉分最多👇：{bottom_point}\n"
    for index, item in enumerate(sorted_star):
        message += f"    {index + 1}.\t{item['nickname']}\t       {item['star_up']:+}\n"

    message += "\n--- 场次榜 ---\n"
    top_play = (
        sorted_battle[0]["nickname"] if sorted_battle[0]["today_num"] > 0 else ""
    )
    if top_play:
        message += f"今日场次最多👆：{top_play}\n"
    for index, item in enumerate(sorted_battle):
        message += f"    {index + 1}.\t{item['nickname']}\t       {item['today_num']}\n"

    message += f"\n{website_link}\n\n"
    if "$" not in rcv_msg:
        message += _zfunc_attr("ai_parser")([message], "rnk")
    return [
        message,
        {top_point, bottom_point, top_play},
        format_errors("排行遍历", traversal_errors),
    ]

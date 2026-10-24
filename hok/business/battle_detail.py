"""Battle-analysis views and single-battle presentation."""

from ..zstatic import (
    analyze_time_gap,
    extra_namenick,
    extra_useridlist,
    line_delim,
    namenick,
    userlist,
)


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def view_process(received_message, time_gap=analyze_time_gap):
    analyses = _zfunc_attr("Analyses")
    message = " "
    if "b" in received_message:
        benefit_data = analyses.get_benefit_data(time_gap=time_gap)[4]
        message += "受益受害：(排位巅峰战队)\n"
        for name, values in benefit_data.items():
            message += (
                f"{namenick[name]}：\n    {round(values[0], 2)} "
                f"{round(values[1] * 100, 1)}% {round(values[2], 2)}\n"
            )
        payload = analyses.get_benefit_debug_payload(time_gap=time_gap)
        message += _zfunc_attr("WebArtifacts").publish_history_json_route(
            payload,
            "benefit",
        ) + "\n"
    if "e" in received_message:
        extreme_data = analyses.get_extreme_data(time_gap=time_gap)
        message += f"近{time_gap}天最高最低评分：\n"
        message += (
            "      ↑"
            + namenick[extreme_data[3]]
            + "的"
            + extreme_data[5]
            + "："
            + str(round(extreme_data[1], 3))
            + "分\n"
        )
        message += (
            "      ↓"
            + namenick[extreme_data[2]]
            + "的"
            + extreme_data[4]
            + "："
            + str(round(extreme_data[0], 3))
            + "分\n"
        )
    if "k" in received_message:
        expert_hero = analyses.get_expert_hero(time_gap=time_gap)
        for name, values in expert_hero.items():
            message += (
                f"{namenick[name]}的最拿手英雄：{list(values[0].keys())[0]},"
                f"拿手程度：{round(list(values[0].values())[0], 3)}\n"
            )
        message += "\n"
    if "i" in received_message:
        intersection_data = analyses.get_intersection_data(time_gap=time_gap)
        for names, value in intersection_data.items():
            players = list(names)
            message += (
                f"{namenick[players[0]]}与{namenick[players[1]]}：{int(value)}\n"
            )
    if "h" in received_message:
        hero_min, hero_max, min_value, max_value, hero_stats = (
            analyses.get_hero_benefit_data(time_gap=30)
        )
        message += "英雄受益受害（近30日）：\n"
        if hero_stats:
            message += f"  受益：{hero_min} ({min_value})\n"
            message += f"  受害：{hero_max} ({max_value})\n{line_delim}"
            message += "\n  受益榜（Top 6）：\n"
            for hero_name, values in list(hero_stats.items())[:6]:
                message += (
                    f"    {hero_name} ( {values[3]} 场 ):\n"
                    f"       {round(values[0], 3)} "
                    f"{round(values[1] * 100, 1)}% {round(values[2], 2)}\n"
                )
            message += f"{line_delim}\n  受害榜（Top 6）：\n"
            for hero_name, values in list(hero_stats.items())[-6:][::-1]:
                message += (
                    f"    {hero_name} ( {values[3]} 场 ):\n"
                    f"       {round(values[0], 3)} "
                    f"{round(values[1] * 100, 1)}% {round(values[2], 2)}\n"
                )
        else:
            message += "  无数据。\n"
    return message


def btldetail_process(
    gameSvrId,
    relaySvrId,
    gameseq,
    pvptype,
    roleid,
    gen_image=False,
    show_profile=False,
    from_web=False,
    individual_show=False,
    strict_filter=True,
):
    from ..tools import gen_battle_res
    from ..zfile import battle_exhibit_image_path, web_history_json_path, writerl
    from ..ztime import current_timestamp

    result = _zfunc_attr("fetch_battle")(gameseq, roleid)
    if not result:
        if str(gameseq).startswith("-"):
            return None, None, None
        result = _zfunc_attr("wzry_get_official")(
            reqtype="btldetail",
            gameseq=gameseq,
            gameSvrId=gameSvrId,
            relaySvrId=relaySvrId,
            roleid=roleid,
            pvptype=pvptype,
        )
    if "head" not in result:
        return None, None, None
    map_name = result["head"]["mapName"]
    if strict_filter and not _zfunc_attr("check_btl_official_with_matching")(
        map_name
    ):
        return None, None, map_name

    my_team = (
        result["redRoles"]
        if result["redTeam"]["acntCamp"] == result["head"]["acntCamp"]
        else result["blueRoles"]
    )
    contribution = _zfunc_attr("calculate_battle_contribution_factor")(result)
    contribution_text = f"贡献: {round(contribution, 2)}" if contribution is not None else ""
    my_userid = result["head"]["userId"]
    related_players = []
    all_related_players = []
    related_userids = userlist | extra_useridlist
    related_nicknames = namenick | extra_namenick
    for player in my_team:
        user_id = player["basicInfo"]["userId"]
        for player_name, player_id in related_userids.items():
            if user_id is None or str(user_id) != str(player_id):
                continue
            player_grade = player["battleStats"]["gradeGame"]
            all_related_players.append([player_name, player_grade])
            if str(user_id) != str(my_userid):
                related_players.append([player_name, player_grade])
            break

    related_players = [
        [related_nicknames[player_name], player_grade]
        for player_name, player_grade in related_players
    ]
    all_related_players = [
        [related_nicknames[player_name], player_grade]
        for player_name, player_grade in all_related_players
    ]
    related_text = ""
    all_related_text = ""
    if related_players:
        related_text = "With: "
        for info in related_players:
            related_text += f"{info[0]}({info[1]}) "
        related_text += "\n"
    if all_related_players:
        for info in all_related_players:
            all_related_text += f"{info[0]}({info[1]}) "
        all_related_text += "\n"

    web_artifacts = _zfunc_attr("WebArtifacts")
    filename_hashed = web_artifacts.make_hash(round(current_timestamp() * 1000000))
    json_output_path = web_history_json_path(filename_hashed)
    link_url = web_artifacts.history_route_link(filename_hashed, "btldetail")
    writerl(json_output_path, result)
    image_path = ""
    if gen_image:
        # Keep compatibility with older test/integration overrides that
        # expose the historical zero-argument path helper.
        try:
            image_path = battle_exhibit_image_path(gameseq)
        except TypeError as error:
            try:
                image_path = battle_exhibit_image_path()
            except TypeError:
                raise error
        if gen_battle_res.generate_battle_ui_image(json_output_path, image_path) is False:
            raise RuntimeError("战局分享图片生成失败")

    if individual_show:
        message = (
            f"{result['battle']['dtEventTime']} {map_name} "
            f"{'🏆' if result['head']['gameResult'] is True else '🏳️'}\n"
            f"{all_related_text}{link_url}"
        )
    elif from_web:
        message = (
            f"{result['battle']['dtEventTime']} {map_name} "
            f"{'🏆' if result['head']['gameResult'] is True else '🏳️'}\n"
            f"{result['head']['roleName']} {result['head']['heroName']} "
            f"{contribution_text}\n{link_url}"
        )
    else:
        head = result["head"]
        message = (
            f"最后一局 {'🏆' if head['gameResult'] is True else '🏳️'} "
            f"{contribution_text}\n"
            f"{map_name} {head['heroName']}: {head['killCnt']}/"
            f"{head['deadCnt']}/{head['assistCnt']} {head['gradeGame']}\n"
            f"{related_text}{link_url}\n\n戳一戳 来评估两方实力"
        )
    return message, image_path, map_name

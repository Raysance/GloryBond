"""Daily hero recommendation selection and presentation."""

import random

from .. import zdynamic as dmc
from ..zfile import (
    hero_skin_asset_path,
    list_hero_skin_files,
    list_hero_skin_names,
    read_hero_skill_descriptions,
)
from ..zstatic import HeroList, force_choice, namenick, userlist


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def _select_hero_name(realname, hero_name_candidates):
    from ..ztime import time_delta, time_r

    selected_way = random.random()
    selected_info = {"way": "", "details": []}
    end_time = time_r()
    start_time = time_delta(end_time, -5)
    game_details, _ = _zfunc_attr("fetch_history")(
        userid=userlist[realname],
        start_date=start_time,
        end_date=end_time,
    )
    game_details = game_details[realname]
    if realname in force_choice:
        return force_choice[realname], {"way": "RANDOM", "details": []}
    if selected_way < 0.45:
        hero_name = random.choice(hero_name_candidates)
        selected_info["way"] = "RANDOM"
    elif selected_way < 0.8 and game_details:
        recent_candidates = {
            detail["HeroName"]
            for detail in game_details
            if detail["HeroName"] in hero_name_candidates
        }
        hero_name = random.choice(list(recent_candidates))
        selected_info["way"] = "RECENT"
        for detail in game_details:
            if detail["HeroName"] == hero_name:
                selected_info["details"].append(
                    {
                        "MapName": detail["MapName"],
                        "GameGrade": detail["GameGrade"],
                    }
                )
    else:
        rank_id = random.choice(list(dmc.herorank.keys()))
        hero_name = ""
        while hero_name not in hero_name_candidates:
            rank_index = random.randint(0, 10)
            hero_name = dmc.herorank[rank_id]["list"][rank_index]["heroInfo"][
                "heroName"
            ]
        hero_rank_info = dmc.herorank[rank_id]["list"][rank_index]
        selected_info["way"] = "HERORANK"
        selected_info["details"].append({})
        valid_data_types = {
            "banRate": "顶端排位被ban率",
            "showRate": "顶端排位出场率",
            "winRate": "顶端排位胜率",
            "killNum": "顶端排位场均击杀数",
            "output": "顶端排位场均输出",
            "mvp": "顶端排位MVP率",
            "goldPlay": "顶端排位金牌率",
        }
        for key, value in hero_rank_info.items():
            if key in valid_data_types and value != 0:
                selected_info["details"][0][valid_data_types[key]] = value
    return hero_name, selected_info


def _random_hero_skin(realname):
    hero_name, selected_info = _select_hero_name(
        realname,
        list_hero_skin_names(),
    )
    skin_file = random.choice(list_hero_skin_files(hero_name))
    skin_name = skin_file.rsplit(".", 1)[0]
    return (
        hero_name,
        skin_name,
        hero_skin_asset_path(hero_name, skin_file),
        selected_info,
    )


def _hero_skin(realname, ignore_limit):
    from ..ztime import time_r

    current_date = time_r().strftime("%Y-%m-%d")
    cached = _zfunc_attr("_today_hero_cached")(
        realname,
        current_date,
        ignore_limit=ignore_limit,
    )
    if cached:
        return (
            cached.get("heroname"),
            cached.get("skinname"),
            cached.get("picpath"),
            cached.get("selectinfo"),
        )

    hero_name, skin_name, picture_path, selected_info = _random_hero_skin(realname)
    data = {
        "date": current_date,
        "heroname": hero_name,
        "skinname": skin_name,
        "picpath": picture_path,
        "selectinfo": selected_info,
    }
    _zfunc_attr("_today_hero_store")(realname, data)
    return hero_name, skin_name, picture_path, selected_info


def todayhero_process(realname, ignore_limit=False, ai_comment=True):
    hero_name, skin_name, picture_path, selected_info = _hero_skin(
        realname,
        ignore_limit,
    )
    hero_id = next(
        hero_id
        for hero_id, known_name in HeroList.items()
        if known_name == hero_name
    )
    hero_skills = read_hero_skill_descriptions(hero_id)
    hero_statistics = _zfunc_attr("single_player_single_hero_process")(
        realname,
        hero_id,
        hero_name,
    )
    if ai_comment:
        play_reason = _zfunc_attr("ai_parser")(
            msg_type="skill_advantage",
            user_query=[
                hero_name,
                namenick[realname],
                str(hero_skills),
                str(selected_info),
                hero_statistics,
            ],
        )
    else:
        play_reason = str(selected_info)
    return (
        f"{namenick[realname]}的今日英雄：{hero_name}",
        play_reason,
        picture_path,
    )

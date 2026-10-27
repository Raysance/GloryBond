"""KPL match selection, image prompting, and push orchestration."""

import json


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def kpl_check_and_push(
    *,
    debug=False,
    event=None,
    force=False,
    preview_only=False,
):
    from .. import zdynamic as dmc
    from ..tools.kpl_match_collector import get_full_match_list, get_match_content
    from ..ztime import date_start_epoch_ms, time_r

    if not preview_only and not getattr(dmc, "KplPushEnabled", True):
        return {
            "pushed": False,
            "cid": None,
            "image_path": None,
            "debug": "KPL_PUSH paused by KplPushEnabled=false",
        }

    loop_guard = 1 if force else 2
    last_result = None
    while loop_guard > 0:
        loop_guard -= 1
        now = time_r()
        if not force and not _zfunc_attr("_kpl_acquire_push_lock")():
            _zfunc_attr("_kpl_mark_push_pending")()
            return {
                "pushed": False,
                "cid": None,
                "image_path": None,
                "debug": "KPL_PUSH locked; pending set",
            }

        try:
            time_ms = date_start_epoch_ms(now)
            mid = getattr(dmc, "KplScheduleMid", 214)
            page_size = getattr(dmc, "KplSchedulePs", 50)
            window_seconds = getattr(dmc, "KplPushWindowSeconds", 3600)
            size = getattr(dmc, "KplImageSize", "1792x1024")
            resolution = getattr(dmc, "KplImageResolution", "2k")

            full = get_full_match_list(
                mid=mid,
                time_ms=time_ms,
                now=now,
                ps=page_size,
            )
            now_epoch = int(full.get("now_epoch") or 0)
            finished = full.get("groups", {}).get("finished") or []

            candidates = []
            for item in finished:
                cid = item.get("cid")
                end_time = item.get("etime") or 0
                if not cid or not end_time:
                    continue
                gap = now_epoch - int(end_time)
                if force or 0 <= gap <= window_seconds:
                    candidates.append((int(end_time), item))
            candidates.sort(key=lambda value: value[0], reverse=True)

            debug_lines = [
                f"KPL_PUSH now_epoch={now_epoch} mid={mid} time_ms={time_ms} "
                f"finished_cnt={len(finished)} cand_cnt={len(candidates)}"
            ]
            local_result = None
            for end_time, item in candidates:
                cid = int(item.get("cid"))
                pushed = _zfunc_attr("_kpl_was_pushed")(cid)
                debug_lines.append(
                    f"KPL_PUSH_CAND cid={cid} etime={end_time} pushed={pushed} "
                    f"home={item.get('home', {}).get('name')} "
                    f"away={item.get('away', {}).get('name')} score={item.get('score')}"
                )
                if pushed and not force:
                    continue

                match_content = get_match_content(item)
                if preview_only:
                    preview = kpl_build_match_image_prompt(match_content=match_content)
                    if debug:
                        debug_lines.extend(
                            [
                                "KPL_PUSH_PROMPT",
                                preview.get("prompt") or "",
                                "KPL_PUSH_PAYLOAD",
                                json.dumps(
                                    preview.get("payload") or {},
                                    ensure_ascii=False,
                                ),
                            ]
                        )
                    local_result = {
                        "pushed": False,
                        "cid": cid,
                        "image_path": None,
                        "debug": "\n".join(debug_lines),
                    }
                    break

                generated = kpl_match_image_generate(
                    match_content=match_content,
                    size=size,
                    resolution=resolution,
                )
                image_url = (generated or {}).get("url") or ""
                if not image_url:
                    raise Exception(f"kpl_push_error: empty image url for cid={cid}")
                if debug:
                    debug_lines.extend(
                        [
                            "KPL_PUSH_PROMPT",
                            (generated or {}).get("prompt") or "",
                            "KPL_PUSH_PAYLOAD",
                            json.dumps(
                                (generated or {}).get("payload") or {},
                                ensure_ascii=False,
                            ),
                        ]
                    )

                local_path = _zfunc_attr("_kpl_save_push_image")(
                    image_url,
                    cid,
                    now.strftime("%Y-%m-%d"),
                )
                home = (item.get("home") or {}).get("name") or ""
                away = (item.get("away") or {}).get("name") or ""
                score = item.get("score") or {}
                score_text = f"{score.get('home', '-')}-{score.get('away', '-')}"
                stage = item.get("game_stage") or item.get("title") or ""
                text = (
                    f"KPL 战局推送：{home} vs {away}  {score_text}\n{stage}\n"
                    f"结束时间: {match_content.get('end_time_iso') or item.get('etime')}"
                )
                _zfunc_attr("_kpl_send_push_message")(text, local_path, event)
                _zfunc_attr("_kpl_mark_pushed")(cid)
                local_result = {
                    "pushed": True,
                    "cid": cid,
                    "image_path": local_path,
                    "debug": "\n".join(debug_lines),
                }
                break

            if local_result is None:
                local_result = {
                    "pushed": False,
                    "cid": None,
                    "image_path": None,
                    "debug": "\n".join(debug_lines),
                }
            last_result = local_result
        finally:
            if not force:
                _zfunc_attr("_kpl_release_push_lock")()

        if force:
            return last_result
        if _zfunc_attr("_kpl_take_push_pending")():
            continue
        return last_result

    return last_result or {
        "pushed": False,
        "cid": None,
        "image_path": None,
        "debug": "KPL_PUSH loop_guard_exceeded",
    }


def kpl_match_image_generate(*, match_content, size, resolution):
    from ..zapi import apimart_images_generate

    built = kpl_build_match_image_prompt(match_content=match_content)
    prompt = built["prompt"]
    payload = built["payload"]
    style = built["style_template"]
    result = apimart_images_generate(
        prompt=prompt,
        reference_image_url="",
        size=size,
        resolution=resolution,
    )
    if not isinstance(result, dict):
        raise Exception(
            f"kpl_match_image_generate_error: unexpected response {str(result)[:500]}"
        )
    result["prompt"] = prompt
    result["payload"] = payload
    result["style_template"] = style
    return result


def kpl_build_match_image_prompt(*, match_content):
    from .. import zdynamic as dmc
    from ..ztime import get_timebased_rand, iso_text_without_timezone

    style_templates = [
        "暗色高级转播UI：深蓝灰渐变背景 + 玻璃拟态卡片，8px圆角、细分割线、轻阴影，整体克制高级；比分与队名用大字号，数据区用表格卡片。",
        "浅色极简信息图：白/浅灰背景，大留白，12列网格对齐；标题用黑字，强调色只用于比分和小图标，表格线极浅，信息密集但不拥挤。",
        "官方海报质感：暗色底 + 柔和聚光，主体居中，左右队名对称；使用干净的几何块面与细线框，不要霓虹，不要花哨纹理，质感像赛事官方宣传图。",
        "现代电竞面板：深色面板+模块化信息块，顶部标题条，中部比分条，底部双列对比表；使用统一图标与小标签，强调对齐与层级。",
    ]
    style_mode = getattr(dmc, "KplImageStyleMode", "fixed")
    fixed_index = getattr(dmc, "KplImageStyleFixedIndex", 1)
    if style_mode == "random":
        style_index = get_timebased_rand(len(style_templates), 10)
    else:
        try:
            style_index = int(fixed_index)
        except Exception:
            style_index = 1
        if style_index < 0 or style_index >= len(style_templates):
            style_index = 1
    style = style_templates[style_index]

    raw = match_content.get("raw") or {}
    raw_data = raw.get("data") or (raw.get("overall_grade") or {}).get("data") or {}
    home_team = match_content.get("home_team") or raw_data.get("home_team") or {}
    away_team = match_content.get("away_team") or raw_data.get("away_team") or {}
    home_name = home_team.get("name") or home_team.get("title") or ""
    away_name = away_team.get("name") or away_team.get("title") or ""
    score_data = match_content.get("score") or {}
    home_score = score_data.get("home", raw_data.get("home_score"))
    away_score = score_data.get("away", raw_data.get("away_score"))
    total_score = None
    if home_score is not None and away_score is not None:
        total_score = f"{home_score}-{away_score}"

    position_names = {
        "TOP": "对抗路",
        "JUG": "打野",
        "MID": "中路",
        "AD": "发育路",
        "SUP": "游走",
    }
    hot_comments = {}
    for player in match_content.get("players") or []:
        if not isinstance(player, dict):
            continue
        name = player.get("player_name")
        hot = str(player.get("hot_comment") or "").strip().replace("\n", " ")
        if not name or not hot:
            continue
        if len(hot) > 80:
            hot = hot[:80] + "..."
        hot_comments[name] = hot

    global_grade = raw_data.get("global_grade_info") or {}
    team_players = {}
    for side in ["home_team", "away_team"]:
        side_info = global_grade.get(side) or {}
        for player in side_info.get("players") or []:
            if not isinstance(player, dict):
                continue
            name = player.get("nickname")
            position = position_names.get(str(player.get("place")), player.get("place"))
            team_name = home_name if side == "home_team" else away_name
            team_players.setdefault(team_name, [])
            item = {"name": name, "pos": position, "score": player.get("avg_grade")}
            if hot_comments.get(name):
                item["hot"] = hot_comments[name]
            team_players[team_name].append(item)

    if not team_players:
        for team in match_content.get("overall_ratings") or []:
            team_name = team.get("name") or ""
            if not team_name:
                continue
            team_players[team_name] = [
                {
                    "name": player.get("name"),
                    "pos": player.get("position"),
                    "score": player.get("rating"),
                }
                for player in team.get("players") or []
            ]

    teams_payload = []
    for name in [home_name, away_name]:
        if not name:
            continue
        score = home_score if name == home_name else away_score if name == away_name else None
        teams_payload.append(
            {
                "name": name,
                "score": score,
                "players": team_players.get(name) or [],
            }
        )

    match_name = (
        f"{home_name} vs {away_name}"
        if home_name and away_name
        else match_content.get("match_name") or "KPL 对局战报"
    )
    payload = {
        "match_name": match_name,
        "start_time": iso_text_without_timezone(
            match_content.get("start_time_text")
            or match_content.get("start_time_iso")
            or ""
        ),
        "end_time": iso_text_without_timezone(
            match_content.get("end_time_text")
            or match_content.get("end_time_iso")
            or ""
        ),
        "total_score": total_score or "-",
        "teams": teams_payload,
    }
    prompt = (
        "你是专业赛事视觉设计师。"
        "请根据以下 JSON 数据生成一张 KPL 系列赛战报信息图（强调整场系列赛的大比分）。"
        "只生成图片，不要输出任何额外解释文字。"
        "整体风格要求高级、现代、干净，确保文字清晰可读。"
        "不要虚构 JSON 中不存在的信息；不要输出 JSON 字段名，只展示内容本身。\n"
        f"风格模板：{style}\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    return {"prompt": prompt, "payload": payload, "style_template": style}

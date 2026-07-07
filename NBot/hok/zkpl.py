"""KPL match data facade.

Only ``get_match_list_json`` and ``get_match_detail_json`` perform KPL data
acquisition. Compatibility and presentation helpers below always consume one
of those two JSON-serializable return values.
"""

from .zstatic import *


def _fetch_match_list_raw(*, mid=94, gid=0, tid=0, stime, etime, pn=1, ps=50):
    """Fetch one page of matches for the selected calendar date range."""
    from .zapi import bilibili_esports_get_json

    return bilibili_esports_get_json(
        "/matchs/list",
        params={
            "mid": mid,
            "gid": gid,
            "tid": tid,
            "pn": pn,
            "ps": ps,
            "contest_status": "",
            "stime": stime,
            "etime": etime,
        },
    )


def _fetch_match_info_raw(*, match_id):
    """Fetch series metadata and the detail JSON URL for every game."""
    from .zapi import bilibili_esports_get_json

    return bilibili_esports_get_json("/match/info", params={"cid": int(match_id), "platform": 2})


def _fetch_match_grade_raw(*, match_id, bo=None):
    """Fetch the Bilibili rating block for a series or a selected game."""
    from .zapi import bilibili_esports_get_json

    params = {"cid": int(match_id)}
    if bo is not None:
        params["bo"] = int(bo)
    return bilibili_esports_get_json("/grade/info", params=params)


def _fetch_game_detail_raw(*, detail_url):
    """Fetch one detail-wrap data document referenced by match/info."""
    url = str(detail_url or "").replace("http://", "https://", 1)
    if not url:
        raise ValueError("kpl_game_detail_error: empty detail_url")

    from .zapi import bilibili_esports_get_json

    return bilibili_esports_get_json(url)


def load_match_asset_bytes(asset_url):
    """Fetch an image asset referenced by normalized KPL match detail JSON."""
    url = str(asset_url or "").replace("http://", "https://", 1)
    if not url:
        raise ValueError("kpl_asset_error: empty asset_url")

    from .zapi import bilibili_esports_get_bytes

    return bilibili_esports_get_bytes(url)


def _safe_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _team(raw, *, score=None):
    raw = raw or {}
    logo = raw.get("logo") or raw.get("icon") or raw.get("team_image_thumb") or ""
    if logo.startswith("/"):
        logo = f"https://i0.hdslb.com{logo}"
    return {
        "id": raw.get("id") or raw.get("team_id"),
        "name": raw.get("title") or raw.get("name") or raw.get("team_name") or "",
        "logo": logo,
        "score": _safe_int(score if score is not None else raw.get("score")),
    }


def _rating_player(raw):
    raw = raw or {}
    return {
        "player_id": raw.get("player_id"),
        "name": raw.get("nickname") or raw.get("name") or "",
        "position": raw.get("position") or raw.get("place") or "",
        "rating": raw.get("avg_grade"),
        "rating_users": _safe_int(raw.get("grade_users")),
        "kills": _safe_int(raw.get("kill")),
        "deaths": _safe_int(raw.get("death")),
        "assists": _safe_int(raw.get("assist")),
        "portrait": raw.get("portrait") or "",
        "hero_image": raw.get("hero_photo") or "",
        "grade_distribution": raw.get("grade_distribution"),
    }


def _rating_teams(raw_data):
    result = []
    for block in (raw_data or {}).get("teams") or []:
        if not isinstance(block, dict):
            continue
        result.append(
            {
                **_team(block),
                "place_id": block.get("place_id"),
                "players": [
                    _rating_player(player)
                    for player in block.get("player_grade_detail") or []
                    if isinstance(player, dict)
                ],
            }
        )
    return result


def _resource_list(entries):
    result = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        result.append(
            {
                "name": entry.get("name") or "",
                "values": [
                    {"image": item.get("image") or "", "count": _safe_int(item.get("num"), 0)}
                    for item in entry.get("value") or []
                    if isinstance(item, dict)
                ],
            }
        )
    return result


def _game_player(raw):
    raw = raw or {}
    return {
        "player_id": raw.get("player_id"),
        "position_id": raw.get("position_id"),
        "name": raw.get("nickname") or "",
        "portrait": raw.get("player_image_thumb") or "",
        "hero_image": raw.get("hero_image") or "",
        "is_mvp": bool(raw.get("mvp")),
        "hero_level": _safe_int(raw.get("champ_level")),
        "kills": _safe_int(raw.get("kills"), 0),
        "deaths": _safe_int(raw.get("deaths"), 0),
        "assists": _safe_int(raw.get("assists"), 0),
        "gold": _safe_int(raw.get("money"), 0),
        "hero_damage": _safe_int(raw.get("damage_dealt_to_champions"), 0),
        "damage_taken": _safe_int(raw.get("total_damage_taken"), 0),
        "items": list(raw.get("device_list") or []),
        "metrics": [
            {"name": item.get("name") or "", "type": item.get("type") or "", "value": item.get("value")}
            for item in raw.get("ext1") or []
            if isinstance(item, dict)
        ],
        "resources": _resource_list(raw.get("ext2")),
    }


def _game_team(raw):
    raw = raw or {}
    return {
        **_team(raw),
        "won": bool(raw.get("win")),
        "kills": _safe_int(raw.get("kills"), 0),
        "deaths": _safe_int(raw.get("deaths"), 0),
        "assists": _safe_int(raw.get("assists"), 0),
        "gold": _safe_int(raw.get("money"), 0),
        "towers": _safe_int(raw.get("tower"), 0),
        "hero_damage": _safe_int(raw.get("damage_dealt_to_champions"), 0),
        "bans": list(raw.get("ban_list") or []),
        "picks": list(raw.get("pick_list") or []),
        "objectives": _resource_list(raw.get("ext2")),
        "players": [_game_player(item) for item in raw.get("player_list") or [] if isinstance(item, dict)],
    }


def _schedule_item(raw, *, mid, time_ms):
    home = _team(raw.get("home_team"), score=raw.get("home_score"))
    away = _team(raw.get("away_team"), score=raw.get("away_score"))
    match_id = raw.get("id")
    return {
        "match_id": match_id,
        "season_id": raw.get("sid") or raw.get("season_id"),
        "season_name": (raw.get("season") or {}).get("title") or "",
        "match_name": raw.get("title") or raw.get("game_stage") or "",
        "game_stage": raw.get("game_stage") or "",
        "start_time": _safe_int(raw.get("stime")),
        "end_time": _safe_int(raw.get("etime")),
        "status": raw.get("contest_status", raw.get("status")),
        "game_state": raw.get("game_state"),
        "live_room": raw.get("live_room"),
        "home_team": home,
        "away_team": away,
        "score": {"home": home.get("score"), "away": away.get("score")},
        "links": {
            "schedule": f"https://www.bilibili.com/v/game/match/schedule?mid={mid}&gid=0&tid=0&time={time_ms}",
            "detail": f"https://www.bilibili.com/v/game/match/singledata/{match_id}?tab=2" if match_id else "",
        },
    }


def get_match_list_json(*, mid=94, gid=0, tid=0, time_ms=None, date=None, ps=50, raw_response=None):
    """Return all matches shown for one selected schedule date as JSON data."""
    from .ztime import date_start_epoch_ms, epoch_ms_to_date, time_r

    if time_ms is None:
        time_ms = date_start_epoch_ms(time_r())
    selected_date = date or epoch_ms_to_date(time_ms)

    if raw_response is not None:
        pages = [raw_response]
    else:
        pages = []
        pn = 1
        while True:
            page_payload = _fetch_match_list_raw(
                mid=mid, gid=gid, tid=tid, stime=selected_date, etime=selected_date, pn=pn, ps=ps
            )
            pages.append(page_payload)
            data = page_payload.get("data") or {}
            page = data.get("page") or {}
            total = _safe_int(page.get("total"), len(data.get("list") or [])) or 0
            if pn * ps >= total:
                break
            pn += 1

    raw_items = []
    for payload in pages:
        raw_items.extend(((payload or {}).get("data") or {}).get("list") or [])
    matches = [_schedule_item(item, mid=mid, time_ms=time_ms) for item in raw_items if isinstance(item, dict)]
    matches.sort(key=lambda item: item.get("start_time") or 0)
    return {
        "query": {"mid": mid, "gid": gid, "tid": tid, "date": selected_date, "time_ms": time_ms},
        "count": len(matches),
        "matches": matches,
        "raw": pages,
    }


def get_match_detail_json(match_params=None, *, match_id=None, raw_info=None, raw_grades=None, raw_games=None):
    """Return series score, ratings, and every detail-wrap game as JSON data."""
    params = dict(match_params or {})
    match_id = match_id or params.get("match_id") or params.get("cid") or params.get("id")
    if match_id is None:
        raise ValueError("match_params 缺少必要字段 match_id/cid")
    match_id = int(match_id)

    from .ztime import epoch_to_text

    info_payload = raw_info if raw_info is not None else _fetch_match_info_raw(match_id=match_id)
    info = (info_payload or {}).get("data") or {}
    contest = info.get("contest") or {}
    detail_refs = info.get("detail") or []
    raw_grades = list(raw_grades or [])
    raw_games = list(raw_games or [])

    games = []
    for index, detail_ref in enumerate(detail_refs, start=1):
        if not isinstance(detail_ref, dict):
            continue
        game_raw = raw_games[index - 1] if index <= len(raw_games) else _fetch_game_detail_raw(
            detail_url=detail_ref.get("bfs_url")
        )
        grade_payload = raw_grades[index - 1] if index <= len(raw_grades) else _fetch_match_grade_raw(
            match_id=match_id, bo=index
        )
        grade_data = (grade_payload or {}).get("data") or {}
        left = _game_team((game_raw or {}).get("team_left"))
        right = _game_team((game_raw or {}).get("team_right"))
        games.append(
            {
                "game_number": index,
                "game_id": (game_raw or {}).get("game_id"),
                "point_data": detail_ref.get("point_data"),
                "duration_seconds": _safe_int((game_raw or {}).get("game_time"), 0),
                "game_type": (game_raw or {}).get("game_type") or "",
                "game_map": (game_raw or {}).get("game_map") or "",
                "winner_team_id": left.get("id") if left.get("won") else right.get("id"),
                "teams": [left, right],
                "ratings": _rating_teams(grade_data),
                "video": {
                    "aid": detail_ref.get("aid"),
                    "url": detail_ref.get("url") or "",
                    "duration": detail_ref.get("duration"),
                    "views": detail_ref.get("view"),
                    "danmaku": detail_ref.get("danmaku"),
                },
                "source_url": str(detail_ref.get("bfs_url") or "").replace("http://", "https://", 1),
            }
        )

    data_warnings = []
    if not detail_refs:
        data_warnings.append(
            "KPL_DETAIL_EMPTY: Bilibili match/info.detail is empty; per-game detail-wrap data is unavailable."
        )

    home = _team(contest.get("home_team") or contest.get("home"), score=contest.get("home_score"))
    away = _team(contest.get("away_team") or contest.get("away"), score=contest.get("away_score"))
    overall_grade_payload = _fetch_match_grade_raw(match_id=match_id)
    start_time = _safe_int(contest.get("stime") or contest.get("start_time"))
    end_time = _safe_int(contest.get("etime") or contest.get("end_time"))
    return {
        "match_id": match_id,
        "season": contest.get("season") or {},
        "match_name": contest.get("title") or contest.get("game_stage") or f"KPL Match {match_id}",
        "game_stage": contest.get("game_stage") or "",
        "start_time": start_time,
        "start_time_text": epoch_to_text(start_time),
        "end_time": end_time,
        "end_time_text": epoch_to_text(end_time),
        "status": contest.get("contest_status", contest.get("status")),
        "home_team": home,
        "away_team": away,
        "score": {"home": home.get("score"), "away": away.get("score")},
        "overall_ratings": _rating_teams((overall_grade_payload or {}).get("data") or {}),
        "games": games,
        "data_warnings": data_warnings,
        "links": {
            "detail": f"https://www.bilibili.com/v/game/match/singledata/{match_id}?tab=2",
            "playback": contest.get("playback") or contest.get("collection_url") or "",
        },
        "raw": {"match_info": info_payload, "overall_grade": overall_grade_payload},
    }


def get_full_match_list(*, mid=94, time_ms=None, now=None, ps=50, tz_name="Asia/Shanghai"):
    """Compatibility formatter backed by get_match_list_json."""
    from .ztime import time_r

    now = now or time_r()
    payload = get_match_list_json(mid=mid, time_ms=time_ms, ps=ps)
    now_epoch = int(now.timestamp())
    groups = {"finished": [], "ongoing": [], "upcoming": []}
    rows = []
    for match in payload.get("matches") or []:
        stime = match.get("start_time") or 0
        etime = match.get("end_time") or 0
        status = "upcoming" if now_epoch < stime else ("finished" if etime and now_epoch >= etime else "ongoing")
        row = {
            "cid": match.get("match_id"),
            "title": match.get("match_name"),
            "game_stage": match.get("game_stage"),
            "stime": stime,
            "etime": etime,
            "home": match.get("home_team") or {},
            "away": match.get("away_team") or {},
            "score": match.get("score") or {},
            "status": status,
        }
        rows.append(row)
        groups[status].append(row)
    return {
        "mid": mid,
        "time": payload.get("query", {}).get("time_ms"),
        "now_epoch": now_epoch,
        "ps": ps,
        "counts": {"total": len(rows), **{key: len(value) for key, value in groups.items()}},
        "groups": groups,
        "list": rows,
    }


def get_match_content(match_params):
    """Compatibility alias backed by get_match_detail_json."""
    return get_match_detail_json(match_params)

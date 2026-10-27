"""Recent game-time summaries and group rankings."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import zapi, zfile, ztime


def _runtime():
    from .. import zfunc

    return zfunc


def recentgames_process(realname):
    runtime = _runtime()
    display_name = runtime.namenick.get(realname, realname)
    rows, _ = _gametime_rows(14)
    player = next((row for row in rows if row["realname"] == realname), None)
    total_hours = player["total"] if player else 0.0
    all_hours = sum(row["total"] for row in rows)
    share = total_hours / all_hours * 100 if all_hours else 0.0
    game_list = [
        f"{'👑' if game == '王者荣耀' else '♨️'} {game}: {hours:.1f}h"
        for game, hours in (player["games"] if player else {}).items()
    ]
    result = f"🎮 {display_name} 最近2周的游戏时长：\n"
    if game_list:
        result += "\n".join(game_list) + f"\n\n📊 总计时长：{total_hours:.1f}h"
    else:
        result += "最近2周没有游戏记录哦~"
    return result + f"\n📈 占所有玩家总时长：{share:.1f}%"


def _steam_games_by_player(api_key, steam_userlist):
    tasks = [
        (realname, steam_id)
        for realname, steam_id in steam_userlist.items()
        if steam_id
    ]
    results = {}
    if not api_key or not tasks:
        return results
    max_workers = min(8, max(1, len(tasks)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(zapi.steam_api_recent_games, api_key, steam_id): realname
            for realname, steam_id in tasks
        }
        for future in as_completed(futures):
            realname = futures[future]
            try:
                results[realname] = future.result() or []
            except Exception as exc:
                raise Exception(
                    f"steam_recent_games_error: {realname} {repr(exc)}"
                )
    return results


def _sorted_games(rows, all_games):
    if not all_games:
        return []
    sums = {}
    for item in rows:
        for game, value in (item.get("games") or {}).items():
            sums[game] = sums.get(game, 0) + float(value or 0)
    other_games = [game for game in all_games if game != "王者荣耀"]
    other_games.sort(key=lambda game: sums.get(game, 0), reverse=True)
    return (["王者荣耀"] if "王者荣耀" in all_games else []) + other_games


def _gametime_rows(days):
    """Collect both sources once, keeping full precision for totals and shares."""
    runtime = _runtime()
    end_date = ztime.time_r()
    start_date = ztime.time_delta(end_date, -days)
    steam_games = _steam_games_by_player(
        runtime.confs.get("Steam", {}).get("api_key"),
        runtime.steam_userlist,
    )
    history, _ = runtime.fetch_history(
        start_date=start_date, end_date=end_date, filter_official=False,
    ) if runtime.userlist else ({}, 0)

    raw_rows = []
    all_games = set()
    realnames = sorted(set(runtime.userlist) | set(runtime.steam_userlist))
    for realname in realnames:
        per_game = {}
        wzry_hours = sum(
            detail.get("Duration_Second", 0)
            for detail in history.get(realname, [])
        ) / 3600.0 if runtime.userlist.get(realname) else 0.0
        if wzry_hours > 0:
            per_game["王者荣耀"] = wzry_hours
        steam_hours = 0.0
        if runtime.steam_userlist.get(realname):
            for game in steam_games.get(realname, []):
                hours = game.get("playtime_2weeks", 0) / 60.0
                if hours <= 0:
                    continue
                steam_hours += hours
                game_name = game.get("name") or "Unknown"
                per_game[game_name] = per_game.get(game_name, 0) + hours
        total_hours = wzry_hours + steam_hours
        if total_hours <= 0:
            continue
        raw_rows.append(
            {
                "realname": realname,
                "player": runtime.namenick.get(realname, realname),
                "total": float(total_hours),
                "games": per_game,
            }
        )
        all_games.update(per_game)
    return raw_rows, all_games


def gametime_rank_process(days=14):
    from ..tools import gen_gametime_table
    from ..tools.gen_gametime_table import merge_gametime_rows

    runtime = _runtime()
    raw_rows, all_games = _gametime_rows(days)
    rows = merge_gametime_rows(
        raw_rows,
        getattr(runtime, "sameuser", {}),
        namenick=runtime.namenick,
    )
    if not rows:
        return f"最近{days}天没有可用的时长记录", ""

    filename_hash = runtime.WebArtifacts.make_hash(
        str(ztime.current_epoch_microseconds())
    )
    picture_path = zfile.gametime_rank_image_path(filename_hash)
    gen_gametime_table.gen(
        rows,
        _sorted_games(rows, all_games),
        picture_path,
        title=f"最近{days}天游戏时长排行",
    )
    return "", picture_path

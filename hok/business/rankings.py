"""Group ranking aggregation and presentation."""

import json

from .. import zfile
from ..zfile import write_daily_history_export
from ..zstatic import namenick, roleidlist, this_season_start_date, userlist


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def compact_report_value(value, max_len=220):
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
    except Exception:
        text = repr(value)
    text = str(text).replace("\n", " ").replace("\r", " ")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def build_traversal_error(source, realname, params, error):
    return {
        "source": source,
        "name": realname,
        "nickname": namenick.get(realname, realname),
        "params": params,
        "error": repr(error),
    }


def format_traversal_error_report(title, errors):
    if not errors:
        return ""
    lines = [f"{title}异常汇总 count={len(errors)}"]
    for index, item in enumerate(errors, 1):
        name = item.get("name", "")
        nickname = item.get("nickname", name)
        source = item.get("source", "")
        params = compact_report_value(item.get("params", {}), 260)
        error = compact_report_value(item.get("error", ""), 180)
        lines.append(
            f"{index}. {source} {nickname}/{name} params={params} err={error}"
        )
    return "\n".join(lines)


def peak_rank_process(player_names=None):
    requested_names = set(
        player_names if player_names is not None else userlist.keys()
    )
    latest_records = {}
    for history_date in zfile.list_history_dates_descending(
        start_date=this_season_start_date
    ):
        if not requested_names:
            break
        daily_data = zfile.read_history_date(history_date)
        if not isinstance(daily_data, list):
            continue
        for player in daily_data:
            if not isinstance(player, dict):
                continue
            realname = str(player.get("key") or "").strip()
            if realname not in requested_names:
                continue
            valid_details = []
            for index, detail in enumerate(player.get("details") or []):
                if not isinstance(detail, dict):
                    continue
                try:
                    peak_score = int(detail.get("PeakGradeAfterGame"))
                except (TypeError, ValueError):
                    continue
                if peak_score <= 0:
                    continue
                try:
                    timestamp = int(detail.get("GameTime_Timestamp") or 0)
                except (TypeError, ValueError):
                    timestamp = 0
                valid_details.append((timestamp, index, peak_score))
            if not valid_details:
                continue
            _, _, peak_score = max(
                valid_details,
                key=lambda item: (item[0], item[1]),
            )
            latest_records[realname] = {
                "realname": realname,
                "name": namenick.get(realname)
                or player.get("nickname")
                or realname,
                "score": peak_score,
                "date": history_date,
            }
            requested_names.remove(realname)
    ranking = sorted(
        latest_records.values(),
        key=lambda item: (-item["score"], item["name"], item["realname"]),
    )
    if not ranking:
        return "【巅峰排名】\n本地历史中暂无有效巅峰数据"
    lines = ["【巅峰排名】"]
    for index, item in enumerate(ranking, 1):
        lines.append(f"{index}. {item['name']}  {item['score']}")
    return "\n".join(lines)


def inactivity_rank_process(player_names=None):
    """Rank saved battles across all modes without requesting game providers."""
    from .. import ztime

    names = list(dict.fromkeys(player_names if player_names is not None else userlist))
    now = ztime.current_epoch_seconds()
    records = zfile.read_latest_player_activity(names, before_epoch=now)
    ranked, other = [], []
    for realname in names:
        record = records.get(realname, {})
        name = namenick.get(realname) or record.get("nickname") or realname
        timestamp = record.get("last_game_epoch")
        if record.get("visible") is False:
            other.append((name, "最近归档战绩隐藏"))
        elif timestamp is None:
            other.append((name, "暂无有效本地对局"))
        else:
            ranked.append((timestamp, name, realname))

    lines = ["【多久没打了排名】", "按距最近收录对局时间从长到短排列（全模式）"]
    dates = [str(row["snapshot_date"]) for row in records.values() if row.get("snapshot_date")]
    if dates:
        lines.append(f"最新归档日期：{max(dates)}")
    for index, (timestamp, name, _) in enumerate(sorted(ranked), 1):
        elapsed = inactivity_duration_text(now - timestamp)
        last_played = ztime.epoch_to_text(timestamp, "%Y-%m-%d %H:%M", "Asia/Shanghai")
        lines.append(f"{index}. {name}  {elapsed}（最近 {last_played}）")
    if not ranked:
        lines.append("暂无可参与排名的对局记录")
    if other:
        lines.append("\n未参与排名：")
        lines.extend(f"{name}  {status}" for name, status in other)
    lines.append("\n仅依据已保存战绩；采集缺档不代表没有游玩，不代表离线时长。")
    return "\n".join(lines)


def inactivity_duration_text(seconds):
    days, remainder = divmod(max(0, int(seconds)), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{minutes}分钟"
    return f"{minutes}分钟" if minutes else "不足1分钟"


def rnk_process(rcv_msg, caller=None, show_zero=True, show_analyze=False, debug=False):
    """Refresh daily battles as before, then deliver the approved shared image.

    Legacy presentation switches remain accepted; the image always includes idle
    players and no longer requests AI commentary or produces text ranking lists.
    """
    from .. import ztime
    from .daily_report import build_daily_report, render_daily_report_file

    report_date = ztime.time_sul().strftime("%Y-%m-%d")
    gameinfo, errors, failed = [], [], set()
    for realname in userlist:
        try:
            gameinfo.append(_zfunc_attr("wzry_data")(realname=realname))
        except Exception as error:
            failed.add(realname)
            errors.append(build_traversal_error("rank.wzry_data", realname, {}, error))
    if not gameinfo:
        return {"text": "王者荣耀数据源错误，暂无可用排行数据", "image_path": None,
                "error_report": format_traversal_error_report("排行遍历", errors)}

    # Preserve already-saved records of failed accounts without presenting them as fresh results.
    previous = zfile.read_history_date(report_date) if failed else []
    retained = [row for row in previous if isinstance(row, dict) and row.get("key") in failed]
    write_daily_history_export(report_date, retained + gameinfo)
    now = ztime.current_epoch_seconds()
    try:
        activity = zfile.read_latest_player_activity(list(userlist), before_epoch=now)
    except Exception as error:
        activity = {}
        errors.append(build_traversal_error("rank.saved_activity", "", {}, error))
    # Query errors may use saved game display fields, but their daily metrics stay unknown.
    report = build_daily_report(retained + gameinfo, list(userlist), activity,
                                report_date=report_date, now=now, failed=failed)
    path = render_daily_report_file(report)
    return {"text": "", "image_path": path,
            "error_report": format_traversal_error_report("排行遍历", errors)}

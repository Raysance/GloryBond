"""Structured battle-history reads with an emergency JSON fallback."""

import logging

from .. import zdb, zfile, ztime
from ..zstatic import record_begin_date, userlist


def _runtime():
    from .. import zfunc

    return zfunc


def _normalized_range(start_date, end_date):
    earliest = ztime.str_to_time(record_begin_date)
    if not start_date or start_date < earliest:
        start_date = earliest
    if not end_date:
        end_date = ztime.time_r()
    return start_date, end_date


def _fetch_json_fallback(userid, start_date, end_date, filter_official):
    game_details = {}
    duration = 0
    runtime = _runtime()
    for history_date in zfile.list_history_archive_dates_descending():
        date_parsed = ztime.str_to_time(history_date)
        if date_parsed > end_date or date_parsed < start_date:
            continue
        duration += 1
        for player in zfile.read_history_archive_date(history_date):
            player_name = player["key"]
            player_details = player["details"][::-1]
            if filter_official:
                player_details = [
                    detail
                    for detail in player_details
                    if runtime.check_btl_official(detail["MapName"])
                ]
            game_details.setdefault(player_name, []).extend(player_details)
    if userid:
        game_details = {
            name: details
            for name, details in game_details.items()
            if userid == userlist[name]
        }
    return game_details, duration


def fetch_history(userid=None, start_date=None, end_date=None, filter_official=True):
    start_date, end_date = _normalized_range(start_date, end_date)
    try:
        return zdb.fetch_history(
            userid=userid,
            start_date=start_date,
            end_date=end_date,
            filter_official=filter_official,
        )
    except Exception as exc:
        _runtime().log_message(
            f"POSTGRES_FETCH_HISTORY_FALLBACK: userid={userid} start={start_date} "
            f"end={end_date} official={filter_official} error={repr(exc)}",
            logging.WARNING,
        )
    return _fetch_json_fallback(
        userid,
        start_date,
        end_date,
        filter_official,
    )

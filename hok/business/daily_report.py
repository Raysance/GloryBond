"""Daily report values and avatar preparation shared by query and scheduled delivery."""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from .. import zfile, ztime


def _integer(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(value)
        return result if str(value).strip() == str(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def build_daily_report(players, player_names, activity, *, report_date, now, failed=()):
    """Use game names, preserve unknowns, and derive inactivity only from saved games."""
    by_name = {row['key']: row for row in players}
    failed = set(failed)
    rows = []
    for key in player_names:
        player = by_name.get(key, {})
        previous = activity.get(key, {})
        hidden = player.get('visible', previous.get('visible')) is False
        available = key not in failed and player.get('visible') is True
        details = player.get('details')
        games = _integer(player.get('today_num')) if available else None
        if games is not None and games < 0:
            games = None
        stars = _integer(player.get('star_up')) if available and player.get('profile_available', True) else None
        peak = None
        if available and isinstance(details, list):
            if any(isinstance(detail, dict) and detail.get('MapType') == 1
                   and detail.get('Source') == 'player_client' for detail in details):
                stars = None
            peak = 0
            for detail in details:
                if not isinstance(detail, dict):
                    peak = None
                    break
                if detail.get('MapType') != -1:
                    continue
                before = _integer(detail.get('PeakGradeBeforeGame'))
                after = _integer(detail.get('PeakGradeAfterGame'))
                if detail.get('Source') == 'player_client' or before is None or after is None or min(before, after) <= 0:
                    peak = None
                    break
                peak += after - before
        timestamps = [previous.get('last_game_epoch')]
        timestamps.extend(detail.get('GameTime_Timestamp') for detail in (details or []) if isinstance(detail, dict))
        valid = [value for raw in timestamps if (value := _integer(raw)) is not None and 0 < value <= now]
        status = '战绩隐藏' if hidden else '查询失败' if key in failed else ''
        rows.append({
            'key': key, 'name': player.get('nickname') or previous.get('nickname') or '昵称未收录',
            'avatar_url': player.get('avatar_url'), 'games': games, 'stars': stars, 'peak': peak,
            'last': max(valid) if valid and not hidden else None, 'status': status,
        })
    return {'date': report_date, 'asof': now,
            'asof_text': ztime.epoch_to_text(now, timezone_name='Asia/Shanghai'), 'rows': rows}


def _avatar(url):
    # The saved role icon is public media; no account credentials or profile refresh.
    parts = urlsplit(str(url or ''))
    if parts.scheme not in {'http', 'https'} or parts.username or parts.password or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if not any(host == suffix or host.endswith('.' + suffix) for suffix in ('qq.com', 'qpic.cn', 'qlogo.cn', 'gtimg.cn', 'gtimg.com')):
        return None
    return zfile.load_battle_report_image(url, max_cache_age=7 * 86400)


def render_daily_report_file(report):
    from ..tools.gen_daily_report import render_daily_report
    from ..zutil import log_message

    avatars = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {row['key']: pool.submit(_avatar, row.get('avatar_url')) for row in report['rows']}
        for key, future in futures.items():
            try:
                avatar = future.result()
                if avatar is not None:
                    avatars[key] = avatar
            except Exception as error:
                log_message(f'DAILY_REPORT_AVATAR_FAILED: error_type={type(error).__name__}')
    return zfile.save_daily_report_image(render_daily_report(report, avatars))

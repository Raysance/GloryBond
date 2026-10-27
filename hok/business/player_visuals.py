"""Player grade-chart and live-battle screenshot workflows."""

from .. import zdynamic as dmc
from ..zstatic import namenick, record_begin_date, roleidlist, userlist


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def gradeanalyze_process(realname):
    from ..tools import gen_grade_chart
    from ..zfile import grade_chart_output_paths
    from ..ztime import str_to_time, time_r

    userid = userlist[realname]
    picture_path, output_directory = grade_chart_output_paths()
    history_data, _ = _zfunc_attr("fetch_history")(
        userid=userid,
        start_date=str_to_time(record_begin_date),
        end_date=time_r(),
        filter_official=True,
    )
    analyze_message = gen_grade_chart.gen_from_history(
        userid,
        namenick.get(realname, realname),
        history_data.get(realname, []),
        output_directory,
    )
    return picture_path, analyze_message


def watchbattle_process(realname):
    from ..tools import gen_battle_shot
    from ..zfile import watch_battle_shot_path

    userid = userlist[realname]
    roleid = roleidlist[realname]
    battle_list = _zfunc_attr("wzry_get_official")(
        reqtype="btlist",
        userid=userid,
        roleid=roleid,
    )
    if not battle_list["isGaming"]:
        return None, None
    gaming = battle_list["gaming"]
    if not gaming["canBeWatch"]:
        return None, None

    save_path = watch_battle_shot_path(roleid)
    if dmc.RTMPListener:
        dmc.RTMPListener.stop()
    dmc.RTMPListener = gen_battle_shot.RTMPListener(
        dmc.streamurl,
        save_path=save_path,
        roleid=roleid,
    )
    dmc.RTMPListener.start()
    dmc.RTMPListener.screenshot()
    return save_path, None

"""Player hero-power and commonly played hero summaries."""

from ..zstatic import namenick, roleidlist, userlist


def _official_request(**kwargs):
    from .. import zfunc

    return zfunc.wzry_get_official(**kwargs)


def heropower_process(realname):
    result = _official_request(
        reqtype="heropower",
        userid=userlist[realname],
        roleid=roleidlist[realname],
    )
    message = f"{namenick[realname]}的战力英雄\n─────────────\n"
    for hero in result["heroList"]:
        try:
            region_name = hero["honorTitle"]["desc"]["full"].split("第")[0]
            hero["honorTitle"]["desc"]["abbr"].split("第")[0]
            message += f"【{hero['basicInfo']['title']}】"
            message += f" {hero['basicInfo']['heroFightPower']}\n"
            message += f" {region_name}  第 {hero['honorTitle']['rank']} 名\n\n"
        except Exception:
            pass
    return message


def allhero_process(realname):
    result = _official_request(
        reqtype="allhero",
        userid=userlist[realname],
        roleid=roleidlist[realname],
    )
    message = f"{namenick[realname]}的拿手英雄\n"
    hero_count = 0
    for hero in result["heroList"]:
        if hero_count > 5:
            break
        hero_count += 1
        message += f"{hero['name']}： {hero['heroFightPower']}\n"
        message += f"   {hero['playNum']}场 {hero['winRate']}\n"
    return message

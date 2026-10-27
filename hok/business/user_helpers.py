"""Small user-identity, greeting, emoji, and parsing helpers."""

from urllib.parse import parse_qs, urlparse

from agent_console.tools.reference_data import account_id_binding

from .. import zapi, zfile, ztime
from ..zstatic import (
    confs,
    emoji_pmpt,
    extra_useridlist,
    namenick,
    nameref,
    qid,
    sameuser,
    userlist,
    roleidlist,
)
from .history_query import txt_contain


def generate_greeting():
    current_hour = ztime.time_r().hour
    if 5 <= current_hour < 12:
        return "早上好"
    if 12 <= current_hour < 14:
        return "中午好"
    if 14 <= current_hour < 18:
        return "下午好"
    if 18 <= current_hour < 23:
        return "晚上好"
    return "这么晚还不睡吗"


def qid2realname(user_qid):
    matches = [key for key, value in qid.items() if str(value) == str(user_qid)]
    return matches[0] if matches else None


def qid2nick(user_qid):
    realname = qid2realname(user_qid)
    return namenick.get(realname, "") if realname else ""


def resolve_chat_qq_ids(players=(), qq_ids=()):
    """Resolve exact player aliases; never interpret a game ID as a QQ filter."""
    resolved = []
    keys = set(qid) | set(namenick) | set(nameref) | set(userlist) | set(roleidlist)
    for player in players:
        label = str(player).strip().casefold()
        matches = [name for name in keys if label == str(name).casefold()]
        matches = matches or [name for name in keys if label in
                   {str(value).casefold() for value in [name, namenick.get(name, ""), *nameref.get(name, [])] if value}]
        bindings = [account_id_binding(name, qid, sameuser)[0] for name in matches]
        targets = {value for ids in bindings for value in ids}
        if not bindings or any(len(ids) != 1 for ids in bindings) or len(targets) != 1:
            raise ValueError(f"chat_player_identity: {player!r} 必须匹配唯一玩家别名；可改传明确的 qq_ids")
        resolved.extend(targets)
    known_qq = {str(value) for value in qid.values()}
    for value in qq_ids:
        identity = str(value).strip()
        if not identity.isascii() or not identity.isdecimal() or int(identity) <= 0:
            raise ValueError("chat_qq_id: qq_ids 必须填写 QQ 号")
        game_matches = [name for name in keys if identity in
                        {str(userlist.get(name, "")), str(roleidlist.get(name, ""))}]
        if identity not in known_qq and game_matches:
            suggestions = [{"player": name, "qq_ids": account_id_binding(name, qid, sameuser)[0]}
                           for name in sorted(game_matches)]
            raise ValueError(f"chat_game_id_not_qq: {identity} 是营地/游戏 ID；请传 players 或 QQ 号：{suggestions}")
        resolved.append(identity)
    return list(dict.fromkeys(resolved))


def get_emoji(text):
    emoji_reference = {
        key: value["content"]
        for key, value in zfile.read_emoji_reference().items()
    }
    prompt = (
        emoji_pmpt[0]
        + emoji_pmpt[1]
        + str(emoji_reference)
        + emoji_pmpt[2]
        + text
        + emoji_pmpt[3]
    )
    return int(zapi.ai_api(prompt, temperature=2))


def get_emoji_url(index):
    domain = confs["WebService"]["server_domain"]
    return f"http://{domain}/doraemon_emojis/{index}.jpg"


def extract_url_params(url):
    params = parse_qs(urlparse(url).query)
    return {
        key: values[0] if len(values) == 1 else values
        for key, values in params.items()
    }


def get_peak_alter_list(details, processed, reverse=1):
    items = []
    if not processed:
        for detail in details:
            if detail["MapType"] != -1:
                continue
            items.append(
                {
                    "PeakBefore": detail["PeakGradeBeforeGame"],
                    "PeakAfter": detail["PeakGradeAfterGame"],
                    "used": False,
                }
            )
    else:
        for detail in details:
            items.append(
                {
                    "PeakBefore": detail[0],
                    "PeakAfter": detail[1],
                    "used": False,
                }
            )
    if reverse == -1:
        items = items[::-1]
    changes = []
    for first in items:
        if first["used"]:
            continue
        first["used"] = True
        peak_before = first["PeakBefore"]
        peak_after = first["PeakAfter"]
        for following in items:
            if following["used"]:
                continue
            if following["PeakBefore"] == peak_after:
                peak_after = following["PeakAfter"]
                following["used"] = True
        changes.append([peak_before, peak_after])
    return changes


def extract_name(from_text, precise=False):
    for is_origin in (True, False):
        for realname, nicknames in nameref.items():
            for nickname in nicknames:
                if txt_contain(nickname, from_text, precise, is_origin):
                    return realname
    for realname in extra_useridlist:
        if txt_contain(realname, from_text, True, True):
            return realname
    return None

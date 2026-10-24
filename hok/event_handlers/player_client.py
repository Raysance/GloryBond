"""Parse the explicit standalone-client command namespace and dispatch queries."""
import asyncio
import json
import shlex

ALIASES = {
    "主页": "homepage", "资料": "profile", "战绩": "history", "英雄": "heroes",
    "统计": "game", "游戏统计": "game", "资产": "hero_assets", "收藏": "collections",
    "皮肤": "displayed_skins", "英雄之路": "hero_road_brief", "英雄详情": "hero_detail",
    "称号": "hero_titles", "搜索": "search",
}
HELP = ("客户端查询：#客户端 <接口> [玩家] [参数]\n"
        "接口：主页、资料、战绩、英雄、游戏统计（或统计）、资产、收藏、皮肤、英雄之路、英雄详情、称号、搜索。\n"
        "玩家可用配置昵称或账号键，省略为本人；英雄可追加 all/season/year，默认以图片展示场次最多的前几个英雄。\n"
        "英雄详情支持英雄名、配置别名或数字ID；例如：#客户端 战绩 我；#客户端 英雄 example_user_10 season；#客户端 英雄详情 example_user_10 小乔；"
        "#客户端 搜索 完整游戏昵称 [all/android/ios]。仅查询，不自动绑定搜索结果。\n"
        "也可发送 #玩家的英雄名、#玩家的英雄（本赛季）、#玩家的数据；例如 #我的小乔、#示例玩家65的英雄。")


def parse_client_command(text):
    text = text.strip()
    if not text.startswith(("#客户端", "＃客户端")):
        return None
    tail = text[4:]
    if tail and not tail[0].isspace():
        return None
    try:
        return shlex.split(tail)
    except ValueError:
        return ["help"]


def resolve_hero_id(value, hero_names, hero_aliases):
    if value.isascii() and value.isdecimal() and 0 < int(value) < 2 ** 32:
        return int(value)
    matches = {int(key) for mapping in (hero_names, hero_aliases) for key, name in mapping.items()
               if str(key).isascii() and str(key).isdecimal() and 0 < int(key) < 2 ** 32 and name == value}
    if len(matches) != 1:
        raise ValueError("英雄名称未识别或不唯一，请使用配置中的完整英雄名、别名或数字ID")
    return matches.pop()


def _player_matches(target, settings, nicknames, player_aliases):
    keys = set(settings.get("players", {})) | set(nicknames) | set(player_aliases)
    return [key for key in keys if target.casefold() in {
        str(value).casefold() for value in (key, nicknames.get(key, ""), *player_aliases.get(key, ())) if value}]


def parse_client_shortcut(text, *, settings, nicknames, player_aliases, hero_names, hero_aliases):
    """Recognize a complete prefixed player query without invoking legacy business."""
    text = text.strip()
    if not text.startswith(("#", "＃")) or text[1:].startswith(("#", "＃")):
        return None
    raw = text[1:].strip()
    if "的" not in raw:
        return None
    player, item = (part.strip() for part in raw.rsplit("的", 1))
    if item.removeprefix("本赛季").removesuffix("本赛季").strip() == "英雄":
        player = player.removesuffix("本赛季").strip()
    if player.casefold() == "群u" or not player or not item:
        return None
    if player != "我" and not _player_matches(player, settings, nicknames, player_aliases):
        return None
    if item == "数据":
        return ["游戏统计", player]
    item = item.removeprefix("本赛季").removesuffix("本赛季").strip()
    if item == "英雄":
        return ["英雄", player, "season"]
    try:
        hero_id = resolve_hero_id(item, hero_names, hero_aliases)
    except ValueError:
        return None
    return ["英雄详情", player, str(hero_id)]


def parse_client_request(text):
    from ..zstatic import player_client_config, namenick, extra_namenick, nameref, HeroList, HeroName_replacements

    explicit = parse_client_command(text)
    if explicit is not None:
        return explicit
    return parse_client_shortcut(text, settings=player_client_config,
        nicknames={**extra_namenick, **namenick}, player_aliases=nameref,
        hero_names=HeroList, hero_aliases=HeroName_replacements)


def query_parameters(tokens, *, user_id, settings, qids, nicknames, hero_names=None, hero_aliases=None, player_aliases=None):
    if not tokens or tokens[0] in {"帮助", "help"}:
        return None
    operation = ALIASES.get(tokens[0], tokens[0])
    from ..api_adapters.player_client import OPERATIONS
    if operation not in OPERATIONS:
        raise ValueError("未知接口，请发送 #客户端 帮助")
    args = tokens[1:]
    if operation == "search":
        if not 1 <= len(args) <= 2 or (len(args) == 2 and args[1] not in {"all", "android", "ios"}):
            raise ValueError("用法：#客户端 搜索 完整游戏昵称 [all/android/ios]")
        platform = {"all": None, "android": 1, "ios": 2}[args[1]] if len(args) == 2 else None
        return operation, {"name": args[0], "platform": platform}, args[0]
    if operation == "hero_detail":
        if not 1 <= len(args) <= 2:
            raise ValueError("用法：#客户端 英雄详情 [玩家] 英雄名或ID，例如 #客户端 英雄详情 我 小乔")
        target, rest = ("我", args) if len(args) == 1 else (args[0], args[1:])
    else:
        target, rest = (args[0], args[1:]) if args else ("我", [])
    mappings = settings.get("players", {})
    if target == "我":
        matches = [key for key in mappings if str(qids.get(key, "")) == str(user_id)]
    else:
        matches = _player_matches(target, settings, nicknames, player_aliases or {})
    if len(matches) != 1 or matches[0] not in mappings:
        raise ValueError("玩家尚未绑定或昵称不唯一，请使用已配置的账号键")
    key = matches[0]
    parameters = {"player": mappings[key]}
    if operation == "heroes":
        if len(rest) > 1 or (rest and rest[0] not in {"all", "season", "year"}):
            raise ValueError("英雄范围只支持 all/season/year")
        parameters["scope"] = rest[0] if rest else "all"
    elif operation == "hero_detail":
        parameters["hero_id"] = resolve_hero_id(rest[0], hero_names or {}, hero_aliases or {})
    elif rest:
        raise ValueError("该接口不接受额外参数")
    return operation, parameters, str(nicknames.get(key, key))


def format_query_result(operation, label, result, settings):
    # Keep a bounded response; never claim clipped data is complete.
    body = json.dumps(result, ensure_ascii=False, indent=2)
    limit = int(settings["max_result_chars"])
    clipped = len(body) > limit
    body = body[:limit]
    text = f"{label} · 客户端 {operation}\n{body}"
    if clipped:
        text += "\n[结果超出展示额度，已截断；请使用更具体的接口]"
    if operation == "history":
        text += "\n仅为接口本次返回战绩，complete 表示本次返回结束，不代表全部历史。"
    size = int(settings["message_chars"])
    return [text[index:index + size] for index in range(0, len(text), size)]


async def command_reply(event):
    from ..zstatic import player_client_config, qid, namenick, extra_namenick, nameref, HeroList, HeroName_replacements
    from ..zfunc import player_client_query, player_client_hero_report
    from ..zapi import PlayerClientRateLimited

    try:
        parsed = query_parameters(parse_client_request(event.get_plaintext()) or [],
                                  user_id=event.get_user_id(), settings=player_client_config,
                                  qids=qid, nicknames={**extra_namenick, **namenick},
                                  hero_names=HeroList, hero_aliases=HeroName_replacements, player_aliases=nameref)
        if parsed is None:
            return [HELP]
        operation, parameters, label = parsed
    except ValueError as error:
        return [str(error)]
    try:
        result = await asyncio.to_thread(player_client_query, operation, **parameters)
        if operation == "heroes":
            return await asyncio.to_thread(player_client_hero_report, label, result)
        return format_query_result(operation, label, result, player_client_config)
    except asyncio.CancelledError:
        raise
    except PlayerClientRateLimited as error:
        return [f"客户端请求正在限速或冷却，请约 {error.retry_after} 秒后再试。没有自动重试。"]
    except Exception as error:
        # Library/transport exception text can contain account material.
        code = getattr(error, "code", None)
        suffix = f"，错误码 {code}" if isinstance(code, int) else ""
        return [f"客户端查询未完成（{type(error).__name__}{suffix}）。请检查玩家绑定、登录会话、隐私或网络状态。"]

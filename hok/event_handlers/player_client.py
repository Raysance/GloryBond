"""Parse the explicit standalone-client command namespace and dispatch queries."""
import asyncio
import shlex

ALIASES = {
    "主页": "homepage", "资料": "profile", "战绩": "history", "英雄": "heroes",
    "统计": "game", "游戏统计": "game", "资产": "hero_assets", "收藏": "collections",
    "皮肤": "displayed_skins", "英雄之路": "hero_road_brief", "英雄详情": "hero_detail",
    "称号": "hero_titles", "搜索": "search", "好友": "friends", "好友列表": "friends",
    "好友状态": "friend_states",
}
HELP = ("客户端查询：#客户端 <接口> [玩家] [参数]\n"
        "接口：主页、资料、战绩、英雄、游戏统计（或统计）、资产、收藏、皮肤、英雄之路、英雄详情、称号、搜索、好友、好友状态。\n"
        "#客户端 好友 [页码]、#客户端 好友状态 [页码] 查看当前登录角色的游戏好友；"
        "#客户端 好友状态 玩家 查看指定已绑定玩家。也可用 #客户端好友、#客户端好友状态。\n"
        "其他接口的玩家可用配置昵称或账号键，省略为本人；英雄可追加 all/season/year，默认按最高战力展示前几个英雄。\n"
        "英雄详情支持英雄名、配置别名或数字ID；例如：#客户端 战绩 我；#客户端 英雄 example_user_10 season；#客户端 英雄详情 example_user_10 小乔；"
        "#客户端 搜索 完整游戏昵称 [all/android/ios]。仅查询，不自动绑定搜索结果。\n"
        "也可发送 #我的资料、#玩家的英雄名、#玩家的英雄、#玩家的数据；英雄查询保留原有文案并附图片。\n"
        "数据默认当前赛季、所有游戏、全部分路；可追加当前赛年、全部比赛、中路/对抗路/发育路/打野/游走，"
        "例如 #我本赛季对抗路数据、#我游走本赛季数据、#我打野这个赛季的数据、#我的全部数据。"
        "必须带 # 或 ＃ 前缀，资料和数据使用简洁卡片图片。")

STATISTICS_OPTIONS = {
    "当前赛季": ("scope", "season"), "本赛季": ("scope", "season"), "season": ("scope", "season"),
    "这个赛季": ("scope", "season"), "这赛季": ("scope", "season"),
    "当前赛年": ("scope", "year"), "当前塞年": ("scope", "year"), "本赛年": ("scope", "year"), "year": ("scope", "year"),
    "这个赛年": ("scope", "year"), "这赛年": ("scope", "year"),
    "全部比赛": ("scope", "all"), "全部时间": ("scope", "all"), "全部": ("scope", "all"), "all": ("scope", "all"),
    "所有游戏": ("mode", "all"), "全部模式": ("mode", "all"), "排位赛": ("mode", "ranked"),
    "排位": ("mode", "ranked"), "匹配": ("mode", "matchmaking"), "巅峰赛": ("mode", "peak"),
    "巅峰": ("mode", "peak"), "娱乐": ("mode", "entertainment"),
    "全部分路": ("branch", None), "所有分路": ("branch", None), "对抗路": ("branch", "top"),
    "中路": ("branch", "mid"), "发育路": ("branch", "bot"), "打野": ("branch", "jungle"),
    "游走": ("branch", "assist"), "游走路": ("branch", "assist"),
    "辅助": ("branch", "assist"), "辅助路": ("branch", "assist"),
}


def statistics_options(text):
    tail, selected = "".join(text.split()), {}
    while tail:
        keyword = next((word for word in sorted(STATISTICS_OPTIONS, key=len, reverse=True) if tail.startswith(word)), None)
        if keyword is None:
            raise ValueError("数据筛选未识别：可用当前赛季、当前赛年、全部比赛、所有游戏及具体分路")
        key, value = STATISTICS_OPTIONS[keyword]
        if key in selected and selected[key] != value:
            raise ValueError("数据筛选条件冲突，请为时间、模式、分路分别指定一个条件")
        selected[key] = value
        tail = tail[len(keyword):]
    options = {"scope": "season", "mode": "all", "branch": None, **selected}
    if options["mode"] == "entertainment" and options["branch"] is not None:
        raise ValueError("娱乐模式暂不提供分路统计，请去掉分路条件或改用排位等模式")
    return options


def parse_client_command(text):
    text = text.strip()
    if not text.startswith(("#客户端", "＃客户端")):
        return None
    tail = text[4:]
    if tail and not tail[0].isspace():
        for name in ("好友状态", "好友列表", "好友"):
            if tail.startswith(name) and (len(tail) == len(name) or tail[len(name)].isspace()):
                break
        else:
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


def _statistics_shortcut(raw, targets):
    """Consume complete filters, with an optional 的 and 数据 in either position."""
    for target in sorted(set(targets), key=len, reverse=True):
        if target.casefold() == "群u" or not raw.casefold().startswith(target.casefold()):
            continue
        tail = raw[len(target):].strip()
        if tail.count("数据") > 1:
            continue
        options = tail.replace("数据", " ", 1).replace("的", " ").strip()
        if not options and "数据" not in tail:
            continue
        try:
            statistics_options(options)
        except ValueError:
            continue
        return ["游戏统计", target, *options.split()]
    return None


def parse_client_shortcut(text, *, settings, nicknames, player_aliases, hero_names, hero_aliases):
    """Recognize a complete prefixed player query without invoking legacy business."""
    text = text.strip()
    if not text.startswith(("#", "＃")) or text[1:].startswith(("#", "＃")):
        return None
    raw = text[1:].strip()
    targets = ["我", *{str(value) for key in set(nicknames) | set(settings.get("players", {})) | set(player_aliases)
                      for value in (key, nicknames.get(key, ""), *player_aliases.get(key, ())) if value}]
    statistics = _statistics_shortcut(raw, targets)
    if statistics is not None:
        return statistics
    if "的" not in raw:
        return None
    player, item = (part.strip() for part in raw.rsplit("的", 1))
    if item == "资料":
        if player == "我" or _player_matches(player, settings, nicknames, player_aliases):
            return ["资料", player]
        return None
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
    if operation in {"friends", "friend_states"}:
        if not args or (len(args) == 1 and args[0].isascii() and args[0].isdecimal()):
            page = int(args[0]) if args else 1
            if page < 1:
                raise ValueError("页码必须为正整数")
            return operation, {"page": page}, "当前登录角色"
        if operation == "friends" or len(args) != 1:
            raise ValueError("用法：#客户端 好友 [页码]；#客户端 好友状态 [玩家或页码]")
        operation = "friend_state"
    if operation == "friend_state" and len(args) != 1:
        raise ValueError("用法：#客户端 好友状态 玩家，例如 #客户端 好友状态 example_user_10")
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
    elif operation == "game":
        parameters.update(statistics_options(" ".join(rest)))
    elif rest:
        raise ValueError("该接口不接受额外参数")
    return operation, parameters, str(nicknames.get(key, key))


async def original_hero_reply(event):
    """Keep the existing personal hero reply before the client supplement."""
    if parse_client_command(event.get_plaintext()) is not None:
        return None
    tokens = parse_client_request(event.get_plaintext())
    if not tokens or ALIASES.get(tokens[0], tokens[0]) not in {"heroes", "hero_detail"}:
        return None
    from ..zstatic import player_client_config, namenick, extra_namenick, nameref, qid
    if tokens[1] == "我":
        matches = [key for key, value in qid.items() if str(value) == str(event.get_user_id())]
    else:
        matches = _player_matches(tokens[1], player_client_config, {**extra_namenick, **namenick}, nameref)
    if len(matches) != 1:
        return None
    from .hero import hero_statistics_reply
    from ..zutil import log_message

    try:
        return await hero_statistics_reply(event)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        log_message(f"PLAYER_CLIENT_ORIGINAL_REPLY_FAILED: error={type(error).__name__}")
        return "原有英雄统计暂时未能完成，继续查询客户端资料。"


async def reply_stream(event):
    """Fetch both sources concurrently while delivering the original reply first."""
    client = asyncio.create_task(command_reply(event))
    try:
        original = await original_hero_reply(event)
        if original:
            yield original
        yield await client
    finally:
        if not client.done():
            client.cancel()
        await asyncio.gather(client, return_exceptions=True)


async def command_reply(event):
    from ..zstatic import player_client_config, qid, namenick, extra_namenick, nameref, HeroList, HeroName_replacements
    from ..zfunc import player_client_query, player_client_hero_report, player_client_text_report, player_client_screen_report
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
        if operation in {"friends", "friend_states"}:
            page = parameters.pop("page")
            result = await asyncio.to_thread(player_client_query, operation, **parameters)
            return await asyncio.to_thread(player_client_text_report, operation, label, result, page=page)
        if operation == "game":
            result = await asyncio.to_thread(player_client_query, "game_statistics", **parameters)
            return await asyncio.to_thread(player_client_screen_report, "game", label, result)
        if operation == "profile":
            result = await asyncio.to_thread(player_client_query, "profile_summary", **parameters)
            return await asyncio.to_thread(player_client_screen_report, "profile", label, result)
        if operation == "hero_detail" and parse_client_command(event.get_plaintext()) is None:
            result = await asyncio.to_thread(player_client_query, "hero_honors", **parameters, scope="all")
            return await asyncio.to_thread(player_client_screen_report, "hero", label, result)
        result = await asyncio.to_thread(player_client_query, operation, **parameters)
        if operation == "heroes":
            return await asyncio.to_thread(player_client_hero_report, label, result)
        return await asyncio.to_thread(player_client_text_report, operation, label, result,
            player=parameters.get("player"), hero_id=parameters.get("hero_id"))
    except asyncio.CancelledError:
        raise
    except PlayerClientRateLimited as error:
        return [f"客户端查询繁忙，请约 {error.retry_after} 秒后再试。"]
    except Exception as error:
        # Library/transport exception text can contain account material.
        code = getattr(error, "code", None)
        suffix = f"，错误码 {code}" if isinstance(code, int) else ""
        from ..zutil import log_message
        log_message(f"PLAYER_CLIENT_QUERY_FAILED: operation={operation} error={type(error).__name__}{suffix}")
        from hok_research import QueryRejected
        if isinstance(error, QueryRejected) and code in player_client_config["rate_limit"]["privacy_codes"]:
            return ["该玩家未开放此项资料。"]
        return ["客户端查询暂时失败，请稍后再试。"]

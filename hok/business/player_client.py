"""Bounded, readable projections of standalone-client hero statistics."""

from math import isfinite


SCOPE_NAMES = {"all": "全部比赛", "season": "本赛季", "year": "当前赛年"}


def _number(value):
    return value if type(value) in (int, float) and isfinite(value) and value >= 0 else None


def _number_text(value):
    if value is None:
        return "—"
    return f"{value:,}" if type(value) is int else f"{value:,.0f}"


def hero_report(label, result, settings, hero_names, *, district_names=None):
    """Select bounded 5v5 cards by highest power; never carry raw protocol fields."""
    from .player_client_screens import branch_models, rank_model
    from .player_client_details import present, table
    label = _text(result.get("player_name")) or "—"
    heroes = result["heroes"]
    limit = max(1, min(10, int(settings["display_hero_limit"])))
    ordered = sorted(heroes, key=lambda row: (-(_number(row.get("highest_fight_value")) or 0), int(row["hero_id"])))
    rows = []
    detail_rows = []
    for hero in ordered[:limit]:
        hero_id = str(hero["hero_id"])
        row = {key: _number(hero.get(key)) for key in (
            "games", "wins", "losses", "win_rate_percent", "fight_value", "highest_fight_value")}
        if not row["games"] or row["win_rate_percent"] is None or row["win_rate_percent"] > 100:
            row["win_rate_percent"] = None
        row.update(hero_id=hero_id, name=str(hero_names.get(hero_id) or hero.get("name") or "未知英雄"),
                   artwork_focus=settings.get("artwork_focus", {}).get(hero_id, [.5, .4]),
                   fight_style=_text((hero.get("fight_style") or {}).get("text")) or None,
                   rank_badge=rank_model(hero.get("rank_badge"), district_names))
        rows.append(row)
        detail_rows.append([row['name'], row['wins'], row['losses'], _number(hero.get('proficiency')),
                            _number(hero.get('unlocked_badge_count'))])
    scope = SCOPE_NAMES.get(result.get("scope"), "当前范围")
    summary = f"{label} · {scope}英雄\n5v5 · 最高战力 · {len(rows)}/{len(heroes)}"
    branches = branch_models(result.get("branches"))
    hint = ""
    text_rows = []
    for index, row in enumerate(rows, 1):
        rate = "—" if row["win_rate_percent"] is None else f"{row['win_rate_percent']:.1f}%"
        rank = row["rank_badge"]
        title = f"，历史称号{rank['text']}" if rank and rank["ranked"] else ""
        text_rows.append(f"{index}. {row['name']}：{_number_text(row['games'])}场，胜率{rate}，"
                         f"当前战力{_number_text(row['fight_value'])}，历史最高{_number_text(row['highest_fight_value'])}{title}")
    text = "\n".join([summary, *text_rows, hint] if rows else [summary, "当前范围没有返回英雄数据。"])
    branch_rows = [[row.get('name'), _number(row.get('level')), _number(row.get('score'))]
                   for row in (result.get('branches') or {}).get('branches') or [] if row.get('name')]
    return {"kind": "heroes", "label": label, "scope": scope, "rows": rows, "total": len(heroes), "branches": branches,
            "summary": summary, "hint": hint, "text": text, "detail_sections": present([
                table('英雄详细数据', ['英雄', '胜场', '负场', '熟练度', '解锁徽章'], detail_rows,
                      ['text', 'integer', 'integer', 'integer', 'integer']),
                table('分路战力', ['分路', '段位', '分路战力'], branch_rows, ['text', 'integer', 'integer'])])}


OPERATION_NAMES = {
    "homepage": "玩家主页", "profile": "玩家资料", "history": "最近战绩", "heroes": "英雄统计",
    "game": "游戏统计", "hero_assets": "英雄与皮肤资料", "collections": "收藏概览",
    "displayed_skins": "展示皮肤", "hero_road_brief": "英雄之路", "hero_detail": "英雄详情",
    "hero_titles": "历史英雄称号", "search": "玩家搜索",
    "friends": "好友列表", "friend_states": "好友状态", "friend_state": "好友状态",
}
BATTLE_MODES = (
    ("stFiveVsFiveInfo", "5v5"), ("stLadderInfo", "排位"), ("stEntertainmentInfo", "娱乐模式"),
    ("stFastFiveVsFiveInfo", "快速5v5"), ("stRank10V10Info", "10v10排位"),
    ("stMatch10V10Info", "10v10匹配"), ("stVsMachineInfo", "人机对战"),
)


def _at(value, *keys):
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, (list, tuple)) else []


def _text(value):
    if isinstance(value, dict):
        value = value.get("text")
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return " ".join(value.replace("\x00", "").split())[:160] if isinstance(value, str) else ""


def _identifier(value):
    return str(value) if type(value) is int and value > 0 else "未提供"


def _name(hero_id, names):
    return names.get(str(hero_id), "未识别英雄")


def _time(value):
    from ..ztime import epoch_to_text

    if _number(value) is None or value <= 0:
        return "时间未提供"
    try:
        return epoch_to_text(value, format_str="%m-%d %H:%M", timezone_name="Asia/Shanghai")
    except (ValueError, OSError, OverflowError):
        return "时间未提供"


def _battle_line(label, games, wins):
    games, wins = _number(games), _number(wins)
    if games is None:
        return None
    if wins is None or wins > games:
        return f"{label}：{_number_text(games)}场，胜负数据未提供。"
    rate = f"，胜率{wins / games * 100:.1f}%" if games else "，暂无胜率样本"
    return f"{label}：{_number_text(games)}场，{_number_text(wins)}胜{_number_text(games - wins)}负{rate}。"


def _add_fields(lines, value, fields):
    for key, label in fields:
        number = _number(_at(value, key))
        if number is not None:
            lines.append(f"{label}：{_number_text(number)}")


def _game_lines(result):
    lines = []
    _add_fields(lines, result, (("dwPvpLevel", "对战等级"), ("dwWangZheCnt", "王者印记次数")))
    stats = _at(result, "stStatistic")
    for key, label in BATTLE_MODES:
        value = _at(stats, key)
        if isinstance(value, dict):
            line = _battle_line(label, value.get("dwTotalNum"), value.get("dwWinNum"))
            if line:
                lines.append(line)
    rank = _at(result, "stRankInfo")
    if isinstance(rank, dict):
        line = _battle_line("当前排位赛季", rank.get("dwTotalFightCnt"), rank.get("dwTotalWinCnt"))
        if line:
            lines.append(line)
        _add_fields(lines, rank, (("dwMaxContinuousWinCnt", "排位最高连胜"),))
    peak = _at(result, "stMasterMatchData")
    if isinstance(peak, dict):
        _add_fields(lines, peak, (("iMasterMatchScore", "当前巅峰积分"),
            ("iMaxSeasonMasterMatchScore", "本赛季最高巅峰积分"), ("iMaxHistoryMasterMatchScore", "历史最高巅峰积分")))
        line = _battle_line("巅峰赛", peak.get("dwTotalFightCnt"), peak.get("dwTotalWinCnt"))
        if line:
            lines.append(line)
    return lines


def _profile_lines(result):
    lines = []
    nickname = _text(result.get("szAcntName"))
    if nickname:
        lines.append("游戏昵称：" + nickname)
    _add_fields(lines, result, (("dwPvpLevel", "对战等级"), ("dwCreditValue", "信誉积分"),
        ("dwAchieveMentScore", "成就积分"), ("ullPopularity", "人气值")))
    if result.get("bIsOnline") in (0, 1):
        lines.append("在线状态：" + ("在线" if result["bIsOnline"] else "离线"))
    if _number(result.get("dwLastLoginTime")):
        lines.append("最近登录：" + _time(result["dwLastLoginTime"]))
    signature = _text(result.get("szSignatureInfo"))
    if signature:
        lines.append("个性签名：" + signature)
    _add_fields(lines, _at(result, "stMostUsedHero"), (("dwTotalHeroNum", "英雄总数"), ("dwTotalSkinNum", "皮肤总数")))
    return lines


def _history_lines(result, player, names, limit):
    records = _rows(result.get("records"))
    records.sort(key=lambda row: _number(row.get("dwGameStartTime")) or 0, reverse=True)
    try:
        target = (int(player["uid"]), int(player["logic_world_id"]))
    except (KeyError, TypeError, ValueError):
        target = None
    lines = [f"本次返回{len(records)}场，展示最近{min(len(records), limit)}场。"]
    for record in records[:limit]:
        matches = [row for row in _rows(record.get("astPlayerFightData")) if target is not None and
            (row.get("ullPlayerUid"), row.get("iPlayerLogicWorldID")) == target]
        detail = _time(record.get("dwGameStartTime"))
        if len(matches) == 1:
            row = matches[0]
            winner, camp = _number(record.get("bWinCamp")), _number(row.get("bPlayerCamp"))
            outcome = ("胜利" if winner == camp else "失利") if winner and camp else "结果未提供"
            kda = "/".join(_number_text(_number(row.get(key))) for key in ("bKill", "bDead", "bAssist"))
            detail += f"  {_name(row.get('dwHeroID'), names)}  {outcome}  击杀/死亡/助攻 {kda}"
        else:
            detail += "  未找到可确认的本人视角，不推断胜负和英雄。"
        lines.append(detail)
    if not records:
        lines.append("本次没有返回对局记录。")
    if result.get("complete") is not True:
        lines.append("本次返回尚未确认结束，不能视为完整结果。")
    lines.append("仅为接口本次返回战绩，不代表全部历史。")
    return lines


def _hero_extra_lines(result, names, limit, hero_id):
    rows = _rows(_at(result, "stDetailHeroExtraInfo", "astDetailHeroExtraData"))
    if hero_id is not None:
        rows = [row for row in rows if row.get("dwHeroID") == hero_id]
    lines = []
    for row in rows[:limit]:
        lines.append(_name(row.get("dwHeroID"), names))
        _add_fields(lines, row.get("stHeroAbilityInfo"), (("dwTotalValue", "英雄能力总值"),))
        _add_fields(lines, row.get("stHeroBadgeInfo"), (("iHeroBadgeNum", "徽章记录数"), ("dwHeroBadgeProficiency", "徽章熟练度")))
        _add_fields(lines, row.get("stHeroTitleInfo"), (("iTitleGroupNum", "称号记录数"),))
        title = _at(row, "stHeroTitleInfo", "stShowTitle", "dwShowTitleID")
        if _number(title) is not None:
            lines.append("展示称号：" + ("已设置" if title else "未设置"))
    if rows:
        lines.append("以上为英雄能力、徽章和称号资料。对局表现可用 #玩家的英雄名 查询。")
    return lines


def _limited_names(lines, prefix, rows, limit, name):
    if rows:
        lines.append(f"{prefix}：共{len(rows)}项，展示前{min(limit, len(rows))}项。")
        lines.extend(name(row) for row in rows[:limit])
    else:
        lines.append(prefix + "：暂无可展示的条目。")


def _collection_lines(result):
    fields = (("stPerfEftList", "wPerfEftCnt", "个性特效"), ("stBattleUISkinList", "dwUISkinNum", "对局界面皮肤"),
        ("stActionList", "wActionCnt", "个性动作"), ("stSoldierSkinList", "dwNum", "小兵皮肤"),
        ("stSkyScreenList", "dwNum", "天幕"), ("stEmojiList", "wEmojiCnt", "表情"),
        ("stSignatureList", "wSignatureCnt", "签名"), ("stHeadImgList", "wHeadImgCnt", "头像"),
        ("stNameCardSkinList", "wNameCardSkinNum", "名片皮肤"), ("stNameCardBackgroundList", "dwNum", "名片背景"),
        ("stPlayerInfoSkinList", "dwPlayerInfoSkinCnt", "主页装扮"), ("stInviteSkinList", "wInviteSkinNum", "邀请界面皮肤"),
        ("stLingBaoSuitList", "dwSuitNum", "灵宝套装"), ("stLingBaoActionList", "dwNum", "灵宝动作"))
    lines = []
    for section, key, label in fields:
        _add_fields(lines, result.get(section), ((key, label),))
    return lines


def _friend_status(state, hero_names, *, details):
    """Offline/hidden snapshots must not disclose their stale game fields."""
    if state.get("hidden") is True:
        return "隐身"
    if state.get("online") is False:
        return "离线"
    if state.get("online") is not True:
        return "状态未知"
    parts = ["在线"]
    if not details:
        return parts[0]
    game = state.get("game_state")
    substate = state.get("game_substate")
    states = {"idle": "空闲", "single_game": "单人游戏", "multiplayer_game": "多人游戏",
              "team": "组队中", "waiting_multiplayer": "等待开局"}
    substates = {"room_or_team": "房间/组队中", "ready": "准备中", "gaming": "对局中",
                 "match_queue": "匹配中", "observing": "观战中", "single_gaming": "单人对局中"}
    parts.append(states[game] if game == "idle" else substates.get(substate) or states.get(game) or "状态未知")
    mode = _text(_at(state, "current_mode", "name"))
    if mode:
        parts.append(mode)
    hero_id = state.get("hero_id")
    if _number(hero_id) and game != "idle":
        parts.append(_name(hero_id, hero_names))
    party = state.get("ranked_party_size")
    if type(party) is int and party in (1, 2, 3, 5):
        parts.append({1: "单排", 2: "双排", 3: "三排", 5: "五排"}[party])
    members, capacity = state.get("current_team_members"), state.get("team_capacity")
    if type(members) is int and members > 0:
        size = f"{members}/{capacity}" if type(capacity) is int and capacity >= members else str(members)
        parts.append(f"队伍{size}人")
    if _number(state.get("game_start_time")):
        parts.append("开局 " + _time(state["game_start_time"]))
    return " · ".join(parts)


def _friend_lines(operation, result, settings, hero_names, page):
    if operation == "friend_state":
        state = result.get("state")
        if result.get("found") is False:
            return ["当前登录角色的游戏好友中没有该玩家。"]
        if not isinstance(state, dict):
            return ["暂未取得好友状态。"]
        name = _text(state.get("name")) or "昵称未提供"
        return [f"{name}：{_friend_status(state, hero_names, details=True)}"]

    rows = _rows(result.get("players"))
    rows.sort(key=lambda state: (0 if state.get("online") is True and state.get("hidden") is not True else 1,
                                 _text(state.get("name")).casefold()))
    online = sum(state.get("online") is True and state.get("hidden") is not True for state in rows)
    complete = result.get("complete") is True
    lines = [f"共{len(rows)}位好友，在线{online}位。" if complete else f"本次返回{len(rows)}位好友，列表未完整。"]
    if not rows:
        return lines + (["暂无游戏好友。"] if complete else [])
    size = max(1, min(50, int(settings.get("friend_page_size", 20))))
    pages = (len(rows) + size - 1) // size
    if not 1 <= page <= pages:
        return lines + [f"页码超出范围，共{pages}页。"]
    lines.append(f"第{page}/{pages}页")
    start = (page - 1) * size
    for index, state in enumerate(rows[start:start + size], start + 1):
        name = _text(state.get("name")) or "昵称未提供"
        lines.append(f"{index}. {name}：{_friend_status(state, hero_names, details=operation == 'friend_states')}")
    if page < pages:
        command = "好友" if operation == "friends" else "好友状态"
        lines.append(f"下一页：#客户端 {command} {page + 1}")
    return lines


def text_report(operation, label, result, settings, hero_names, *, player=None, hero_id=None, skin_names=None, page=1):
    """Explicit field projections only: no raw dictionaries or protocol fallback."""
    result = result if isinstance(result, dict) else {}
    limit = max(1, min(20, int(settings["display_item_limit"])))
    lines = []
    if operation in {"friends", "friend_states", "friend_state"}:
        lines = _friend_lines(operation, result, settings, hero_names, page)
    elif operation == "game":
        lines = _game_lines(result)
    elif operation == "profile":
        lines = _profile_lines(result)
    elif operation == "homepage":
        lines = _profile_lines(result.get("profile") or {}) + _game_lines(result.get("game") or {})
        history = result.get("history")
        if isinstance(history, dict):
            lines += _history_lines(history, player, hero_names, limit)
        elif "history" in (result.get("errors") or {}):
            lines.append("战绩未能取得，可能受隐私设置限制；以上资料仍可使用。")
    elif operation == "history":
        lines = _history_lines(result, player, hero_names, limit)
    elif operation == "hero_detail":
        lines = _hero_extra_lines(result, hero_names, limit, hero_id)
    elif operation == "hero_road_brief":
        rows = _rows(_at(result, "stHeroRoadBriefInfo", "astHeroRoadBriefData"))
        _limited_names(lines, "英雄之路", rows, limit, lambda row:
            f"{_name(row.get('dwHeroID'), hero_names)}：已解锁徽章{_number_text(_number(row.get('dwUnLockBadgeNum')))}个")
    elif operation == "hero_titles":
        rows = _rows(_at(result, "stHistoryHeroLbsTitleInfo", "astHeroLbsTitleData"))
        rows.sort(key=lambda row: _number(row.get("dwMaxFightScore")) or 0, reverse=True)
        _limited_names(lines, "历史荣耀称号", rows, limit, lambda row:
            f"{_name(row.get('dwHeroID'), hero_names)}：历史最高战力{_number_text(_number(row.get('dwMaxFightScore')))}，"
            f"称号记录{_number_text(_number(row.get('dwTitleTypeCnt')))}类")
    elif operation == "hero_assets":
        rows = _rows(_at(result, "stHeroInfo", "stHeroList", "astHeroIDMasks"))
        _limited_names(lines, "英雄资料", rows, limit, lambda row: _name(row.get("dwHeroID"), hero_names))
        skins = _at(result, "stHeroInfo", "stSkinList", "astHeroSkinList")
        if isinstance(skins, list):
            lines.append(f"另返回{len(skins)}个英雄的皮肤资料。")
        lines.append("本次资料不代表完整的英雄、皮肤持有清单。")
    elif operation == "collections":
        lines = _collection_lines(result)
    elif operation == "displayed_skins":
        rows = _rows(_at(result, "stShowSkinInfo", "astShowSkinData"))
        _limited_names(lines, "展示皮肤", rows, limit,
            lambda row: (skin_names or {}).get(str(row.get("dwSkinID")), "皮肤名称暂未识别"))
    elif operation == "search":
        rows = _rows(result.get("candidates"))
        _limited_names(lines, "搜索候选", rows, limit, lambda row:
            f"{_text(row.get('nickname')) or '昵称未提供'} · "
            f"{({1: '安卓', 2: 'iOS'}).get(row.get('platform'), '平台未提供')} · "
            f"对战等级{_number_text(_number(row.get('pvp_level')))}\n"
            f"游戏UID {_identifier(row.get('uid'))}，区服编号 {_identifier(row.get('logic_world_id'))}")
        lines.append("搜索结果仅供确认目标，不会自动绑定账号。")
    else:
        lines.append("请使用英雄统计图查看英雄场次、胜率和战力。")
    if not lines:
        lines = ["本次返回没有可展示的已识别资料；未提供的数据不按0处理。"]
    body = "\n".join(lines)
    max_chars = int(settings["max_result_chars"])
    if len(body) > max_chars:
        body = body[:max_chars] + "\n〔展示内容已截断〕"
        if operation == "history":
            body += "\n仅为接口本次返回战绩，不代表全部历史。"
    text = f"{label} · 客户端{OPERATION_NAMES.get(operation, '查询结果')}\n{body}"
    size = int(settings["message_chars"])
    return [text[index:index + size] for index in range(0, len(text), size)]

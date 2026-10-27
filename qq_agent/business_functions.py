"""Trusted HOK bindings; adding a function does not add a model tool schema."""

from typing import Literal

from pydantic import Field, create_model

from agent_console.function_calls import FunctionArgs, FunctionCatalog, FunctionOutput


def _text(value):
    return FunctionOutput(text=str(value) if value is not None else "当前没有可用结果")


def _text_image(value):
    return FunctionOutput(text=value[0] or "", images=[value[1]] if value[1] else [])


def _image_text(value):
    return FunctionOutput(text=value[1] or "", images=[value[0]] if value[0] else [])


def build_hok_function_catalog(functions, *, player_keys, player_aliases=None, policy=None):
    """functions is a trusted application namespace, never a model argument."""
    policy = dict(policy or {})
    player_aliases = player_aliases or {}
    catalog = FunctionCatalog(**{key: policy[key] for key in
        ("max_calls", "timeout_seconds", "max_result_chars") if key in policy})
    player_type = Literal[tuple(sorted(set(player_keys)))] if player_keys else str
    player_field = (player_type, Field(description="权威参考目录中的 player_key，不接受昵称、QQ或猜测的玩家键"))
    days = (int, Field(default=30, ge=1, le=366, strict=True))
    top = (int, Field(default=5, ge=1, le=20, strict=True))
    minimum = (int, Field(default=2, ge=1, le=1000, strict=True))
    season = (bool, Field(default=False, strict=True))

    def add(name, description, category, fields=None, *, project=_text, bind=None):
        model = create_model("HOK_" + name, __base__=FunctionArgs, **(fields or {}))
        # Resolve exactly once from an application-owned name. There is no
        # getattr/import/eval based on model input, nor automatic module scan.
        function = functions[name]

        def handler(args, ctx):
            values = args.model_dump()
            if bind:
                values = bind(values, ctx)
            return project(function(**values))

        catalog.register(name=name, description=description, category=category,
                         args_model=model, handler=handler)

    def owner(values, ctx):
        player = ctx.principal.attributes.get("identity", {}).get("player_key")
        if player not in player_keys:
            raise ValueError("当前用户没有唯一绑定的玩家，不能查询本人今日英雄")
        return {"realname": player, "ignore_limit": False, "ai_comment": False}

    def report(values, ctx):
        # Keep natural-language dispatch and AI commentary out of this adapter.
        player = values["player"]
        aliases = [player, *player_aliases.get(player, [])]
        label = next((name for name in aliases if functions["extract_name"](name) == player), None)
        if label is None:
            raise ValueError("该玩家没有可唯一识别的战报名称")
        return {"rcv_msg": f"{label}战报${values['days_ago'] or ''}"}

    def representative(value):
        return FunctionOutput(text="\n".join(filter(None, [value.get("text"), value.get("commentary")]))
            if value.get("found") else "该日期没有代表局", images=[value["image_path"]] if value.get("image_path") else [])

    add("online_process", "查询配置玩家的王者与Steam在线状态；部分数据源失败会明确提示", "players",
        project=lambda value: FunctionOutput(text=(value[0] + ("\n部分数据源查询失败" if value[1] else ""))
            if isinstance(value, tuple) else str(value)))
    add("peak_rank_process", "查询本地历史巅峰排名，返回各玩家最近记录", "rankings")
    add("single_process", "查询指定玩家当天或前若干天的单日战报，不生成额外AI点评", "players",
        {"player": player_field, "days_ago": (int, Field(default=0, ge=0, le=366, strict=True))},
        bind=report, project=lambda value: _text(value[0] if value else None))
    add("heropower_process", "查询玩家英雄荣耀战力与地区排名", "heroes", {"realname": player_field})
    add("allhero_process", "查询玩家常用英雄、场次、胜率与战力", "heroes", {"realname": player_field})
    add("single_player_mult_hero_process", "统计单个玩家近期或本赛季的英雄表现榜单", "heroes",
        {"username": player_field, "days": days, "top_n": top, "min_games": minimum, "this_season": season})
    add("mult_player_mult_hero_process", "统计全部配置玩家近期或本赛季的英雄表现榜单", "heroes",
        {"days": days, "top_n": top, "min_games": minimum, "this_season": season})
    add("honor_power_query_process", "查询指定英雄与地区的荣耀战力门槛；英雄名和地区放query_text", "heroes",
        {"realname": player_field, "query_text": (str, Field(min_length=2, max_length=100))})
    add("todayhero_process", "查询调用者本人的今日英雄推荐，沿用当天缓存与次数限制", "heroes",
        bind=owner, project=lambda value: FunctionOutput(text="\n".join(filter(None, value[:2])),
            images=[value[2]] if value[2] else []))
    add("hero_tier_query_process", "获取当前英雄梯度长图", "heroes", project=lambda value:
        FunctionOutput(images=[value]) if value else _text(None))
    add("gradeanalyze_process", "生成玩家评分和星数趋势图与分析", "visuals", {"realname": player_field}, project=_image_text)
    add("watchbattle_process", "获取玩家当前对局观战截图与说明", "visuals", {"realname": player_field}, project=_image_text)
    add("recent_power_process", "查询玩家近期底蕴历史与统计", "power",
        {"realname": player_field, "days": (int, Field(default=7, ge=1, le=366, strict=True))})
    add("power_rank_process", "生成近期底蕴排行榜图片", "power",
        {"days": (int, Field(default=7, ge=1, le=366, strict=True))}, project=_text_image)
    add("recentgames_process", "查询玩家最近两周的王者和Steam游戏时长", "activity", {"realname": player_field})
    add("gametime_rank_process", "生成游戏时长排行图片；Steam来源固定近两周，王者使用days", "activity",
        {"days": (int, Field(default=14, ge=1, le=366, strict=True))}, project=_text_image)
    add("representative_battle_query_impl", "查询指定日期的代表局文字、图片及点评；支持今天、昨天或具体日期", "battles",
        {"query_text": (str, Field(default="今天", max_length=100))}, project=representative)
    return catalog

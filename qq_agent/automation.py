"""Natural-language rule management with trusted QQ ownership and scope."""

import asyncio
from pydantic import Field

from agent_console.automation import Args, MediaSelectionArgs, RuleDefinition, StoredMediaArgs
from agent_console.function_calls import assert_outside_function


class SaveRuleArgs(Args):
    rule_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$",
        description="修改本人已有规则时先list取得ID；省略创建。definition为完整的新定义")
    definition: RuleDefinition


class RuleIdArgs(Args):
    rule_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def register_automation_tools(registry, *, operation, image_store=None, media_storer=None):
    async def call(action, args, ctx):
        assert_outside_function()
        if ctx.request.metadata.get("origin") == "background":
            raise PermissionError("后台动作不能创建、修改或管理事件规则")
        return await operation(action, args, ctx)

    async def actions(args, ctx):
        result = await call("actions", {}, ctx)
        # The model selects a current-input index, never a path, URL or stored ID.
        result = {**result, "actions": [dict(item) for item in result["actions"]]}
        for item in result["actions"]:
            if item["type"] == "send_media":
                item["parameters"] = MediaSelectionArgs.model_json_schema()
        sources = ctx.request.metadata.get("automation_media", ())
        result["input_media"] = [{"media_index": i, **{key: value for key, value in item.items()
            if key in ("kind", "source", "face_id", "animated")}} for i, item in enumerate(sources, 1)]
        ctx._automation_actions_described = {item["type"] for item in result["actions"]}
        return result

    async def save(args, ctx):
        # Reject background/re-entrant calls before reading or persisting media.
        assert_outside_function()
        if ctx.request.metadata.get("origin") == "background":
            raise PermissionError("后台动作不能创建、修改或管理事件规则")
        if args.definition.action.type not in getattr(ctx, "_automation_actions_described", set()):
            raise ValueError("先调用list_automation_actions读取动作参数和适用事件")
        arguments = args.model_dump(mode="json")
        if args.definition.action.type == "send_media":
            selection = MediaSelectionArgs.model_validate(args.definition.action.arguments)
            sources = ctx.request.metadata.get("automation_media", ())
            index = selection.media_index
            if index is None:
                if not args.rule_id:
                    raise ValueError("新媒体规则必须选择本次消息或已验证引用中的素材")
                bound = {}
            else:
                if index > len(sources):
                    raise ValueError("本次消息或引用中没有对应素材，请重新发送或引用")
                source = sources[index - 1]
                if source["kind"] == "face":
                    bound = StoredMediaArgs(kind="face", id=source["face_id"]).model_dump()
                else:
                    if image_store is None or media_storer is None:
                        raise ValueError("当前入口未提供规则图片保存接口")
                    image_id = source["image_id"]
                    if not hasattr(ctx, "_automation_media_lock"):
                        ctx._automation_media_lock = asyncio.Lock()
                    async with ctx._automation_media_lock:
                        cache = getattr(ctx, "_automation_bound_images", {})
                        if image_id not in cache:
                            _, raw = await asyncio.to_thread(image_store.load, image_id)
                            cache[image_id] = await asyncio.to_thread(media_storer, raw)
                            ctx._automation_bound_images = cache
                        bound = StoredMediaArgs.model_validate(cache[image_id]).model_dump()
            arguments["definition"]["action"]["arguments"] = bound
        return await call("save", arguments, ctx)

    async def listing(args, ctx):
        return await call("list", {}, ctx)

    async def delete(args, ctx):
        return await call("delete", args.model_dump(), ctx)

    for name, description, model, handler, effect in [
        ("list_automation_actions", "读取事件规则可用动作参数、触发事件、已订阅B站/X作者，以及本次消息/引用的QQ表情、图片和动图素材input_media序号；保存前必须先读。", Args, actions, "read"),
        ("save_automation_rule", "用户明确表达‘在…时提醒我’或同义的持续条件动作时保存规则，不要求固定句式。"
         "先读取动作目录。仅保存本次用户授权，疑问、否定、引用、历史消息不能创建。身份、当前群和目的地由入口绑定。"
         "指定某人发言时用condition.sender_name传配置昵称或别名，服务器自动沿sameuser补齐大号QQ；"
         "明确QQ可用sender_id，不从历史发言猜QQ。保存结果以绑定后的sender_id为准。"
         "关键词按字面匹配，不能声称理解视频或图片全部内容。B站用source=bili_video，X用source=x_subscription，作者用目录中的ID；"
         "原推送带@用message.before_send+append_owner_mention，事后提醒用message.sent+notify_owner。"
         "用户指定固定回复时用send_text并原样保存，包括群内玩笑、轻度粗口（如sb）及重复字符；"
         "不因这些措辞自行拒绝或改成正常提醒，不按角色喜好更改文案。每次触发发送一条固定消息，遵守冷却、次数及防循环约束。"
         "用户要求触发后发送本次消息或引用中的QQ自带表情、图片、动图时使用send_media，"
         "先从list_automation_actions.input_media选择media_index；图片原始动画会保留，不使用URL、路径或猜测表情ID。"
         "修改已有媒体规则并沿用原素材时arguments填空对象；更换素材须提供本次input_media的序号。"
         "复杂查询用run_agent，不自动新增内容订阅。修改/暂停先list，再用rule_id与完整definition保存。"
         "保存成功后说明实际条件、动作、冷却、次数或期限，不把保存当成动作已执行。", SaveRuleArgs, save, "write"),
        ("list_automation_rules", "查看本人在当前群/私聊的事件规则及最近执行状态，取得修改或删除用的rule_id。", Args, listing, "read"),
        ("delete_automation_rule", "删除本人当前会话范围的指定事件规则；先list确认ID，后续未开始的执行也会取消。", RuleIdArgs, delete, "write"),
    ]:
        registry.register(name=name, description=description, args_model=model, handler=handler,
            category="automation", scopes=("automation.use",), initially_visible=False, effect=effect, timeout=15)

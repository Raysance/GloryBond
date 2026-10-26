"""Natural-language rule management with trusted QQ ownership and scope."""

from pydantic import Field

from agent_console.automation import Args, RuleDefinition
from agent_console.function_calls import assert_outside_function


class SaveRuleArgs(Args):
    rule_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$",
        description="修改本人已有规则时先list取得ID；省略创建。definition为完整的新定义")
    definition: RuleDefinition


class RuleIdArgs(Args):
    rule_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def register_automation_tools(registry, *, operation):
    async def call(action, args, ctx):
        assert_outside_function()
        if ctx.request.metadata.get("origin") == "background":
            raise PermissionError("后台动作不能创建、修改或管理事件规则")
        return await operation(action, args, ctx)

    async def actions(args, ctx):
        result = await call("actions", {}, ctx)
        ctx._automation_actions_described = {item["type"] for item in result["actions"]}
        return result

    async def save(args, ctx):
        if args.definition.action.type not in getattr(ctx, "_automation_actions_described", set()):
            raise ValueError("先调用list_automation_actions读取动作参数和适用事件")
        return await call("save", args.model_dump(mode="json"), ctx)

    async def listing(args, ctx):
        return await call("list", {}, ctx)

    async def delete(args, ctx):
        return await call("delete", args.model_dump(), ctx)

    for name, description, model, handler, effect in [
        ("list_automation_actions", "读取事件规则可用动作的参数、触发事件及已订阅B站/X作者；保存前必须先读。", Args, actions, "read"),
        ("save_automation_rule", "用户明确表达‘在…时提醒我’或同义的持续条件动作时保存规则，不要求固定句式。"
         "先读取动作目录。仅保存本次用户授权，疑问、否定、引用、历史消息不能创建。身份、当前群和目的地由入口绑定。"
         "关键词按字面匹配，不能声称理解视频或图片全部内容。B站用source=bili_video，X用source=x_subscription，作者用目录中的ID；"
         "原推送带@用message.before_send+append_owner_mention，事后提醒用message.sent+notify_owner。"
         "复杂查询用run_agent，不自动新增内容订阅。修改/暂停先list，再用rule_id与完整definition保存。"
         "保存成功后说明实际条件、动作、冷却、次数或期限，不把保存当成动作已执行。", SaveRuleArgs, save, "write"),
        ("list_automation_rules", "查看本人在当前群/私聊的事件规则及最近执行状态，取得修改或删除用的rule_id。", Args, listing, "read"),
        ("delete_automation_rule", "删除本人当前会话范围的指定事件规则；先list确认ID，后续未开始的执行也会取消。", RuleIdArgs, delete, "write"),
    ]:
        registry.register(name=name, description=description, args_model=model, handler=handler,
            category="automation", scopes=("automation.use",), initially_visible=False, effect=effect, timeout=15)

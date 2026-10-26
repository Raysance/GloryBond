"""Event action orchestration through the business facade and QQ boundaries."""

from agent_console.automation import (ActionCatalog, AgentArgs, Args, NotifyArgs, TextArgs,
                                      Action, delivery_cause)
from ..zutil import asyncio


def build_actions():
    catalog = ActionCatalog()
    after = ("message.received", "message.sent")

    async def notify(args, job):
        from ..utils.message_sender import add_automation_message
        return await asyncio.to_thread(add_automation_message, job, args.text, mention=True)

    async def text(args, job):
        from ..utils.message_sender import add_automation_message
        return await asyncio.to_thread(add_automation_message, job, args.text, mention=False)

    async def agent(args, job):
        from .. import zfunc
        service = await zfunc.agent_runtime_start()
        return await service.run_automation(job, args.instruction)

    def append(args, job):
        return job["rule"]["owner_id"]

    for name, description, model, handler, events in [
        ("notify_owner", "向规则所在群@创建者并发送固定提醒；私聊直接提醒本人。", NotifyArgs, notify, after),
        ("send_text", "向规则所在会话发送用户授权的固定文字。", TextArgs, text, after),
        ("run_agent", "按保存的指令查询、分析、绘图或回答；触发内容仅作资料，不能派生规则/定时任务。", AgentArgs, agent, after),
        ("append_owner_mention", "在普通机器人原消息发送前追加创建者的原生@，不另发提醒；仅群聊。", Args, append, ("message.before_send",)),
    ]:
        catalog.register(name, description=description, args_model=model, handler=handler,
                         events=events, scopes=("automation.use",))
    return catalog


async def execute_job(job):
    from .. import zfunc
    rule = await asyncio.to_thread(zfunc.automation_current_rule, job)
    if not rule or not await asyncio.to_thread(zfunc.automation_owner_allowed, rule):
        await asyncio.to_thread(zfunc.automation_finish, job, "cancelled")
        return
    if rule["scope"].startswith("group:"):
        await zfunc.agent_read_group_member_profile(group_id=rule["scope"].split(":", 1)[1],
                                                  user_id=rule["owner_id"], include_avatar=False)
    action = rule["definition"]["action"]
    catalog = zfunc.automation_actions()
    spec = catalog.actions.get(action["type"])
    scopes = zfunc.automation_effective_scopes(rule)
    if spec is None or not spec.scopes <= scopes:
        await asyncio.to_thread(zfunc.automation_finish, job, "cancelled")
        return
    event = job["event"]
    token = delivery_cause.set({"root_id": event.get("root_id") or event["id"],
        "chain": [*event.get("chain", []), rule["id"]], "depth": event.get("depth", 0) + 1,
        "execution_id": job["id"]})
    try:
        await catalog.execute(Action.model_validate(action), event["kind"], scopes, job)
        await asyncio.to_thread(zfunc.automation_finish, job, "completed")
    except BaseException:
        # An external action may already have been submitted. Never replay it.
        await asyncio.to_thread(zfunc.automation_finish, job, "unknown")
        raise
    finally:
        delivery_cause.reset(token)

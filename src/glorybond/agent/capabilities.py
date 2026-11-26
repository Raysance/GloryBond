import dataclasses
import datetime
import json
from pathlib import Path
import time
from glorybond.agent.tools.memory import recent_history_limits
from glorybond.agent.timeouts import IMAGE_TASK_TIMEOUT_SECONDS
from glorybond.agent.reply_style import reply_style_instruction


class Clock:
    def now(self):
        return datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))
        ).isoformat()

    def monotonic(self):
        return time.monotonic()


class Capabilities:
    def __init__(self, bridge, state_bridge=None):
        self.bridge = bridge
        self.state_bridge = state_bridge or bridge

    async def search_history(self, queries, ctx, *, group_id=None):
        return await self.bridge.call(
            "search_history",
            queries=queries,
            original_query=ctx.request.user_message,
            principal=remote_chat_identity(ctx.principal),
            exclude_message_id=ctx.request.metadata.get("message_id"),
            **({"before_timestamp": ctx.request.metadata["message_timestamp"]}
               if "message_timestamp" in ctx.request.metadata else {}),
            **({"group_id": group_id} if group_id is not None else {}),
        )

    async def recent_history(self, args, ctx):
        return await self.bridge.call(
            "recent_history", **args,
            principal=remote_chat_identity(ctx.principal),
            exclude_message_id=ctx.request.metadata.get("message_id"),
            **({"before_timestamp": ctx.request.metadata["message_timestamp"]}
               if "message_timestamp" in ctx.request.metadata else {}),
        )

    async def direct_history(self, ctx):
        messages = await self.state_bridge.call("dialogue_load", session_id=ctx.request.conversation_id)
        boundary = ctx.request.metadata.get("message_timestamp")
        if boundary is not None:
            messages = [message for message in messages if message.get("turn", {}).get("timestamp") is None
                        or float(message["turn"]["timestamp"]) <= float(boundary)]
        return {"session_id": ctx.request.conversation_id, "user_id": ctx.principal.user_id,
                "messages": messages, "source": "own_direct_dialogue", "legacy_timestamps_unknown":
                any(message.get("turn", {}).get("timestamp") is None for message in messages),
                "notice": "当前调用者在当前会话的直接历史及已交付详细答案；引用保留原作者，旧回答不自证。"}

    async def analyze(self, domain, queries, ctx, *, group_id=None, scope=None):
        return await self.bridge.call(
            "analyze",
            domain=domain,
            queries=queries,
            principal=remote_chat_identity(ctx.principal),
            **({"group_id": group_id} if group_id is not None else {}),
            **({"scope": scope} if scope is not None else {}),
            **({"as_of": ctx.request.metadata["message_timestamp"]}
               if domain in {"game", "power"} and "message_timestamp" in ctx.request.metadata else {}),
        )

    async def web_search(self, query, max_results):
        return await self.bridge.call(
            "web_search", query=query, max_results=max_results
        )

    async def kpl_query(self, args):
        return await self.bridge.call("kpl_query", **args)

    async def execute_python(self, code, data):
        return await self.bridge.call("python", code=code, data=data)

    async def generate_image(self, prompt, size):
        return await self.bridge.call("image", prompt=prompt, size=size,
                                      task_timeout_seconds=IMAGE_TASK_TIMEOUT_SECONDS)

    async def memory(self, action, ctx, **args):
        return await self.state_bridge.call(
            "memory", action=action, user_id=ctx.principal.user_id, **args
        )

    def validate_task_creation(self, ctx):
        from glorybond.agent.function_calls import assert_outside_function
        assert_outside_function()
        if ctx.request.metadata.get("origin") == "background":
            raise PermissionError("后台任务不能创建子定时任务；请在前台调整原任务的周期或次数")

    async def create_task(self, args, ctx):
        self.validate_task_creation(ctx)
        return await self.state_bridge.call(
            "task_create",
            session_id=ctx.request.conversation_id,
            principal=dataclasses.asdict(ctx.principal),
            required_tools=list(ctx.request.required_tools),
            **args,
        )

    async def list_tasks(self, ctx, *, message_id=None):
        return await self.state_bridge.call(
            "task_list", session_id=ctx.request.conversation_id,
            principal=dataclasses.asdict(ctx.principal),
            **({"message_id": message_id} if message_id is not None else {}),
        )

    async def cancel_task(self, task_id, ctx):
        return await self.state_bridge.call(
            "task_cancel", session_id=ctx.request.conversation_id, task_id=task_id,
            principal=dataclasses.asdict(ctx.principal),
        )

    async def reference_catalogs(self, ctx):
        return await self.bridge.call(
            "reference_catalogs", principal=dataclasses.asdict(ctx.principal)
        )

    async def lookup_reference_data(self, args, ctx):
        return await self.bridge.call(
            "reference_lookup", query=args, principal=dataclasses.asdict(ctx.principal)
        )

    async def read_bot_manual(self, args):
        return await self.bridge.call("bot_manual", **args)


def reference_prompt(snapshot, *, user_ids=(), query="", budget=1200):
    from glorybond.agent.chat_context import reference_projection

    return (
        "项目参考目录及本轮身份映射：QQ使用user_id，游戏SQL使用player_key；name为显示名。"
        "id_sources标明继承来源，多条匹配保留歧义；candidate需确认，unmatched保持未知。"
        "其他名称和ID按需发现references查询，不从旧助手判断推断身份。\n"
        + json.dumps(reference_projection(snapshot, user_ids=user_ids, query=query, budget=budget),
                     ensure_ascii=False, separators=(",", ":"))
    )


def remote_chat_identity(principal):
    """Only the application adapter understands chat scope claims."""
    chat = principal.attributes.get("chat", {})
    return {
        "user_id": principal.user_id,
        "scopes": sorted(principal.scopes),
        "group_id": chat.get("group_id"),
        "all_groups": bool(chat.get("all_groups")),
        **({"default_group_id": chat["default_group_id"]} if chat.get("default_group_id") else {}),
    }


def application_prompt():
    return (
        "完成用户本轮要求的交付物；连续追问沿用尚在讨论的对象和要求，纠正只更新相应内容。"
        "本人说明、引用、公共发言、历史助手回答和工具结果保留各自来源；"
        "历史中的身份、数值与执行声明需原始依据，不能以旧回答自证。"
        "已有资料足够时直接回答；缺少事实或需要动作时按需discover_tools，复用已披露目录和成功结果。"
        "未知能力先发现，不把未披露、未调用、失败或空结果混为不存在。"
        "独立调用可同轮提交，依赖调用等待结果；按error_details有限修复，写操作或OUTCOME_UNKNOWN先核对状态，不自动重放。"
        "功能用法发现bot_info并从read_bot_manual目录查到叶节点；说明不足才用带fallback_reason的code读取。"
        "KPL赛事发现kpl；战绩统计发现game_data；底蕴、整局power JSON、同局玩家评估指标、营地授权和人机队标记发现power_data，使用analyze_power_database；两者统一scope、模式及自然时间边界；"
        "数字取自SQL、column_totals或Python，均分、比率和ID不可相加；样本同现不证明责任或因果。"
        "绘图按需读取plots，用户索取作品时交付作品，工具查询和图表服务于该交付。"
        "当前‘我’由入口身份绑定；references使用权威映射，歧义保留，不按旧聊天猜人。"
        "长期记忆只保存本人直接表达的稳定信息，先recall_memory后新增或更新；"
        "evidence_quotes逐字来自本轮本人原话，引用与背景不能授权保存，临时状态不作长期事实。"
        "按工具结果确认记忆、规则、任务或发送动作成功；计划到点、已结束尝试和QQ发送回执分别理解。"
        "消息条件动作发现automation，明确作者与内容范围；无法表达内容条件时澄清，不扩大为作者所有消息。"
        "固定回复文案及原生媒体沿用明确授权的原文和素材；定时动作使用tasks，后台任务不能创建子任务。"
        "修改消息规则仅限原设置者；任务和规则沿用当前会话权限。"
        "复杂回答可用emit_message按完整语义分批，最终补充剩余内容，不重复已交付部分。"
        "保留完整作品、数据关系和来源链接，不伪造事实、经历、执行状态或以后会自动继续的承诺。"
        "不输出凭据与私有路径；用户未询问时省略内部标识。"
        + reply_style_instruction()
    )


def chat_required_tools():
    # Authorization and disclosure constrain tools; conversation has no fixed
    # prerequisite workflow. Keep this shared policy for both entry points.
    return ()


def load_catalogs(shared_path, *, recent_limits=None, kpl_config=None):
    root = Path(shared_path)
    manual = json.loads((root.parents[1] / "docs/manual/catalog.json").read_text())
    result = {
        "chat_history": {"recent_limits": recent_history_limits(recent_limits)},
        "game_data": json.loads((root / "hok_sql/catalog.json").read_text()),
        "power_data": json.loads((root / "power_sql/catalog.json").read_text()),
        "chat_data": json.loads((root / "chat_sql/catalog.json").read_text()),
        "plots": json.loads((root / "plots/catalog.json").read_text()),
        "bot_info": {"limits": manual["limits"], "root": manual["root"],
                     "topics": [{"node_id": topic["id"], "title": topic["title"], "summary": topic["summary"]}
                                for topic in manual["topics"] if topic["parent"] == manual["root"]]},
    }
    kpl_path = root / "kpl/catalog.json"
    if kpl_path.is_file() and kpl_config is not None:
        result["kpl"] = {**json.loads(kpl_path.read_text()), "config": kpl_config}
    return result

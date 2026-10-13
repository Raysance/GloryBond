"""Application tools for the local HOK console; never part of the agent kernel."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_runtime.models import ToolResult
from .observations import project_sql_result
from .plotting import PlotArgs, build_plot_code


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiscoverArgs(Args):
    categories: list[str] = Field(min_length=1, max_length=4)


class SearchArgs(Args):
    queries: list[str] = Field(
        min_length=2,
        max_length=6,
        description="从问题提取人物、对象、事件或同义词，生成互补简短查询，不重复原问题",
    )


class WebArgs(Args):
    query: str = Field(min_length=1, max_length=400)
    max_results: int = Field(default=5, ge=1, le=10)


class Query(Args):
    sql: str = Field(min_length=1, max_length=20000)
    params: dict[str, Any] = Field(default_factory=dict)
    intent: str = ""


class SQLArgs(Args):
    queries: list[Query] = Field(min_length=1, max_length=6)


class PythonArgs(Args):
    code: str = Field(min_length=1, max_length=20000)
    dataset_ids: list[str] = Field(default_factory=list, max_length=6)


class ImageArgs(Args):
    prompt: str = Field(min_length=1, max_length=3000)
    size: str = Field(default="1:1", description="图片比例，例如 1:1、3:2、2:3")


class RecallArgs(Args):
    query: str = Field(default="", max_length=300)


class RememberArgs(Args):
    content: str = Field(min_length=1, max_length=2000)
    memory_id: str = ""


class ForgetArgs(Args):
    memory_id: str = Field(min_length=1, max_length=80)


class EmitArgs(Args):
    text: str = Field(min_length=1, max_length=5000)


class EmptyArgs(Args):
    pass


class ReferenceArgs(Args):
    catalogs: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="目录名；空列表查询所有已披露参考目录",
    )
    terms: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="名称、别名或 ID；空列表分页读取目录",
    )
    namespace: str | None = Field(
        default=None,
        description="查询 ID 时指定目录声明的命名空间，例如 qq、player_key、hero_id",
    )
    match: str = Field(default="exact", pattern="^(exact|contains)$")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class TaskArgs(Args):
    kind: Literal["agent", "message"] = Field(
        default="agent",
        description="固定文字定时发送用message；需要查询、推理或调用工具用agent",
    )
    instruction: str = Field(
        default="", max_length=2000, description="agent任务执行的指令"
    )
    message: str | None = Field(
        default=None,
        min_length=1,
        max_length=5000,
        description="message任务发送的固定文字，可用{run}和{max_runs}表示序号和总次数",
    )
    delay_seconds: int | None = Field(
        default=None,
        ge=0,
        le=31536000,
        description="首次执行延迟；省略时周期任务延迟一个周期，单次任务立即执行",
    )
    interval_seconds: int | None = Field(default=None, ge=1, le=31536000)
    max_runs: int = Field(default=1, ge=1, le=1000)

    @model_validator(mode="after")
    def require_action(self):
        if self.kind == "message" and not (self.message or "").strip():
            raise ValueError("message任务必须提供message")
        if self.kind == "agent" and not self.instruction.strip():
            raise ValueError("agent任务必须提供instruction")
        if self.max_runs > 1 and self.interval_seconds is None:
            raise ValueError("多次执行必须提供interval_seconds")
        return self


class CancelTaskArgs(Args):
    task_id: str


def register_application_tools(registry, *, service, catalogs):
    async def discover(args, ctx):
        available = registry.available(ctx)
        unknown = set(args.categories) - {spec.category for spec in available.values()}
        if unknown:
            raise ValueError("未知能力类别：" + ", ".join(sorted(unknown)))
        names = [
            name for name, spec in available.items() if spec.category in args.categories
        ]
        ctx.disclosed.update(names)
        resources = {key: catalogs[key] for key in args.categories if key in catalogs}
        return {
            "tools": names,
            "catalogues": resources,
            "notice": "工具已披露，下一轮可直接调用；能力用途以工具定义为准。SQL 根据查询目录动态生成。",
        }

    async def search(args, ctx):
        return await service.search_history(args.queries, ctx)

    async def sql(args, ctx, domain):
        queries = [
            {**item.model_dump(), "intent": item.intent or ctx.request.user_message}
            for item in args.queries
        ]
        data = await service.analyze(domain, queries, ctx)
        for observation in data["observations"]:
            if observation.get("ok"):
                observation["dataset_id"] = ctx.add_resource(dict(observation))
        return ToolResult(
            all(item.get("ok") for item in data["observations"]),
            data=data,
            error=None
            if all(item.get("ok") for item in data["observations"])
            else "部分查询执行失败",
        )

    async def game_sql(args, ctx):
        return await sql(args, ctx, "game")

    async def chat_sql(args, ctx):
        return await sql(args, ctx, "chat")

    async def web(args, ctx):
        return await service.web_search(args.query, args.max_results)

    async def python(args, ctx):
        data = {key: ctx.resource(key)["rows"] for key in args.dataset_ids}
        result = await service.execute_python(args.code, data)
        for artifact in result.get("artifacts", []):
            await ctx.emit("output.artifact", artifact)
        return result

    async def plot(args, ctx):
        dataset = ctx.resource(args.dataset_id)
        code = build_plot_code(args, dataset, catalogs.get("plots"))
        result = await service.execute_python(code, {args.dataset_id: dataset["rows"]})
        for artifact in result.get("artifacts", []):
            await ctx.emit("output.artifact", artifact)
        return result

    async def image(args, ctx):
        await ctx.emit(
            "output.message",
            {"kind": "progress", "text": "正在生成图片，完成后会发送产物。"},
        )
        result = await service.generate_image(args.prompt, args.size)
        await ctx.emit(
            "output.artifact", {k: v for k, v in result.items() if k != "request"}
        )
        return result

    async def recall(args, ctx):
        return await service.memory("recall", ctx, query=args.query)

    async def remember(args, ctx):
        return await service.memory("remember", ctx, **args.model_dump())

    async def forget(args, ctx):
        return await service.memory("forget", ctx, memory_id=args.memory_id)

    async def emit(args, ctx):
        event = await ctx.emit("output.message", {"kind": "partial", "text": args.text})
        return {"queued": True, "message_id": event["id"]}

    async def templates(args, ctx):
        return {
            **catalogs.get("plots", {}),
            "python": "可用pd、np、plt、df、datasets、render_chart、apply_plot_style、plot_themes。datasets[id]是行列表，需pd.DataFrame转换。默认图表主题已应用；可用apply_plot_style(plot_themes['midnight'])切换。设置result返回JSON，保存PNG或用plt绘图会自动导出。沙箱无网络与凭据。",
        }

    async def task(args, ctx):
        return await service.create_task(args.model_dump(), ctx)

    async def tasks(args, ctx):
        return await service.list_tasks(ctx)

    async def cancel_task(args, ctx):
        return await service.cancel_task(args.task_id, ctx)

    async def reference_catalogs(args, ctx):
        return await service.reference_catalogs(ctx)

    async def reference_lookup(args, ctx):
        result = await service.lookup_reference_data(args.model_dump(), ctx)
        # A reference table can be joined with query datasets by sandbox code.
        # SQL result rows remain the original database observations.
        rows = []
        for item in result.get("matches", []):
            row = {
                "catalog": item["catalog"],
                item["id_namespace"]: item["id"],
                "name": item["name"],
                "aliases": item["aliases"],
            }
            row.update(item.get("ids", {}))
            if "value" in item:
                row["value"] = item["value"]
            rows.append(row)
        if rows:
            result["dataset_id"] = ctx.add_resource(
                {
                    "rows": rows,
                    "columns": list(dict.fromkeys(key for row in rows for key in row)),
                    "source": result["source"],
                    "version": result["version"],
                }
            )
        return result

    specs = [
        (
            "discover_tools",
            "按任务需要披露能力。类别：chat_history、chat_data、game_data、references、internet、python、plots、images、memory、tasks。",
            DiscoverArgs,
            discover,
            "core",
            (),
            30,
            "read",
        ),
        (
            "emit_message",
            "向当前会话发送一条阶段性回复，可以多次调用。",
            EmitArgs,
            emit,
            "core",
            (),
            30,
            "message_send",
        ),
        (
            "search_chat_history",
            "从可信群范围的全部已归档发言中做多 query BM25/RRF 检索；原问题由程序追加。不能用命中条数估算总体。",
            SearchArgs,
            search,
            "chat_history",
            ("chat.read",),
            45,
            "read",
        ),
        (
            "analyze_chat_database",
            "根据发现结果的聊天SQL目录提交动态只读SQL。整批全部校验通过后执行。",
            SQLArgs,
            chat_sql,
            "chat_data",
            ("chat.read",),
            40,
            "read",
        ),
        (
            "analyze_game_database",
            "根据发现结果的王者语义目录提交动态只读SQL。整批先校验，成功结果有dataset_id。",
            SQLArgs,
            game_sql,
            "game_data",
            ("game.read",),
            40,
            "read",
        ),
        (
            "list_reference_catalogs",
            "读取权威参考数据目录、字段用途及版本，包括名称、别名和不同类型 ID 的关系。",
            EmptyArgs,
            reference_catalogs,
            "references",
            ("reference.read",),
            20,
            "read",
        ),
        (
            "lookup_reference_data",
            "按名称、别名或指定命名空间的 ID 查询权威对应关系，或分页读取目录。保留全部歧义匹配。返回 dataset_id 可与 SQL 数据集在 Python 中关联；参考数据不提供战绩、发言统计或权限。",
            ReferenceArgs,
            reference_lookup,
            "references",
            ("reference.read",),
            20,
            "read",
        ),
        (
            "web_search",
            "联网搜索真实网页，返回标题、链接、摘要及发布时间。",
            WebArgs,
            web,
            "internet",
            ("web.read",),
            45,
            "read",
        ),
        (
            "execute_python",
            "在Linux沙箱运行Python；传当前执行的dataset_ids，预置pd、np、plt、df、datasets。设置result返回结果，PNG会自动导出。",
            PythonArgs,
            python,
            "python",
            ("python.execute",),
            40,
            "read",
        ),
        (
            "list_plot_templates",
            "读取图表类型和隔离Python绘图规范。",
            EmptyArgs,
            templates,
            "plots",
            ("python.execute",),
            10,
            "read",
        ),
        (
            "render_plot",
            "使用真实dataset_id绘制设计过的统计图，默认极光主题；可选midnight夜色、sunset落日。支持bar、line、scatter、heatmap、donut；长表热力图必须传value数值列。先读取list_plot_templates。",
            PlotArgs,
            plot,
            "plots",
            ("python.execute",),
            40,
            "read",
        ),
        (
            "generate_image",
            "根据提示词生成图片并发送产物。耗时较长。",
            ImageArgs,
            image,
            "images",
            ("image.generate",),
            180,
            "external_write",
        ),
        (
            "recall_memory",
            "检索当前用户在服务器上的长期事实记忆。",
            RecallArgs,
            recall,
            "memory",
            ("memory.use",),
            20,
            "read",
        ),
        (
            "remember_memory",
            "保存当前用户直接表达的稳定事实，更新时传已查询到的memory_id。",
            RememberArgs,
            remember,
            "memory",
            ("memory.use",),
            20,
            "memory_write",
        ),
        (
            "forget_memory",
            "删除当前用户指定记忆。先查询取得memory_id。",
            ForgetArgs,
            forget,
            "memory",
            ("memory.use",),
            20,
            "memory_write",
        ),
        (
            "create_task",
            "创建当前会话的定时任务。固定文字通知用kind=message直接发送，不再请求模型；查询/推理用kind=agent。周期最短1秒，max_runs为实际执行次数，省略delay_seconds时第一次在一个周期后执行。",
            TaskArgs,
            task,
            "tasks",
            ("task.use",),
            20,
            "task_write",
        ),
        (
            "list_tasks",
            "查看当前会话的后台任务。",
            EmptyArgs,
            tasks,
            "tasks",
            ("task.use",),
            20,
            "read",
        ),
        (
            "cancel_task",
            "取消当前会话的任务，后续触发将停止。",
            CancelTaskArgs,
            cancel_task,
            "tasks",
            ("task.use",),
            20,
            "task_write",
        ),
    ]

    def describe_discovery(ctx):
        categories = sorted(
            {
                spec.category
                for spec in registry.available(ctx).values()
                if spec.category != "core"
            }
        )
        return "按任务需要披露能力。当前注册的能力类别：" + ", ".join(categories)

    for name, description, args, handler, category, scopes, timeout, effect in specs:
        registry.register(
            name=name,
            description=description,
            args_model=args,
            handler=handler,
            category=category,
            scopes=scopes,
            timeout=timeout,
            effect=effect,
            initially_visible=category == "core",
            description_provider=describe_discovery
            if name == "discover_tools"
            else None,
            result_projector=project_sql_result
            if name in {"analyze_game_database", "analyze_chat_database"}
            else None,
        )

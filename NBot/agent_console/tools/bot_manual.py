"""The manual tool contract belongs to the application, not the agent engine."""

from pydantic import BaseModel, ConfigDict, Field, create_model
from typing import Literal


class ManualArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["browse", "search", "read", "code"] | None = Field(default=None,
        description="browse浏览子目录；search在当前节点子目录检索；read读取选中叶节点；code仅用于已读完叶节点仍缺少事实时兜底")
    query: str = Field(default="", max_length=400, description="具体的功能问题；search不跨层全文搜索，按返回node_id继续定位")
    node_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$",
        description="目录返回的节点ID；首次省略即从manual根开始")
    offset: int = Field(default=0, ge=0, le=100000, strict=True, description="只使用返回的next_offset继续读取当前层目录或叶节点正文")
    fallback_reason: str = Field(default="", max_length=400, description="code时必填：已读说明仍未解释的具体事实，不能泛泛写需要代码")


def register_bot_manual_tool(registry, *, service, catalog):
    limits = catalog["limits"]
    arguments = create_model("BotManualArgs", __base__=ManualArgs,
        limit=(int, Field(default=limits["default_limit"], ge=1, le=limits["max_limit"], strict=True,
                          description="最多返回几个相关章节，优先少量精确内容")))

    async def read(args, ctx):
        reads = getattr(ctx, "_manual_reads", {})
        if args.action == "code":
            previous = reads.get(args.node_id)
            if not previous or not previous["complete"] or not args.fallback_reason.strip():
                raise ValueError("先在本轮read对应叶节点的完整正文，再说明未找到的事实后调用code")
        arguments = args.model_dump()
        if args.action == "code":
            arguments["expected_version"] = previous["version"]
        result = await service.read_bot_manual(arguments)
        if args.action == "code" and previous["version"] != result["manual_version"]:
            raise ValueError("手册版本已变动，请重新读取叶节点说明后再核对代码")
        if result["action"] == "read" and result["node"]["is_leaf"]:
            key = result["node"]["node_id"]
            previous = reads.get(key)
            if args.offset == 0 or (previous and previous["version"] == result["manual_version"] and previous["next_offset"] == args.offset):
                reads[key] = {"version": result["manual_version"], "next_offset": result["next_offset"],
                              "complete": result["next_offset"] is None}
                ctx._manual_reads = reads
        available = registry.available(ctx)
        names = list(dict.fromkeys(name for topic in [result["node"], *result["topics"]] for name in topic["related_tools"]))
        result["current_channel"] = ctx.principal.attributes.get("delivery", {}).get("platform", "web")
        result["tool_availability"] = [{"name": name, "registered": name in registry.tools, "authorized": name in available}
                                       for name in names]
        result["notice"] += " 当前工具状态仅表示注册与本次入口授权，外部服务是否成功仍以实际调用结果为准；QQ命令不等于agent可调用工具。"
        return result

    registry.register(name="read_bot_manual", description="查询这个QQ机器人自身的功能、特性、用法、命令、权限和常见问题。"
        "按目录树逐层定位：browse/search返回下一层目录，read只读叶节点说明。"
        "说明不足时code读取该已读叶节点标注的代码位置，并提交fallback_reason；不可直接读取任意代码。"
        "先说明能做什么、怎么操作、会得到什么及使用限制，代码只辅助核对功能，图片不读取。"
        "不能凭模型常识或旧群聊声称机器人有某项功能；不读取任意文件或配置。",
        args_model=arguments, handler=read, category="bot_info", scopes=(), initially_visible=False, timeout=20, effect="read")

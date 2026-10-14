"""The manual tool contract belongs to the application, not the agent engine."""

from pydantic import BaseModel, ConfigDict, Field, create_model


class ManualArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=400, description="有关机器人的功能、命令、特性或实现的问题；空查询返回功能概览")
    section_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$",
        description="可选，使用之前检索结果中的章节ID精确读取")
    include_code: bool = Field(default=False, strict=True, description="手册不够明确或用户询问实现时，读取章节关联的已批准代码摘录")


def register_bot_manual_tool(registry, *, service, catalog):
    limits = catalog["limits"]
    arguments = create_model("BotManualArgs", __base__=ManualArgs,
        limit=(int, Field(default=limits["default_limit"], ge=1, le=limits["max_limit"], strict=True,
                          description="最多返回几个相关章节，优先少量精确内容")))

    async def read(args, ctx):
        result = await service.read_bot_manual(args.model_dump())
        available = registry.available(ctx)
        names = list(dict.fromkeys(name for topic in result["topics"] for name in topic["related_tools"]))
        result["current_channel"] = ctx.principal.attributes.get("delivery", {}).get("platform", "web")
        result["tool_availability"] = [{"name": name, "registered": name in registry.tools, "authorized": name in available}
                                       for name in names]
        result["notice"] += " 当前工具状态仅表示注册与本次入口授权，外部服务是否成功仍以实际调用结果为准；QQ命令不等于agent可调用工具。"
        return result

    registry.register(name="read_bot_manual", description="查询这个QQ机器人自身的功能、特性、用法、命令、权限、记忆与实现。"
        "按问题检索最相关的手册章节，必要时include_code=true读取章节关联的代码摘录；支持section_id精确追问。"
        "先查手册，不能凭模型常识或旧群聊声称机器人有某项功能；不读取任意文件或配置。",
        args_model=arguments, handler=read, category="bot_info", scopes=(), initially_visible=False, timeout=20, effect="read")

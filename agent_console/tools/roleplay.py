"""Injectable role tools; their names and content never enter agent_runtime."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(Args):
    pass


class SelectArgs(Args):
    role_id: str = Field(
        min_length=1, max_length=120, description="目录role_id或唯一的角色名称"
    )


class AddArgs(Args):
    character: str = Field(min_length=1, max_length=120)
    work: str = Field(
        default="", max_length=120, description="所属作品，避免同名角色混淆"
    )
    select: bool = Field(
        default=True, description="创建成功后选用该角色；下一次对话生效"
    )


class PreferencesArgs(Args):
    length: Literal["concise", "standard", "detailed"] | None = None
    address: str | None = Field(default=None, max_length=80)
    style: str | None = Field(
        default=None,
        max_length=1000,
        description="用户直接要求的表达偏好，不用于存储角色背景或授权",
    )

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("至少提供一项回复偏好")
        return self


def register_roleplay_tools(registry, service):
    async def list_roles(args, ctx):
        return await service.manage(ctx.principal)

    async def select_role(args, ctx):
        result = await service.manage(ctx.principal, "select", role_id=args.role_id)
        await ctx.emit(
            "roleplay.changed",
            {"selected": result["selected"], "preferences": result["preferences"]},
        )
        return {**result, "applies": "下一次对话及后台agent任务生效"}

    async def add_role(args, ctx):
        return await service.add_from_web(args, ctx)

    async def preferences(args, ctx):
        result = await service.manage(
            ctx.principal, "preferences", preferences=args.model_dump(exclude_none=True)
        )
        await ctx.emit(
            "roleplay.changed",
            {"selected": result["selected"], "preferences": result["preferences"]},
        )
        return result

    for name, description, schema, handler, timeout, effect in [
        (
            "list_roles",
            "读取当前用户可选角色、当前角色和回复偏好。内置角色共用，联网添加角色仅当前用户可见。",
            EmptyArgs,
            list_roles,
            20,
            "read",
        ),
        (
            "select_role",
            "为当前用户选用已存在的角色，跨会话保存；下一次对话及后台agent任务生效。关闭角色风格请选择assistant。",
            SelectArgs,
            select_role,
            20,
            "preference_write",
        ),
        (
            "add_role_from_web",
            "联网搜索指定角色和作品，依据真实来源生成背景、性格与语言风格，保存到当前用户角色库。可创建后自动选用。",
            AddArgs,
            add_role,
            160,
            "external_write",
        ),
        (
            "set_reply_preferences",
            "保存当前用户的回复长度、称呼、表达偏好，跨会话生效。兴趣等稳定事实使用memory工具。",
            PreferencesArgs,
            preferences,
            20,
            "preference_write",
        ),
    ]:
        registry.register(
            name=name,
            description=description,
            args_model=schema,
            handler=handler,
            category="roleplay",
            scopes=("roleplay.use", "web.read")
            if name == "add_role_from_web"
            else ("roleplay.use",),
            timeout=timeout,
            effect=effect,
            initially_visible=False,
        )

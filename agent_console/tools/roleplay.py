"""Injectable role tools; their names and content never enter agent_runtime."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from agent_console.roleplay import emit_role_change, role_change_applies


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleTargetArgs(Args):
    target_user_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$",
        description="省略表示本人；仅QQ超级管理员可指定其他用户QQ，须来自本次明确目标、原生@或权威名称映射")


class SelectArgs(RoleTargetArgs):
    role_id: str = Field(
        min_length=1, max_length=120, description="目录role_id或唯一的角色名称"
    )


class AddArgs(RoleTargetArgs):
    character: str = Field(min_length=1, max_length=120)
    work: str = Field(
        default="", max_length=120, description="所属作品，避免同名角色混淆"
    )
    select: bool = Field(
        default=True, description="创建成功后为目标用户选用该角色；未指定目标时本次最终回复及后续对话生效"
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


def register_roleplay_tools(registry, service, *, authorize_target=None):
    async def target_user(args, ctx):
        target = args.target_user_id
        if target is None or target == ctx.principal.user_id:
            return None
        if "roleplay.manage_others" not in ctx.principal.scopes or authorize_target is None:
            raise PermissionError("仅QQ超级管理员可为其他用户管理角色")
        await authorize_target(ctx, target)
        return target

    async def list_roles(args, ctx):
        target = await target_user(args, ctx)
        return await service.manage(ctx.principal, target_user_id=target)

    async def select_role(args, ctx):
        target = await target_user(args, ctx)
        result = await service.manage(ctx.principal, "select", role_id=args.role_id, target_user_id=target)
        await emit_role_change(ctx, result, target)
        return {**result, "applies": role_change_applies(target)}

    async def add_role(args, ctx):
        target = await target_user(args, ctx)
        return await service.add_from_web(args, ctx, target_user_id=target)

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
            "读取本人可选角色、当前角色和回复偏好。QQ超级管理员可用target_user_id查看指定用户的角色目录及当前角色，不返回对方回复偏好。内置角色共用，联网添加角色按用户隔离。",
            RoleTargetArgs,
            list_roles,
            20,
            "read",
        ),
        (
            "select_role",
            "为本人选用已存在的角色，跨会话保存；本次最终回复、后续对话及后台agent任务生效。"
            "QQ超级管理员可指定target_user_id为别人换角色，先用list_roles(target_user_id)读取目标目录，"
            "角色不存在时按用户要求用add_role_from_web为同一目标添加并选用。替别人换角色不会切换管理员本人，关闭角色风格请选择assistant。",
            SelectArgs,
            select_role,
            20,
            "preference_write",
        ),
        (
            "add_role_from_web",
            "联网搜索指定角色和作品，依据真实来源生成背景、性格与语言风格，保存到本人角色库。可创建后自动选用。"
            "QQ超级管理员可指定target_user_id为别人添加并选用角色，保存到目标用户的独立角色库，不更改管理员自己的角色或目标回复偏好。",
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

"""Explicit application functions with bounded, run-local disclosure and execution.

This adapter never imports modules or resolves attributes supplied by a model.
"""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
import inspect
import json
import re

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime import ToolResult


_active_function = ContextVar("application_function", default=None)


def assert_outside_function():
    if _active_function.get() is not None:
        raise RuntimeError("业务函数调用中禁止重新进入 AI、注册工具或创建定时任务")


@dataclass
class FunctionOutput:
    text: str = ""
    images: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    description: str
    category: str
    args_model: type[BaseModel]
    handler: object
    scopes: frozenset[str]
    effect: str


class FunctionCatalog:
    """Only trusted application code can register callable implementations."""

    def __init__(self, *, max_calls=8, timeout_seconds=60, max_result_chars=12000):
        self.max_calls = max(1, min(16, int(max_calls)))
        self.timeout = max(1, min(180, float(timeout_seconds)))
        self.max_result_chars = max(1000, min(24000, int(max_result_chars)))
        self.functions = {}
        # Legacy renderers share output paths. Hold this slot until the actual
        # worker completes, including after the caller times out or cancels.
        self._running = None
        self._busy = False

    def register(self, *, name, description, category, args_model, handler,
                 scopes=("game.read",), effect="read"):
        assert_outside_function()
        if (not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", name)
                or name.startswith(("agent_", "chat_", "task_", "_"))
                or name in {"ai_parser", "service_health_check", "notify_msg_impl"}):
            raise ValueError("禁止登记 AI、调度、诊断或内部入口")
        if name in self.functions:
            raise ValueError("业务函数已登记：" + name)
        if (not isinstance(description, str) or not 1 <= len(description) <= 300
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", category)):
            raise ValueError("业务函数需要简短描述和合法分类")
        if effect not in {"read", "write"} or not callable(handler):
            raise ValueError("业务函数必须声明 read/write 及可信处理器")
        if args_model.model_config.get("extra") != "forbid":
            raise ValueError("业务参数必须拒绝未声明字段")
        if len(json.dumps(args_model.model_json_schema(), ensure_ascii=False)) > 6000:
            raise ValueError("单个业务函数参数定义过大，请拆分接口")
        self.functions[name] = FunctionSpec(name, description, category, args_model,
            handler, frozenset(scopes), effect)

    def available(self, ctx):
        return {name: spec for name, spec in self.functions.items()
                if spec.scopes <= ctx.principal.scopes}

    def search(self, args, ctx):
        terms = args.query.casefold().split()
        matches = [spec for spec in self.available(ctx).values()
                   if (not args.category or args.category == spec.category)
                   and all(term in f"{spec.name} {spec.description} {spec.category}".casefold()
                           for term in terms)]
        page = matches[args.offset:args.offset + args.limit]
        return {"functions": [{"name": s.name, "description": s.description,
                    "category": s.category, "effect": s.effect} for s in page],
                "categories": sorted({s.category for s in self.available(ctx).values()}),
                "total": len(matches),
                "next_offset": args.offset + len(page) if args.offset + len(page) < len(matches) else None,
                "notice": "先 describe_hok_function 读取选中函数参数，再调用；未列出的函数不可执行。"}

    def _state(self, ctx):
        if not hasattr(ctx, "_hok_function_state"):
            ctx._hok_function_state = {"described": set(), "calls": {}}
        return ctx._hok_function_state

    def describe(self, name, ctx):
        spec = self.available(ctx).get(name)
        if spec is None:
            return ToolResult(False, error="函数不存在或未获授权", code="FUNCTION_UNAVAILABLE")
        self._state(ctx)["described"].add(name)
        return {"name": name, "description": spec.description, "category": spec.category,
                "parameters": spec.args_model.model_json_schema(), "effect": spec.effect}

    async def call(self, name, arguments, ctx, *, publish_image=None, format_text=str):
        assert_outside_function()
        spec = self.available(ctx).get(name)
        state = self._state(ctx)
        if spec is None:
            return ToolResult(False, error="函数不存在或未获授权", code="FUNCTION_UNAVAILABLE")
        if name not in state["described"]:
            return ToolResult(False, error="先读取本轮函数参数定义", code="FUNCTION_NOT_DESCRIBED")
        try:
            args = spec.args_model.model_validate(arguments)
        except ValueError as exc:
            return ToolResult(False, error=str(exc), code="INVALID_ARGUMENTS")
        key = (name, json.dumps(args.model_dump(mode="json"), sort_keys=True, ensure_ascii=False))
        if key in state["calls"]:
            previous = state["calls"][key]
            return previous if previous is not None else ToolResult(False,
                error="相同调用正在执行或已被取消，禁止重复提交", code="FUNCTION_ALREADY_CALLED")
        if len(state["calls"]) >= self.max_calls:
            return ToolResult(False, error="本轮业务函数调用次数已达上限", code="FUNCTION_CALL_LIMIT")
        if self._busy:
            return ToolResult(False, error="上一业务调用尚未结束，请稍后再查", code="FUNCTION_BUSY")
        state["calls"][key] = None
        self._busy = True

        async def invoke():
            token = _active_function.set(name)
            try:
                if inspect.iscoroutinefunction(spec.handler):
                    return await spec.handler(args, ctx)
                return await asyncio.to_thread(spec.handler, args, ctx)
            finally:
                _active_function.reset(token)

        job = self._running = asyncio.create_task(invoke())
        # Consume late failures without replaying or producing late output.
        job.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        try:
            async with asyncio.timeout(self.timeout):
                output = await asyncio.shield(job)
                if not isinstance(output, FunctionOutput):
                    raise TypeError("业务函数必须返回 FunctionOutput")
                text = format_text(output.text)
                data = json.loads(json.dumps(output.data, ensure_ascii=False, allow_nan=False))
                if len(json.dumps(data, ensure_ascii=False)) > self.max_result_chars:
                    raise ValueError("业务结构化结果过大，请收窄参数")
                truncated = len(text) > self.max_result_chars
                text = text[:self.max_result_chars]
                images = []
                for image in output.images[:4]:
                    if publish_image is None:
                        raise ValueError("此入口没有图片产物出口")
                    images.append(await publish_image(image, ctx))
                result = ToolResult(True, data={"function": name, "text": text, "data": data,
                    "artifacts": images, "truncated": truncated or len(output.images) > 4})
        except TimeoutError:
            result = ToolResult(False, error="业务函数超时；不重复执行本轮相同调用",
                code="OUTCOME_UNKNOWN" if spec.effect != "read" else "TOOL_TIMEOUT")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Record failure before diagnostics formats it; retrying the same
            # failing call must never produce another side effect.
            state["calls"][key] = ToolResult(False, error="本轮相同调用已失败，请检查先前诊断",
                code="FUNCTION_ALREADY_CALLED")
            raise
        finally:
            if job.done():
                self._busy = False
            else:
                job.add_done_callback(lambda done: setattr(self, "_busy", False))
        state["calls"][key] = result
        return result


class FunctionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFunctionsArgs(FunctionArgs):
    query: str = Field(default="", max_length=100, description="用途、名称或关键词；空字符串按分类浏览")
    category: str = Field(default="", max_length=80)
    offset: int = Field(default=0, ge=0, le=10000, strict=True)
    limit: int = Field(default=5, ge=1, le=8, strict=True)


class DescribeFunctionArgs(FunctionArgs):
    name: str = Field(min_length=1, max_length=80)


class CallFunctionArgs(DescribeFunctionArgs):
    arguments: dict = Field(default_factory=dict, description="严格按本轮 describe 返回的参数填写，不得提供身份、目的地或模块路径")


def register_function_tools(registry, *, catalog, publish_image=None, format_text=str):
    async def search(args, ctx):
        return catalog.search(args, ctx)

    async def describe(args, ctx):
        return catalog.describe(args.name, ctx)

    async def call(args, ctx):
        return await catalog.call(args.name, args.arguments, ctx,
                                  publish_image=publish_image, format_text=format_text)

    for name, description, args, handler in [
        ("search_hok_functions", "按用途或分类搜索现有 HOK 业务函数，仅返回有权限的简短卡片，分页按需读取。", SearchFunctionsArgs, search),
        ("describe_hok_function", "只读取一个选中函数的参数定义；每轮调用前须先读取，不披露其他函数定义。", DescribeFunctionArgs, describe),
        ("call_hok_function", "执行本轮已读取定义的现有业务函数。前台与定时agent任务共用；相同参数本轮只执行一次。禁止递归AI或派生定时任务。", CallFunctionArgs, call),
    ]:
        registry.register(name=name, description=description, args_model=args, handler=handler,
            category="hok_business", scopes=("game.read",), initially_visible=False,
            timeout=catalog.timeout + 2, effect="write" if name == "call_hok_function" else "read")

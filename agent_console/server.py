from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, model_validator
import yaml
from dotenv import dotenv_values

from agent_runtime import AgentRuntime, RunRequest
from .tools.diagnostics import DiagnosticToolRegistry
from .tool_errors import redact_error
from .tasks import TaskScheduler
from .timeouts import application_budget
from .tools.application import register_application_tools
from .capabilities import (
    Capabilities,
    Clock,
    application_prompt,
    chat_required_tools,
    load_catalogs,
    reference_prompt,
)
from .provider import DeepSeekModel, remote_model_options
from .image_inputs import ImageLimits, ImageStore
from .local_logs import LocalEventLog
from .remote import BridgeUnavailable, RemoteBridge, RemoteState
from .roleplay import RoleplayService
from .replies import DeliveryHistory, ReplyComposer, ReplyPolicy
from .identity import local_principal
from .model_metadata import observe_model_event
from .webpages import WebPageFetcher, WebPageLimits
from .tools.roleplay import PreferencesArgs, SelectArgs, register_roleplay_tools


class EventBroker:
    def __init__(self, bridge, event_projector=None, local_log=None):
        self.bridge = bridge
        self.event_projector = event_projector
        self.local_log = local_log
        self.events = {}
        self.delivery_history = DeliveryHistory()
        self.condition = asyncio.Condition()

    async def publish(self, event):
        observe_model_event(event)
        if self.event_projector:
            event = self.event_projector(event)
        clean = self.bridge.redact(event)
        if self.local_log and not await self.local_log.record(clean):
            clean["local_log_error"] = self.local_log.last_error
        async with self.condition:
            self.events.setdefault(event["session_id"], []).append(clean)
            self.condition.notify_all()
            self.delivery_history.record(clean)


class ChatInput(BaseModel):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    message: str = Field(default="", max_length=12000)
    image_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.message.strip() and not self.image_ids:
            raise ValueError("请提供文字或图片")
        return self


def local_model_settings(config, remote, *, environment):
    """Resolve only Web credentials; an endpoint override never reuses a remote key."""
    overrides = config.get("llm")
    if not overrides:
        return {
            **remote_model_options(remote),
            "api_key": remote["private"]["api_key"],
            "base_url": remote["public"]["base_url"],
            "model": remote["public"]["model"],
            "vision_model": config.get("vision_model", remote["public"]["model"]),
            "proxy_url": remote["public"].get("proxy_url", ""),
        }
    base_url, key_name = overrides.get("base_url"), overrides.get("api_key_env")
    if not base_url or not key_name:
        raise ValueError("LocalAgent.llm 必须同时配置 base_url 和 api_key_env")
    key = environment.get(key_name)
    if not key:
        raise ValueError(f"本地模型密钥未配置：{key_name}")
    model = overrides.get("model", remote["public"]["model"])
    return {
        "api_key": key, "base_url": base_url, "model": model,
        "vision_model": overrides.get("vision_model", model),
        "proxy_url": overrides.get("proxy_url", ""),
    }


def create_app(*, config_path=None):
    root = Path(__file__).resolve().parents[1]
    document = yaml.safe_load(Path(config_path or root / "config.yaml").read_text())
    config = document.get("LocalAgent", {})
    token = secrets.token_urlsafe(32)
    shared = root / "shared/agent"
    public = {}
    active_sessions = {}
    image_store = ImageStore(
        root / "file_transfer/agent_inputs", ImageLimits(**config.get("images", {}))
    )
    webpages = WebPageFetcher(WebPageLimits(**config.get("webpages", {})),
                             proxy_url=os.environ.get("HOK_CLASH_PROXY_URL") or document.get("Proxy", {}).get("clash_url"))

    @asynccontextmanager
    async def lifespan(app):
        bridge = RemoteBridge(
            config.get("ssh_host", "Aliyun"),
            config.get("remote_root", "/srv/modules/hok/apps/HOK_QQBot"),
            config.get("remote_python", "/srv/modules/hok/apps/HOK_QQBot/.venv/bin/python"),
            shared,
        )
        state_bridge = RemoteBridge(bridge.host, bridge.root, bridge.python, shared)
        bridge.kpl_config = state_bridge.kpl_config = document.get("AgentKPL")
        try:
            remote = await bridge.start()
            await state_bridge.start()
            public.update(remote["public"])
            model_settings = local_model_settings(config, remote, environment={
                **dotenv_values(os.environ.get("HOK_ENV_FILE") or root / ".env"),
                **os.environ,
            })
            for connection in (bridge, state_bridge):
                if model_settings["api_key"] not in connection.secrets:
                    connection.secrets.append(model_settings["api_key"])
            public.update({name: model_settings[name] for name in ("base_url", "model", "vision_model", "proxy_url")})
            model = DeepSeekModel(
                **model_settings,
                thinking=config.get("thinking", True),
                max_tokens=config.get("max_tokens", 4096),
                image_store=image_store,
            )
            registry = DiagnosticToolRegistry(redactor=lambda value: redact_error(state_bridge.redact(bridge.redact(value))))
            catalogs = load_catalogs(shared, recent_limits=public.get("recent_history_limits"),
                                     kpl_config=public.get("kpl_config"))
            catalogs["references"] = public["references"]["directory"]
            register_application_tools(
                registry, service=Capabilities(bridge, state_bridge), catalogs=catalogs
            )
            roles = RoleplayService(
                bridge=state_bridge,
                capabilities=Capabilities(bridge, state_bridge),
                model=model,
                default_role=config.get("default_role", "makise_kurisu"),
            )
            register_roleplay_tools(registry, roles)
            reply_model = DeepSeekModel(
                **model_settings,
                thinking=False,
                max_tokens=config.get("max_tokens", 4096),
                response_format={"type": "json_object"},
            )
            app.state.roles = roles
            app.state.principal = local_principal(
                public["references"], config.get("player_key", "")
            )
            public["identity"] = app.state.principal.attributes["identity"]
            log_config = config.get("local_logging", {})
            local_log = LocalEventLog(
                root / log_config.get("directory", "log/agent_console"),
                enabled=log_config.get("enabled", True),
                redactor=bridge.redact,
            )
            app.state.local_log = local_log
            state = RemoteState(
                state_bridge, event_projector=image_store.project_event, local_log=local_log
            )
            broker = EventBroker(
                bridge, event_projector=image_store.project_event, local_log=local_log
            )
            runtime = AgentRuntime(
                model=model,
                registry=registry,
                state=state,
                output=broker,
                clock=Clock(),
                finalizer=ReplyComposer(
                    model=reply_model,
                    roles=roles,
                    policy=ReplyPolicy(**config.get("reply", {})),
                    delivery_history=broker.delivery_history,
                ),
            )
            app.state.bridge, app.state.runtime, app.state.broker = (
                bridge,
                runtime,
                broker,
            )
            app.state.state_bridge = state_bridge
            system_prompt = (
                application_prompt()
                + "当前是通过已认证SSH连接的本地管理员控制台，群聊查询允许全归档。"
                f"现在时间 {Clock().now()}。英雄历史统计未指定时期时从本赛季 {public.get('season_start')} 开始。"
            )
            app.state.system_prompt = system_prompt
            app.state.catalogs = catalogs

            async def current_prompt(principal=None, query=""):
                snapshot = await bridge.call("reference_snapshot")
                public["references"] = snapshot
                catalogs["references"] = snapshot["directory"]
                if principal is None:
                    principal = local_principal(
                        snapshot, config.get("player_key", "")
                    )
                    app.state.principal = principal
                    public["identity"] = principal.attributes["identity"]
                return (
                    system_prompt
                    + "\n本次请求时间："
                    + Clock().now()
                    + "\n"
                    + reference_prompt(snapshot)
                    + await roles.context(principal, query)
                )

            app.state.current_prompt = current_prompt

            task_scheduler = TaskScheduler(
                runtime=runtime,
                bridge=state_bridge,
                state=state,
                output=broker,
                clock=Clock(),
                prompt_factory=current_prompt,
                budget=application_budget(config.get("budget")),
            )
            app.state.task_scheduler = task_scheduler
            scheduler = asyncio.create_task(task_scheduler.run())
            yield
            scheduler.cancel()
            try:
                await scheduler
            except asyncio.CancelledError:
                pass
            await task_scheduler.close()
            await runtime.close()
        finally:
            await state_bridge.close()
            await bridge.close()

    app = FastAPI(title="Agent Studio", lifespan=lifespan)

    @app.exception_handler(BridgeUnavailable)
    async def bridge_unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.cookies.get("agent_console") != token:
                return Response(
                    "Local console authentication required", status_code=403
                )
            if request.method != "GET" and request.headers.get("x-local-ui") != "1":
                return Response("Missing local UI header", status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return Response("Origin rejected", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).with_name("static")),
        name="static",
    )

    @app.get("/")
    async def index():
        response = HTMLResponse(
            Path(__file__).with_name("static").joinpath("index.html").read_text()
        )
        response.set_cookie("agent_console", token, httponly=True, samesite="strict")
        return response

    @app.get("/api/status")
    async def status():
        connections = await asyncio.gather(app.state.bridge.health(), app.state.state_bridge.health())
        return {
            **public,
            "connections": {"business": connections[0], "state": connections[1]},
            "thinking": config.get("thinking", True),
            "vision_model": public.get("vision_model", config.get("vision_model", public.get("model"))),
            "image_limits": vars(image_store.limits),
            "local_logging": app.state.local_log.status,
            "tools": [
                {"name": t.name, "category": t.category, "description": t.description}
                for t in app.state.runtime.registry.tools.values()
            ],
        }

    @app.post("/api/images")
    async def upload_image(request: Request, name: str = "图片"):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > image_store.limits.max_image_bytes:
                raise HTTPException(413, "图片超过单张大小限制")
            data.extend(chunk)
        try:
            return image_store.save(bytes(data), name)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/images/{image_id}")
    async def input_image(image_id: str):
        try:
            info, data = image_store.load(image_id)
            return Response(data, media_type=info["mime"])
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/sessions/{session_id}")
    async def session(session_id: str):
        events = await app.state.runtime.state.load_events(session_id)
        starts = {event["run_id"] for event in events if event["kind"] == "run.start"}
        ends = {event["run_id"] for event in events if event["kind"] == "run.end"}
        for interrupted in (
            starts
            - ends
            - set(app.state.runtime.active)
            - app.state.task_scheduler.active_run_ids
        ):
            marker = {
                "id": secrets.token_hex(16),
                "run_id": interrupted,
                "session_id": session_id,
                "time": Clock().now(),
                "kind": "run.end",
                "data": {"status": "interrupted"},
                "transient": False,
            }
            await app.state.runtime.state.append_event(session_id, marker)
            await app.state.local_log.record(marker)
            events.append(marker)
        app.state.broker.events.setdefault(session_id, events)
        return {"events": events, "active_run": active_sessions.get(session_id)}

    @app.get("/api/roleplay")
    async def roleplay():
        return {
            "identity": app.state.principal.attributes["identity"],
            **await app.state.roles.manage(app.state.principal),
        }

    @app.post("/api/roleplay/select")
    async def select_role(body: SelectArgs):
        try:
            return await app.state.roles.manage(
                app.state.principal, "select", role_id=body.role_id, target_user_id=body.target_user_id
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/roleplay/preferences")
    async def reply_preferences(body: PreferencesArgs):
        return await app.state.roles.manage(
            app.state.principal,
            "preferences",
            preferences=body.model_dump(exclude_none=True),
        )

    @app.post("/api/chat")
    async def chat(body: ChatInput):
        if body.session_id in active_sessions:
            raise HTTPException(409, "当前会话仍在执行，可停止后再发送")
        try:
            images = image_store.inputs(body.image_ids)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        message = body.message.strip() or "请分析这些图片。"
        run_id = secrets.token_hex(16)
        async def log_request(kind, data):
            await app.state.local_log.record({
                "id": secrets.token_hex(16), "run_id": run_id,
                "session_id": body.session_id, "time": Clock().now(),
                "kind": kind, "data": data, "transient": False,
            })

        await log_request("request.received", body.model_dump())
        try:
            prompt = await app.state.current_prompt(query=message)
            role_name = (await app.state.roles.manage(app.state.principal))["selected"]["name"]
            page_context = await webpages.prepare([("message", message)])
            if page_context.report:
                await log_request("request.webpages", page_context.report)
            if body.session_id in active_sessions:
                raise HTTPException(409, "当前会话仍在执行，可停止后再发送")
        except Exception as exc:
            await log_request("request.failed", {
                **body.model_dump(), "error": str(exc),
                "type": type(exc).__name__, "traceback": traceback.format_exc(),
            })
            raise
        principal = app.state.principal
        request = RunRequest(
            run_id=run_id,
            user_message=message,
            budget=application_budget(config.get("budget")),
            images=images,
            context_messages=page_context.messages,
            conversation_id=body.session_id,
            principal=principal,
            system_prompt=prompt,
            required_tools=chat_required_tools(),
            metadata={"role_name": role_name},
        )
        run_id = app.state.runtime.submit(request)
        active_sessions[body.session_id] = run_id
        task = app.state.runtime.active[run_id]
        task.add_done_callback(lambda _: active_sessions.pop(body.session_id, None))
        return {"run_id": run_id}

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        return {"cancelled": await app.state.runtime.cancel(run_id)}

    @app.get("/api/events/{session_id}")
    async def events(session_id: str, request: Request):
        broker = app.state.broker
        last = request.headers.get("last-event-id") or request.query_params.get("after")
        if session_id not in broker.events:
            broker.events[session_id] = await app.state.runtime.state.load_events(
                session_id
            )
        existing = broker.events[session_id]
        offset = (
            next((i + 1 for i, e in enumerate(existing) if e["id"] == last), 0)
            if last
            else 0
        )

        async def generate():
            nonlocal offset
            while not await request.is_disconnected():
                current = broker.events.get(session_id, [])
                while offset < len(current):
                    event = current[offset]
                    offset += 1
                    yield f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                try:
                    async with broker.condition:
                        await asyncio.wait_for(broker.condition.wait(), 10)
                except TimeoutError:
                    yield ": keepalive\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/api/artifacts/{artifact_id}")
    async def artifact(artifact_id: str):
        if len(artifact_id) != 32 or any(
            c not in "0123456789abcdef" for c in artifact_id
        ):
            raise HTTPException(404)
        value = await app.state.bridge.call("artifact", artifact_id=artifact_id)
        if not value:
            raise HTTPException(404, "产物已过期")
        raw = base64.b64decode(value)
        mime = (
            "image/png"
            if raw.startswith(b"\x89PNG")
            else "image/jpeg"
            if raw.startswith(b"\xff\xd8")
            else "image/webp"
            if raw.startswith(b"RIFF")
            else None
        )
        if not mime:
            raise HTTPException(415, "不支持的图片格式")
        return Response(raw, media_type=mime)

    return app

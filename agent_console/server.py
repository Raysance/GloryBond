from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
import yaml

from agent_runtime import AgentRuntime, RunRequest, ToolRegistry
from .tasks import TaskScheduler
from .tools.application import register_application_tools
from .capabilities import (
    Capabilities,
    Clock,
    application_prompt,
    chat_required_tools,
    load_catalogs,
    reference_prompt,
)
from .provider import DeepSeekModel
from .remote import RemoteBridge, RemoteState
from .roleplay import RoleplayService
from .identity import local_principal
from .tools.roleplay import PreferencesArgs, SelectArgs, register_roleplay_tools


class EventBroker:
    def __init__(self, bridge):
        self.bridge = bridge
        self.events = {}
        self.condition = asyncio.Condition()

    async def publish(self, event):
        clean = self.bridge.redact(event)
        async with self.condition:
            self.events.setdefault(event["session_id"], []).append(clean)
            self.condition.notify_all()


class ChatInput(BaseModel):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    message: str = Field(min_length=1, max_length=12000)


def create_app(*, config_path=None):
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load(Path(config_path or root / "config.yaml").read_text()).get(
        "LocalAgent", {}
    )
    token = secrets.token_urlsafe(32)
    shared = root / "shared/agent"
    public = {}
    active_sessions = {}

    @asynccontextmanager
    async def lifespan(app):
        bridge = RemoteBridge(
            config.get("ssh_host", "Aliyun"),
            config.get("remote_root", "/srv/modules/hok/apps/NBot"),
            config.get("remote_python", "/srv/modules/hok/apps/NBot/.venv/bin/python"),
            shared,
        )
        state_bridge = RemoteBridge(bridge.host, bridge.root, bridge.python, shared)
        try:
            remote = await bridge.start()
            await state_bridge.start()
            public.update(remote["public"])
            model = DeepSeekModel(
                api_key=remote["private"]["api_key"],
                base_url=public["base_url"],
                model=public["model"],
                thinking=config.get("thinking", True),
                max_tokens=config.get("max_tokens", 4096),
            )
            registry = ToolRegistry()
            catalogs = load_catalogs(shared)
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
            app.state.roles = roles
            app.state.principal = local_principal(
                public["references"], config.get("player_key", "example_user_10")
            )
            public["identity"] = app.state.principal.attributes["identity"]
            state = RemoteState(state_bridge)
            broker = EventBroker(bridge)
            runtime = AgentRuntime(
                model=model,
                registry=registry,
                state=state,
                output=broker,
                clock=Clock(),
            )
            app.state.bridge, app.state.runtime, app.state.broker = (
                bridge,
                runtime,
                broker,
            )
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
                        snapshot, config.get("player_key", "example_user_10")
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
        return {
            **public,
            "thinking": config.get("thinking", True),
            "tools": [
                {"name": t.name, "category": t.category, "description": t.description}
                for t in app.state.runtime.registry.tools.values()
            ],
        }

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
                app.state.principal, "select", role_id=body.role_id
            )
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
        prompt = await app.state.current_prompt(query=body.message)
        principal = app.state.principal
        if body.session_id in active_sessions:
            raise HTTPException(409, "当前会话仍在执行，可停止后再发送")
        request = RunRequest(
            user_message=body.message,
            conversation_id=body.session_id,
            principal=principal,
            system_prompt=prompt,
            required_tools=chat_required_tools(),
            metadata={
                "role_name": (await app.state.roles.manage(principal))["selected"][
                    "name"
                ]
            },
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

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import shlex


class RemoteBridge:
    """One authenticated SSH connection; no database port or remote web server."""

    def __init__(self, host, root, python, shared_path):
        self.host, self.root, self.python = host, root, python
        self.shared_path = Path(shared_path)
        self.process = None
        self.lock = asyncio.Lock()
        self.config = {}
        self.secrets = []

    async def start(self):
        source = Path(__file__).with_name("remote_worker.py").read_text()
        command = (
            "exec(__import__('base64').b64decode("
            + repr(base64.b64encode(source.encode()).decode())
            + "))"
        )
        self.process = await asyncio.create_subprocess_exec(
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            self.host,
            self.python,
            "-u",
            "-c",
            shlex.quote(command),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,
        )
        catalogs = {
            domain: json.loads((self.shared_path / domain / "catalog.json").read_text())
            for domain in ("hok_sql", "chat_sql")
        }
        definitions = json.loads((self.shared_path / "hok_sql/views.json").read_text())
        validator = Path(__file__).with_name("tools") / "sql_validation.py"
        self.config = await self.call(
            "bootstrap",
            root=self.root,
            catalogs=catalogs,
            definitions=definitions,
            validator=validator.read_text(),
            sandbox_runner=Path(__file__).with_name("sandbox_worker.py").read_text(),
            plot_renderer=Path(__file__).with_name("plot_renderer.py").read_text(),
            plot_catalog=json.loads(
                (self.shared_path / "plots/catalog.json").read_text()
            ),
            task_timing=Path(__file__).with_name("task_timing.py").read_text(),
            roleplay_models=Path(__file__).with_name("roleplay_models.py").read_text(),
            roleplay_store=Path(__file__).with_name("roleplay_store.py").read_text(),
            roles=[
                json.loads(path.read_text())
                for path in sorted((self.shared_path / "roles").glob("*.json"))
            ],
            reference_manifest=json.loads(
                (self.shared_path / "reference_data/manifest.json").read_text()
            ),
            reference_builder=(
                Path(__file__).with_name("tools") / "reference_data.py"
            ).read_text(),
        )
        self.secrets = [
            value
            for value in self.config.get("private", {}).values()
            if isinstance(value, str) and value
        ]
        return self.config

    def redact(self, value):
        if isinstance(value, dict):
            return {
                k: (
                    "[redacted]"
                    if any(
                        t in k.lower()
                        for t in ("api_key", "password", "authorization", "dsn")
                    )
                    else self.redact(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
        return value

    async def call(self, op, **args):
        # A cancelled caller must not leave an unread response for the next RPC.
        exchange = asyncio.create_task(self._exchange(op, **args))

        def consume_error(task):
            if not task.cancelled():
                task.exception()

        exchange.add_done_callback(consume_error)
        return await asyncio.shield(exchange)

    async def _exchange(self, op, **args):
        async with self.lock:
            if not self.process or self.process.returncode is not None:
                raise RuntimeError("SSH 连接未启动或已断开，请重启本地界面")

            def encode(value):
                return (
                    sorted(value) if isinstance(value, (set, frozenset)) else str(value)
                )

            self.process.stdin.write(
                (
                    json.dumps({"op": op, **args}, ensure_ascii=False, default=encode)
                    + "\n"
                ).encode()
            )
            await self.process.stdin.drain()
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), 190)
            except TimeoutError:
                # A late response must not be mistaken for the next RPC's result.
                self.process.terminate()
                raise
            if not line:
                raise RuntimeError("SSH 适配器连接已断开")
            payload = json.loads(line)
            if not payload.get("ok"):
                raise RuntimeError(self.redact(payload.get("error", "远程操作失败")))
            return payload.get("data")

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()


class RemoteState:
    def __init__(self, bridge, event_projector=None, local_log=None):
        self.bridge = bridge
        self.event_projector = event_projector
        self.local_log = local_log

    async def append_event(self, session_id, event):
        if self.event_projector:
            event = self.event_projector(event)
        await self.bridge.call(
            "state_append", session_id=session_id, event=self.bridge.redact(event)
        )

    async def load_events(self, session_id):
        events = await self.bridge.call("state_events", session_id=session_id)
        if self.local_log:
            await self.local_log.record_many(events)
        return events

    async def load_dialogue(self, session_id):
        return await self.bridge.call("dialogue_load", session_id=session_id)

    async def save_dialogue(self, session_id, question, answer):
        await self.bridge.call(
            "dialogue_save", session_id=session_id, question=question, answer=answer
        )

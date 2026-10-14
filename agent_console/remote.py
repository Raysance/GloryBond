from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import shlex
import yaml


class BridgeUnavailable(ConnectionError):
    """Transport or health failure suitable for an HTTP 503 response."""


class RemoteBridge:
    """One authenticated SSH connection; no database port or remote web server."""

    def __init__(self, host, root, python, shared_path):
        self.host, self.root, self.python = host, root, python
        self.shared_path = Path(shared_path)
        self.process = None
        self.lock = asyncio.Lock()
        self.config = {}
        self.secrets = []
        self._bootstrap_args = None
        self._closed = False
        self.response_timeout = 190
        self.kpl_config = None

    async def _spawn_worker(self):
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

    def _bootstrap_arguments(self):
        catalogs = {
            domain: json.loads((self.shared_path / domain / "catalog.json").read_text())
            for domain in ("hok_sql", "chat_sql")
        }
        definitions = json.loads((self.shared_path / "hok_sql/views.json").read_text())
        validator = Path(__file__).with_name("tools") / "sql_validation.py"
        return dict(
            root=self.root, catalogs=catalogs, definitions=definitions,
            validator=validator.read_text(),
            memory_tools=(Path(__file__).with_name("tools") / "memory.py").read_text(),
            kpl_catalog=json.loads((self.shared_path / "kpl/catalog.json").read_text()),
            kpl_client=Path(__file__).with_name("kpl_client.py").read_text(),
            kpl_config=self.kpl_config if self.kpl_config is not None else yaml.safe_load(
                (self.shared_path.parents[1] / "config.yaml").read_text())["AgentKPL"],
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
                if not path.name.startswith(".")
            ],
            reference_manifest=json.loads(
                (self.shared_path / "reference_data/manifest.json").read_text()
            ),
            reference_builder=(
                Path(__file__).with_name("tools") / "reference_data.py"
            ).read_text(),
            bot_manual_catalog=json.loads((self.shared_path / "manual/catalog.json").read_text()),
            bot_manual_handbook=(self.shared_path / "manual/handbook.md").read_text(),
            bot_manual_reader=Path(__file__).with_name("bot_manual.py").read_text(),
            use_process_environment=getattr(self, "use_process_environment", False),
        )

    def _connected(self):
        return bool(
            self.process and self.process.returncode is None
            and not self.process.stdin.is_closing()
            and not self.process.stdout.at_eof()
        )

    async def start(self):
        async with self.lock:
            self._closed = False
            if self._bootstrap_args is None:
                self._bootstrap_args = self._bootstrap_arguments()
            if not self._connected():
                await self._connect_locked()
            return self.config

    async def _connect_locked(self):
        await self._stop_worker_locked()
        try:
            await self._spawn_worker()
            self.config = await self._request_locked("bootstrap", **self._bootstrap_args)
        except Exception as exc:
            await self._stop_worker_locked()
            raise BridgeUnavailable("远程数据连接暂不可用，请稍后重试。") from exc
        private_values = [
            value
            for value in self.config.get("private", {}).values()
            if isinstance(value, str) and value
        ]
        self.secrets = list(dict.fromkeys([*self.secrets, *private_values]))

    async def health(self):
        try:
            return await self.call("health")
        except RuntimeError as exc:
            raise BridgeUnavailable("远程数据服务暂不可用，请稍后重试。") from exc

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
            if self._closed or self._bootstrap_args is None:
                raise BridgeUnavailable("远程数据连接尚未启动或已关闭。")
            if not self._connected():
                # Restore before sending a new request, never replay an operation
                # whose remote execution may already have completed.
                await self._connect_locked()
            return await self._request_locked(op, **args)

    async def _request_locked(self, op, **args):
        def encode(value):
            return sorted(value) if isinstance(value, (set, frozenset)) else str(value)

        request = (json.dumps({"op": op, **args}, ensure_ascii=False, default=encode) + "\n").encode()
        try:
            self.process.stdin.write(request)
            await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(), self.response_timeout)
            if not line:
                raise EOFError("worker closed stdout")
            payload = json.loads(line)
            if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
                raise ValueError("invalid worker response")
        except (OSError, EOFError, TimeoutError, ValueError) as exc:
            # Discard the stream: a late reply must never become the next result.
            await self._stop_worker_locked()
            raise BridgeUnavailable(
                "远程连接中断，本次操作结果未确认，未自动重试；请刷新查看记录后再决定是否重试。"
            ) from exc
        if not payload["ok"]:
            raise RuntimeError(self.redact(payload.get("error", "远程操作失败")))
        return payload.get("data")

    async def _stop_worker_locked(self):
        process, self.process = self.process, None
        if process and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

    async def close(self):
        self._closed = True
        async with self.lock:
            await self._stop_worker_locked()


class ProcessBridge(RemoteBridge):
    """The same worker protocol on the QQ host, without an SSH connection."""

    use_process_environment = True

    def __init__(self, root, python, shared_path):
        super().__init__("local", root, python, shared_path)

    async def _spawn_worker(self):
        self.process = await asyncio.create_subprocess_exec(
            self.python, "-u", str(Path(__file__).with_name("remote_worker.py")),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024,
        )


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

"""Debug logs survive replay/restarts without disrupting chat delivery."""

import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from agent_console.local_logs import LocalEventLog
from agent_console.remote import RemoteBridge, RemoteState
from agent_console.server import EventBroker, create_app


def event(identifier, kind="output.message", *, run="run-1", session="session-1", data=None, transient=False):
    return {
        "id": identifier, "session_id": session, "run_id": run,
        "kind": kind, "time": "2026-10-13T15:00:00+08:00",
        "data": data if data is not None else {"kind": "final", "text": "测试回复"},
        "transient": transient,
    }


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class LogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bridge = RemoteBridge("unused", "unused", "unused", self.root)
        self.bridge.secrets = ["test-secret-value"]
        self.log = LocalEventLog(self.root, redactor=self.bridge.redact)

    async def test_full_payload_and_stream_survive_with_credentials_redacted(self):
        broker = EventBroker(self.bridge, local_log=self.log)
        question = event("q", "run.start", data={"message": "你好"})
        response = event("model", "model.response", data={
            "request_payload": {"messages": [{"role": "system", "content": "上下文" * 10000}]},
            "response_payload": {"content": "完整回答", "nested": {"api_key": "hidden"}},
            "usage": {"prompt_tokens": 123, "completion_tokens": 45},
            "raw": "test-secret-value appears here",
        })
        partial = event("partial", "model.delta", data={"text": "已收到的片段"}, transient=True)
        original = copy.deepcopy(response)
        for item in (question, partial, response, event("reply"), event("end", "run.end", data={"status": "completed"})):
            await broker.publish(item)
        trace_path = self.root / "session-1/runs/run-1.jsonl"
        trace = rows(trace_path)
        self.assertEqual(len(trace), 5)
        self.assertEqual(trace[2]["data"]["request_payload"]["messages"][0]["content"], "上下文" * 10000)
        self.assertNotIn("test-secret-value", trace_path.read_text())
        self.assertEqual(trace[2]["data"]["response_payload"]["nested"]["api_key"], "[redacted]")
        self.assertEqual(trace[1]["data"]["text"], "已收到的片段")
        self.assertEqual([row["id"] for row in rows(self.root / "session-1/dialogue.jsonl")], ["q", "reply", "end"])
        self.assertEqual(response, original)
        self.assertEqual(trace_path.stat().st_mode & 0o777, 0o600)

    async def test_history_replay_and_restart_are_idempotent(self):
        history = [event("q", "run.start"), event("a"), event("end", "run.end")]
        self.bridge.call = AsyncMock(return_value=history)
        state = RemoteState(self.bridge, local_log=self.log)
        self.assertEqual(await state.load_events("session-1"), history)
        await self.log.record_many(history)
        restarted = LocalEventLog(self.root, redactor=self.bridge.redact)
        await restarted.record_many(history)
        await restarted.record(event("new", run="run-2"))
        self.assertEqual(len(rows(self.root / "session-1/runs/run-1.jsonl")), 3)
        self.assertEqual(len(rows(self.root / "session-1/dialogue.jsonl")), 4)

    async def test_concurrent_background_runs_and_cancelled_partial_are_retained(self):
        items = [event(str(i), "model.delta", run="run-" + str(i % 2), data={"text": str(i)}, transient=True) for i in range(30)]
        await asyncio.gather(*(self.log.record(item) for item in items))
        await self.log.record(event("cancel", "run.end", run="run-0", data={"status": "cancelled"}))
        await self.log.record(event("notice", run="run-1", data={"kind": "notification", "text": "后台通知"}))
        zero, one = rows(self.root / "session-1/runs/run-0.jsonl"), rows(self.root / "session-1/runs/run-1.jsonl")
        self.assertEqual(len(zero), 16)
        self.assertEqual(len(one), 16)
        self.assertTrue(all(row["run_id"] == "run-0" for row in zero))
        self.assertEqual(zero[-1]["data"]["status"], "cancelled")
        self.assertEqual(one[-1]["data"]["text"], "后台通知")

    async def test_write_failure_does_not_block_event_delivery(self):
        blocked = self.root / "not-a-directory"
        blocked.write_text("occupied")
        log = LocalEventLog(blocked)
        broker = EventBroker(self.bridge, local_log=log)
        with self.assertLogs("agent_console.local_logs", level="WARNING"):
            await broker.publish(event("a"))
        self.assertEqual(broker.events["session-1"][0]["data"]["text"], "测试回复")
        self.assertIn("local_log_error", broker.events["session-1"][0])
        self.assertIsNotNone(log.status["last_error"])
        error = log.last_error
        await log.record_many([])
        self.assertEqual(log.last_error, error)

    async def test_partial_tail_is_preserved_and_new_events_remain_readable(self):
        await self.log.record(event("first"))
        path = self.root / "session-1/runs/run-1.jsonl"
        with path.open("ab") as handle:
            handle.write(b'{"id":"torn')
        restarted = LocalEventLog(self.root)
        await restarted.record(event("second"))
        lines = path.read_text().splitlines()
        self.assertEqual(json.loads(lines[0])["id"], "first")
        self.assertEqual(lines[1], '{"id":"torn')
        self.assertEqual(json.loads(lines[2])["id"], "second")

    async def test_invalid_paths_and_disabled_logger_create_no_files(self):
        with self.assertLogs("agent_console.local_logs", level="WARNING"):
            self.assertFalse(await self.log.record(event("escape", session="../escape")))
        disabled = LocalEventLog(self.root / "disabled", enabled=False)
        self.assertTrue(await disabled.record(event("off")))
        self.assertEqual(list(self.root.iterdir()), [])


class IngressLogTests(unittest.TestCase):
    def test_prompt_failure_is_recorded_before_runtime_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app()
            app.state.local_log = LocalEventLog(tmp)
            app.state.current_prompt = AsyncMock(side_effect=RuntimeError("SSH unavailable"))
            client = TestClient(app, raise_server_exceptions=False)
            try:
                client.get("/")
                result = client.post("/api/chat", headers={"X-Local-UI": "1"}, json={"session_id": "s", "message": "我的问题"})
            finally:
                client.close()
            self.assertEqual(result.status_code, 500)
            trace = rows(next((Path(tmp) / "s/runs").glob("*.jsonl")))
            self.assertEqual([row["kind"] for row in trace], ["request.received", "request.failed"])
            self.assertEqual(trace[0]["data"]["message"], "我的问题")
            self.assertIn("RuntimeError", trace[1]["data"]["traceback"])
            self.assertEqual(rows(Path(tmp) / "s/dialogue.jsonl")[0]["data"]["error"], "SSH unavailable")


if __name__ == "__main__":
    unittest.main()

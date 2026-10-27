"""Same-group task permissions and receipt-based attribution stay channel-bound."""

from contextlib import ExitStack
from dataclasses import asdict
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agent_console import remote_worker as worker
from agent_console.capabilities import Capabilities
from agent_console.task_timing import normalized_task_action, next_task_time
from agent_console.tools.application import ListTasksArgs
from agent_runtime import Principal, RunRequest
from agent_runtime.models import ToolContext
from local_debugger import import_hok_module
from qq_agent.output import QQOutput
from qq_agent.service import qq_principal
from tests.test_qq_agent_transport import Store


FUNC = import_hok_module("zfunc")


def principal(user="101", group="200"):
    result = asdict(qq_principal(user, group, "创建者" + user, admin_id="999",
        references={"context": {"catalogs": {"players": []}}}, admin_private_default_group_id="200"))
    result["scopes"] = sorted(result["scopes"])
    return result


class TaskStore(Store):
    def __init__(self):
        super().__init__()
        self.ttls = {}

    def scan_iter(self, prefix):
        return [key for key in self.values if key.startswith(prefix.rstrip("*"))]

    def set(self, key, value, *, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True


class TaskScopeTests(unittest.TestCase):
    def setUp(self):
        self.store = TaskStore()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(worker.CONTEXT, store=self.store,
            task_timing={"normalized_task_action": normalized_task_action, "next_task_time": next_task_time}))
        self.stack.enter_context(patch.object(worker.time, "time", return_value=100))

    def create(self, user="101", group="200", **overrides):
        identity = principal(user, group)
        session = f"qq_g_{group}_{user}" if group else f"qq_p_{user}"
        return worker.dispatch({"op": "task_create", "session_id": session, "principal": identity,
            "kind": "message", "message": "相同提醒文案", "interval_seconds": 10, "max_runs": 3, **overrides})

    def request(self, op, user="102", group="200", **kwargs):
        return worker.dispatch({"op": op, "session_id": f"qq_g_{group}_{user}" if group else f"qq_p_{user}",
            "principal": principal(user, group), **kwargs})

    def test_all_group_members_see_creators_but_no_other_groups_private_or_web_tasks(self):
        own, other = self.create(), self.create("102")
        other["lease_token"] = "private-lease"
        self.store.set(worker.STATE_PREFIX + "task:" + other["task_id"], json.dumps(other))
        for user, group in [("101", "300"), ("101", None), ("999", None)]:
            self.create(user, group)
        self.create(session_id="web_session")
        for user in ("101", "102", "103", "999"):
            result = self.request("task_list", user=user)
            self.assertEqual({task["task_id"] for task in result["tasks"]}, {own["task_id"], other["task_id"]})
            self.assertEqual({task["creator"]["user_id"] for task in result["tasks"]}, {"101", "102"})
            self.assertTrue(all(task["creator"]["name"].startswith("创建者") for task in result["tasks"]))
            self.assertEqual((result["scope"], result["group_id"]), ("group", "200"))
            self.assertNotIn("principal", json.dumps(result))
            self.assertNotIn("private-lease", json.dumps(result))

    def test_absolute_time_is_persisted_indexed_and_reported_consistently(self):
        task = self.create(run_at="1970-01-01T08:03:00+08:00")
        stored = json.loads(self.store.get(worker.STATE_PREFIX + "task:" + task["task_id"]))
        self.assertEqual(stored["next_run_at"], 180)
        self.assertEqual(self.store.indexes[worker.STATE_PREFIX + "tasks:qq"][task["task_id"]], 180)
        self.assertEqual(task["next_run_at_text"], "1970-01-01T08:03:00+08:00")
        self.assertEqual(self.request("task_list")["tasks"][0]["next_run_at_text"], task["next_run_at_text"])

    def test_invalid_start_time_does_not_write_or_index_task(self):
        for args in ({"run_at": "1970-01-01T08:03:00+08:00", "delay_seconds": 1},
                     {"run_at": "1970-01-01T08:01:40+08:00"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.create(**args)
        self.assertFalse(self.store.values)
        self.assertFalse(self.store.indexes)

    def test_another_member_cancels_same_group_task_without_changing_creator_or_delivery(self):
        task = self.create()
        before = task["principal"]
        result = self.request("task_cancel", task_id=task["task_id"])
        self.assertEqual(result, {"cancelled": True})
        stored = json.loads(self.store.get(worker.STATE_PREFIX + "task:" + task["task_id"]))
        self.assertEqual(stored["status"], "cancelled")
        self.assertEqual(stored["principal"], before)
        self.assertNotIn(task["task_id"], self.store.indexes[worker.STATE_PREFIX + "tasks:qq"])
        self.assertEqual(self.request("task_list")["tasks"][0]["creator"]["user_id"], "101")

    def test_other_groups_and_private_admin_cannot_cancel_group_task(self):
        task = self.create()
        for user, group in [("102", "300"), ("101", None), ("999", None)]:
            with self.subTest(user=user, group=group), self.assertRaises(PermissionError):
                self.request("task_cancel", user, group, task_id=task["task_id"])
        self.assertEqual(self.request("task_list", "999", None)["tasks"], [])

    def test_private_and_web_tasks_stay_in_their_original_session(self):
        task = self.create("101", None)
        other = self.create("102", None)
        web = self.create(session_id="web_session")
        self.assertEqual([row["task_id"] for row in self.request("task_list", "101", None)["tasks"]], [task["task_id"]])
        with self.assertRaises(PermissionError):
            self.request("task_cancel", "101", None, task_id=other["task_id"])
        result = worker.dispatch({"op": "task_list", "session_id": "web_session", "principal": principal()})
        self.assertEqual([row["task_id"] for row in result["tasks"]], [web["task_id"]])
        self.assertEqual(self.request("task_cancel", "101", None, task_id=task["task_id"]), {"cancelled": True})

    def test_destination_or_creator_mismatch_cannot_grant_group_access(self):
        for edit in (lambda task: task["principal"].update(user_id="999"),
                     lambda task: task["principal"]["attributes"]["chat"].update(group_id="300"),
                     lambda task: task["principal"]["attributes"]["delivery"].update(recipient_id="300")):
            task = self.create()
            edit(task)
            self.store.set(worker.STATE_PREFIX + "task:" + task["task_id"], json.dumps(task))
            self.assertEqual(self.request("task_list")["tasks"], [])
            with self.assertRaises(PermissionError):
                self.request("task_cancel", task_id=task["task_id"])

    def test_receipt_lookup_identifies_exact_creator_despite_same_text_and_different_mention(self):
        first, second = self.create(), self.create("102")
        second["principal"]["attributes"]["delivery"]["mention_user_id"] = "101"
        second["status"] = "completed"
        self.store.set(worker.STATE_PREFIX + "task:" + second["task_id"], json.dumps(second))
        with patch.object(FUNC.dmc, "redis_deamon", self.store):
            FUNC.agent_record_task_message(group_id="200", message_id=-42, task_id=first["task_id"])
            FUNC.agent_record_task_message(group_id="200", message_id=43, task_id=second["task_id"])
        result = self.request("task_list", user="103", message_id="43")
        self.assertTrue(result["message_lookup"]["matched"])
        self.assertEqual(result["tasks"][0]["creator"]["user_id"], "102")
        self.assertEqual(result["tasks"][0]["status"], "completed")
        self.assertEqual(self.request("task_list", message_id="-42")["tasks"][0]["task_id"], first["task_id"])
        self.assertEqual(self.store.ttls[worker.STATE_PREFIX + "task_message:200:43"], 2592000)
        self.assertFalse(self.request("task_list", group="300", message_id="43")["message_lookup"]["matched"])
        self.assertFalse(self.request("task_list", message_id="44")["message_lookup"]["matched"])
        with self.assertRaises(PermissionError):
            self.request("task_list", "999", None, message_id="43")

    def test_receipt_write_rejects_missing_receipts_cross_group_and_non_tasks(self):
        task = self.create()
        with patch.object(FUNC.dmc, "redis_deamon", self.store):
            for kwargs in ({"message_id": None}, {"message_id": 0}, {"message_id": True},
                           {"group_id": "300"}, {"task_id": "a" * 32}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    FUNC.agent_record_task_message(**{"group_id": "200", "message_id": 42,
                                                      "task_id": task["task_id"], **kwargs})
        self.assertFalse(any("task_message:" in key for key in self.store.values))


class TaskDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        observer = patch.object(FUNC, "automation_publish_event", return_value=[])
        observer.start()
        self.addCleanup(observer.stop)

    def sender(self):
        with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
            return import_hok_module("utils.message_sender")

    async def test_queue_send_saves_real_receipt_and_never_infers_one_or_replays(self):
        sender = self.sender()
        bot = SimpleNamespace(send_group_msg=AsyncMock(return_value={"message_id": 42}), send_private_msg=AsyncMock())
        payload = {"type": "group", "toid": 200, "content": "提醒", "task_id": "a" * 32}
        with patch.object(FUNC, "agent_record_task_message") as record:
            await sender._send_queued_message(bot, payload)
            record.assert_called_once_with(group_id=200, message_id=42, task_id="a" * 32)
        bot.send_group_msg.return_value = {}
        with patch.object(FUNC, "agent_record_task_message", side_effect=ValueError("no receipt")) as record, patch.object(sender, "log_message") as log:
            await sender._send_queued_message(bot, payload)
            record.assert_called_once_with(group_id=200, message_id=None, task_id="a" * 32)
            log.assert_called_once()
        self.assertEqual(bot.send_group_msg.await_count, 2)
        bot.send_group_msg.side_effect = OSError("send failed")
        with patch.object(FUNC, "agent_record_task_message") as record:
            with self.assertRaises(OSError):
                await sender._send_queued_message(bot, payload)
            record.assert_not_called()

    async def test_task_link_is_separate_from_model_body_and_packet_fields(self):
        sender = self.sender()
        packet = {"text": "提醒", "task_id": "b" * 32}
        destination = {"platform": "qq", "channel": "group", "recipient_id": "200"}
        with patch.object(sender, "_enqueue_payload") as enqueue:
            sender.add_chat_result_msg(packet, destination=destination, task_id="a" * 32)
            self.assertEqual(enqueue.call_args.args[0]["task_id"], "a" * 32)
            sender.add_chat_result_msg(packet, destination=destination)
            self.assertNotIn("task_id", enqueue.call_args.args[0])
            sender.add_chat_result_msg(packet, destination={**destination, "channel": "private"}, task_id="a" * 32)
            self.assertNotIn("task_id", enqueue.call_args.args[0])

        bridge = AsyncMock()
        output = QQOutput(bridge=bridge, local_log=AsyncMock(), sender=AsyncMock(), prepare_reply=AsyncMock(), store_artifact=AsyncMock())
        event = {"id": "event", "run_id": "run", "session_id": "qq_g_200_101", "time": "now",
                 "metadata": {"origin": "background", "task_id": "a" * 32}}
        await output.send(packet, destination, event)
        self.assertEqual(output.sender.call_args.args[0]["task_id"], "a" * 32)
        await output.send(packet, destination, {**event, "metadata": {}})
        self.assertNotIn("task_id", output.sender.call_args.args[0])

    async def test_capability_passes_trusted_identity_without_model_scope_arguments(self):
        bridge = AsyncMock()
        identity = principal()
        ctx = ToolContext(RunRequest("谁设的", "qq_g_200_101", Principal(**identity)), None)
        capability = Capabilities(bridge)
        await capability.list_tasks(ctx, message_id="42")
        bridge.call.assert_awaited_once_with("task_list", session_id="qq_g_200_101", principal=identity, message_id="42")
        bridge.call.reset_mock()
        await capability.cancel_task("a" * 32, ctx)
        self.assertEqual(bridge.call.call_args.kwargs["principal"], identity)
        for kwargs in ({"group_id": "300"}, {"principal": {}}, {"message_id": "not-a-message"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ListTasksArgs(**kwargs)


if __name__ == "__main__":
    unittest.main()

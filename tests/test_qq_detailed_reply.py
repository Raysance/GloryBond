"""QQ final variants support native records with isolated mentions and receipts."""

import asyncio
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from local_debugger import import_hok_module
from agent_console.capabilities import application_prompt
from agent_console.replies import ReplyPolicy, reply_instruction

ZFUNC = import_hok_module("zfunc")
TEXT = import_hok_module("tools.chat_text")
with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module("utils.message_sender")


class DetailedReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.destination = {"platform": "qq", "channel": "group", "recipient_id": "200", "mention_user_id": "100"}
        self.detail = "第一段有数据和依据。\n\n" + "完整内容[CQ:at,qq=all]，" * 200 + "\n\n最后一句。"
        self.packet = {"text": self.detail, "artifacts": [{"path": "/tmp/chat_plot_example.png"}],
            "delivery_variant": "detailed", "_automation_metadata": {"source": "agent", "origin_run_id": "run"}}

    def enqueue(self, packet=None, destination=None, **kwargs):
        with patch.object(SENDER, "_enqueue_payload", return_value=1) as enqueue:
            SENDER.add_chat_result_msg(packet or self.packet, destination=destination or self.destination, **kwargs)
        enqueue.assert_called_once()
        return enqueue.call_args.args[0]

    def test_detail_is_one_forward_with_complete_text_and_native_image(self):
        original = copy.deepcopy(self.packet)
        payload = self.enqueue()
        self.assertEqual((payload["kind"], payload["type"], payload["toid"]), ("group_forward", "group", 200))
        segments = [segment for node in payload["messages"] for segment in node["data"]["content"]]
        text = "".join(segment["data"]["text"] for segment in segments if segment["type"] == "text")
        self.assertEqual(text, self.detail)
        self.assertEqual([part["type"] for part in segments if part["type"] != "text"], ["image"])
        self.assertTrue(all(node["data"]["uin"] == str(SENDER.confs["QQBot"]["bot_qid"]) for node in payload["messages"]))
        self.assertEqual(payload["automation_metadata"], self.packet["_automation_metadata"])
        self.assertNotIn("运行记录", text)
        self.assertEqual(self.packet, original)
        self.assertIn("[CQ:at,qq=100]", payload["reply_notice"])

    def test_chat_adds_same_variant_records_and_legacy_stays_direct(self):
        for variant in (None, "chat"):
            packet = {"text": "详细内容完整如下。" * 500, "variants": {"detailed": "详细版未发送内容"},
                      "artifacts": [{"path": "/tmp/chat_plot_example.png"}]}
            if variant:
                packet["delivery_variant"] = variant
            payload = self.enqueue(packet)
            self.assertNotIn("kind", payload)
            self.assertTrue(payload["content"].startswith("[CQ:at,qq=100]"))
            self.assertIn(packet["text"], payload["content"])
            if variant is None:
                self.assertNotIn("chat_forward_copy", payload)
                continue
            forward = payload["chat_forward_copy"]
            self.assertEqual((forward["kind"], forward["toid"]), ("group_forward", 200))
            self.assertEqual(forward["title"], SENDER.confs["QQAgent"]["reply_forward"]["chat_title"])
            self.assertTrue(forward["chat_forward_mirror"])
            self.assertNotIn("reply_notice", forward)
            segments = [segment for node in forward["messages"] for segment in node["data"]["content"]]
            self.assertEqual("".join(part["data"]["text"] for part in segments if part["type"] == "text"), packet["text"])
            self.assertEqual([part["data"]["file"] for part in segments if part["type"] == "image"],
                             [part.data["file"] for part in SENDER.Message(payload["content"]) if part.type == "image"])

    def test_chat_mirror_has_no_extra_notice_for_private_no_mention_or_all_members(self):
        for destination in ({"platform": "qq", "channel": "private", "recipient_id": "100"},
                            {**self.destination, "mention_user_id": None},
                            {**self.destination, "mention_user_id": "all"}):
            payload = self.enqueue({**self.packet, "delivery_variant": "chat"}, destination=destination)
            forward = payload["chat_forward_copy"]
            self.assertEqual(forward["kind"], destination["channel"] + "_forward")
            self.assertEqual(forward["toid"], int(destination["recipient_id"]))
            self.assertNotIn("reply_notice", forward)
            mentions = [part.data["qq"] for part in SENDER.Message(payload["content"]) if part.type == "at"]
            self.assertEqual(mentions, ["all"] if destination.get("mention_user_id") == "all" else [])

    async def test_chat_copy_follows_confirmed_direct_send_with_two_task_receipts_and_one_sent_event(self):
        payload = self.enqueue({**self.packet, "delivery_variant": "chat"}, task_id="a" * 32)
        bot = SimpleNamespace(send_group_msg=AsyncMock(return_value={"message_id": 41}),
                              send_group_forward_msg=AsyncMock(return_value={"message_id": 42}))
        with patch.object(ZFUNC, "automation_publish_event", return_value=[]) as publish, \
             patch.object(ZFUNC, "agent_record_task_message", return_value=True) as record, \
             patch.object(SENDER, "_enqueue_payload", return_value=1) as enqueue, \
             patch.object(SENDER, "add_msg") as notice:
            receipt = await SENDER._send_queued_message(bot, payload)
            self.assertEqual(receipt, {"message_id": 41})
            enqueue.assert_called_once()
            forward = enqueue.call_args.args[0]
            self.assertEqual(forward["automation_metadata"]["origin_run_id"], "run")
            await SENDER._handle_forward_msg(bot, forward)
        bot.send_group_msg.assert_awaited_once()
        bot.send_group_forward_msg.assert_awaited_once()
        self.assertEqual([call.kwargs["message_id"] for call in record.call_args_list], [41, 42])
        self.assertTrue(all(call.kwargs["task_id"] == "a" * 32 for call in record.call_args_list))
        self.assertEqual([call.args[0]["kind"] for call in publish.call_args_list], ["message.before_send", "message.sent"])
        notice.assert_not_called()

    async def test_chat_copy_is_not_queued_when_direct_receipt_is_unknown_or_send_fails(self):
        for outcome in ({}, {"message_id": True}, {"message_id": "0"}, TimeoutError(), asyncio.CancelledError()):
            bot = SimpleNamespace(send_group_msg=AsyncMock())
            if isinstance(outcome, BaseException):
                bot.send_group_msg.side_effect = outcome
            else:
                bot.send_group_msg.return_value = outcome
            with patch.object(SENDER, "_automation_before_send", new=AsyncMock(side_effect=lambda payload: payload)), \
                 patch.object(SENDER, "_automation_sent", new=AsyncMock()), \
                 patch.object(SENDER, "_enqueue_payload") as enqueue, patch.object(SENDER, "log_message"):
                payload = self.enqueue({**self.packet, "delivery_variant": "chat"})
                if isinstance(outcome, BaseException):
                    with self.assertRaises(type(outcome)):
                        await SENDER._send_queued_message(bot, payload)
                else:
                    await SENDER._send_queued_message(bot, payload)
            enqueue.assert_not_called()
            bot.send_group_msg.assert_awaited_once()

    async def test_chat_copy_queue_failure_preserves_direct_success_without_replay(self):
        payload = self.enqueue({**self.packet, "delivery_variant": "chat"})
        bot = SimpleNamespace(send_group_msg=AsyncMock(return_value={"message_id": 41}))
        with patch.object(SENDER, "_automation_before_send", new=AsyncMock(side_effect=lambda payload: payload)), \
             patch.object(SENDER, "_automation_sent", new=AsyncMock()), \
             patch.object(SENDER, "_enqueue_payload", side_effect=RuntimeError("queue unavailable")) as enqueue, \
             patch.object(SENDER, "log_message") as log:
            self.assertEqual(await SENDER._send_queued_message(bot, payload), {"message_id": 41})
        enqueue.assert_called_once()
        bot.send_group_msg.assert_awaited_once()
        self.assertIn("CHAT_FORWARD_COPY_QUEUE_FAILED", log.call_args.args[0])

    def test_private_and_explicit_no_mention_have_no_group_notice(self):
        for destination in ({"platform": "qq", "channel": "private", "recipient_id": "100"},
                            {**self.destination, "mention_user_id": None}):
            payload = self.enqueue(destination=destination)
            self.assertNotIn("reply_notice", payload)
            self.assertEqual(payload["kind"], destination["channel"] + "_forward")

    def test_all_members_mention_is_kept_in_success_notice(self):
        payload = self.enqueue(destination={**self.destination, "mention_user_id": "all"})
        message = SENDER.Message(payload["reply_notice"])
        self.assertEqual([segment.data["qq"] for segment in message if segment.type == "at"], ["all"])

    def test_invalid_destination_mention_and_task_id_never_enqueue(self):
        for variant in ("detailed", "chat"):
            for destination, kwargs in (({**self.destination, "recipient_id": "bad"}, {}),
                                        ({**self.destination, "mention_user_id": "bad"}, {}),
                                        (self.destination, {"task_id": "bad"})):
                with patch.object(SENDER, "_enqueue_payload") as enqueue, self.assertRaises(ValueError):
                    SENDER.add_chat_result_msg({**self.packet, "delivery_variant": variant}, destination=destination, **kwargs)
                enqueue.assert_not_called()

    async def test_success_records_forward_receipt_and_queues_native_mention_once(self):
        payload = self.enqueue(task_id="a" * 32)
        bot = SimpleNamespace(send_group_forward_msg=AsyncMock(return_value={"message_id": 42}))
        with patch.object(SENDER, "_automation_sent", new=AsyncMock()), \
             patch.object(ZFUNC, "agent_record_task_message", return_value=True) as record, \
             patch.object(SENDER, "add_msg", return_value=1) as notice:
            await SENDER._handle_forward_msg(bot, payload)
        bot.send_group_forward_msg.assert_awaited_once()
        record.assert_called_once_with(group_id=200, message_id=42, task_id="a" * 32)
        notice.assert_called_once()
        message = notice.call_args.args[0]
        self.assertEqual([part.data["qq"] for part in message if part.type == "at"], ["100"])
        self.assertNotIn("第一段", message.extract_plain_text())
        self.assertEqual(notice.call_args.kwargs["task_id"], "a" * 32)
        self.assertEqual(notice.call_args.kwargs["metadata"], self.packet["_automation_metadata"])

    async def test_failed_forward_has_no_task_receipt_or_group_mention_and_is_not_replayed(self):
        for failure in ({}, {"message_id": True}, {"message_id": "bad"}, {"message_id": "0"}, TimeoutError("transport detail")):
            bot = SimpleNamespace(send_group_forward_msg=AsyncMock())
            if isinstance(failure, Exception):
                bot.send_group_forward_msg.side_effect = failure
            else:
                bot.send_group_forward_msg.return_value = failure
            with patch.object(ZFUNC, "agent_record_task_message") as record, \
                 patch.object(SENDER, "add_msg") as notice, patch.object(SENDER, "log_message"):
                await SENDER._handle_forward_msg(bot, self.enqueue(task_id="a" * 32))
            bot.send_group_forward_msg.assert_awaited_once()
            record.assert_not_called()
            self.assertTrue(all(call.kwargs.get("msg_type") == "private" for call in notice.call_args_list))

    async def test_private_uses_private_forward_adapter_and_no_extra_message(self):
        payload = self.enqueue(destination={"platform": "qq", "channel": "private", "recipient_id": "100"})
        bot = SimpleNamespace(send_private_forward_msg=AsyncMock(return_value={"message_id": 50}))
        with patch.object(SENDER, "_automation_sent", new=AsyncMock()), patch.object(SENDER, "add_msg") as notice:
            await SENDER._handle_forward_msg(bot, payload)
        self.assertEqual(bot.send_private_forward_msg.call_args.kwargs["user_id"], 100)
        notice.assert_not_called()

    async def test_mention_queue_failure_keeps_confirmed_forward_and_does_not_resend(self):
        bot = SimpleNamespace(send_group_forward_msg=AsyncMock(return_value={"message_id": 42}))
        with patch.object(SENDER, "_automation_sent", new=AsyncMock()), \
             patch.object(SENDER, "add_msg", side_effect=RuntimeError("queue unavailable")) as notice, \
             patch.object(SENDER, "log_message") as log:
            await SENDER._handle_forward_msg(bot, self.enqueue())
        bot.send_group_forward_msg.assert_awaited_once()
        notice.assert_called_once()
        self.assertIn("CHAT_FORWARD_MENTION_FAILED", log.call_args.args[0])

    def test_split_preserves_all_characters_and_respects_node_budget(self):
        for text in ("短段\n\n" * 40, "长段" * 100, "abc def ghi\n下一行\n\n尾段" * 20):
            nodes = TEXT.split_chat_forward_text(text, 12)
            self.assertEqual("".join(nodes), text)
            self.assertTrue(all(len(node) <= 12 for node in nodes))

    def test_both_generation_stages_share_concrete_fact_style(self):
        for instruction in (application_prompt(), reply_instruction(ReplyPolicy())):
            self.assertIn("回复表达约定", instruction)
            self.assertIn("没有详细的证据", instruction)
            self.assertIn("统计覆盖本群最近20条消息", instruction)
            self.assertIn("不增加确定性", instruction)

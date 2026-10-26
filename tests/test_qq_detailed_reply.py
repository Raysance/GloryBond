"""QQ sends existing detailed records, then existing brief text, in both channels."""

import asyncio
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from local_debugger import import_hok_module
from agent_console.capabilities import application_prompt
from agent_console.replies import ReplyPolicy, reply_instruction

ZFUNC = import_hok_module("zfunc")
TEXT = import_hok_module("tools.chat_text")
with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module("utils.message_sender")


def forward_text(payload):
    return "".join(part["data"]["text"] for node in payload["messages"]
                   for part in node["data"]["content"] if part["type"] == "text")


class DetailedReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.destination = {"platform": "qq", "channel": "group", "recipient_id": "200", "mention_user_id": "100"}
        self.detail = "第一段有数据和依据。\n\n" + "完整内容[CQ:at,qq=all]，" * 200 + "\n\n最后一句。"
        self.brief = "这是简略结论。[CQ:at,qq=all]"
        self.packet = {"text": "通用text字段，不应用于替代已有版本", "artifacts": [{"path": "/tmp/chat_plot_example.png"}],
            "variants": {"detailed": self.detail, "chat": self.brief},
            "_automation_metadata": {"source": "agent", "origin_run_id": "run"}}

    def enqueue(self, packet=None, destination=None, **kwargs):
        with patch.object(SENDER, "_enqueue_payload", return_value=1) as enqueue:
            SENDER.add_chat_result_msg(packet or self.packet, destination=destination or self.destination, **kwargs)
        enqueue.assert_called_once()
        return enqueue.call_args.args[0]

    def test_two_versions_use_existing_fields_without_selection_copying_or_rewriting(self):
        original = copy.deepcopy(self.packet)
        for variant in (None, "chat", "detailed"):
            packet = {**self.packet, **({"delivery_variant": variant} if variant else {})}
            payload = self.enqueue(packet)
            self.assertEqual((payload["kind"], payload["type"], payload["toid"]), ("group_forward", "group", 200))
            self.assertEqual(forward_text(payload), self.detail)
            self.assertEqual(payload["title"], SENDER.confs["QQAgent"]["reply_forward"]["title"])
            direct = payload["reply_direct"]
            self.assertEqual((direct["type"], direct["toid"]), ("group", 200))
            message = SENDER.Message(direct["content"])
            self.assertEqual(message.extract_plain_text().strip(), self.brief)
            self.assertEqual([part.data["qq"] for part in message if part.type == "at"], ["100"])
            images = [part for node in payload["messages"] for part in node["data"]["content"] if part["type"] == "image"]
            self.assertEqual([part["data"]["file"] for part in images], ["/tmp/chat_plot_example.png"])
            self.assertEqual([part.data["file"] for part in message if part.type == "image"], ["/tmp/chat_plot_example.png"])
            self.assertTrue(all(node["data"]["uin"] == str(SENDER.confs["QQBot"]["bot_qid"]) for node in payload["messages"]))
            self.assertEqual(payload["automation_metadata"], self.packet["_automation_metadata"])
            self.assertNotIn("reply_notice", payload)
            self.assertNotIn("chat_forward_mirror", payload)
            self.assertNotIn("运行记录", forward_text(payload))
        self.assertEqual(self.packet, original)

    def test_private_no_mention_and_all_members_keep_destination_and_no_third_notice(self):
        for destination in ({"platform": "qq", "channel": "private", "recipient_id": "100"},
                            {**self.destination, "mention_user_id": None},
                            {**self.destination, "mention_user_id": "all"}):
            payload = self.enqueue(destination=destination)
            self.assertEqual(payload["kind"], destination["channel"] + "_forward")
            self.assertEqual(payload["toid"], int(destination["recipient_id"]))
            direct = payload["reply_direct"]
            self.assertEqual((direct["type"], direct["toid"]), (payload["type"], payload["toid"]))
            self.assertNotIn("reply_notice", payload)
            mentions = [part.data["qq"] for part in SENDER.Message(direct["content"]) if part.type == "at"]
            self.assertEqual(mentions, ["all"] if destination.get("mention_user_id") == "all" else [])

    def test_fixed_and_partial_messages_without_two_versions_stay_direct(self):
        payload = self.enqueue({"text": "详细内容完整如下。" * 100, "artifacts": []})
        self.assertNotIn("kind", payload)
        self.assertNotIn("reply_direct", payload)
        self.assertIn("详细内容完整如下。", payload["content"])

    def test_equal_generated_versions_are_delivered_as_supplied(self):
        payload = self.enqueue({**self.packet, "variants": {"chat": "短问题的回答", "detailed": "短问题的回答"}})
        self.assertEqual(forward_text(payload), "短问题的回答")
        self.assertEqual(SENDER.Message(payload["reply_direct"]["content"]).extract_plain_text().strip(), "短问题的回答")

    def test_invalid_destination_mention_and_task_never_enqueue(self):
        for destination, kwargs in (({**self.destination, "recipient_id": "bad"}, {}),
                                    ({**self.destination, "mention_user_id": "bad"}, {}),
                                    (self.destination, {"task_id": "bad"})):
            with patch.object(SENDER, "_enqueue_payload") as enqueue, self.assertRaises(ValueError):
                SENDER.add_chat_result_msg(self.packet, destination=destination, **kwargs)
            enqueue.assert_not_called()

    async def test_both_channels_send_records_first_brief_second_and_record_real_receipts(self):
        for channel, recipient in (("group", "200"), ("private", "100")):
            with self.subTest(channel=channel):
                destination = {**self.destination, "channel": channel, "recipient_id": recipient}
                payload = SENDER._prepare_automation_payload(self.enqueue(destination=destination, task_id="a" * 32))
                calls = []

                async def send_forward(**kwargs):
                    calls.append(("detailed", kwargs))
                    return {"message_id": 41}

                async def send_brief(**kwargs):
                    calls.append(("brief", kwargs))
                    return {"message_id": 42}

                bot = SimpleNamespace(**{"send_" + channel + "_forward_msg": AsyncMock(side_effect=send_forward),
                                         "send_" + channel + "_msg": AsyncMock(side_effect=send_brief)})
                with patch.object(ZFUNC, "automation_publish_event", return_value=[]) as publish, \
                     patch.object(ZFUNC, "agent_record_task_message", return_value=True) as record, \
                     patch.object(SENDER, "_enqueue_payload", return_value=1) as enqueue, \
                     patch.object(SENDER, "add_msg") as notice:
                    await SENDER._handle_forward_msg(bot, payload)
                    self.assertEqual([kind for kind, args in calls], ["detailed"])
                    enqueue.assert_called_once()
                    direct = enqueue.call_args.args[0]
                    self.assertEqual(direct["automation_metadata"], payload["automation_metadata"])
                    await SENDER._send_queued_message(bot, direct)
                self.assertEqual([kind for kind, args in calls], ["detailed", "brief"])
                self.assertEqual(SENDER.Message(calls[1][1]["message"]).extract_plain_text().strip(), self.brief)
                observed = [call.args[0]["text"] for call in publish.call_args_list if call.args[0]["kind"] == "message.sent"]
                self.assertEqual(len(observed), 2)
                self.assertIn("第一段有数据和依据。", observed[0])
                self.assertIn("最后一句。", observed[0])
                self.assertIn("[CQ:at,qq=all]", observed[0])
                self.assertEqual(observed[1].strip(), self.brief)
                if channel == "group":
                    self.assertEqual([call.kwargs["message_id"] for call in record.call_args_list], [41, 42])
                    self.assertTrue(all(call.kwargs["task_id"] == "a" * 32 for call in record.call_args_list))
                else:
                    record.assert_not_called()
                    self.assertNotIn("task_id", direct)
                notice.assert_not_called()

    async def test_failed_or_unknown_forward_still_schedules_brief_without_replaying_detail(self):
        for failure in ({}, {"message_id": True}, {"message_id": "bad"}, {"message_id": "0"}, TimeoutError("transport detail")):
            payload = self.enqueue(task_id="a" * 32)
            bot = SimpleNamespace(send_group_forward_msg=AsyncMock())
            if isinstance(failure, Exception):
                bot.send_group_forward_msg.side_effect = failure
            else:
                bot.send_group_forward_msg.return_value = failure
            with patch.object(ZFUNC, "agent_record_task_message") as record, \
                 patch.object(SENDER, "_automation_sent", new=AsyncMock()) as observe, \
                 patch.object(SENDER, "_enqueue_payload", return_value=1) as enqueue, \
                 patch.object(SENDER, "add_msg") as notice, patch.object(SENDER, "log_message"):
                await SENDER._handle_forward_msg(bot, payload)
            bot.send_group_forward_msg.assert_awaited_once()
            record.assert_not_called()
            observe.assert_not_awaited()
            enqueue.assert_called_once()
            self.assertNotIn("kind", enqueue.call_args.args[0])
            self.assertEqual(SENDER.Message(enqueue.call_args.args[0]["content"]).extract_plain_text().strip(), self.brief)
            self.assertTrue(all(call.kwargs.get("msg_type") == "private" for call in notice.call_args_list))

    async def test_brief_queue_failure_keeps_detail_success_without_extra_send(self):
        payload = self.enqueue()
        bot = SimpleNamespace(send_group_forward_msg=AsyncMock(return_value={"message_id": 41}))
        with patch.object(SENDER, "_automation_sent", new=AsyncMock()), \
             patch.object(SENDER, "_enqueue_payload", side_effect=RuntimeError("queue unavailable")) as enqueue, \
             patch.object(SENDER, "add_msg") as notice, patch.object(SENDER, "log_message") as log:
            await SENDER._handle_forward_msg(bot, payload)
        enqueue.assert_called_once()
        bot.send_group_forward_msg.assert_awaited_once()
        notice.assert_not_called()
        self.assertIn("CHAT_BRIEF_QUEUE_FAILED", log.call_args.args[0])

    async def test_cancellation_during_forward_propagates_without_queuing_more_messages(self):
        payload = self.enqueue()
        bot = SimpleNamespace(send_group_forward_msg=AsyncMock(side_effect=asyncio.CancelledError()))
        with patch.object(SENDER, "_enqueue_payload") as enqueue, patch.object(SENDER, "add_msg") as notice:
            with self.assertRaises(asyncio.CancelledError):
                await SENDER._handle_forward_msg(bot, payload)
        enqueue.assert_not_called()
        notice.assert_not_called()

    def test_legacy_detailed_packet_remains_supported(self):
        payload = self.enqueue({"text": self.detail, "delivery_variant": "detailed"})
        self.assertEqual(forward_text(payload), self.detail)
        self.assertIn("[CQ:at,qq=100]", payload["reply_notice"])

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

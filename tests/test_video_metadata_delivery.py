import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tools.debugger import import_project_module
from glorybond.apps.qq.messages import VideoWithMetadata

with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    sender = import_project_module("glorybond.apps.qq.message_sender")


class MetadataDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def payload(self, channel="group"):
        result = VideoWithMetadata("标题：[CQ:at,qq=all]\n作者：测试\n发布时间：2026-01-01", "[CQ:video,file=file:///tmp/video.mp4]")
        return sender._message_payload(result, msg_type=channel, to_id=123, metadata={"source": "bili_video", "source_text": "title"})

    def test_both_parts_enter_the_queue_atomically_as_literal_text_and_native_video(self):
        queue = Mock()
        result = VideoWithMetadata("标题：[CQ:at,qq=all]", "[CQ:video,file=file:///tmp/video.mp4]")
        with patch.object(sender.dmc, "MessageQueue", queue):
            sender.add_msg(result, msg_type="group", to_id=123)
        queue.lpush.assert_called_once()
        payload = json.loads(queue.lpush.call_args.args[1])
        self.assertEqual(payload["kind"], "video_with_metadata")
        self.assertEqual([s.type for s in sender.Message(payload["caption"])], ["text"])
        self.assertEqual(sender.Message(payload["caption"]).extract_plain_text(), result.text)
        self.assertEqual(sender.Message(payload["content"])[0].type, "video")

    async def test_group_and_private_send_caption_then_video_and_observe_only_once(self):
        for channel in ("group", "private"):
            send = AsyncMock(side_effect=[{"message_id": 1}, {"message_id": 2}])
            bot = SimpleNamespace(**{"send_" + channel + "_msg": send})
            with patch.object(sender, "_automation_before_send", side_effect=lambda value: value) as before, \
                 patch.object(sender, "_automation_sent", new_callable=AsyncMock) as observe, \
                 patch.object(sender, "_record_task_receipt", new_callable=AsyncMock) as record:
                await sender._send_video_with_metadata(bot, self.payload(channel))
            self.assertEqual([c.kwargs["message"][0].type for c in send.call_args_list], ["text", "video"])
            self.assertNotIn("_timeout", send.call_args_list[0].kwargs)
            self.assertEqual(send.call_args_list[1].kwargs["_timeout"], 180)
            before.assert_awaited_once()
            observe.assert_awaited_once()
            record.assert_awaited_once()

    async def test_uncertain_caption_does_not_send_video_or_replay_caption(self):
        bot = SimpleNamespace(send_group_msg=AsyncMock(return_value={}))
        with self.assertRaisesRegex(RuntimeError, "未确认"):
            await sender._send_video_with_metadata(bot, self.payload())
        bot.send_group_msg.assert_awaited_once()

    async def test_failed_video_does_not_repeat_metadata_or_original_video(self):
        bot = SimpleNamespace(send_group_msg=AsyncMock(side_effect=[{"message_id": 1}, TimeoutError()]))
        with patch.object(sender, "_automation_before_send", side_effect=lambda value: value), \
             patch.object(sender, "_automation_sent", new_callable=AsyncMock), self.assertRaises(TimeoutError):
            await sender._send_video_with_metadata(bot, self.payload())
        self.assertEqual(bot.send_group_msg.await_count, 2)

    async def test_queue_dispatches_the_bundle_before_the_next_message(self):
        queue = Mock()
        queue.rpop.side_effect = [json.dumps(self.payload()), asyncio.CancelledError()]
        with patch.object(sender.dmc, "MessageQueue", queue), \
             patch.object(sender.dmc, "last_msg_send_ts", 0, create=True), \
             patch.object(sender, "MESSAGE_SEND_INTERVAL", 0), \
             patch.object(sender.nonebot, "get_bot", return_value=Mock()), \
             patch.object(sender, "_send_video_with_metadata", new_callable=AsyncMock) as deliver:
            with self.assertRaises(asyncio.CancelledError):
                await sender.message_sender_loop()
        deliver.assert_awaited_once()

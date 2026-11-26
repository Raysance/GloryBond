"""Failed QQ deliveries must not terminate the shared outbound consumer."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tools.debugger import import_project_module
from glorybond.apps.qq import errors

with patch('nonebot.get_driver', return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_project_module('glorybond.apps.qq.message_sender')


class MessageSenderRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_video_only_subscription_retains_title_for_content_rules(self):
        payload = {"type": "group", "toid": 123, "content": "[CQ:video,file=file:///tmp/video.mp4]",
                   "delivery_id_internal": "test", "automation_metadata": {
                       "source": "bili_video", "author_id": "42", "source_text": "赛事回顾"}}
        event = SENDER._automation_event(payload, "message.before_send")
        self.assertEqual(event["text"], "赛事回顾")
        self.assertEqual(event["author_id"], "42")
        self.assertNotIn("赛事回顾", payload["content"])

    async def run_queue(self, entries, bot, logger):
        zfunc = import_project_module('glorybond.features.facade')
        queue = Mock()
        errors._recent.clear()
        queue.rpop.side_effect = [*entries, asyncio.CancelledError()]
        with patch.object(zfunc, 'automation_publish_event', return_value=[]), \
             patch.object(SENDER.dmc, 'MessageQueue', queue), \
             patch.object(SENDER.dmc, 'last_msg_send_ts', 0, create=True), \
             patch.object(SENDER, 'MESSAGE_SEND_INTERVAL', 0), \
             patch.object(SENDER.nonebot, 'get_bot', return_value=bot), \
             patch.object(SENDER, 'log_message', logger):
            with self.assertRaises(asyncio.CancelledError):
                await SENDER.message_sender_loop()
        # Only a diagnostic may be queued; never replay an unconfirmed message.
        for call in queue.lpush.call_args_list:
            self.assertEqual(json.loads(call.args[1])["automation_metadata"]["source"], "diagnostic")
            self.assertNotIn('secret transport body', call.args[1])
        queue.rpush.assert_not_called()

    async def test_timeout_does_not_replay_or_stop_next_group_and_private_deliveries(self):
        bot = SimpleNamespace(
            send_group_msg=AsyncMock(side_effect=[TimeoutError('secret transport body'), {'message_id': 1}]),
            send_private_msg=AsyncMock(return_value={'message_id': 2}))
        payloads = [dict(type=kind, toid=123, content=text) for kind, text in
                    [('group', 'first'), ('group', 'second'), ('private', 'third')]]
        logger = Mock()
        await self.run_queue([json.dumps(row) for row in payloads], bot, logger)
        self.assertEqual(bot.send_group_msg.await_count, 2)
        bot.send_private_msg.assert_awaited_once()
        logger.assert_called_once()
        self.assertIn('TimeoutError', logger.call_args.args[0])
        self.assertNotIn('secret transport body', logger.call_args.args[0])

    async def test_malformed_payload_does_not_block_later_message(self):
        bot = SimpleNamespace(send_private_msg=AsyncMock(return_value={'message_id': 1}))
        await self.run_queue(['invalid json', json.dumps(dict(type='private', toid=123, content='ok'))], bot, Mock())
        bot.send_private_msg.assert_awaited_once()

    async def test_video_upload_has_its_own_timeout_and_preserves_native_segment(self):
        bot = SimpleNamespace(send_group_msg=AsyncMock(return_value={"message_id": 1}))
        payload = dict(type="group", toid=123, content="[CQ:video,file=file:///tmp/video.mp4]")
        await self.run_queue([json.dumps(payload)], bot, Mock())
        arguments = bot.send_group_msg.call_args.kwargs
        self.assertEqual(arguments["_timeout"], 180)
        self.assertEqual(arguments["message"][0].type, "video")

    async def test_cancellation_during_send_propagates_without_error_notice(self):
        bot = SimpleNamespace(send_private_msg=AsyncMock(side_effect=asyncio.CancelledError()))
        logger = Mock()
        await self.run_queue([json.dumps(dict(type='private', toid=123, content='ok'))], bot, logger)
        logger.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Failed QQ deliveries must not terminate the shared outbound consumer."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from local_debugger import import_hok_module

with patch('nonebot.get_driver', return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module('utils.message_sender')


class MessageSenderRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def run_queue(self, entries, bot, logger):
        queue = Mock()
        queue.rpop.side_effect = [*entries, asyncio.CancelledError()]
        with patch.object(SENDER.dmc, 'MessageQueue', queue), \
             patch.object(SENDER.dmc, 'last_msg_send_ts', 0, create=True), \
             patch.object(SENDER, 'MESSAGE_SEND_INTERVAL', 0), \
             patch.object(SENDER.nonebot, 'get_bot', return_value=bot), \
             patch.object(SENDER, 'log_message', logger):
            with self.assertRaises(asyncio.CancelledError):
                await SENDER.message_sender_loop()
        queue.lpush.assert_not_called()
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

    async def test_cancellation_during_send_propagates_without_error_notice(self):
        bot = SimpleNamespace(send_private_msg=AsyncMock(side_effect=asyncio.CancelledError()))
        logger = Mock()
        await self.run_queue([json.dumps(dict(type='private', toid=123, content='ok'))], bot, logger)
        logger.assert_not_called()


if __name__ == '__main__':
    unittest.main()

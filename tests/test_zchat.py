"""The compatibility facade delegates to the same asynchronous QQ gateway."""
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from local_debugger import import_hok_module

CHAT = import_hok_module("zchat")
FUNCS = import_hok_module("zfunc")


class FacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_returns_sent_text_and_preserves_input(self):
        run = AsyncMock(return_value={"text": "实际发送内容", "artifacts": []})
        with patch.object(FUNCS, "agent_chat", run):
            text = await CHAT.chat_process(user_text="你好", user_id="100", nickname="A", group_id="200")
        self.assertEqual(text, "实际发送内容")
        run.assert_awaited_once_with(user_text="你好", user_id="100", nickname="A", group_id="200")

    async def test_result_retains_artifacts_and_trace(self):
        packet = {"text": "答案", "artifacts": [{"path": "a.png"}], "trace": {"engine": "agent_runtime"}}
        with patch.object(FUNCS, "agent_chat", AsyncMock(return_value=packet)):
            self.assertIs(await CHAT.chat_process_async(return_artifacts=True, user_text="图"), packet)

    async def test_service_callbacks_use_real_facade_io_and_message_sender(self):
        files = import_hok_module("zfile")
        with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda function: function)):
            sender = import_hok_module("utils.message_sender")
        received = {}

        class Service:
            def __init__(self, **options):
                received.update(options)

            async def start(self):
                pass

            async def close(self):
                pass

        prepare = Mock(side_effect=lambda packet: packet)
        store = Mock(return_value={"path": "trusted.png"})
        send = Mock(return_value=True)
        with patch.object(FUNCS.dmc, "qq_agent_service", None), \
                patch("qq_agent.QQAgentService", Service), \
                patch.object(FUNCS, "chat_prepare_reply", prepare), \
                patch.object(files, "store_agent_artifact", store), \
                patch.object(sender, "add_chat_result_msg", send):
            await FUNCS.agent_runtime_start()
            packet = {"text": "回复", "artifacts": []}
            self.assertEqual(await received["prepare_reply"](packet), packet)
            self.assertEqual(await received["store_artifact"]("a" * 32, b"pixels"), {"path": "trusted.png"})
            destination = {"platform": "qq", "channel": "group", "recipient_id": "200"}
            await received["sender"](packet, destination)
            prepare.assert_called_once_with(packet)
            store.assert_called_once_with("a" * 32, b"pixels")
            send.assert_called_once_with(packet, destination=destination)
            await FUNCS.agent_runtime_stop()
            self.assertIsNone(FUNCS.dmc.qq_agent_service)

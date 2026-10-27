"""QQ business facade binds the shared service to the existing IO outlets."""
import unittest
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from local_debugger import import_hok_module

FUNCS = import_hok_module("zfunc")


class FacadeTests(unittest.IsolatedAsyncioTestCase):


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
            self.assertIs(received["member_profile_reader"], FUNCS.agent_read_group_member_profile)
            self.assertIs(received["private_message_sender"], FUNCS.agent_send_group_member_private_message)
            self.assertIs(received["chat_ignore_operation"], FUNCS.agent_chat_ignore_operation)
            self.assertEqual(len(received["business_functions"].functions), 17)
            self.assertEqual(received["bot_id"], FUNCS.confs["QQBot"]["bot_qid"])
            packet = {"text": "回复", "artifacts": []}
            self.assertEqual(await received["prepare_reply"](packet), packet)
            self.assertEqual(await received["store_artifact"]("a" * 32, b"pixels"), {"path": "trusted.png"})
            destination = {"platform": "qq", "channel": "group", "recipient_id": "200", "mention_user_id": "101"}
            await received["sender"](packet, destination)
            prepare.assert_called_once_with(packet)
            store.assert_called_once_with("a" * 32, b"pixels")
            send.assert_called_once_with(packet, destination=destination)
            send.reset_mock()
            background = {**packet, "task_id": "a" * 32}
            await received["sender"](background, destination)
            send.assert_called_once_with(background, destination=destination, task_id="a" * 32)
            await FUNCS.agent_runtime_stop()
            self.assertIsNone(FUNCS.dmc.qq_agent_service)

    async def test_registered_business_function_cannot_reenter_chat_or_scheduler(self):
        from agent_console.function_calls import FunctionArgs, FunctionCatalog
        from tests.test_hok_function_calls import context
        for operation in (FUNCS.agent_chat, FUNCS.agent_runtime_start, FUNCS.agent_task_tick, FUNCS.agent_runtime_stop):
            async def recursive(args, ctx):
                return await operation()
            catalog = FunctionCatalog()
            catalog.register(name="query_recursive", description="test", category="test",
                args_model=FunctionArgs, handler=recursive)
            ctx = context()
            catalog.describe("query_recursive", ctx)
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(RuntimeError, "禁止重新进入"):
                await catalog.call("query_recursive", {}, ctx)

    async def test_business_image_snapshot_validates_pixels_and_rejects_path_escape(self):
        from PIL import Image
        files = import_hok_module("zfile")
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            image = Path(directory) / "business.png"
            Image.new("RGB", (24, 16), "red").save(image)
            external = Path(outside) / "private.png"
            Image.new("RGB", (24, 16), "blue").save(external)
            link = Path(directory) / "escape.png"
            link.symlink_to(external)
            with patch.object(files, "temp_path", directory):
                result = files.store_business_agent_image(str(image), "a" * 32)
                self.assertEqual(result["width"], 24)
                self.assertEqual(Path(result["path"]).name, "chat_plot_" + "a" * 32 + ".png")
                for source in (external, link):
                    with self.assertRaises(ValueError):
                        files.store_business_agent_image(str(source), "b" * 32)
                image.write_bytes(b"invalid pixels")
                with self.assertRaises(Exception):
                    files.store_business_agent_image(str(image), "c" * 32)

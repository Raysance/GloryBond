import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tools.debugger import import_project_module


POKE = import_project_module("glorybond.apps.qq.handlers.poke")
ZTIME = import_project_module("glorybond.time")
FUNCS = import_project_module("glorybond.features.facade")
GEN = import_project_module("glorybond.rendering.gen_emoji_image")


class EventStub:
    target_id = 10
    self_id = 10

    def get_user_id(self):
        return "10001"


class PokeEventHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = {
            name: getattr(POKE.dmc, name)
            for name in (
                "repair", "RTMPStatus", "LastBtlMsgStatus",
                "LastBtlMsgTime", "LastBtlMsgCoolDownTime", "EmojiImageProb",
            )
        }
        POKE.dmc.repair = False
        POKE.dmc.RTMPStatus = False
        POKE.dmc.LastBtlMsgStatus = False
        POKE.dmc.EmojiImageProb = 0
        POKE.dmc.LastBtlMsgCoolDownTime = "2000-01-01 00:00:00"
        context = patch.object(FUNCS, "poke_chat_context", return_value=[])
        self.context = context.start()
        self.addCleanup(context.stop)
        service = patch.object(POKE.dmc, "qq_agent_service", None)
        service.start()
        self.addCleanup(service.stop)

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(POKE.dmc, name, value)

    async def test_ignores_poke_targeting_another_user(self):
        event = EventStub()
        event.target_id = 20
        self.assertEqual(await POKE.group_poke_reply(event), {"kind": "none"})

    async def test_repair_mode_returns_blocked_result(self):
        POKE.dmc.repair = True
        self.assertEqual(await POKE.group_poke_reply(EventStub()), {"kind": "blocked"})

    async def test_cooldown_suppresses_reply(self):
        now = datetime.datetime.now()
        POKE.dmc.LastBtlMsgCoolDownTime = ZTIME.time_to_str(
            now + datetime.timedelta(minutes=1)
        )
        self.assertEqual(await POKE.group_poke_reply(EventStub()), {"kind": "none"})

    async def test_successful_emoji_generation_keeps_the_original_group_scope(self):
        POKE.dmc.EmojiImageProb = 1
        event = EventStub()
        event.group_id = 200
        with patch.object(POKE.random, "random", side_effect=[0.5, 0.0]), \
             patch.object(GEN, "generate_user_emoji_image", return_value={"image_path": "/tmp/emoji.png"}) as generate, \
             patch.object(FUNCS, "ai_parser") as text:
            self.assertEqual(await POKE.group_poke_reply(event), {"kind": "image", "image_path": "/tmp/emoji.png"})
        generate.assert_called_once_with(user_qid="10001", group_id=200)
        text.assert_not_called()

    async def test_missing_templates_fall_back_to_text_instead_of_sending_internal_error(self):
        POKE.dmc.EmojiImageProb = 1
        with patch.object(POKE.random, "random", side_effect=[0.5, 0.0]), \
             patch.object(GEN, "generate_user_emoji_image", side_effect=GEN.EmojiTemplatesUnavailable()), \
             patch.object(FUNCS, "ai_parser", return_value="别戳啦。") as text, \
             patch.object(FUNCS, "qid2nick", return_value="示例玩家"), \
             self.assertLogs(POKE.__name__, level="WARNING"):
            self.assertEqual(await POKE.group_poke_reply(EventStub()), {"kind": "text", "text": "别戳啦。"})
        self.assertEqual(text.call_args.args[1], "poke")

    async def test_other_generation_errors_keep_the_existing_diagnostics(self):
        POKE.dmc.EmojiImageProb = 1
        with patch.object(POKE.random, "random", side_effect=[0.5, 0.0]), \
             patch.object(GEN, "generate_user_emoji_image", side_effect=RuntimeError("provider unavailable")), \
             patch.object(FUNCS, "ai_parser") as text:
            result = await POKE.group_poke_reply(EventStub())
        self.assertEqual(result["kind"], "error")
        self.assertEqual(result["text"], "emoji_gen_error: provider unavailable")
        self.assertIn("RuntimeError", result["traceback"])
        text.assert_not_called()

    async def test_twenty_five_percent_image_boundary_uses_one_draw(self):
        POKE.dmc.EmojiImageProb = .25
        for probability, expected in ((.249, "image"), (.25, "text"), (.99, "text")):
            with self.subTest(probability=probability), \
                 patch.object(POKE.random, "random", return_value=probability) as draw, \
                 patch.object(GEN, "generate_user_emoji_image", return_value={"image_path": "/tmp/emoji.png"}), \
                 patch.object(FUNCS, "ai_parser", return_value="你来了。"):
                result = await POKE.group_poke_reply(EventStub())
                self.assertEqual(result["kind"], expected)
                draw.assert_called_once()

    async def test_text_binds_event_time_group_and_current_user_role(self):
        event = EventStub()
        event.group_id, event.time = 200, 1234567890
        self.context.return_value = [{"speaker": "戳人者", "text": "晚饭还没吃。"}]
        role = {"selected": {"role_id": "assistant", "name": "助手"}, "preferences": {"length": "concise"}}
        roles = SimpleNamespace(manage=AsyncMock(return_value=role))
        with patch.object(POKE.dmc, "qq_agent_service", SimpleNamespace(roles=roles)), \
             patch.object(FUNCS, "ai_parser", return_value="饭选好了吗？") as generate:
            result = await POKE.group_poke_reply(event)
        self.assertEqual(result, {"kind": "text", "text": "饭选好了吗？"})
        self.context.assert_called_once_with("10001", 200, as_of=1234567890)
        self.assertEqual(roles.manage.call_args.args[0].user_id, "10001")
        self.assertEqual(generate.call_args.args[0][2:], [self.context.return_value, role])

    async def test_context_failures_still_reply_without_invented_history(self):
        self.context.side_effect = RuntimeError("history offline")
        with patch.object(FUNCS, "ai_parser", return_value="收到，戳一下就上线。") as generate, \
             self.assertLogs(POKE.__name__, level="WARNING"):
            self.assertEqual((await POKE.group_poke_reply(EventStub()))["kind"], "text")
        self.assertEqual(generate.call_args.args[0][2], [])

    async def test_text_provider_failure_uses_diagnostics_instead_of_raw_text(self):
        with patch.object(FUNCS, "ai_parser", side_effect=RuntimeError("provider failed")):
            result = await POKE.group_poke_reply(EventStub())
        self.assertEqual(result["kind"], "error")
        self.assertIsInstance(result["error"], RuntimeError)


if __name__ == "__main__":
    unittest.main()

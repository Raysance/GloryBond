import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from local_debugger import import_hok_module


POKE = import_hok_module("event_handlers.poke")
ZTIME = import_hok_module("ztime")
FUNCS = import_hok_module("zfunc")
GEN = import_hok_module("tools.gen_emoji_image")


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


if __name__ == "__main__":
    unittest.main()

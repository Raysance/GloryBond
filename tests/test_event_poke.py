import datetime
import unittest
from types import SimpleNamespace

from local_debugger import import_hok_module


POKE = import_hok_module("event_handlers.poke")
ZTIME = import_hok_module("ztime")


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


if __name__ == "__main__":
    unittest.main()

import unittest

from local_debugger import import_hok_module


CHAT_HANDLER = import_hok_module("event_handlers.chat")
ZFUNC = import_hok_module("zfunc")


class FakeEvent:
    def __init__(self, text, *, group_id=None, message_id=None):
        self.text = text
        self.message_id = message_id
        if group_id is not None:
            self.group_id = group_id

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return "1001"


class ChatEventTests(unittest.TestCase):
    def setUp(self):
        self.original_nick = ZFUNC.qid2nick
        ZFUNC.qid2nick = lambda user_id: "Alice"

    def tearDown(self):
        ZFUNC.qid2nick = self.original_nick

    def test_group_request_normalizes_markers_and_metadata(self):
        request = CHAT_HANDLER.prepare_chat_request(
            FakeEvent(
                "＃ ab a & nomem",
                group_id=123,
                message_id=456,
            ),
            {"ab": "长词", "a": "短词"},
            default_use_memory=True,
        )

        self.assertEqual(request["user_text"], "长词 短词 &")
        self.assertEqual(request["nickname"], "Alice")
        self.assertEqual(request["group_id"], 123)
        self.assertEqual(request["message_id"], 456)
        self.assertFalse(request["use_memory"])
        self.assertNotIn("network", request)

    def test_private_request_keeps_default_memory(self):
        request = CHAT_HANDLER.prepare_chat_request(
            FakeEvent("# hello"),
            {},
            default_use_memory=True,
        )

        self.assertEqual(request["user_text"], "hello")
        self.assertIsNone(request["group_id"])
        self.assertTrue(request["use_memory"])
        self.assertNotIn("network", request)


if __name__ == "__main__":
    unittest.main()

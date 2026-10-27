import unittest

from local_debugger import import_hok_module


HISTORY_HANDLER = import_hok_module("event_handlers.history_query")
ZFUNC = import_hok_module("zfunc")


class EventStub:
    def __init__(self, text, user_id="10001"):
        self.text = text
        self.user_id = user_id

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return self.user_id


class HistoryQueryEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_error_is_forwarded(self):
        original_nick = ZFUNC.qid2nick
        original_query = ZFUNC.history_query_handler
        received = []
        ZFUNC.qid2nick = lambda user_qid: "alice"
        ZFUNC.history_query_handler = lambda text: received.append(text) or "查询失败"
        try:
            result = await HISTORY_HANDLER.history_query_reply(EventStub("查我的战绩"))
        finally:
            ZFUNC.qid2nick = original_nick
            ZFUNC.history_query_handler = original_query

        self.assertEqual(received, ["查alice的战绩"])
        self.assertEqual(result, {"kind": "text", "text": "查询失败"})

    async def test_single_match_dispatches_detail_workflow(self):
        originals = {
            "nick": ZFUNC.qid2nick,
            "query": ZFUNC.history_query_handler,
            "single": ZFUNC.history_query_single_match,
        }
        detail = {"GameSeq": "123", "Params": {"gameseq": "123"}}
        ZFUNC.qid2nick = lambda user_qid: "alice"
        ZFUNC.history_query_handler = lambda text: [
            {},
            [[detail, "alice"]],
            "测试条件",
            {},
        ]
        ZFUNC.history_query_single_match = lambda value, realname: (
            "局内详情",
            "/tmp/detail.png",
            "地图",
        )
        try:
            result = await HISTORY_HANDLER.history_query_reply(EventStub("查询"))
        finally:
            ZFUNC.qid2nick = originals["nick"]
            ZFUNC.history_query_handler = originals["query"]
            ZFUNC.history_query_single_match = originals["single"]

        self.assertEqual(result["kind"], "battle")
        self.assertEqual(result["text"], "🔍查询条件：测试条件\n\n局内详情")
        self.assertEqual(result["image_path"], "/tmp/detail.png")

    async def test_multiple_matches_dispatches_web_link_workflow(self):
        originals = {
            "nick": ZFUNC.qid2nick,
            "query": ZFUNC.history_query_handler,
            "multiple": ZFUNC.history_query_multiple_matches_link,
        }
        matches = [[{"GameSeq": "1"}, "alice"], [{"GameSeq": "2"}, "bob"]]
        ZFUNC.qid2nick = lambda user_qid: "alice"
        ZFUNC.history_query_handler = lambda text: [
            {"PlayerName": "alice"},
            matches,
            "两局",
            {},
        ]
        ZFUNC.history_query_multiple_matches_link = lambda target, values: "https://example/link"
        try:
            result = await HISTORY_HANDLER.history_query_reply(EventStub("查询"))
        finally:
            ZFUNC.qid2nick = originals["nick"]
            ZFUNC.history_query_handler = originals["query"]
            ZFUNC.history_query_multiple_matches_link = originals["multiple"]

        self.assertEqual(result["kind"], "text")
        self.assertIn("找到 2 局", result["text"])
        self.assertTrue(result["text"].endswith("https://example/link"))


if __name__ == "__main__":
    unittest.main()

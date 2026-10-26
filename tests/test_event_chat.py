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
        self.assertEqual(request["original_user_text"], "＃ ab a & nomem")
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
        self.assertEqual(request["original_user_text"], "# hello")
        self.assertIsNone(request["group_id"])
        self.assertTrue(request["use_memory"])
        self.assertNotIn("network", request)

    def test_original_native_text_is_kept_before_entry_normalization(self):
        event = FakeEvent("缩写", group_id=200)
        event.self_id = "10"
        event.original_message = [{"type": "at", "data": {"qq": "10"}},
                                  {"type": "text", "data": {"text": " ＃缩写 nomem\n"}}]
        request = CHAT_HANDLER.prepare_chat_request(event, {"缩写": "完整名称"}, True)
        self.assertEqual(request["original_user_text"], " ＃缩写 nomem\n")
        self.assertEqual(request["user_text"], "完整名称")

    def test_native_and_cq_mentions_preserve_current_target_but_exclude_bot_and_quote_author(self):
        for message in (
            [{'type': 'at', 'data': {'qq': '10'}}, {'type': 'at', 'data': {'qq': '20'}},
             {'type': 'at', 'data': {'qq': '20'}}, {'type': 'at', 'data': {'qq': 'all'}}],
            '[CQ:at,qq=10][CQ:at,qq=20][CQ:at,qq=20][CQ:at,qq=all]',
        ):
            event = FakeEvent('提醒他休息', group_id=200)
            event.self_id = '10'
            event.original_message = message
            event.reply = {'message_id': '42', 'message_type': 'group', 'group_id': 200,
                           'sender': {'user_id': '30'}, 'message': '[CQ:at,qq=40]引用里的提及'}
            request = CHAT_HANDLER.prepare_chat_request(event, {}, True)
            self.assertEqual(request['user_text'], '提醒他休息\n[本次消息提及的群成员QQ：20]\n[本次消息包含原生@全体成员]')
            self.assertEqual(request['user_id'], '1001')

    def test_native_and_cq_dynamic_faces_supply_deduplicated_pixels(self):
        sources = [{"type":"image", "data":{"url":"https://gxh.vip.qq.com/raw300.gif", "emoji_id":"abc"}},
            {"type":"mface", "data":{"url":"https://gxh.vip.qq.com/raw300.gif"}},
            {"type":"marketface", "data":{"file":"https://gchat.qpic.cn/face.gif"}}]
        event = FakeEvent("#解释这个动图")
        event.original_message = sources
        request = CHAT_HANDLER.prepare_chat_request(event, {}, True)
        self.assertEqual(request["image_urls"], ["https://gxh.vip.qq.com/raw300.gif", "https://gchat.qpic.cn/face.gif"])
        self.assertEqual(CHAT_HANDLER.image_urls("[CQ:mface,url=https://gxh.vip.qq.com/raw300.gif]"), ["https://gxh.vip.qq.com/raw300.gif"])

    def test_unresolved_faces_are_explicitly_unseen_without_inventing_an_asset_url(self):
        event = FakeEvent("#解释这个表情")
        event.original_message = [{"type":"face", "data":{"id":"14"}}]
        request = CHAT_HANDLER.prepare_chat_request(event, {}, True)
        self.assertEqual(request["image_urls"], [])
        self.assertIn("未读取其像素", request["user_text"])

    def test_quoted_dynamic_faces_are_media_and_do_not_change_current_memory_flag(self):
        event = FakeEvent("#看看这条", group_id=200)
        event.self_id = 10
        event.original_message = [{"type":"reply", "data":{"id":"42"}}]
        event.reply = {"message_id":42, "message_type":"group", "group_id":200,
            "sender":{"user_id":20}, "message":[{"type":"text", "data":{"text":"#nomem"}},
            {"type":"mface", "data":{"url":"https://gxh.vip.qq.com/raw300.gif"}}]}
        request = CHAT_HANDLER.prepare_chat_request(event, {}, True)
        self.assertTrue(request["use_memory"])
        self.assertEqual(request["user_text"], "看看这条")
        self.assertEqual(request["image_urls"], [])
        self.assertEqual(request["quoted_message"]["image_urls"], ["https://gxh.vip.qq.com/raw300.gif"])


if __name__ == "__main__":
    unittest.main()

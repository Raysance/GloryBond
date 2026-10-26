import unittest
from types import SimpleNamespace
from unittest.mock import patch

from local_debugger import import_hok_module


USER_HELPERS = import_hok_module("business.user_helpers")
ZFUNC = import_hok_module("zfunc")


class UserHelperTests(unittest.TestCase):
    def test_greeting_boundaries(self):
        original_time = USER_HELPERS.ztime.time_r
        try:
            cases = {
                5: "早上好",
                12: "中午好",
                14: "下午好",
                18: "晚上好",
                23: "这么晚还不睡吗",
            }
            for hour, expected in cases.items():
                USER_HELPERS.ztime.time_r = lambda hour=hour: SimpleNamespace(
                    hour=hour
                )
                self.assertEqual(ZFUNC.generate_greeting(), expected)
        finally:
            USER_HELPERS.ztime.time_r = original_time

    def test_identity_lookup_accepts_string_and_numeric_qid(self):
        original_qid = USER_HELPERS.qid
        original_namenick = USER_HELPERS.namenick
        USER_HELPERS.qid = {"alice": 123}
        USER_HELPERS.namenick = {"alice": "Alice"}
        try:
            self.assertEqual(ZFUNC.qid2realname("123"), "alice")
            self.assertEqual(ZFUNC.qid2nick(123), "Alice")
            self.assertIsNone(ZFUNC.qid2realname("999"))
        finally:
            USER_HELPERS.qid = original_qid
            USER_HELPERS.namenick = original_namenick

    def test_url_params_keep_single_and_repeated_values(self):
        self.assertEqual(
            ZFUNC.extract_url_params("https://example/path?a=1&b=2&b=3"),
            {"a": "1", "b": ["2", "3"]},
        )

    def test_chat_alias_uses_sameuser_main_qq_and_preserves_explicit_subaccount_qq(self):
        with patch.multiple(USER_HELPERS, qid={"main": 10001},
                namenick={"main": "大号", "alt": "示例玩家34"},
                nameref={"alt": ["example_user_7", "示例玩家34"]}, sameuser={"main": ["main", "alt"]},
                userlist={"alt": 88888}, roleidlist={}):
            for alias in ("示例玩家34", "example_user_7", "alt"):
                self.assertEqual(USER_HELPERS.resolve_chat_qq_ids(players=[alias]), ["10001"])
            with self.assertRaisesRegex(ValueError, "chat_game_id_not_qq"):
                USER_HELPERS.resolve_chat_qq_ids(qq_ids=["88888"])
            USER_HELPERS.qid["alt"] = 20002
            self.assertEqual(USER_HELPERS.resolve_chat_qq_ids(players=["示例玩家34"]), ["20002"])

    def test_chat_alias_rejects_unresolved_or_ambiguous_accounts(self):
        with patch.multiple(USER_HELPERS, qid={"a": 10001, "b": 20002},
                namenick={"a": "重名", "b": "重名", "alt": "示例玩家34"}, nameref={},
                sameuser={"a": ["alt"], "b": ["alt"]}, userlist={}, roleidlist={}):
            for alias in ("重名", "示例玩家34", "未知"):
                with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, "chat_player_identity"):
                    USER_HELPERS.resolve_chat_qq_ids(players=[alias])

    def test_peak_changes_merge_contiguous_segments(self):
        details = [
            {"MapType": -1, "PeakGradeBeforeGame": 1200, "PeakGradeAfterGame": 1210},
            {"MapType": -1, "PeakGradeBeforeGame": 1210, "PeakGradeAfterGame": 1230},
            {"MapType": 1, "PeakGradeBeforeGame": -1, "PeakGradeAfterGame": -1},
        ]

        self.assertEqual(
            ZFUNC.get_peak_alter_list(details, processed=False),
            [[1200, 1230]],
        )

    def test_emoji_selection_uses_file_and_api_boundaries(self):
        original_reader = USER_HELPERS.zfile.read_emoji_reference
        original_ai = USER_HELPERS.zapi.ai_api
        calls = []
        USER_HELPERS.zfile.read_emoji_reference = lambda: {
            "1": {"content": "happy"}
        }
        USER_HELPERS.zapi.ai_api = lambda prompt, temperature: calls.append(
            (prompt, temperature)
        ) or "1"
        try:
            result = ZFUNC.get_emoji("今天很好")
        finally:
            USER_HELPERS.zfile.read_emoji_reference = original_reader
            USER_HELPERS.zapi.ai_api = original_ai

        self.assertEqual(result, 1)
        self.assertIn("今天很好", calls[0][0])
        self.assertEqual(calls[0][1], 2)


if __name__ == "__main__":
    unittest.main()

import unittest

from local_debugger import import_hok_module


EXPORT_HANDLER = import_hok_module("event_handlers.history_export")
ZFUNC = import_hok_module("zfunc")


class HistoryExportEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.originals = {
            "users": EXPORT_HANDLER.userlist,
            "roles": EXPORT_HANDLER.roleidlist,
            "dump": ZFUNC.dump_specific_user,
        }

    def tearDown(self):
        EXPORT_HANDLER.userlist = self.originals["users"]
        EXPORT_HANDLER.roleidlist = self.originals["roles"]
        ZFUNC.dump_specific_user = self.originals["dump"]

    async def test_invalid_command_returns_usage(self):
        self.assertEqual(
            await EXPORT_HANDLER.export_history_replies("#exp alice"),
            ["参数错误，格式：#exp realname date"],
        )

    async def test_all_export_skips_users_without_role_and_flattens_failures(self):
        EXPORT_HANDLER.userlist = {"alice": 1, "bob": 2}
        EXPORT_HANDLER.roleidlist = {"alice": 11}
        calls = []

        def dump(userid, roleid, target_date):
            calls.append((userid, roleid, target_date))
            return {
                "unaccessible_battles": [
                    {"GameSeq": "missing", "Error": "unavailable"}
                ]
            }

        ZFUNC.dump_specific_user = dump

        replies = await EXPORT_HANDLER.export_history_replies(
            "#exp all 2026-09-23"
        )

        self.assertEqual(calls, [(1, 11, "2026-09-23")])
        self.assertEqual(replies[0], "开始导出所有用户数据: 2026-09-23")
        self.assertIn("'GameSeq': 'missing'", replies[1])
        self.assertNotIn("[[", replies[1])

    async def test_specific_export_keeps_start_and_completion_messages(self):
        EXPORT_HANDLER.userlist = {"alice": 1}
        EXPORT_HANDLER.roleidlist = {"alice": 11}
        ZFUNC.dump_specific_user = lambda *args: {"unaccessible_battles": []}

        replies = await EXPORT_HANDLER.export_history_replies(
            "#exp alice 2026-09-23"
        )

        self.assertEqual(
            replies,
            [
                "开始导出特定用户数据: alice 2026-09-23",
                "导出完成",
            ],
        )


if __name__ == "__main__":
    unittest.main()

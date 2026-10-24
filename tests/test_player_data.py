import json
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


PLAYER_DATA = import_hok_module("business.player_data")
ZFUNC = import_hok_module("zfunc")


class PlayerDataTests(unittest.TestCase):
    def setUp(self):
        archive = patch.object(PLAYER_DATA.zfile, "writerl")
        archive.start()
        self.addCleanup(archive.stop)

    def test_failed_dump_does_not_delete_existing_daily_entry(self):
        with (patch.object(ZFUNC, "userlist", {"alice": 1001}),
              patch.object(ZFUNC, "wzry_data", side_effect=RuntimeError("战绩分页失败")),
              patch.object(ZFUNC, "log_message"),
              patch.object(PLAYER_DATA.zfile, "read_history_date") as read,
              patch.object(PLAYER_DATA.zfile, "writerl") as write):
            with self.assertRaisesRegex(RuntimeError, "战绩分页失败"):
                ZFUNC.dump_specific_user(1001, 42, "2026-09-23")
            read.assert_not_called()
            write.assert_not_called()

    def test_invisible_profile_keeps_summary_and_visibility_sync_contract(self):
        originals = {
            "users": ZFUNC.userlist,
            "roles": ZFUNC.roleidlist,
            "official": ZFUNC.wzry_get_official,
            "sync": ZFUNC.sync_battle_visibility_state,
            "export": ZFUNC.export_btldetail,
            "log": ZFUNC.log_message,
        }
        ZFUNC.userlist = {"alice": 1001}
        ZFUNC.roleidlist = {"alice": 42}
        calls = []
        visibility = []

        def official(**kwargs):
            calls.append(kwargs)
            if kwargs["reqtype"] == "btlist":
                return {
                    "invisible": True,
                    "isGaming": False,
                    "gaming": {},
                    "list": [],
                }
            return {
                "roleList": [
                    {"roleId": 42, "roleName": "Alice"},
                ],
                "head": {
                    "mods": [
                        {
                            "modId": 701,
                            "name": "最强王者",
                            "param1": json.dumps({"rankingStar": 12}),
                        }
                    ]
                },
            }

        ZFUNC.wzry_get_official = official
        ZFUNC.sync_battle_visibility_state = (
            lambda realname, visible: visibility.append((realname, visible))
        )
        ZFUNC.export_btldetail = lambda details, roleid: []
        ZFUNC.log_message = lambda *args, **kwargs: None
        try:
            result = ZFUNC.wzry_data(
                "alice",
                target_date="2026-09-23",
                sync_battle_visibility=True,
            )
        finally:
            ZFUNC.userlist = originals["users"]
            ZFUNC.roleidlist = originals["roles"]
            ZFUNC.wzry_get_official = originals["official"]
            ZFUNC.sync_battle_visibility_state = originals["sync"]
            ZFUNC.export_btldetail = originals["export"]
            ZFUNC.log_message = originals["log"]

        self.assertEqual(
            [call["reqtype"] for call in calls],
            ["btlist", "profile"],
        )
        self.assertEqual(visibility, [("alice", False)])
        self.assertEqual(result["id"], 1001)
        self.assertEqual(result["roleid"], 42)
        self.assertEqual(result["nickname"], "Alice")
        self.assertFalse(result["visible"])
        self.assertEqual(result["details"], [])

    def test_dump_specific_user_replaces_existing_daily_entry(self):
        originals = {
            "users": ZFUNC.userlist,
            "wzry": ZFUNC.wzry_data,
            "read": PLAYER_DATA.zfile.read_history_date,
            "write": PLAYER_DATA.zfile.writerl,
            "log": ZFUNC.log_message,
        }
        ZFUNC.userlist = {"alice": 1001}
        ZFUNC.wzry_data = lambda **kwargs: {
            "id": 1001,
            "key": kwargs["realname"],
        }
        PLAYER_DATA.zfile.read_history_date = lambda target_date: [
            {"id": 1001, "key": "stale"},
            {"id": 1002, "key": "bob"},
        ]
        writes = []
        PLAYER_DATA.zfile.writerl = lambda path, payload: writes.append(
            (path, payload)
        )
        ZFUNC.log_message = lambda *args, **kwargs: None
        try:
            result = ZFUNC.dump_specific_user(1001, 42, "2026-09-23")
        finally:
            ZFUNC.userlist = originals["users"]
            ZFUNC.wzry_data = originals["wzry"]
            PLAYER_DATA.zfile.read_history_date = originals["read"]
            PLAYER_DATA.zfile.writerl = originals["write"]
            ZFUNC.log_message = originals["log"]

        self.assertEqual(result["key"], "alice")
        self.assertEqual([item["id"] for item in writes[-1][1]], [1002, 1001])
        self.assertEqual(
            writes[-1][0],
            PLAYER_DATA.zfile.daily_history_path("2026-09-23"),
        )

    def test_battle_detail_export_filters_and_reports_api_failures(self):
        originals = {
            "exists": PLAYER_DATA.zfile.battle_detail_exists,
            "write": PLAYER_DATA.zfile.writerl,
            "official": ZFUNC.check_btl_official_with_matching_with_entertain,
            "api": ZFUNC.wzry_get_official,
        }
        PLAYER_DATA.zfile.battle_detail_exists = lambda gameseq: gameseq == "cached"
        PLAYER_DATA.zfile.writerl = lambda path, payload: self.fail(
            f"failed API response must not be written: {path} {payload}"
        )
        ZFUNC.check_btl_official_with_matching_with_entertain = (
            lambda map_name: map_name != "非正式"
        )
        ZFUNC.wzry_get_official = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("detail unavailable")
        )
        battles = [
            {"GameSeq": "cached", "MapName": "排位赛", "Params": {}},
            {"GameSeq": "casual", "MapName": "非正式", "Params": {}},
            {
                "GameSeq": "missing",
                "MapName": "巅峰赛",
                "Params": {"gameSvrId": 1},
            },
        ]
        try:
            failures = ZFUNC.export_btldetail(battles, roleid=42)
        finally:
            PLAYER_DATA.zfile.battle_detail_exists = originals["exists"]
            PLAYER_DATA.zfile.writerl = originals["write"]
            ZFUNC.check_btl_official_with_matching_with_entertain = originals[
                "official"
            ]
            ZFUNC.wzry_get_official = originals["api"]

        self.assertEqual(
            failures,
            [
                {
                    "roleid": 42,
                    "GameSeq": "missing",
                    "Error": "detail unavailable",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()

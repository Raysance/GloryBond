import json
import unittest

from local_debugger import import_hok_module


PLAYER_DATA = import_hok_module("business.player_data")
ZFUNC = import_hok_module("zfunc")


class PlayerDataTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

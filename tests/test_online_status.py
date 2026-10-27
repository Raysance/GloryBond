import unittest

from local_debugger import import_hok_module


ONLINE_STATUS = import_hok_module("business.online_status")
ZAPI = import_hok_module("zapi")
ZFUNC = import_hok_module("zfunc")


class OnlineStatusTests(unittest.TestCase):
    def test_partial_failures_keep_available_game_and_steam_results(self):
        originals = {
            "userlist": ONLINE_STATUS.userlist,
            "roleidlist": ONLINE_STATUS.roleidlist,
            "steam_userlist": ONLINE_STATUS.steam_userlist,
            "steam": ONLINE_STATUS.confs.get("Steam"),
            "official": ZFUNC.wzry_get_official,
            "hero": ZFUNC.safe_hero_name,
            "steam_api": ZAPI.steam_api_user_status,
        }
        ONLINE_STATUS.userlist = {"alice": 11, "bob": 22}
        ONLINE_STATUS.roleidlist = {"alice": 111, "bob": 222}
        ONLINE_STATUS.steam_userlist = {"steam-user": "steam-1"}
        ONLINE_STATUS.confs["Steam"] = {"api_key": "test-key"}

        def official_api(*, reqtype, userid, roleid):
            if userid == 22:
                raise RuntimeError("profile unavailable")
            if reqtype == "profile":
                return {
                    "roleList": [
                        {
                            "gameOnline": True,
                            "roleName": "游戏昵称",
                            "shortRoleJobName": "王者",
                        }
                    ]
                }
            return {
                "isGaming": True,
                "gaming": {
                    "battleId": "battle-1",
                    "mapName": "排位赛",
                    "heroId": 123,
                    "duration": 8,
                },
            }

        ZFUNC.wzry_get_official = official_api
        ZFUNC.safe_hero_name = lambda hero_id: "赵云"
        ZAPI.steam_api_user_status = lambda api_key, steam_id: {
            "personaname": "Steam昵称",
            "personastate": 1,
            "gameextrainfo": "测试游戏",
        }
        try:
            message, error_report = ZFUNC.camp_online_process()
        finally:
            ONLINE_STATUS.userlist = originals["userlist"]
            ONLINE_STATUS.roleidlist = originals["roleidlist"]
            ONLINE_STATUS.steam_userlist = originals["steam_userlist"]
            ZFUNC.wzry_get_official = originals["official"]
            ZFUNC.safe_hero_name = originals["hero"]
            ZAPI.steam_api_user_status = originals["steam_api"]
            if originals["steam"] is None:
                ONLINE_STATUS.confs.pop("Steam", None)
            else:
                ONLINE_STATUS.confs["Steam"] = originals["steam"]

        self.assertIn("在线 1 人", message)
        self.assertIn("游戏昵称 王者  赵云", message)
        self.assertIn("Steam 在线 1 人", message)
        self.assertIn("Steam昵称  测试游戏", message)
        self.assertIn("在线遍历异常汇总 count=1", error_report)
        self.assertIn("online.profile", error_report)
        self.assertIn("bob", error_report)

    def test_no_online_users_keeps_empty_message_and_shows_friend_scope(self):
        originals = {
            "userlist": ONLINE_STATUS.userlist,
            "roleidlist": ONLINE_STATUS.roleidlist,
            "steam_userlist": ONLINE_STATUS.steam_userlist,
        }
        ONLINE_STATUS.userlist = {}
        ONLINE_STATUS.roleidlist = {}
        ONLINE_STATUS.steam_userlist = {}
        try:
            message, error_report = ZFUNC.online_process()
        finally:
            ONLINE_STATUS.userlist = originals["userlist"]
            ONLINE_STATUS.roleidlist = originals["roleidlist"]
            ONLINE_STATUS.steam_userlist = originals["steam_userlist"]

        self.assertEqual(message, "🐟🐟无人在线\n\n只跟踪王者好友")
        self.assertEqual(error_report, "")


if __name__ == "__main__":
    unittest.main()

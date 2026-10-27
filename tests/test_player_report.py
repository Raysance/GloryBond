import unittest
from unittest.mock import Mock

from local_debugger import import_hok_module


PLAYER_REPORT = import_hok_module("business.player_report")
ZFUNC = import_hok_module("zfunc")


class FakeAnalyses:
    @staticmethod
    def get_expert_hero(userid):
        return {}


class PlayerReportTests(unittest.TestCase):
    def test_latest_battle_has_no_mode_filter_and_does_not_change_original_params(self):
        for mode in ("共鸣之战", "匹配赛", "火焰山大战", "其他娱乐模式", "排位赛"):
            params = {"gameSvrId": "1", "relaySvrId": "2", "gameseq": "latest", "pvptype": "4"}
            details = [{"MapName": "排位赛", "Params": {"gameseq": "old"}},
                       {"MapName": mode, "Params": params}]
            with self.subTest(mode=mode):
                self.assertEqual(PLAYER_REPORT.latest_battle_params(details), params)
                self.assertIsNot(PLAYER_REPORT.latest_battle_params(details), params)

    def test_latest_saved_client_game_needs_no_camp_link_and_never_falls_back_to_old_game(self):
        old = {"MapName": "排位赛", "Params": {"gameseq": "old"}}
        sequence = "-9223372036854775806"
        result = PLAYER_REPORT.latest_battle_params([old, {"MapName": "共鸣之战", "GameSeq": sequence, "Params": {}}])
        self.assertEqual(result, {"gameseq": sequence, "gameSvrId": "", "relaySvrId": "", "pvptype": 0})
        self.assertIsNone(PLAYER_REPORT.latest_battle_params([old, {"MapName": "共鸣之战"}]))
        self.assertIsNone(PLAYER_REPORT.latest_battle_params([]))

    def test_history_suffix_parser_preserves_supported_forms(self):
        self.assertEqual(
            PLAYER_REPORT.extract_single_history_query("alice昨天"),
            [1, [1]],
        )
        self.assertEqual(
            PLAYER_REPORT.extract_single_history_query("alice前天"),
            [1, [2]],
        )
        self.assertEqual(
            PLAYER_REPORT.extract_single_history_query("alice7-2"),
            [2, [7, 2]],
        )
        self.assertEqual(
            PLAYER_REPORT.extract_single_history_query("alice3"),
            [1, [3]],
        )
        self.assertEqual(
            PLAYER_REPORT.extract_single_history_query("alice"),
            [0, []],
        )

    def test_current_report_keeps_return_contract_and_last_battle_state(self):
        originals = {
            "userlist": PLAYER_REPORT.userlist,
            "roleidlist": PLAYER_REPORT.roleidlist,
            "namenick": PLAYER_REPORT.namenick,
            "extract_name": ZFUNC.extract_name,
            "wzry_data": ZFUNC.wzry_data,
            "check": ZFUNC.check_btl_official_with_matching,
            "average": ZFUNC.calculate_official_battle_average,
            "contribution": ZFUNC.calculate_official_battle_contribution_average,
            "analyses": ZFUNC.Analyses,
            "make_hash": ZFUNC.WebArtifacts.__dict__["make_hash"],
            "route_link": ZFUNC.WebArtifacts.__dict__["history_route_link"],
            "read_history": PLAYER_REPORT.read_history_date,
            "daily_writer": PLAYER_REPORT.write_daily_history_export,
            "web_path": PLAYER_REPORT.web_history_json_path,
            "last_requests": PLAYER_REPORT.dmc.LastSingleRequestTime,
            "last_battle_params": getattr(PLAYER_REPORT.dmc, "LastBtlParams", None),
            "last_battle_roleid": getattr(PLAYER_REPORT.dmc, "LastBtlRoleId", None),
            "last_battle_time": getattr(PLAYER_REPORT.dmc, "LastBtlMsgTime", None),
            "last_battle_status": getattr(PLAYER_REPORT.dmc, "LastBtlMsgStatus", None),
        }
        PLAYER_REPORT.userlist = {"alice": 11}
        PLAYER_REPORT.roleidlist = {"alice": 111}
        PLAYER_REPORT.namenick = {"alice": "Alice"}
        PLAYER_REPORT.dmc.LastSingleRequestTime = {}
        detail_params = {
            "gameSvrId": "1",
            "relaySvrId": "2",
            "gameseq": "3",
            "pvptype": "4",
        }
        gameinfo = {
            "key": "alice",
            "roleid": 111,
            "nickname": "Alice",
            "visible": True,
            "details": [
                {
                    "MapName": "排位赛",
                    "Params": detail_params,
                    "GameTime": "12:00",
                    "HeroName": "赵云",
                    "GameGrade": 10,
                }
            ],
            "gaming_info": {},
            "map_cnt": {"排位": [1, 1]},
            "today_num": 2,
            "star_up": 2,
            "peak_up": [],
            "rank_name": "王者",
            "rank_star": 10,
            "source_warnings": ["客户端为本次返回范围，不代表全部历史；娱乐战绩没有完整结束标记。"],
        }
        gameinfo["details"].append(dict(Source="player_client", Params={}, GameSeq="-123", MapName="共鸣之战",
            GameTime="12:10", HeroName="小乔", Result="胜利", KillCnt=3, DeadCnt=4, AssistCnt=5,
            GradeMissing=True, DataMissing=["评分", "段位变化"]))
        ZFUNC.extract_name = lambda text: "alice"
        ZFUNC.wzry_data = lambda *args, **kwargs: dict(gameinfo)
        mode_check = Mock(side_effect=AssertionError("latest game must not be filtered by mode"))
        ZFUNC.check_btl_official_with_matching = mode_check
        ZFUNC.calculate_official_battle_average = lambda details: 10.0
        ZFUNC.calculate_official_battle_contribution_average = (
            lambda details, roleid: 1.25
        )
        ZFUNC.Analyses = FakeAnalyses
        ZFUNC.WebArtifacts.make_hash = staticmethod(lambda seed=None: "fixed")
        ZFUNC.WebArtifacts.history_route_link = staticmethod(
            lambda *args, **kwargs: "https://example/player"
        )
        PLAYER_REPORT.read_history_date = lambda date_text: []
        daily_writes = []
        PLAYER_REPORT.write_daily_history_export = (
            lambda date_text, payload: daily_writes.append((date_text, payload))
        )
        PLAYER_REPORT.web_history_json_path = lambda key: "/tmp/fixed.json"
        try:
            result = ZFUNC.single_process("$alice")
            last_state = (PLAYER_REPORT.dmc.LastBtlParams, PLAYER_REPORT.dmc.LastBtlRoleId,
                          PLAYER_REPORT.dmc.LastBtlMsgStatus)
        finally:
            PLAYER_REPORT.userlist = originals["userlist"]
            PLAYER_REPORT.roleidlist = originals["roleidlist"]
            PLAYER_REPORT.namenick = originals["namenick"]
            ZFUNC.extract_name = originals["extract_name"]
            ZFUNC.wzry_data = originals["wzry_data"]
            ZFUNC.check_btl_official_with_matching = originals["check"]
            ZFUNC.calculate_official_battle_average = originals["average"]
            ZFUNC.calculate_official_battle_contribution_average = originals[
                "contribution"
            ]
            ZFUNC.Analyses = originals["analyses"]
            ZFUNC.WebArtifacts.make_hash = originals["make_hash"]
            ZFUNC.WebArtifacts.history_route_link = originals["route_link"]
            PLAYER_REPORT.read_history_date = originals["read_history"]
            PLAYER_REPORT.write_daily_history_export = originals["daily_writer"]
            PLAYER_REPORT.web_history_json_path = originals["web_path"]
            PLAYER_REPORT.dmc.LastSingleRequestTime = originals["last_requests"]
            PLAYER_REPORT.dmc.LastBtlParams = originals["last_battle_params"]
            PLAYER_REPORT.dmc.LastBtlRoleId = originals["last_battle_roleid"]
            PLAYER_REPORT.dmc.LastBtlMsgTime = originals["last_battle_time"]
            PLAYER_REPORT.dmc.LastBtlMsgStatus = originals["last_battle_status"]

        message, poke_names, battle_exists, last_params, roleid = result
        self.assertIn("🚩Alice", message)
        self.assertIn("场次：2", message)
        self.assertNotIn("客户端补充", message)
        self.assertNotIn("不代表全部历史", message)
        self.assertNotIn("未取得", message)
        self.assertIn("平均评分: 10.0", message)
        self.assertIn("平均贡献: 1.25", message)
        self.assertIn("https://example/player", message)
        self.assertEqual(poke_names, ["Alice"])
        self.assertTrue(battle_exists)
        self.assertEqual(last_params, {"gameseq": "-123", "gameSvrId": "", "relaySvrId": "", "pvptype": 0})
        self.assertEqual(last_state, (last_params, 111, True))
        mode_check.assert_not_called()
        self.assertEqual(roleid, 111)
        self.assertEqual(len(daily_writes), 1)


if __name__ == "__main__":
    unittest.main()

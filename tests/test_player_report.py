from copy import deepcopy
from datetime import datetime
import unittest
from unittest.mock import Mock, patch

from tools.debugger import import_project_module


PLAYER_REPORT = import_project_module("glorybond.features.game.player_report")
ZFUNC = import_project_module("glorybond.features.facade")


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


class HistoricalPlayerReportTests(unittest.TestCase):
    def setUp(self):
        self.archives = {}
        self.exports = []
        self.read = Mock(side_effect=lambda date: deepcopy(self.archives.get(date, [])))
        self.write = Mock(side_effect=lambda path, payload: self.exports.append(deepcopy(payload)))
        patches = [
            patch.object(PLAYER_REPORT, 'userlist', {'alice': 11}),
            patch.object(PLAYER_REPORT, 'roleidlist', {'alice': 111}),
            patch.object(PLAYER_REPORT, 'namenick', {'alice': 'Alice'}),
            patch.object(PLAYER_REPORT.dmc, 'LastSingleRequestTime', {}),
            patch.object(PLAYER_REPORT, 'list_history_dates_descending', side_effect=lambda: sorted(self.archives, reverse=True)),
            patch.object(PLAYER_REPORT, 'read_history_date', self.read),
            patch.object(PLAYER_REPORT, 'writerl', self.write),
            patch.object(PLAYER_REPORT, 'web_history_json_path', return_value='/tmp/history-test.json'),
            patch.object(PLAYER_REPORT, 'read_personal_history', return_value={'btlist': {'list': []}}),
            patch.object(PLAYER_REPORT, 'write_daily_history_export', side_effect=AssertionError('history is read-only')),
            patch.object(ZFUNC, 'extract_name', return_value='alice'),
            patch.object(ZFUNC, 'Analyses', FakeAnalyses),
            patch.object(ZFUNC, 'wzry_data', side_effect=AssertionError('no live collection')),
            patch.object(ZFUNC, 'wzry_get_official', side_effect=AssertionError('no Camp request')),
            patch.object(ZFUNC, 'ai_parser', side_effect=AssertionError('no historical AI call')),
            patch.object(ZFUNC.WebArtifacts, 'make_hash', return_value='fixed'),
            patch.object(ZFUNC.WebArtifacts, 'history_route_link', return_value='https://example/history'),
            patch('glorybond.time.time_r', return_value=datetime(2026, 11, 27, 1, 14, 34)),
        ]
        for item in patches:
            item.start(); self.addCleanup(item.stop)

    @staticmethod
    def snapshot(date, wins=1, total=1, *, player='alice'):
        return {'key': player, 'id': 11 if player == 'alice' else 22, 'roleid': 111,
                'nickname': 'Alice', 'date': date, 'visible': True, 'gaming_info': {},
                'today_num': total, 'map_cnt': {'排位': [wins, total]}, 'up_tourna': 0,
                'up_peak': 0, 'star_up': 0, 'peak_up': [], 'rank_name': '王者', 'rank_star': 10,
                'details': [{'MapName': '排位赛', 'GameGrade': 8, 'Result': '胜利' if i < wins else '失败'}
                            for i in range(total)]}

    def test_midnight_range_keeps_requested_dates_and_available_counts(self):
        self.archives = {'2024-01-01': [self.snapshot('2024-01-01', 99, 99)],
                         '2026-11-24': [self.snapshot('2026-11-24', 1, 2)],
                         '2026-11-25': [self.snapshot('2026-11-25', 2, 3)],
                         '2026-11-26': [self.snapshot('2026-11-26')]}
        for suffix in ('0-3', '3-0'):
            with self.subTest(suffix=suffix):
                PLAYER_REPORT.dmc.LastSingleRequestTime.clear()
                self.read.reset_mock(); self.exports.clear()
                result = PLAYER_REPORT.single_process('#alice的战绩' + suffix)
                self.assertIn('场次：6', result[0])
                self.assertIn('排位WIN：4  / 6', result[0])
                self.assertIn('11-24 - 11-27', result[0])
                self.assertIn('缺少 11-27 的归档，仅统计已收录日期', result[0])
                self.assertEqual([c.args[0] for c in self.read.call_args_list],
                                 ['2026-11-24', '2026-11-25', '2026-11-26'])
                self.assertEqual([row['date'] for row in self.exports[0]],
                                 ['2026-11-24', '2026-11-25', '2026-11-26'])
                self.assertIsNone(result[3])

    def test_missing_start_and_player_snapshot_do_not_pull_older_history(self):
        self.archives = {'2024-01-01': [self.snapshot('2024-01-01', 99, 99)],
                         '2026-11-25': [self.snapshot('2026-11-25', player='other')],
                         '2026-11-26': [self.snapshot('2026-11-26')],
                         '2026-11-27': [self.snapshot('2026-11-27')]}
        result = PLAYER_REPORT.single_process('#alice的战绩0-3')
        self.assertIn('场次：2', result[0])
        self.assertIn('缺少 11-24、11-25 的归档', result[0])
        self.assertNotIn('2024-01-01', [c.args[0] for c in self.read.call_args_list])

    def test_empty_range_returns_no_archive_message_without_merging_or_writing(self):
        for archives in ({}, {'2024-01-01': [self.snapshot('2024-01-01')]},
                         {'2026-11-25': [self.snapshot('2026-11-25', player='other')]}):
            with self.subTest(dates=list(archives)):
                self.archives = archives
                PLAYER_REPORT.dmc.LastSingleRequestTime.clear()
                with patch.object(ZFUNC, 'merge_crossday_gamedata') as merge:
                    result = PLAYER_REPORT.single_process('#alice的战绩0-3')
                merge.assert_not_called(); self.write.assert_not_called()
                self.assertIn('2026-11-24 至 2026-11-27', result[0])
                self.assertIn('未收录', result[0])
                self.assertNotIn('场次：0', result[0])
                self.assertEqual(result[1:], [[], False, None, 111])

    def test_single_missing_date_or_player_does_not_fall_back_to_oldest_record(self):
        for rows in (None, [self.snapshot('2026-11-27', player='other')]):
            self.archives = {'2024-01-01': [self.snapshot('2024-01-01')]}
            if rows is not None:
                self.archives['2026-11-27'] = rows
            PLAYER_REPORT.dmc.LastSingleRequestTime.clear()
            self.read.reset_mock()
            result = PLAYER_REPORT.single_process('#alice的战绩0')
            self.assertIn('2026-11-27', result[0]); self.assertIn('未收录', result[0])
            self.assertEqual(result[1:], [[], False, None, 111])
            self.assertNotIn('2024-01-01', [c.args[0] for c in self.read.call_args_list])
            self.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()

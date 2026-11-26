import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.debugger import import_project_module


RANKINGS = import_project_module("glorybond.features.game.rankings")
ZFILE = import_project_module("glorybond.storage.files")
ZDB = import_project_module("glorybond.storage.database")
ZFUNC = import_project_module("glorybond.features.facade")
ZTIME = import_project_module("glorybond.time")


class InactivityRankTests(unittest.TestCase):
    def test_local_ranking_keeps_unknown_and_hidden_out_and_never_calls_provider(self):
        now = 1800000000
        rows = {
            "recent": {"last_game_epoch": now - 120, "nickname": "Recent"},
            "old": {"last_game_epoch": now - 3 * 86400 - 3600, "nickname": "Old",
                    "snapshot_date": "2026-11-23"},
            "hidden": {"last_game_epoch": now - 1000000, "visible": False},
        }
        with patch.object(ZFILE, "read_latest_player_activity", return_value=rows) as read, \
             patch.object(ZTIME, "current_epoch_seconds", return_value=now), \
             patch.object(RANKINGS, "namenick", {}), \
             patch.object(ZFUNC, "wzry_get_official", side_effect=AssertionError("network")):
            text = ZFUNC.inactivity_rank_process(["recent", "hidden", "old", "missing"])
        read.assert_called_once_with(["recent", "hidden", "old", "missing"], before_epoch=now)
        self.assertIn("1. Old  3天1小时", text)
        self.assertIn("2. Recent  2分钟", text)
        self.assertIn("hidden  最近归档战绩隐藏", text)
        self.assertIn("missing  暂无有效本地对局", text)
        self.assertIn("最新归档日期：2026-11-23", text)
        self.assertIn("采集缺档不代表没有游玩", text)

    def test_archive_fallback_uses_max_timestamp_across_dates_and_all_modes(self):
        data = {
            "2026-11-24": [{"key": "alpha", "visible": True, "nickname": "Alpha",
                            "details": [{"GameTime_Timestamp": 100, "MapName": "排位"}]}],
            "2026-11-23": [{"key": "alpha", "visible": False, "details": [
                {"GameTime_Timestamp": "200", "MapName": "共鸣之战"},
                {"GameTime_Timestamp": 99999}, {"GameTime_Timestamp": True},
                {"GameTime_Timestamp": "invalid"}, {"GameTime_Timestamp": None},
                {"GameTime_Timestamp": -1}, None,
            ]}, {"key": "other", "details": [{"GameTime_Timestamp": 500}]}],
        }
        with patch.object(ZDB, "read_latest_player_activity", side_effect=RuntimeError), \
             patch.object(ZFILE, "list_history_archive_dates_descending", return_value=list(data)), \
             patch.object(ZFILE, "read_history_archive_date", side_effect=data.get), \
             patch.object(ZFILE, "log_message"):
            rows = ZFILE.read_latest_player_activity(["alpha", "missing"], before_epoch=1000)
        self.assertEqual(set(rows), {"alpha"})
        self.assertEqual(rows["alpha"]["last_game_epoch"], 200)
        self.assertTrue(rows["alpha"]["visible"])
        self.assertEqual(rows["alpha"]["snapshot_date"], "2026-11-24")

    def test_database_result_does_not_scan_json(self):
        with patch.object(ZDB, "read_latest_player_activity", return_value={"alpha": {}}), \
             patch.object(ZFILE, "list_history_archive_dates_descending") as archives:
            self.assertEqual(ZFILE.read_latest_player_activity(["alpha"], before_epoch=1000), {"alpha": {}})
        archives.assert_not_called()

    def test_empty_data_and_duration_boundaries(self):
        with patch.object(ZFILE, "read_latest_player_activity", return_value={}):
            self.assertIn("暂无可参与排名", ZFUNC.inactivity_rank_process([]))
        for seconds, text in [(0, "不足1分钟"), (59, "不足1分钟"), (60, "1分钟"),
                              (3660, "1小时1分钟"), (86400, "1天0小时")]:
            self.assertEqual(RANKINGS.inactivity_duration_text(seconds), text)

    def test_command_precedes_general_rank_and_preserves_entry_rule(self):
        tree = ast.parse((Path(__file__).parents[1] / "src/glorybond/apps/qq/events.py").read_text())
        entries = {node.targets[0].id: node.value for node in tree.body
                   if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        entry = entries["_inactivity_rank"]
        self.assertEqual(entry.func.id, "on_fullmatch")
        commands = ast.literal_eval(entry.args[0])
        for text in ("#多久没打了", "＃多久没打了", "#多久没打排名", "#多久没打了排行"):
            self.assertIn(text, commands)
        options = {keyword.arg: keyword.value for keyword in entry.keywords}
        self.assertEqual(options["rule"].id, "judge_to_me")
        self.assertTrue(ast.literal_eval(options["block"]))
        general = {keyword.arg: keyword.value for keyword in entries["_rnk"].keywords}
        self.assertLess(ast.literal_eval(options["priority"]), ast.literal_eval(general["priority"]))


if __name__ == "__main__":
    unittest.main()

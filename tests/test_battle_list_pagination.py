"""Daily reports and exports must include battles beyond the first API page."""

import json
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


PLAYER_DATA = import_hok_module("business.player_data")
ZFUNC = import_hok_module("zfunc")
ZTIME = import_hok_module("ztime")


def battle(sequence, time_text):
    return {
        "gameSeq": sequence,
        "dtEventTime": str(ZTIME.parse_chat_time_bound(time_text)),
        "gametime": time_text,
        "heroId": 112,
        "mapName": "排位赛",
        "roleJobName": "最强王者",
        "stars": 12,
        "killcnt": 5,
        "deadcnt": 2,
        "assistcnt": 6,
        "gameresult": 1 if sequence % 2 else 2,
        "gradeGame": 8,
        "usedTime": 600,
        "detailUrl": f"https://example/battle?gameseq={sequence}",
    }


def page(games, cursor=0, has_more=True, **metadata):
    return dict(list=games, lastTime=cursor, hasMore=has_more,
                invisible=False, isGaming=False, gaming={}, **metadata)


class BattleListPaginationTests(unittest.TestCase):
    def setUp(self):
        self.target = ZTIME.str_to_time("2026-10-23").date()
        self.games = [battle(1000 + index, f"2026-10-23 {hour:02d}:{minute:02d}:00")
                      for index, (hour, minute) in enumerate(
                          (divmod(5 * 60 + offset * 10, 60) for offset in range(65)))]
        self.games.reverse()
        self.older = battle(1, "2026-10-23 03:29:59")

    def collect(self, pages):
        with patch.object(ZFUNC, "wzry_get_official", side_effect=pages) as api:
            result = PLAYER_DATA._battle_list_for_date(1001, 42, self.target)
            return result, api.call_args_list

    def test_overlapping_pages_collect_more_than_sixty_games_and_keep_first_status(self):
        result, calls = self.collect([
            page(self.games[:30], 300, online=True),
            page(self.games[29:59], "200", online=False),
            page(self.games[58:] + [self.older], 100),
        ])
        self.assertEqual(len(result["list"]), 66)
        self.assertEqual([game["gameSeq"] for game in result["list"]],
                         [game["gameSeq"] for game in self.games] + [1])
        self.assertEqual([call.kwargs["last_time"] for call in calls], [0, 300, 200])
        self.assertTrue(all(call.kwargs["userid"] == 1001 and call.kwargs["roleid"] == 42
                            for call in calls))
        self.assertTrue(result["online"])
        self.assertEqual(result["lastTime"], 100)

    def test_short_page_does_not_imply_end_and_exact_day_boundary_is_included(self):
        boundary = battle(2, "2026-10-23 03:30:00")
        result, calls = self.collect([
            page([self.games[0]], 300),
            page([boundary], 200),
            page([self.older], 100),
        ])
        self.assertEqual(len(calls), 3)
        self.assertIn(boundary, result["list"])
        self.assertEqual(ZTIME.time_sul(ZTIME.stamp_to_time(int(boundary["dtEventTime"]))).date(),
                         self.target)

    def test_newer_days_do_not_stop_historical_collection(self):
        newer = battle(9999, "2026-10-24 08:00:00")
        result, calls = self.collect([
            page([newer], 300),
            page(self.games[:30], 200),
            page(self.games[30:] + [self.older], 100),
        ])
        self.assertEqual(len(result["list"]), 67)
        self.assertEqual(len(calls), 3)

    def test_empty_or_explicit_last_page_stops_without_a_cursor(self):
        for ending in ({"list": []}, {"list": self.games[30:], "hasMore": False}):
            with self.subTest(ending=ending):
                result, calls = self.collect([page(self.games[:30], 300), ending])
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(result["list"]), 30 + len(ending["list"]))
                if not ending["list"]:
                    self.assertFalse(result["hasMore"])

    def test_full_terminal_page_stops_but_missing_has_more_keeps_paging(self):
        result, calls = self.collect([page(self.games[:30], has_more=False)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result["list"]), 30)
        first = page(self.games[:30], 300)
        first.pop("hasMore")
        result, calls = self.collect([first, page(self.games[30:], has_more=False)])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["list"]), 65)

    def test_invalid_or_nonadvancing_pagination_never_returns_partial_history(self):
        for invalid in (
            {"list": self.games[30:], "hasMore": True},
            page(self.games[30:], 0),
            page(self.games[30:], 300),
            page(self.games[30:], 400),
            page(self.games[30:], True),
            page(self.games[:30], 200),
            {"invisible": True},
            {"list": None},
            page([{"gameSeq": 1, "dtEventTime": "invalid"}], 200),
            page([{"gameSeq": 1, "dtEventTime": True}], 200),
        ):
            with self.subTest(invalid=invalid):
                with patch.object(ZFUNC, "wzry_get_official", side_effect=[
                    page(self.games[:30], 300), invalid
                ]) as api:
                    with self.assertRaisesRegex(RuntimeError, "战绩分页失败"):
                        PLAYER_DATA._battle_list_for_date(1001, 42, self.target)
                    self.assertEqual(api.call_count, 2)

    def test_initial_private_history_does_not_request_more_pages(self):
        result, calls = self.collect([{"invisible": True, "isGaming": False}])
        self.assertTrue(result["invisible"])
        self.assertEqual(len(calls), 1)

    def run_daily_workflow(self, *, exporting=False, fail_second_page=False):
        profile = {"roleList": [{"roleId": 42, "roleName": "Alice"}],
                   "head": {"mods": [{"modId": 701, "name": "最强王者",
                                       "param1": json.dumps({"rankingStar": 12})}]}}
        pages = [page(self.games[:30], 300), page(self.games[29:59], 200),
                 page(self.games[58:] + [self.older], 100)]
        cursors = []

        def api(*, reqtype, **kwargs):
            if reqtype == "profile":
                return profile
            cursors.append(kwargs["last_time"])
            if fail_second_page and len(cursors) == 2:
                raise RuntimeError("second page unavailable")
            return pages[len(cursors) - 1]

        original_time_sul = ZTIME.time_sul
        now = ZTIME.str_to_time("2026-10-23 23:00:00")
        with (patch.object(ZFUNC, "userlist", {"alice": 1001}),
              patch.object(ZFUNC, "roleidlist", {"alice": 42}),
              patch.object(ZFUNC, "wzry_get_official", side_effect=api),
              patch.object(ZFUNC, "log_message"),
              patch.object(ZFUNC, "export_btldetail", return_value=[]) as details,
              patch.object(ZFUNC, "calculate_official_battle_contribution_average", return_value=1),
              patch.object(PLAYER_DATA.zdb, "latest_rank_star_before", return_value=50),
              patch.object(PLAYER_DATA.zfile, "read_battle_detail", return_value=None),
              patch.object(PLAYER_DATA.zfile, "read_history_date", return_value=[{"id": 1002}]),
              patch.object(PLAYER_DATA.zfile, "writerl") as write,
              patch.object(ZTIME, "time_sul", side_effect=lambda value=None: original_time_sul(value or now))):
            if fail_second_page:
                with self.assertRaisesRegex(RuntimeError, "second page unavailable"):
                    if exporting:
                        ZFUNC.dump_specific_user(1001, 42, "2026-10-23")
                    else:
                        ZFUNC.wzry_data("alice", savepath="report.json")
                write.assert_not_called()
                details.assert_not_called()
                return
            if exporting:
                result = ZFUNC.dump_specific_user(1001, 42, "2026-10-23")
            else:
                result = ZFUNC.wzry_data("alice", savepath="report.json")
            self.assertEqual(cursors, [0, 300, 200])
            self.assertEqual(result["today_num"], 65)
            self.assertEqual(len(result["details"]), 65)
            self.assertEqual([detail["GameSeq"] for detail in result["details"]], list(range(1000, 1065)))
            self.assertEqual(len(details.call_args.args[0]), 65)
            personal_payload = write.call_args_list[0].args[1]
            self.assertEqual(len(personal_payload["btlist"]["list"]), 66)
            if exporting:
                aggregate = write.call_args_list[-1].args[1]
                self.assertEqual([row["id"] for row in aggregate], [1002, 1001])
                self.assertEqual(len(aggregate[-1]["details"]), 65)

    def test_today_query_includes_every_page_in_statistics_and_web_payload(self):
        self.run_daily_workflow()

    def test_dated_export_includes_every_page_in_personal_and_daily_archive(self):
        self.run_daily_workflow(exporting=True)

    def test_later_page_failure_does_not_write_partial_query_or_export(self):
        for exporting in (False, True):
            with self.subTest(exporting=exporting):
                self.run_daily_workflow(exporting=exporting, fail_second_page=True)


if __name__ == "__main__":
    unittest.main()

"""Cohorts are applied before aggregates across battle, equipment and roster reads."""

import datetime
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from sqlglot import parse_one

from agent_console import remote_worker as worker
from agent_console.tools import sql_validation as validation
from agent_console.tools.application import GameScope
from agent_console.tools.observations import numeric_column_totals, project_sql_result


CATALOG = json.loads((Path(__file__).parents[1] / "shared/agent/hok_sql/catalog.json").read_text())


class GameScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE battles (game_seq INTEGER, snapshot_date TEXT, game_time_epoch INTEGER, is_official BOOLEAN)")
        self.db.execute("CREATE TABLE roster (game_seq INTEGER, snapshot_date TEXT, game_time_epoch INTEGER, is_official BOOLEAN)")
        self.db.execute("CREATE TABLE equipment (game_seq INTEGER, snapshot_date TEXT, game_time_epoch INTEGER, is_official BOOLEAN)")
        records = [
            (1, "2024-12-31", "2024-12-31T23:50:00+08:00", True),
            (2, "2024-12-31", "2025-01-01T00:10:00+08:00", True),
            (3, "2024-12-31", "2025-01-01T00:20:00+08:00", False),
            (4, "2025-01-31", "2025-02-01T00:00:00+08:00", True),
        ]
        for game, day, timestamp, official in records:
            row = (game, day, datetime.datetime.fromisoformat(timestamp).timestamp(), official)
            self.db.execute("INSERT INTO battles VALUES (?,?,?,?)", row)
            for _ in range(4):
                self.db.execute("INSERT INTO roster VALUES (?,?,?,?)", row)
            for _ in range(6):
                self.db.execute("INSERT INTO equipment VALUES (?,?,?,?)", row)
        definitions = {"chat_player_battles": "SELECT * FROM battles",
                       "chat_player_battle_roster": "SELECT * FROM roster",
                       "chat_player_equipment": "SELECT * FROM equipment"}
        context = {"definitions": definitions, "catalogs": {"hok_sql": CATALOG}, "validation": validation.__dict__}
        self.patcher = patch.dict(worker.CONTEXT, context, clear=True)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def count(self, relation, scope):
        sql = worker.expand_semantic_views(f"SELECT COUNT(*) FROM hok.{relation}", validation.normalize_game_scope(scope))
        return self.db.execute(parse_one(sql, read="postgres").sql(dialect="sqlite")).fetchone()[0]

    def test_calendar_month_crosses_year_and_business_day_without_losing_after_midnight_games(self):
        scope = {"start_at": "2025-01-01T00:00:00+08:00", "end_at": "2025-02-01T00:00:00+08:00"}
        self.assertEqual(self.count("chat_player_battles", scope), 1)
        self.assertEqual(self.count("chat_player_battle_roster", scope), 4)
        self.assertEqual(self.count("chat_player_equipment", scope), 6)
        self.assertEqual(self.count("chat_player_battles", {**scope, "mode": "all"}), 2)

    def test_equivalent_utc_bounds_and_explicit_business_day_keep_different_meanings(self):
        scope = {"start_at": "2024-12-31T16:00:00+00:00", "end_at": "2025-01-31T16:00:00+00:00"}
        self.assertEqual(self.count("chat_player_battles", scope), 1)
        self.assertEqual(self.count("chat_player_battles", {**scope, "time_basis": "business"}), 1)
        # Calendar selects game 2; the archived January business day selects game 4.
        for basis, expected in [("calendar", 2), ("business", 4)]:
            compiled = worker.expand_semantic_views("SELECT game_seq FROM hok.chat_player_battles",
                validation.normalize_game_scope({**scope, "time_basis": basis}))
            self.assertEqual(self.db.execute(parse_one(compiled, read="postgres").sql(dialect="sqlite")).fetchall(), [(expected,)])

    def test_conflicting_calendar_filter_rejects_entire_batch_before_database_access(self):
        with patch.object(worker, "db_connection") as connect:
            with self.assertRaisesRegex(validation.ChatSQLValidationError, "自然日/月/周"):
                worker.analyze({"domain": "game", "principal": {}, "scope": {}, "queries": [
                    {"sql": "SELECT COUNT(*) FROM hok.chat_player_battles"},
                    {"sql": "SELECT COUNT(*) FROM hok.chat_player_battle_roster WHERE snapshot_date >= DATE '2025-01-01'"}]})
            connect.assert_not_called()

    def test_invalid_bounds_and_scope_fields_fail_before_execution(self):
        for scope in ({"start_at": "2025-01-01"}, {"mode": "ranked"},
                      {"start_at": "2025-02-01T00:00:00+08:00", "end_at": "2025-01-01T00:00:00+08:00"},
                      {"time_basis": "business", "start_at": "2025-01-01T00:01:00+08:00"},
                      {"player_id": "untrusted"}):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                validation.normalize_game_scope(scope)
        with self.assertRaises(ValueError):
            GameScope(start_at="not a timestamp")

    def test_ingress_clock_excludes_records_that_arrived_after_historical_request(self):
        scope = validation.normalize_game_scope({"start_at": "2025-01-01T00:00:00+08:00"})
        scope["as_of"] = "2025-01-01T00:05:00+08:00"
        sql = worker.expand_semantic_views("SELECT COUNT(*) FROM hok.chat_player_battles", scope)
        self.assertEqual(self.db.execute(parse_one(sql, read="postgres").sql(dialect="sqlite")).fetchone()[0], 0)


class ObservationArithmeticTests(unittest.TestCase):
    def test_totals_are_exact_nullable_and_retained_after_context_projection(self):
        observation = {"columns": ["games", "hours", "name", "flag", "missing"], "rows": [
            {"games": 8, "hours": 2.42, "name": "00", "flag": True},
            {"games": 4, "hours": 1.16, "name": "01", "flag": False},
            {"games": 1, "hours": .38, "name": "02"},
            {"games": 4, "hours": .78, "name": "23"}], "truncated": False}
        observation["column_totals"] = numeric_column_totals(observation)
        columns = observation["column_totals"]["columns"]
        self.assertEqual(columns, {"games": {"sum": "17", "non_null_rows": 4},
                                   "hours": {"sum": "4.74", "non_null_rows": 4}})
        projected = project_sql_result({"data": {"observations": [observation]}}, 100)
        self.assertEqual(projected["data"]["observations"][0]["column_totals"], observation["column_totals"])
        self.assertFalse(numeric_column_totals({**observation, "truncated": True})["complete"])


if __name__ == "__main__":
    unittest.main()

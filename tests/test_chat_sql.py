"""Regression tests for SQL validation and the dedicated reader boundary."""

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import json
import re
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


SQL = import_hok_module("tools.chat_sql")
CATALOG = import_hok_module("chat_sql_schema")
DB = import_hok_module("zdb")


class ChatSQLValidationTests(unittest.TestCase):
    def test_catalog_does_not_embed_question_specific_query_templates(self):
        catalog = CATALOG.schema_catalog()
        self.assertNotIn("examples", catalog)
        self.assertNotIn("query_templates", catalog)

    def test_columns_are_verified_against_actual_schema(self):
        schema = (Path(__file__).resolve().parents[1] / "database/schema.sql").read_text()
        for table, info in CATALOG.CHAT_SQL_TABLES.items():
            body = re.search(rf"CREATE TABLE IF NOT EXISTS hok\.{table} \((.*?)\n\);", schema, re.S).group(1)
            actual_columns = set(re.findall(r"^    ([a-z_]+) \w+", body, re.M))
            self.assertEqual(set(info["columns"]), actual_columns - {"source_path"})

    def test_private_group_chat_table_stays_hidden_behind_scoped_sql_view(self):
        root = Path(__file__).resolve().parents[1]
        schema = (root / "database/schema.sql").read_text()
        grants = (root / "database/chat_readonly.sql").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS hok.group_chat_messages", schema)
        self.assertIn("CREATE OR REPLACE VIEW hok.chat_history_messages", schema)
        self.assertNotIn("group_chat_messages", CATALOG.CHAT_SQL_TABLES)
        self.assertIn("chat_history_messages", CATALOG.CHAT_HISTORY_SQL_TABLES)
        self.assertNotRegex(grants, r"GRANT\s+SELECT[\s\S]*?ON\s+hok\.group_chat_messages")
        self.assertRegex(grants, r"ON\s+hok\.chat_history_messages\s+TO\s+hok_chat_reader")
        with self.assertRaisesRegex(SQL.ChatSQLValidationError, "表不在允许的业务表"):
            SQL.validate_readonly_sql("SELECT message_text FROM hok.group_chat_messages")

    def test_group_chat_validator_allows_only_the_scoped_view(self):
        aggregate = SQL.validate_readonly_sql(
            """SELECT user_id, COUNT(*) AS message_count,
                      MIN(sent_at) AS first_message, MAX(sent_at) AS last_message
                 FROM hok.chat_history_messages
                GROUP BY user_id ORDER BY message_count DESC""",
            allowed_tables=CATALOG.CHAT_HISTORY_SQL_TABLES,
            column_usage={},
            schema_tool_name="get_chat_history_database_schema",
        )
        self.assertIn("hok.chat_history_messages", aggregate)
        for sql in (
            "SELECT message_text FROM hok.group_chat_messages",
            "SELECT game_seq FROM hok.battle_records",
            "SELECT payload FROM hok.chat_history_messages",
        ):
            with self.subTest(sql=sql), self.assertRaises(SQL.ChatSQLValidationError):
                SQL.validate_readonly_sql(
                    sql, allowed_tables=CATALOG.CHAT_HISTORY_SQL_TABLES,
                    column_usage={}, schema_tool_name="get_chat_history_database_schema",
                )

    def test_group_chat_catalog_describes_bound_scope_and_database_coverage(self):
        current = CATALOG.chat_history_schema_catalog("current_group")
        admin = CATALOG.chat_history_schema_catalog("all_saved_groups")
        self.assertEqual(current["scope_mode"], "current_group")
        self.assertEqual(admin["scope_mode"], "all_saved_groups")
        self.assertTrue(any("PostgreSQL" in item for item in current["semantics"]))
        with self.assertRaises(ValueError):
            CATALOG.chat_history_schema_catalog("model_selected_group")

    def test_rejects_mutations_nested_writes_locks_and_multiple_statements(self):
        queries = [
            "DELETE FROM hok.battle_records",
            "SELECT 1; SELECT 2",
            "SELECT 1; DROP TABLE hok.battle_records",
            "WITH x AS (DELETE FROM hok.battle_records RETURNING game_seq) SELECT game_seq FROM x",
            "SELECT game_seq INTO TEMP scratch FROM hok.battle_records",
            "SELECT game_seq FROM hok.battle_records FOR UPDATE",
            "SELECT game_seq FROM hok.battle_records FOR SHARE",
            "COPY hok.battle_records TO '/tmp/a'",
            "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT n FROM x",
        ]
        for sql in queries:
            with self.subTest(sql=sql), self.assertRaises(SQL.ChatSQLValidationError):
                SQL.validate_readonly_sql(sql)

    def test_rejects_catalog_file_network_setting_sequence_and_custom_function_access(self):
        queries = [
            "SELECT rolname FROM pg_catalog.pg_roles",
            "SELECT table_name FROM information_schema.tables",
            "SELECT source_path FROM hok.history_players",
            "SELECT source_path FROM hok.json_import_manifest",
            "SELECT token FROM public.secrets",
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT pg_sleep(10)",
            "SELECT set_config('transaction_read_only','off',false)",
            "SELECT nextval('hok.my_seq')",
            "SELECT dblink('host=evil', 'SELECT 1')",
            "SELECT lo_import('/etc/passwd')",
            "SELECT current_setting('my.secret')",
            "SELECT query_to_xml('SELECT * FROM pg_authid',true,false,'')",
            "SELECT public.sum(game_grade) FROM hok.battle_records",
            "SELECT 'hok.battle_records'::regclass",
            "SELECT tableoid FROM hok.battle_records",
            "SELECT game_seq COLLATE public.custom FROM hok.battle_records",
            "SELECT 'a' OPERATOR(public.||) 'b'",
        ]
        for sql in queries:
            with self.subTest(sql=sql), self.assertRaises(SQL.ChatSQLValidationError):
                SQL.validate_readonly_sql(sql)

    def test_cte_name_does_not_authorize_table_in_different_scope(self):
        sql = "SELECT (WITH secrets AS (SELECT 1 AS n) SELECT n FROM secrets) FROM secrets"
        with self.assertRaises(SQL.ChatSQLValidationError):
            SQL.validate_readonly_sql(sql)

    def test_valid_cte_union_and_schema_qualification(self):
        sql = "WITH a AS (SELECT game_seq FROM battle_records) SELECT game_seq FROM a UNION SELECT game_seq FROM hok.battle_details"
        result = SQL.validate_readonly_sql(sql)
        self.assertIn("FROM hok.battle_records", result)
        self.assertIn("FROM a", result)

    def test_window_json_and_time_expressions(self):
        sql = """
            SELECT p.role_id, p.payload->>'isAuth' AS authorized,
                   AVG(p.single_level) OVER(PARTITION BY p.game_seq) AS avg_level,
                   DATE_TRUNC('day', TO_TIMESTAMP(r.game_time_epoch)) AS played_day
            FROM hok.battle_power_players p JOIN hok.battle_records r
              ON p.game_seq=r.game_seq AND p.role_id=r.role_id
            WHERE r.game_time_epoch >= EXTRACT(EPOCH FROM DATE '2026-01-01')
        """
        self.assertIn("DATE_TRUNC", SQL.validate_readonly_sql(sql))

    def test_postgres_unnest_is_not_rejected_as_sqlglot_explode(self):
        sql = "SELECT UNNEST(ARRAY[1, 2, 3]) AS role_id"
        self.assertIn("UNNEST", SQL.validate_readonly_sql(sql))

    def test_unknown_physical_columns_fail_before_database_execution(self):
        for sql in (
            "SELECT d.game_time_epoch FROM hok.battle_details d",
            "SELECT game_time_epoch FROM hok.battle_details",
        ):
            with self.subTest(sql=sql), self.assertRaisesRegex(
                SQL.ChatSQLValidationError, "列不在已披露schema中.*game_time_epoch"
            ):
                SQL.validate_readonly_sql(sql)

    def test_duplicate_result_names_fail_before_database_execution(self):
        with self.assertRaisesRegex(SQL.ChatSQLValidationError, "结果列名重复.*start_time_label"):
            SQL.validate_readonly_sql(
                "SELECT game_seq, start_time_label, start_time_label FROM hok.battle_details"
            )

    def test_lateral_json_array_expansion(self):
        sql = "SELECT x.value->>'equipName' AS equip FROM hok.battle_participants p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'battleRecords'->'finalEquips') x(value)"
        self.assertIn("JSONB_ARRAY_ELEMENTS", SQL.validate_readonly_sql(sql))

    def test_catalog_makes_identity_time_and_period_rules_structured(self):
        catalog = CATALOG.schema_catalog()
        self.assertIn("guidance", catalog)
        self.assertIsNone(catalog["guidance"]["time"]["battle_details"]["exact_epoch"])
        self.assertIn("禁止", catalog["guidance"]["identity"]["rule"])
        self.assertEqual(catalog["column_usage"]["battle_details.start_time_label"]["usage"], "display_only")

    def test_display_only_time_labels_can_be_selected_but_not_analyzed(self):
        self.assertIn(
            "start_time_label",
            SQL.validate_readonly_sql("SELECT start_time_label FROM hok.battle_details"),
        )
        invalid = (
            "SELECT game_seq FROM hok.battle_details WHERE start_time_label >= '2026-09-23'",
            "SELECT start_time_label, COUNT(*) FROM hok.battle_details GROUP BY start_time_label",
            "SELECT start_time_label FROM hok.battle_details ORDER BY start_time_label",
        )
        for sql in invalid:
            with self.subTest(sql=sql), self.assertRaisesRegex(SQL.ChatSQLValidationError, "字段仅供展示"):
                SQL.validate_readonly_sql(sql)

    def test_star_projection_is_blocked_but_count_is_allowed(self):
        self.assertIn("COUNT(*)", SQL.validate_readonly_sql("SELECT COUNT(*) FROM hok.history_players"))
        for sql in ("SELECT * FROM hok.history_players", "SELECT h.* FROM hok.history_players h"):
            with self.assertRaises(SQL.ChatSQLValidationError):
                SQL.validate_readonly_sql(sql)

    def test_named_parameters_cannot_escape_literal(self):
        attack = "'; DELETE FROM hok.battle_records; --"
        sql = SQL.validate_readonly_sql(
            "SELECT player_key FROM hok.battle_records WHERE player_key=:player",
            {"player": attack},
        )
        # Parsing the generated SQL again proves the semicolons remain data.
        self.assertEqual(SQL.validate_readonly_sql(sql), sql)
        self.assertIn("''; DELETE", sql)

    def test_invalid_parameter_shape_or_size_is_rejected(self):
        for params in (["a"], {"missing": "a"}, {"player": []}):
            with self.subTest(params=params), self.assertRaises(SQL.ChatSQLValidationError):
                SQL.validate_readonly_sql("SELECT :player", params)
        with self.assertRaises(SQL.ChatSQLValidationError):
            SQL.validate_readonly_sql("SELECT 1", max_sql_chars=2)


class _Cursor:
    def __init__(self, connection, result_cursor=False):
        self.connection = connection
        self.result_cursor = result_cursor
        self.rows = list(connection.rows) if result_cursor else []
        self.description = [SimpleNamespace(name=name) for name in connection.columns]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, params))
        if self.result_cursor and self.connection.error:
            raise self.connection.error

    def executemany(self, sql, params_seq):
        self.connection.executed.append((sql, list(params_seq)))

    def fetchone(self):
        if not self.result_cursor:
            return self.connection.identity
        return self.rows.pop(0) if self.rows else None


class _Connection:
    def __init__(self, rows=(), columns=("n",), identity=None, error=None):
        self.rows, self.columns, self.error = rows, columns, error
        self.identity = identity or ("hok_chat_reader", False, False, False, False, False, False)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self, name=None):
        return _Cursor(self, bool(name))


class ChatSQLExecutionTests(unittest.TestCase):
    def setUp(self):
        self.limits = {
            "max_rows": 2, "max_columns": 3, "max_bytes": 1000,
            "max_sql_chars": 20000, "statement_timeout_ms": 1000,
            "connect_timeout_seconds": 5,
        }

    @contextmanager
    def reader(self, connection):
        with patch.object(DB, "_chat_sql_limits", return_value=self.limits), patch.object(
            DB, "_chat_readonly_connect", return_value=connection
        ), patch.object(DB, "_connect", side_effect=AssertionError("writer DSN must never be used")):
            yield

    def test_readonly_transaction_and_limits_are_applied_before_query(self):
        connection = _Connection(rows=[(1,), (2,), (3,)])
        with self.reader(connection):
            result = DB.chat_query_readonly("SELECT 1 AS n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], [{"n": 1}, {"n": 2}])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["truncation_reason"], "row_limit")
        statements = [sql for sql, _ in connection.executed]
        self.assertEqual(statements[0], "SET TRANSACTION READ ONLY")
        self.assertIn("statement_timeout", statements[1])
        self.assertTrue(statements[-1].endswith("LIMIT 3"))

    def test_group_chat_upsert_is_idempotent_and_batch_skips_invalid_records(self):
        connection = _Connection()
        records = [
            {"group_id": "200", "message_id": "1", "user_id": "100", "timestamp": 10,
             "time": "1970-01-01 08:00:10", "text": "旧值"},
            {"group_id": "200", "message_id": "1", "user_id": "100", "timestamp": 11,
             "time": "1970-01-01 08:00:11", "text": "新值"},
            {"group_id": "200", "message_id": "", "text": "无效"},
            {"group_id": "200", "message_id": "2", "timestamp": 10 ** 30, "text": "越界"},
        ]
        with patch.object(DB, "_connect", return_value=connection):
            result = DB.upsert_group_chat_messages(records)
        self.assertEqual(result, {"source_records": 4, "upserted_records": 1, "invalid_records": 2})
        sql, values = connection.executed[0]
        self.assertIn("ON CONFLICT (group_id, message_id) DO UPDATE", sql)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0][5:7], (11, "新值"))

    def test_rejects_privileged_or_wrong_database_user(self):
        for identity in [
            ("postgres", False, False, False, False, False, False),
            ("hok_chat_reader", True, False, False, False, False, False),
            ("hok_chat_reader", False, False, False, False, False, True),
        ]:
            connection = _Connection(identity=identity)
            with self.reader(connection):
                result = DB.chat_query_readonly("SELECT 1 AS n")
            self.assertFalse(result["ok"])
            self.assertFalse(any("AS chat_result" in sql for sql, _ in connection.executed))

    def test_json_caps_do_not_cut_a_row_or_create_invalid_json(self):
        self.limits["max_bytes"] = 25
        connection = _Connection(rows=[("short",), ("中文" * 100,)])
        with self.reader(connection):
            result = DB.chat_query_readonly("SELECT 'short' AS n")
        self.assertEqual(result["rows"], [{"n": "short"}])
        self.assertEqual(result["truncation_reason"], "byte_limit")
        self.assertEqual(json.loads(json.dumps(result))["rows"], result["rows"])

    def test_duplicate_and_excess_columns_are_rejected(self):
        for columns in [("n", "n"), ("a", "b", "c", "d")]:
            connection = _Connection(columns=columns)
            with self.reader(connection):
                result = DB.chat_query_readonly("SELECT 1 AS n")
            self.assertFalse(result["ok"])

    def test_values_remain_chart_usable_and_large_ids_are_exact(self):
        connection = _Connection(rows=[(Decimal("8.125"), 99999999999999999, {"nested": Decimal("0.5")})], columns=("grade", "game_seq", "data"))
        with self.reader(connection):
            result = DB.chat_query_readonly("SELECT 1 AS n")
        self.assertEqual(result["rows"], [{"grade": 8.125, "game_seq": "99999999999999999", "data": {"nested": 0.5}}])

    def test_bad_sql_never_opens_connection(self):
        with patch.object(DB, "_chat_sql_limits", return_value=self.limits), patch.object(DB, "_chat_readonly_connect") as connect:
            result = DB.chat_query_readonly("SELECT pg_sleep(9)")
        self.assertFalse(result["ok"])
        connect.assert_not_called()

    def test_timeout_becomes_an_observation(self):
        error = RuntimeError("not public")
        error.sqlstate = "57014"
        connection = _Connection(error=error)
        with self.reader(connection):
            result = DB.chat_query_readonly("SELECT COUNT(*) FROM hok.battle_records")
        self.assertFalse(result["ok"])
        self.assertIn("超时", result["error"])
        self.assertNotIn("not public", result["error"])

    def test_connection_failure_does_not_expose_connection_string(self):
        with patch.object(DB, "_chat_sql_limits", return_value=self.limits), patch.object(
            DB, "_chat_readonly_connect", side_effect=RuntimeError("postgresql://user:secret@host/hok")
        ):
            result = DB.chat_query_readonly("SELECT 1 AS n")
        self.assertFalse(result["ok"])
        self.assertNotIn("secret", result["error"])

    def test_group_chat_query_sets_trusted_scope_before_reading_view(self):
        connection = _Connection(rows=[("100", 9)], columns=("user_id", "message_count"))
        with self.reader(connection):
            result = DB.chat_query_history_readonly(
                "SELECT user_id, COUNT(*) AS message_count "
                "FROM hok.chat_history_messages GROUP BY user_id",
                group_id="200",
            )
        self.assertTrue(result["ok"])
        scope_calls = [(sql, params) for sql, params in connection.executed
                       if "hok.chat_group_scope" in sql]
        self.assertEqual(scope_calls, [
            ("SELECT set_config('hok.chat_group_scope', %s, true)", ("200",)),
        ])
        self.assertIn("hok.chat_history_messages", connection.executed[-1][0])

    def test_group_chat_scope_is_not_model_selectable(self):
        with self.assertRaisesRegex(ValueError, "trusted group_id"):
            DB.chat_query_history_readonly(
                "SELECT COUNT(*) AS n FROM hok.chat_history_messages",
            )
        with self.assertRaisesRegex(ValueError, "cannot include group_id"):
            DB.chat_query_history_readonly(
                "SELECT COUNT(*) AS n FROM hok.chat_history_messages",
                group_id="200", all_groups=True,
            )
        connection = _Connection(rows=[(1,)], columns=("n",))
        with self.reader(connection):
            result = DB.chat_query_history_readonly(
                "SELECT COUNT(*) AS n FROM hok.chat_history_messages",
                all_groups=True,
            )
        self.assertTrue(result["ok"])
        self.assertIn(("SELECT set_config('hok.chat_group_scope', %s, true)", ("*",)),
                      connection.executed)


if __name__ == "__main__":
    unittest.main()

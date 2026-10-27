"""Business capabilities and persistence translation belong to the adapter."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch
from pydantic import BaseModel

from agent_runtime import Principal, ToolRegistry
from agent_runtime.models import RunRequest, ToolContext
from agent_console.capabilities import remote_chat_identity
from agent_console.tasks import task_request
from agent_console.tools.application import register_application_tools
from agent_console.tools.observations import project_sql_result
from agent_console.tools.sql_validation import (
    ChatSQLValidationError,
    validate_readonly_sql,
)


class SQLTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parents[1]
        self.catalog = json.loads(
            (root / "shared/agent/hok_sql/catalog.json").read_text()
        )

    def validate(self, sql, params=None):
        return validate_readonly_sql(
            sql,
            params,
            allowed_tables=self.catalog["tables"],
            column_usage=self.catalog["column_usage"],
            schema_name=self.catalog["schema"],
        )

    def test_raw_storage_write_and_scope_mutation_are_rejected(self):
        for sql in [
            "SELECT game_seq FROM hok.battle_records",
            "DELETE FROM hok.chat_player_battles",
            "SELECT set_config('hok.chat_group_scope','*',true)",
            "SELECT 1; SELECT 2",
        ]:
            with self.subTest(sql=sql), self.assertRaises(ChatSQLValidationError):
                self.validate(sql)

    def test_parameters_are_ast_literals_not_text_interpolation(self):
        result = self.validate(
            "SELECT player_key FROM hok.chat_player_battles WHERE player_key=:player",
            {"player": "x'; DELETE FROM hok.battle_records; --"},
        )
        self.assertIn("x''; DELETE", result)

    def test_batch_validation_failure_opens_no_connection(self):
        from agent_console import remote_worker

        with patch.dict(
            remote_worker.CONTEXT,
            {
                "catalogs": {"hok_sql": self.catalog},
                "validation": {"validate_readonly_sql": validate_readonly_sql},
            },
        ):
            with patch.object(remote_worker, "db_connection") as connect:
                with self.assertRaises(ChatSQLValidationError):
                    remote_worker.analyze(
                        {
                            "domain": "game",
                            "queries": [
                                {
                                    "sql": "SELECT player_key FROM hok.chat_player_battles"
                                },
                                {"sql": "DELETE FROM hok.chat_player_battles"},
                            ],
                            "principal": {},
                        }
                    )
                connect.assert_not_called()

    def test_schema_is_explicit_and_another_schema_can_be_selected(self):
        tables = {"items": {"columns": {"id": "integer"}}}
        with self.assertRaises(ChatSQLValidationError):
            validate_readonly_sql(
                "SELECT id FROM inventory.items", allowed_tables=tables
            )
        result = validate_readonly_sql(
            "SELECT id FROM inventory.items",
            allowed_tables=tables,
            schema_name="inventory",
        )
        self.assertIn("inventory.items", result)
        with self.assertRaises(ChatSQLValidationError):
            validate_readonly_sql(
                "SELECT id FROM hok.items",
                allowed_tables=tables,
                schema_name="inventory",
            )


class AdapterTests(unittest.TestCase):
    def test_legacy_tasks_preserve_trusted_chat_scope_after_translation(self):
        task = {
            "instruction": "test",
            "session_id": "session",
            "principal": {
                "user_id": "local-user",
                "scopes": ["chat.read", "chat.cross_group"],
                "all_groups": True,
                "group_id": None,
            },
            "required_tools": ["search_chat_history"],
        }
        request = task_request(task)
        self.assertTrue(remote_chat_identity(request.principal)["all_groups"])
        self.assertEqual(
            request.required_tools, ("search_chat_history", "discover_tools")
        )
        self.assertNotIn("attributes", task["principal"])

    def test_scope_and_cross_group_permission_are_still_both_required(self):
        from agent_console.remote_worker import trusted_scope

        ordinary = Principal(
            "user",
            frozenset({"chat.read"}),
            {"chat": {"group_id": "123", "all_groups": True}},
        )
        self.assertEqual(trusted_scope(remote_chat_identity(ordinary)), "123")
        admin = Principal(
            "user",
            frozenset({"chat.read", "chat.cross_group"}),
            {"chat": {"all_groups": True}},
        )
        self.assertEqual(trusted_scope(remote_chat_identity(admin)), "*")
        with self.assertRaises(PermissionError):
            trusted_scope(remote_chat_identity(Principal("user")))

    def test_new_categories_are_disclosed_by_application_description(self):
        class EmptyArgs(BaseModel):
            pass

        registry = ToolRegistry()
        register_application_tools(registry, service=object(), catalogs={})
        registry.register(
            name="custom",
            description="custom",
            args_model=EmptyArgs,
            handler=lambda *args: None,
            category="inventory",
        )
        ctx = ToolContext(RunRequest("test", "session", Principal("user")), None)
        ctx.disclosed.update(registry.initial_names(ctx))
        schema = next(
            item
            for item in registry.schemas(ctx)
            if item["function"]["name"] == "discover_tools"
        )
        self.assertIn("inventory", schema["function"]["description"])
        self.assertNotIn("analyze_game_database", ctx.disclosed)

    def test_sql_projection_retains_every_query_status_and_dataset_handle(self):
        value = {
            "ok": False,
            "data": {
                "observations": [
                    {"ok": True, "dataset_id": "d", "rows": list(range(30))},
                    {"ok": False, "error": "failed"},
                ]
            },
        }
        projected = project_sql_result(value, 1000)
        self.assertEqual(projected["data"]["observations"][0]["dataset_id"], "d")
        self.assertEqual(projected["data"]["observations"][1]["error"], "failed")
        self.assertEqual(len(value["data"]["observations"][0]["rows"]), 30)


if __name__ == "__main__":
    unittest.main()

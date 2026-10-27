"""Reference relationships are data, not heuristics attached to SQL answers."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_runtime import Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_console.tools.application import register_application_tools
from agent_runtime.tools.executor import execute
from agent_console.tools.reference_data import ReferenceData, account_id_binding


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "shared/agent/reference_data/manifest.json").read_text())


def values():
    return {
        "namenick": {"p1": "示例玩家74", "p2": "KK", "p3": "KK"},
        "nameref": {"p1": ["甲", "Dog"], "p2": ["乙"]},
        "qid": {"p1": 10001, "p2": 10002, "p3": 10002},
        "userlist": {"p1": 20001},
        "roleidlist": {"p1": 30001},
        "steam_userlist": {"p1": 2000000128},
        "idname": {"游戏名": "p1"},
        "sameuser": {"p2": ["p2", "p3"]},
        "extra_namenick": {"extra": "KK"},
        "extra_useridlist": {"extra": 20002},
        "HeroList": {"112": "鲁班七号"},
        "HeroName_replacements": {"112": "卤蛋"},
        "ranklist": {"最强王者": 50, "荣耀王者": 50},
        "common_expr": {"tsg": "图书馆", "library": "图书馆"},
        "api_key": "must-never-be-included",
    }


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.references = ReferenceData(MANIFEST, values(), source="fixture")

    def test_names_aliases_reverse_aliases_and_ids_share_one_record(self):
        for term in ["甲", "dog", "游戏名", "10001", "20001", "30001"]:
            result = self.references.lookup(catalogs=["players"], terms=[term])
            self.assertEqual(result["matches"][0]["id"], "p1")
            self.assertEqual(result["matches"][0]["name"], "示例玩家74")
        self.assertEqual(result["matches"][0]["ids"]["steam_id"], ["2000000128"])

    def test_namespaces_prevent_using_game_id_as_qq(self):
        result = self.references.lookup(
            catalogs=["players"], terms=["20001"], namespace="qq"
        )
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["unmatched_terms"], ["20001"])
        with self.assertRaises(ValueError):
            self.references.lookup(catalogs=["heroes"], namespace="qq")

    def test_collisions_and_account_relations_are_preserved(self):
        matches = self.references.lookup(
            catalogs=["players"], terms=["10002"], namespace="qq"
        )["matches"]
        self.assertEqual([item["id"] for item in matches], ["p2", "p3"])
        self.assertEqual(matches[0]["relations"]["same_person_accounts"], ["p3"])
        named = self.references.lookup(catalogs=["players"], terms=["KK"])
        self.assertEqual(named["total_matches"], 3)
        ranks = self.references.lookup(
            catalogs=["ranks"], terms=["50"], namespace="rank_score_base"
        )
        self.assertEqual(ranks["total_matches"], 2)
        expressions = self.references.lookup(catalogs=["expressions"], terms=["图书馆"])
        self.assertEqual(expressions["total_matches"], 2)

    def test_missing_qq_uses_main_account_and_exposes_binding_source(self):
        data = values()
        data["qid"]["p3"] = None
        references = ReferenceData(MANIFEST, data, source="fixture")
        player = references.lookup(catalogs=["players"], terms=["p3"])["matches"][0]
        self.assertEqual(player["ids"]["qq"], ["10002"])
        self.assertEqual(player["id_sources"], {"qq": "p2"})
        context = references.context()["catalogs"]["players"]
        projected = next(item for item in context if item["player_key"] == "p3")
        self.assertEqual(projected["qq"], ["10002"])
        self.assertEqual(projected["id_sources"], {"qq": "p2"})
        data["qid"]["p3"] = "10003"
        explicit = ReferenceData(MANIFEST, data, source="fixture").lookup(
            catalogs=["players"], terms=["p3"])["matches"][0]
        self.assertEqual(explicit["ids"]["qq"], ["10003"])
        self.assertNotIn("id_sources", explicit)

    def test_account_fallback_handles_chains_and_rejects_conflicts_cycles_and_siblings(self):
        self.assertEqual(account_id_binding("alt", {"main": "100"},
            {"main": ["main", "middle"], "middle": ["middle", "alt"]}), (["100"], "main"))
        for ids, groups in [
            ({"a": "100", "b": "200"}, {"a": ["alt"], "b": ["alt"]}),
            ({}, {"a": ["alt"], "alt": ["a"]}),
            ({"sibling": "100"}, {"main": ["alt", "sibling"]}),
        ]:
            with self.subTest(groups=groups):
                self.assertEqual(account_id_binding("alt", ids, groups), ([], None))

    def test_context_projection_and_catalogs_exclude_undeclared_fields(self):
        context = self.references.context()
        self.assertEqual(context["catalogs"]["players"][0]["qq"], ["10001"])
        serialized = json.dumps(context)
        self.assertNotIn("camp_user_id", serialized)
        self.assertNotIn("must-never", json.dumps(self.references.directory()))
        self.assertNotIn("must-never", json.dumps(self.references.lookup()))
        self.assertNotIn("heroes", context["catalogs"])

    def test_pagination_and_version_change_when_configuration_changes(self):
        first = self.references.lookup(catalogs=["players"], limit=2)
        second = self.references.lookup(
            catalogs=["players"], offset=first["next_offset"], limit=2
        )
        self.assertEqual(second["next_offset"], None)
        self.assertEqual(len(first["matches"] + second["matches"]), 4)
        changed = values()
        changed["namenick"]["p1"] = "新名"
        self.assertNotEqual(
            ReferenceData(MANIFEST, changed, source="fixture").version,
            self.references.version,
        )

    def test_remote_source_refreshes_without_opening_database(self):
        from agent_console import remote_worker

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "static_variable.json"
            manifest = {**MANIFEST, "source": {"path": path.name, "format": "json"}}
            path.write_text(json.dumps(values()))
            with patch.dict(
                remote_worker.CONTEXT,
                {
                    "root": Path(directory),
                    "reference_class": ReferenceData,
                    "reference_manifest": manifest,
                },
            ):
                with patch.object(remote_worker, "db_connection") as connection:
                    before = remote_worker.reference_snapshot()
                    changed = values()
                    changed["namenick"]["p1"] = "修改后"
                    path.write_text(json.dumps(changed))
                    after = remote_worker.reference_snapshot()
                    self.assertNotEqual(
                        before["context"]["version"], after["context"]["version"]
                    )
                    connection.assert_not_called()


class ReferenceToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_lookup_and_dataset_share_same_reference_source(self):
        reference = ReferenceData(MANIFEST, values(), source="fixture")

        class Service:
            async def lookup_reference_data(self, args, ctx):
                return reference.lookup(**args)

        registry = ToolRegistry()
        register_application_tools(
            registry, service=Service(), catalogs={"references": reference.directory()}
        )

        async def emit(*args):
            return {}

        ctx = ToolContext(
            RunRequest(
                "昵称", "session", Principal("user", frozenset({"reference.read"}))
            ),
            emit,
        )
        ctx.disclosed.add("discover_tools")
        discovered = await execute(
            registry,
            {
                "function": {
                    "name": "discover_tools",
                    "arguments": json.dumps({"categories": ["references"]}),
                }
            },
            ctx,
        )
        self.assertTrue(discovered.ok)
        self.assertIn("lookup_reference_data", ctx.disclosed)
        lookup = await execute(
            registry,
            {
                "function": {
                    "name": "lookup_reference_data",
                    "arguments": json.dumps(
                        {"catalogs": ["players"], "terms": ["10001"], "namespace": "qq"}
                    ),
                }
            },
            ctx,
        )
        self.assertTrue(lookup.ok)
        dataset = ctx.resource(lookup.data["dataset_id"])
        self.assertEqual(dataset["rows"][0]["name"], "示例玩家74")
        self.assertEqual(dataset["rows"][0]["qq"], ["10001"])


if __name__ == "__main__":
    unittest.main()

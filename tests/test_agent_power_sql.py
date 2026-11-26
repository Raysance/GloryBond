"""Power has its own discoverable SQL contract, match clock and full JSON shape."""

import datetime
import json
from pathlib import Path
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlglot import parse_one
from agent_runtime import Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from glorybond.agent import remote_worker as worker
from glorybond.agent.capabilities import Capabilities, load_catalogs
from glorybond.agent.tools.application import register_application_tools
from glorybond.agent.tools import sql_validation as validation
from tests.test_agent_runtime import call

ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / 'resources/agent/power_sql/catalog.json').read_text())
GAME_CATALOG = json.loads((ROOT / 'resources/agent/hok_sql/catalog.json').read_text())
DEFINITIONS = json.loads((ROOT / 'resources/agent/hok_sql/views.json').read_text())
DEFINITIONS.update(json.loads((ROOT / 'resources/agent/power_sql/views.json').read_text()))


def validate(sql, params=None, catalog=CATALOG):
    return validation.validate_readonly_sql(sql, params, allowed_tables=catalog['tables'], schema_name='hok')


class PowerContractTests(unittest.TestCase):
    def test_catalog_examples_execute_through_the_same_validator_and_compiler(self):
        with patch.dict(worker.CONTEXT, {'definitions': DEFINITIONS,
                'catalogs': {'hok_sql': GAME_CATALOG, 'power_sql': CATALOG},
                'validation': validation.__dict__}, clear=True):
            for example in CATALOG['examples']:
                with self.subTest(example=example['purpose']):
                    sql = validate(example['sql'], example.get('params'))
                    scope = validation.normalize_game_scope(example.get('scope', {}))
                    compiled = worker.expand_semantic_views(sql, scope, [])
                    self.assertIsNotNone(parse_one(compiled, read='postgres'))

    def test_each_tool_rejects_the_other_catalog_and_raw_storage(self):
        for sql, catalog in [
            ('SELECT game_seq FROM hok.chat_player_battles', CATALOG),
            ('SELECT game_seq FROM hok.chat_battle_power', GAME_CATALOG),
            ('SELECT payload FROM hok.battle_power', CATALOG),
            ('SELECT role_id FROM hok.chat_battle_power_players', CATALOG),
        ]:
            with self.subTest(sql=sql), self.assertRaises(validation.ChatSQLValidationError):
                validate(sql, catalog=catalog)
        sql = "SELECT game_seq, p->>'heroName' AS hero FROM hok.chat_battle_power CROSS JOIN LATERAL jsonb_array_elements(payload->'players') AS p WHERE player_keys && ARRAY[:a,:b]"
        self.assertTrue(validate(sql, {'a': 'one', 'b': 'two'}))

    def test_power_batch_rejects_cross_catalog_query_before_opening_database(self):
        with patch.dict(worker.CONTEXT, {'catalogs': {'power_sql': CATALOG},
                'validation': validation.__dict__}, clear=True), patch.object(worker, 'db_connection') as connect:
            with self.assertRaises(validation.ChatSQLValidationError):
                worker.analyze({'domain': 'power', 'scope': {}, 'principal': {}, 'queries': [
                    {'sql': 'SELECT game_seq FROM hok.chat_battle_power'},
                    {'sql': 'SELECT game_seq FROM hok.chat_player_battles'}]})
            connect.assert_not_called()

    def test_match_scope_is_applied_before_counts_and_includes_undated_only_without_bounds(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE power(game_seq INTEGER, snapshot_date TEXT, game_time_epoch INTEGER, is_official BOOLEAN)')
        epoch = int(datetime.datetime.fromisoformat('2026-11-02T00:10:00+08:00').timestamp())
        db.executemany('INSERT INTO power VALUES (?,?,?,?)', [(1, '2026-11-01', epoch, 1),
            (2, '2026-11-02', epoch + 86400, 1), (3, '2026-11-01', epoch, 0), (4, None, None, 1)])
        definitions = {name: 'SELECT * FROM power' for name in CATALOG['tables']}
        with patch.dict(worker.CONTEXT, {'definitions': definitions, 'catalogs': {'power_sql': CATALOG},
                'validation': validation.__dict__}, clear=True):
            for scope, count in [
                ({'start_at': '2026-11-02T00:00:00+08:00', 'end_at': '2026-11-03T00:00:00+08:00'}, 1),
                ({'start_at': '2026-11-02T00:00:00+08:00', 'end_at': '2026-11-03T00:00:00+08:00', 'mode': 'all'}, 2),
                ({'start_at': '2026-11-02T00:00:00+08:00', 'end_at': '2026-11-03T00:00:00+08:00', 'time_basis': 'business'}, 1),
                ({}, 3),
            ]:
                for name in CATALOG['tables']:
                    scoped = validation.normalize_game_scope(scope)
                    scoped['as_of'] = '2026-11-04T00:00:00+08:00'
                    sql = worker.expand_semantic_views(f'SELECT COUNT(*) FROM hok.{name}', scoped)
                    self.assertEqual(db.execute(parse_one(sql, read='postgres').sql(dialect='sqlite')).fetchone()[0], count)
            scoped = validation.normalize_game_scope({})
            scoped['as_of'] = '2026-11-02T00:00:00+08:00'
            sql = worker.expand_semantic_views('SELECT COUNT(*) FROM hok.chat_battle_power', scoped)
            self.assertEqual(db.execute(parse_one(sql, read='postgres').sql(dialect='sqlite')).fetchone()[0], 1)


class PowerToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_is_separate_and_propagates_scope_clock_and_dataset(self):
        bridge = SimpleNamespace(call=AsyncMock(return_value={'observations': [
            {'ok': True, 'rows': [{'games': 2}], 'columns': ['games'], 'truncated': False}]}))
        registry = ToolRegistry()
        register_application_tools(registry, service=Capabilities(bridge), catalogs=load_catalogs(ROOT / 'resources/agent'))
        ctx = ToolContext(RunRequest('统计底蕴', 'session', Principal('u', frozenset({'game.read'})),
            metadata={'message_timestamp': 1800000000}), AsyncMock())
        ctx.disclosed.update(registry.initial_names(ctx))
        result = await execute(registry, call('discover_tools', {'categories': ['power_data']}), ctx)
        self.assertTrue(result.ok)
        self.assertIn('examples', result.data['catalogues']['power_data'])
        self.assertIn('analyze_power_database', ctx.disclosed)
        self.assertNotIn('analyze_game_database', ctx.disclosed)
        scope = {'start_at': '2026-11-01T00:00:00+08:00', 'end_at': '2026-11-02T00:00:00+08:00'}
        result = await execute(registry, call('analyze_power_database', {'scope': scope,
            'queries': [{'sql': 'SELECT COUNT(*) AS games FROM hok.chat_battle_power'}]}), ctx)
        self.assertTrue(result.ok)
        arguments = bridge.call.call_args.kwargs
        self.assertEqual(arguments['domain'], 'power')
        self.assertEqual(arguments['as_of'], 1800000000)
        self.assertEqual(arguments['scope']['start_at'], scope['start_at'])
        self.assertIn('dataset_id', result.data['observations'][0])
        denied = ToolContext(RunRequest('x', 's', Principal('u')), AsyncMock())
        denied.disclosed.update(registry.initial_names(denied))
        result = await execute(registry, call('discover_tools', {'categories': ['power_data']}), denied)
        self.assertNotIn('analyze_power_database', denied.disclosed)


if __name__ == '__main__':
    unittest.main()

"""Public KPL protocol, bounded projections and actual shared tool wiring."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests
import yaml
from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry

from agent_console.capabilities import Capabilities, load_catalogs
from agent_console.kpl_client import query_kpl_data
from agent_console.remote import RemoteBridge
from agent_console import remote_worker
from agent_console.tools.application import register_application_tools
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call

ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / 'shared/agent/kpl/catalog.json').read_text())
CONFIG = yaml.safe_load((ROOT / 'config.yaml').read_text())['AgentKPL']


class Response:
    def __init__(self, data=None, *, status=200, mime='application/json', raw=None):
        self.status_code, self.headers = status, {'Content-Type': mime}
        self.raw = raw if raw is not None else json.dumps(data, ensure_ascii=False).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, **kwargs):
        for index in range(0, len(self.raw), 64):
            yield self.raw[index:index+64]


class ProtocolTests(unittest.TestCase):
    def query(self, response, *, config=None, **args):
        self.transport = Mock(return_value=response)
        return query_kpl_data(CATALOG, config or CONFIG, args, transport=self.transport)

    def test_fixed_get_origin_validated_ids_params_and_no_redirect_auth(self):
        result = self.query(Response({'data': {'heroName': '安琪拉', 'pickCount': 115, 'winRate': 53.04}}),
                            action='hero_summary', params={'leagueId': 6, 'heroId': 100})
        args, kwargs = self.transport.call_args
        self.assertEqual(args[0], 'https://kplll.online/api/heroes/100/stats-summary')
        self.assertEqual(kwargs['params'], {'leagueId': 6})
        self.assertFalse(kwargs['allow_redirects'])
        self.assertNotIn('Authorization', kwargs['headers'])
        self.assertEqual(result['data']['winRate'], 53.04)
        self.assertEqual(result['source_url'], 'https://kplll.online/heroes/100')
        self.assertTrue(result['retrieved_at'].endswith('+08:00'))
        self.assertEqual(result['params']['heroId'], 100)

    def test_all_declared_routes_match_expected_collection_and_object_schemas(self):
        for action, spec in CATALOG['actions'].items():
            params = {}
            for name in spec['required']:
                definition = CATALOG['parameters'][spec['params'][name]]
                params[name] = definition.get('enum', [definition.get('min', 1) if definition['type'] == 'integer' else 'player-id'])[0]
            if 'position2' in params:
                params['position2'] = 5
            data = [{'id': 1, 'name': '对象'}] if spec['collection'] else {'id': 1, 'name': '对象'}
            payload = data
            for name in reversed(spec['data_path']):
                payload = {name: payload}
            if spec.get('server_pagination'):
                payload['data']['total'] = 1
            with self.subTest(action=action):
                result = self.query(Response(payload), action=action, params=params)
                self.assertEqual(result['data'], data)

    def test_unknown_args_wrong_types_and_path_injection_make_no_http_call(self):
        cases = [
            {'action': 'feedback'}, {'action': 'teams'},
            {'action': 'teams', 'params': {'leagueId': True}},
            {'action': 'teams', 'params': {'leagueId': 6, 'url': 'http://127.0.0.1/'}},
            {'action': 'player_detail', 'params': {'leagueId': 6, 'playerId': '../../secret'}},
            {'action': 'player_rankings', 'params': {'leagueId': 6, 'type': 'kda'}},
            {'action': 'hero_combos', 'params': {'leagueId': 6, 'teamId': 1, 'position1': 2, 'position2': 2}},
            {'action': 'leagues', 'limit': 1000},
            {'action': 'leagues', 'date_from': '2026-02-30'},
        ]
        for args in cases:
            transport = Mock()
            with self.subTest(args=args), self.assertRaises(ValueError):
                query_kpl_data(CATALOG, CONFIG, args, transport=transport)
            transport.assert_not_called()

    def test_nonpaginated_name_filter_then_slice_and_conditional_fields(self):
        rows = [{'id': 1, 'name': 'AG vs WB', 'icon': '/logo.png', 'team1Wins': 3},
                {'id': 2, 'name': 'AG vs TTG'}, {'id': 3, 'name': '狼队 vs WB'}]
        result = self.query(Response({'data': rows}), action='matches', params={'leagueId': 6},
                            search='ag', limit=1, fields=['id', 'name', 'team1Wins'])
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['filtered_total'], 2)
        self.assertEqual(result['next_offset'], 1)
        self.assertTrue(result['truncated'])
        self.assertNotIn('icon', result['data'][0])
        result = self.query(Response({'data': rows}), action='matches', params={'leagueId': 6},
                            limit=3, fields=['id', 'name', 'team1Wins'])
        self.assertIsNone(result['data'][1]['team1Wins'])

    def test_calendar_filters_apply_before_limit_and_keep_timezone_semantics(self):
        rows = [{'id': 1, 'name': 'UTC晚场', 'startTime': '2026-10-13T17:00:00Z'},
                {'id': 2, 'name': '原日期', 'startTime': '2026-10-14T19:00:00.000'},
                {'id': 3, 'name': '其他日期', 'startTime': '2026-10-13T20:00:00.000'}]
        result = self.query(Response({'data': rows}), action='matches', params={'leagueId': 6}, limit=1,
                            date_from='2026-10-14', date_to='2026-10-14')
        self.assertEqual(result['data'][0]['id'], 1)
        self.assertEqual(result['filtered_total'], 2)
        self.assertEqual(result['next_offset'], 1)

    def test_rank_pagination_total_and_invalid_search_alignment(self):
        result = self.query(Response({'data': {'rankings': [{'rank': 21, 'playerName': '选手'}], 'total': 21}}),
                            action='player_rankings', params={'leagueId': 6, 'type': 'hurt'}, offset=20, limit=20)
        self.assertEqual(self.transport.call_args.kwargs['params']['page'], 2)
        self.assertEqual(result['filtered_total'], 21)
        self.assertIsNone(result['next_offset'])
        self.assertTrue(result['truncated'])
        for extra in ({'offset': 3}, {'search': '选手'}):
            transport = Mock()
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                query_kpl_data(CATALOG, CONFIG, {'action': 'player_rankings', 'params': {'leagueId': 6, 'type': 'hurt'}, **extra}, transport=transport)
            transport.assert_not_called()

    def test_empty_missing_changed_schemas_http_errors_and_body_limits(self):
        empty = self.query(Response({'data': []}), action='teams', params={'leagueId': 6})
        self.assertEqual(empty['row_count'], 0)
        for response in [Response({'data': None}), Response({'unknown': []}),
                         Response(status=404), Response(mime='text/html'), Response(raw=b'{not JSON'),
                         Response(raw=b'x' * (CONFIG['max_response_bytes'] + 1))]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.query(response, action='teams', params={'leagueId': 6})
        with self.assertRaises(ValueError):
            query_kpl_data(CATALOG, CONFIG, {'action': 'leagues'}, transport=Mock(side_effect=requests.Timeout('timeout')))

    def test_nested_truncation_and_response_reduction_do_not_fake_complete_results(self):
        result = self.query(Response({'data': {'name': '队伍', 'battles': [{'id': x} for x in range(4)]}}),
                            action='team_detail', params={'leagueId': 6, 'teamId': 1}, nested_limit=2)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['nested_truncations'], [{'path': 'data.battles', 'total': 4, 'returned': 2}])
        with self.assertRaises(ValueError):
            self.query(Response({'data': [{'name': 'x' * 500}]}), config={**CONFIG, 'max_observation_chars': 100}, action='leagues')

    def test_portable_bootstrap_contains_latest_client_and_only_public_settings(self):
        bridge = RemoteBridge('test', str(ROOT), 'python', ROOT / 'shared/agent')
        arguments = bridge._bootstrap_arguments()
        namespace = {}
        exec(compile(arguments['kpl_client'], 'portable_kpl', 'exec'), namespace)
        result = namespace['query_kpl_data'](arguments['kpl_catalog'], arguments['kpl_config'],
                                            {'action': 'leagues'}, transport=Mock(return_value=Response({'data': []})))
        self.assertEqual(result['row_count'], 0)
        self.assertNotIn('api_key', arguments['kpl_config'])

    def test_private_or_invalid_configuration_is_rejected_before_request(self):
        for config in [{**CONFIG, 'api_key': 'private-value'},
                       {**CONFIG, 'api_base_url': 'https://user:secret@kplll.online/api'},
                       {**CONFIG, 'site_url': 'http://kplll.online'},
                       {**CONFIG, 'timeout_seconds': False}]:
            transport = Mock()
            with self.subTest(config=config), self.assertRaises(ValueError):
                query_kpl_data(CATALOG, config, {'action': 'leagues'}, transport=transport)
            transport.assert_not_called()


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_react_discovery_rpc_source_observation_and_plot_resource(self):
        catalogues = load_catalogs(ROOT / 'shared/agent', kpl_config=CONFIG)
        registry = ToolRegistry()
        observed = []
        def client(catalog, config, args):
            return query_kpl_data(catalog, config, args, transport=Mock(return_value=Response({'data': {'data': [
                {'id': 100, 'name': '安琪拉', 'pickCount': 115, 'winRate': 53.04},
            ]}})))
        class Bridge:
            async def call(self, op, **args):
                observed.append((op, args))
                with patch.dict(remote_worker.CONTEXT, store=object(), kpl_client=client, kpl_catalog=CATALOG, kpl_config=CONFIG):
                    return remote_worker.dispatch({'op': op, **args})
        register_application_tools(registry, service=Capabilities(Bridge()), catalogs=catalogues)
        model = ScriptedModel([
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['kpl']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('query_kpl', {'action': 'heroes', 'params': {'leagueId': 6, 'name': '安琪拉'}}, 'k')]},
            {'role': 'assistant', 'content': '该赛事安琪拉115次选用，胜率53.04%。'},
        ])
        state = State()
        runtime = AgentRuntime(model=model, registry=registry, state=state, output=Sink(), clock=Clock())
        result = await runtime.run(RunRequest('查询KPL安琪拉表现', 'kpl', Principal('u', frozenset({'web.read'})), required_tools=('discover_tools',)))
        self.assertEqual(observed[0][0], 'kpl_query')
        resource = next(iter(result['resources'].values()))
        self.assertEqual(resource['rows'][0]['winRate'], 53.04)
        self.assertIn('name', resource['columns'])
        self.assertIn('dataset_id', json.dumps(state.events))
        self.assertIn('kplll.online', json.dumps(state.events))
        self.assertIn('query_kpl', [s['function']['name'] for s in model.schemas[-1]])

    async def test_disabled_configuration_registers_no_tool(self):
        registry = ToolRegistry()
        register_application_tools(registry, service=None, catalogs={'kpl': {**CATALOG, 'config': {**CONFIG, 'enabled': False}}})
        self.assertNotIn('query_kpl', registry.tools)


if __name__ == '__main__':
    unittest.main()

"""Client routing, exact identity selection, paced dispatch and fail-closed limits."""
import unittest
from unittest.mock import Mock, patch

from local_debugger import import_hok_module

HANDLER = import_hok_module('event_handlers.player_client')
ADAPTER = import_hok_module('api_adapters.player_client')
ZFUNC = import_hok_module('zfunc')
DYNAMIC = import_hok_module('zdynamic')
PRESENTATION = import_hok_module('business.player_client')


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'players': {'alice': {'uid': 7, 'logic_world_id': 8, 'fake_description_id': 9}},
                         'max_result_chars': 50, 'message_chars': 30, 'display_item_limit': 5}

    def parse(self, text, qids=None):
        return HANDLER.query_parameters(HANDLER.parse_client_command(text), user_id='1', settings=self.settings,
                                        qids=qids or {'alice': '1'}, nicknames={'alice': '甲'},
                                        hero_names={'106': '小乔', '112': '鲁班七号'},
                                        hero_aliases={'112': '卤蛋', '-1': '轮椅'})

    def test_prefix_requires_boundary_and_accepts_fullwidth(self):
        self.assertIsNone(HANDLER.parse_client_command('客户端 战绩'))
        self.assertIsNone(HANDLER.parse_client_command('#客户端别的'))
        self.assertEqual(HANDLER.parse_client_command('＃客户端 战绩 我'), ['战绩', '我'])

    def test_self_and_configured_nickname_bind_explicit_ref(self):
        self.assertEqual(self.parse('#客户端 战绩')[1]['player']['uid'], 7)
        self.assertEqual(self.parse('#客户端 资料 甲')[1]['player']['fake_description_id'], 9)

    def test_ambiguous_self_and_unknown_target_rejected(self):
        self.settings['players']['alt'] = self.settings['players']['alice']
        with self.assertRaises(ValueError):
            self.parse('#客户端 战绩 我', {'alice': '1', 'alt': '1'})
        with self.assertRaises(ValueError):
            self.parse('#客户端 战绩 arbitrary')

    def test_query_parameters_are_strict(self):
        self.assertEqual(self.parse('#客户端 英雄 alice year')[1]['scope'], 'year')
        self.assertEqual(self.parse('#客户端 游戏统计 alice')[0], 'game')
        self.assertEqual(self.parse('#客户端 英雄详情 alice 166')[1]['hero_id'], 166)
        for text in ('#客户端 英雄 alice week', '#客户端 英雄详情 alice -1', '#客户端 资料 alice extra'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)
        self.assertIsNone(self.parse('#客户端 搜索 游戏昵称')[1]['platform'])
        self.assertIsNone(self.parse('#客户端 搜索 游戏昵称 all')[1]['platform'])
        self.assertEqual(self.parse('#客户端 搜索 "游戏 昵称" ios')[1], {'name': '游戏 昵称', 'platform': 2})

    def test_hero_names_aliases_and_implicit_self(self):
        for text, expected in (('#客户端 英雄详情 alice 小乔', 106),
                               ('＃客户端 英雄详情 甲 卤蛋', 112),
                               ('#客户端 英雄详情 小乔', 106),
                               ('#客户端 英雄详情 166', 166)):
            with self.subTest(text=text):
                _, parameters, _ = self.parse(text)
                self.assertEqual(parameters['hero_id'], expected)
                self.assertEqual(parameters['player']['uid'], 7)

    def test_unknown_partial_ambiguous_or_placeholder_heroes_are_rejected(self):
        for hero in ('小', '不存在', '轮椅', '0', str(2 ** 32)):
            with self.subTest(hero=hero), self.assertRaises(ValueError):
                self.parse('#客户端 英雄详情 alice ' + hero)
        with self.assertRaises(ValueError):
            HANDLER.resolve_hero_id('重名', {'1': '重名'}, {'2': '重名'})

    def test_clipping_is_explicit_and_messages_bounded(self):
        parts = PRESENTATION.text_report('history', '甲', {'records': [{"dwGameStartTime": 1792822073}] * 10},
                                         self.settings, {})
        self.assertTrue(all(len(part) <= 30 for part in parts))
        self.assertIn('已截断', ''.join(parts))
        self.assertIn('不代表全部历史', ''.join(parts))


class AdapterTests(unittest.TestCase):
    def make(self, gate=None, on_error=None):
        fake = Mock()
        settings = {'timeout_seconds': 1, 'query_interval_seconds': 5, 'platform_id': 21,
                    'rate_limit': {'privacy_codes': [32002]}}
        with patch('hok_research.HokClient.from_resources', return_value=fake), \
             patch('hok_research.MsdkSession.load'):
            adapter = ADAPTER.PlayerClientAdapter(paths={'resources': 'r', 'installation': 'i', 'session': 's'},
                                                  settings=settings, gate=gate or Mock(), on_error=on_error or Mock())
        return adapter, fake

    def test_gate_precedes_login_and_each_request(self):
        gate = Mock()
        adapter, fake = self.make(gate)
        fake.search_players.return_value.to_json_value.return_value = {'candidates': []}
        self.assertEqual(adapter.query('search', name='甲', platform=1), {'candidates': []})
        self.assertEqual([call.args[0] for call in gate.call_args_list], ['login', 'query'])
        fake.search_players.assert_called_once()

    def test_dual_search_gates_both_platforms_and_keeps_not_found_as_empty(self):
        from hok_research import PlayerSearchResult, SearchPlatform
        gate, failed = Mock(), Mock()
        adapter, fake = self.make(gate, failed)
        fake.search_players.side_effect = [PlayerSearchResult("甲", platform, {
            "stResultInfo": {"iResultId": 13002}, "bIsMadeUpBySvr": False})
            for platform in (SearchPlatform.ANDROID, SearchPlatform.IOS)]
        result = adapter.query("search", name="甲")
        self.assertEqual(result["platforms"], [1, 2])
        self.assertEqual(result["candidates"], [])
        self.assertEqual([c.kwargs["platform"] for c in fake.search_players.call_args_list], [1, 2])
        self.assertEqual([c.args[0] for c in gate.call_args_list], ["login", "query", "query"])
        failed.assert_not_called()

    def test_blocked_query_makes_no_network_call(self):
        gate = Mock(side_effect=[None, ADAPTER.PlayerClientRateLimited(12)])
        adapter, fake = self.make(gate)
        with self.assertRaises(ADAPTER.PlayerClientRateLimited):
            adapter.query('history', player={'uid': 1, 'logic_world_id': 2, 'fake_description_id': 3})
        fake.history.assert_not_called()

    def test_explicit_target_required(self):
        adapter, fake = self.make()
        with self.assertRaises(ValueError):
            adapter.query('profile')
        fake.profile.assert_not_called()

    def test_successful_sources_are_cached_by_exact_target_then_expire_without_sharing_mutations(self):
        from hok_research import PlayerRef
        adapter,fake=self.make()
        fake.game.return_value={'value':[1]}
        clock=import_hok_module('ztime')
        with patch.object(clock,'monotonic_seconds',return_value=0):
            first=adapter._read('game',PlayerRef(1,2,3))
        first['value'].append(9)
        with patch.object(clock,'monotonic_seconds',return_value=1):
            self.assertEqual(adapter._read('game',PlayerRef(1,2,3)),{'value':[1]})
            adapter._read('game',PlayerRef(1,4,3))
        self.assertEqual(fake.game.call_count,2)
        with patch.object(clock,'monotonic_seconds',return_value=61):
            adapter._read('game',PlayerRef(1,2,3))
        self.assertEqual(fake.game.call_count,3)
        self.assertEqual([call.args[0] for call in adapter.gate.call_args_list],['login','query','query','query'])
        adapter.close()
        self.assertEqual(len(adapter._cache),0)

    def test_cache_is_bounded_and_failed_sources_are_never_cached(self):
        from hok_research import PlayerRef
        adapter,fake=self.make()
        adapter.settings['query_cache_max_entries']=2
        fake.game.return_value={'value':1}
        for uid in (1,2,3):adapter._read('game',PlayerRef(uid,2,3))
        self.assertEqual(len(adapter._cache),2)
        fake.game.side_effect=TimeoutError('not logged')
        for _ in range(2):
            with self.assertRaises(TimeoutError):adapter._read('game',PlayerRef(9,2,3))
        self.assertEqual(fake.game.call_count,5)

    def test_query_failure_not_retried(self):
        failed = Mock()
        adapter, fake = self.make(on_error=failed)
        fake.search_players.side_effect = TimeoutError('secret material')
        with self.assertRaises(TimeoutError):
            adapter.query('search', name='甲', platform=1)
        fake.search_players.assert_called_once()
        failed.assert_called_once()

    def test_incomplete_response_logs_only_counts_and_stage_timing_without_caching_or_retry(self):
        from hok_research import QueryTimeout
        clock = import_hok_module('ztime')
        util = import_hok_module('zutil')
        error = QueryTimeout(records=[{'private': 'PRIVATE_SENTINEL'}],
                             chunks=[{'secret': 'PRIVATE_SENTINEL'}, {'secret': 'PRIVATE_SENTINEL'}])
        adapter, fake = self.make()
        adapter.settings['timeout_seconds'] = 30
        fake.history.side_effect = error
        with patch.object(clock, 'monotonic_seconds', side_effect=[0, 2, 32]), \
             patch.object(util, 'log_message') as log:
            with self.assertRaises(QueryTimeout):
                adapter._read('history')
        line = log.call_args.args[0]
        for expected in ('operation=history', 'response_chunks', 'response_records',
                         'gate_ms=2000', 'request_ms=30000', 'timeout_ms=30000'):
            self.assertIn(expected, line)
        self.assertNotIn('PRIVATE_SENTINEL', line)
        self.assertEqual(ADAPTER.player_client_error_info(error),
                         {'type': 'QueryTimeout', 'response_chunks': 2, 'response_records': 1})
        self.assertEqual(adapter._cache, {})
        fake.history.assert_called_once_with(timeout=30)
        adapter.on_error.assert_called_once_with(error, login=False)

    def test_homepage_paces_both_requests(self):
        from hok_research import Profile, PlayerRef
        gate = Mock()
        adapter, fake = self.make(gate)
        fake.profile.return_value = Profile(PlayerRef(1, 2, 3), {key: {} for key in ('stMostUsedHero', 'stCurSeasonMostUsedHero', 'stCurYearMostUsedHero')})
        fake.history.return_value.to_json_value.return_value = {'records': []}
        adapter.query('homepage', player={'uid': 1, 'logic_world_id': 2, 'fake_description_id': 3})
        self.assertEqual([call.args[0] for call in gate.call_args_list], ['login', 'query', 'query'])


class RateTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'rate_limit': {'min_interval_seconds': 10, 'jitter_seconds': 0,
                         'per_minute': 5, 'per_hour': 120, 'login_interval_seconds': 60,
                         'login_per_hour': 6, 'max_wait_seconds': 20,
                         'privacy_codes': [32002, 296203, 296204], 'risk_codes': [262034],
                         'risk_cooldown_seconds': 900, 'login_failure_cooldown_seconds': 1800,
                         'error_cooldown_seconds': 60}}

    def test_redis_failure_is_closed(self):
        redis = Mock()
        redis.eval.side_effect = ConnectionError('offline')
        with patch.object(DYNAMIC, 'redis_deamon', redis), patch.object(ZFUNC, 'player_client_config', self.settings):
            with self.assertRaises(ConnectionError):
                ZFUNC.player_client_rate_gate('query')

    def test_cooldown_does_not_sleep_or_retry(self):
        redis = Mock()
        redis.eval.return_value = [0, 899000, 1]
        with patch.object(DYNAMIC, 'redis_deamon', redis), patch.object(ZFUNC, 'player_client_config', self.settings):
            with self.assertRaises(ADAPTER.PlayerClientRateLimited) as error:
                ZFUNC.player_client_rate_gate('query')
        self.assertEqual(error.exception.retry_after, 899)
        redis.eval.assert_called_once()

    def test_short_minute_quota_wait_does_not_abort_batch(self):
        redis = Mock()
        redis.eval.side_effect = [[0, 5000, 3], [1, 0, 0]]
        ztime = import_hok_module("ztime")
        with patch.object(DYNAMIC, "redis_deamon", redis), patch.object(ZFUNC, "player_client_config", self.settings), \
             patch.object(ztime, "sleep_seconds") as sleep:
            ZFUNC.player_client_rate_gate("query")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [3, 2])
        self.assertEqual(redis.eval.call_count, 2)

    def test_privacy_does_not_open_circuit_but_risk_and_login_do(self):
        from hok_research import QueryRejected
        redis = Mock()
        with patch.object(DYNAMIC, 'redis_deamon', redis), patch.object(ZFUNC, 'player_client_config', self.settings):
            ZFUNC.player_client_request_error(QueryRejected(32002, {}))
            redis.eval.assert_not_called()
            ZFUNC.player_client_request_error(QueryRejected(262034, {}))
            self.assertEqual(redis.eval.call_args.args[-1], 900000)
            ZFUNC.player_client_request_error(TimeoutError(), login=True)
            self.assertEqual(redis.eval.call_args.args[-1], 1800000)

    def test_query_timeout_does_not_open_global_cooldown_but_login_and_rejection_still_do(self):
        from hok_research import QueryTimeout, QueryRejected
        redis = Mock()
        with patch.object(DYNAMIC, 'redis_deamon', redis), patch.object(ZFUNC, 'player_client_config', self.settings):
            ZFUNC.player_client_request_error(QueryTimeout())
            redis.eval.assert_not_called()
            ZFUNC.player_client_request_error(QueryRejected(12345, {}))
            self.assertEqual(redis.eval.call_args.args[-1], 60000)
            ZFUNC.player_client_request_error(QueryRejected(262034, {}))
            self.assertEqual(redis.eval.call_args.args[-1], 900000)
            ZFUNC.player_client_request_error(QueryTimeout(), login=True)
            self.assertEqual(redis.eval.call_args.args[-1], 1800000)

    def test_query_timeout_discards_connection_and_releases_slot_without_relogin_or_replay(self):
        import threading
        from hok_research import QueryTimeout
        zapi = import_hok_module('zapi')
        zfile = import_hok_module('zfile')
        adapter, factory, lock = Mock(), Mock(), threading.Lock()
        factory.return_value = adapter
        adapter.query.side_effect = QueryTimeout()
        settings = {**self.settings, 'enabled': True}
        with patch.object(ZFUNC, 'player_client_config', settings), \
             patch.object(DYNAMIC, 'player_client_lock', lock), \
             patch.object(DYNAMIC, 'player_client_adapter', None), \
             patch.object(DYNAMIC, 'player_client_session_fingerprint', None), \
             patch.object(zapi, 'PlayerClientAdapter', factory), \
             patch.object(zfile, 'refresh_login_credentials', return_value=''), \
             patch.object(zfile, 'player_client_state_paths', return_value={}), \
             patch.object(ZFUNC, 'log_message'):
            with self.assertRaises(QueryTimeout):
                ZFUNC.player_client_query('friend_states')
            self.assertIsNone(DYNAMIC.player_client_adapter)
            self.assertFalse(lock.locked())
        factory.assert_called_once()
        adapter.query.assert_called_once_with('friend_states')
        adapter.close.assert_called_once()

    def test_normal_minute_queue_wait_keeps_connection_alive_and_retains_admission_limits(self):
        self.settings['rate_limit']['max_wait_seconds']=65
        redis=Mock();redis.eval.side_effect=[[0,50000,3],[1,0,0]]
        adapter=Mock();clock=import_hok_module('ztime')
        with patch.object(DYNAMIC,'redis_deamon',redis),patch.object(DYNAMIC,'player_client_adapter',adapter), \
             patch.object(ZFUNC,'player_client_config',self.settings),patch.object(clock,'sleep_seconds') as sleep:
            ZFUNC.player_client_rate_gate('query')
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[3]*16+[2])
        self.assertEqual(adapter.heartbeat.call_count,17)
        self.assertEqual(redis.eval.call_count,2)

    def test_heartbeat_never_logs_in_and_skips_an_active_query(self):
        adapter=Mock();factory=Mock()
        import threading
        lock=threading.Lock()
        with patch.object(DYNAMIC,'player_client_lock',lock),patch.object(DYNAMIC,'player_client_adapter',adapter), \
             patch.object(ZFUNC,'player_client_config',{'enabled':True}):
            lock.acquire()
            ZFUNC.player_client_heartbeat()
            adapter.heartbeat.assert_not_called()
            lock.release()
            ZFUNC.player_client_heartbeat()
            adapter.heartbeat.assert_called_once()
        with patch.object(DYNAMIC,'player_client_adapter',None),patch.object(ZFUNC,'player_client_config',{'enabled':True}), \
             patch.object(import_hok_module('zapi'),'PlayerClientAdapter',factory):
            ZFUNC.player_client_heartbeat()
        factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()

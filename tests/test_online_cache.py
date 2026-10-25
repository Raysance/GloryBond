"""One minute of online snapshots, with concurrent refreshes and failures bounded."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from hok_research import QueryTimeout, QueryRejected
from local_debugger import import_hok_module
from tests.test_client_online_status import state

ZFUNC = import_hok_module('zfunc')
ZTIME = import_hok_module('ztime')
ZAPI = import_hok_module('zapi')
DYNAMIC = import_hok_module('zdynamic')
ONLINE = import_hok_module('business.online_status')
ZFILE = import_hok_module('zfile')


def snapshot(name='玩家'):
    return {'complete': True, 'players': [state(1, name)], 'total': 1}


class OnlineCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.settings = {'enabled': True, 'online_cache_ttl_seconds': 60,
                         'rate_limit': {'max_wait_seconds': 1}}
        patches = [patch.object(DYNAMIC, 'player_client_online_lock', threading.Lock()),
                   patch.object(DYNAMIC, 'player_client_online_cache', None),
                   patch.object(ZFUNC, 'player_client_config', self.settings),
                   patch.object(ZTIME, 'monotonic_seconds', side_effect=lambda: self.now),
                   patch.object(ZFUNC, '_player_client_account_fingerprint', return_value='account-a'),
                   patch.object(ZFUNC, 'player_client_query', return_value=snapshot()),
                   patch.object(ZFUNC, 'log_message')]
        for setting in patches:
            setting.start(); self.addCleanup(setting.stop)
        self.query = ZFUNC.player_client_query
        self.fingerprint = ZFUNC._player_client_account_fingerprint

    def test_success_reuses_snapshot_for_sixty_seconds_without_sliding_expiry_or_mutation(self):
        first = ZFUNC.player_client_online_snapshot()
        first['players'][0]['name'] = '调用方修改'
        self.now = 59.9
        second = ZFUNC.player_client_online_snapshot()
        self.assertEqual(second['players'][0]['name'], '玩家')
        second['players'].clear()
        self.assertEqual(len(ZFUNC.player_client_online_snapshot()['players']), 1)
        self.query.assert_called_once_with('friend_states')
        self.query.return_value = snapshot('刷新后')
        self.now = 60
        self.assertEqual(ZFUNC.player_client_online_snapshot()['players'][0]['name'], '刷新后')
        self.assertEqual(self.query.call_count, 2)

    def test_window_starts_when_the_refresh_finishes_and_default_is_one_minute(self):
        self.settings.pop('online_cache_ttl_seconds')
        def delayed(*args):
            self.now += 30
            return snapshot()
        self.query.side_effect = delayed
        ZFUNC.player_client_online_snapshot()
        self.now = 89.9
        ZFUNC.player_client_online_snapshot()
        self.query.assert_called_once()
        self.now = 90
        ZFUNC.player_client_online_snapshot()
        self.assertEqual(self.query.call_count, 2)

    def test_successfully_empty_friend_list_is_a_valid_cached_snapshot(self):
        self.query.return_value = {'complete': True, 'players': [], 'total': 0}
        self.assertEqual(ZFUNC.player_client_online_snapshot()['players'], [])
        self.now = 59
        self.assertEqual(ZFUNC.player_client_online_snapshot()['players'], [])
        self.query.assert_called_once()

    def test_simultaneous_requests_share_one_refresh_including_the_waiters(self):
        start, entered, release = threading.Barrier(3, timeout=2), threading.Event(), threading.Event()
        def delayed(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return snapshot()
        def request():
            start.wait()
            return ZFUNC.player_client_online_snapshot()
        self.query.side_effect = delayed
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(request) for _ in range(2)]
            start.wait()
            self.assertTrue(entered.wait(2))
            release.set()
            results = [item.result(timeout=2) for item in pending]
        self.assertEqual(results[0], results[1])
        self.assertIsNot(results[0], results[1])
        self.query.assert_called_once_with('friend_states')

    def test_timeouts_and_server_rejections_do_not_trigger_repeated_refreshes_within_a_minute(self):
        for error in (QueryTimeout(), QueryRejected(262034, {}), ZAPI.PlayerClientRateLimited(900)):
            with self.subTest(error=type(error).__name__):
                self.now = 0
                DYNAMIC.player_client_online_cache = None
                self.query.reset_mock()
                self.query.side_effect = error
                with self.assertRaises(type(error)):
                    ZFUNC.player_client_online_snapshot()
                self.assertIsNone(DYNAMIC.player_client_online_cache['snapshot'])
                self.now = 59
                with self.assertRaises(ZAPI.PlayerClientRateLimited) as caught:
                    ZFUNC.player_client_online_snapshot()
                self.assertEqual(caught.exception.retry_after, 1)
                self.query.assert_called_once()
                self.query.side_effect = None
                self.now = 60
                self.assertEqual(ZFUNC.player_client_online_snapshot()['total'], 1)
                self.assertEqual(self.query.call_count, 2)

    def test_incomplete_or_malformed_snapshots_never_become_cached_online_results(self):
        for value in (None, {}, {'complete': False, 'players': [state(1, '部分玩家')]},
                      {'complete': True}, {'complete': True, 'players': None}):
            with self.subTest(value=value):
                DYNAMIC.player_client_online_cache = None
                self.query.reset_mock()
                self.query.return_value = value
                with self.assertRaises(ValueError):
                    ZFUNC.player_client_online_snapshot()
                with self.assertRaises(ZAPI.PlayerClientRateLimited):
                    ZFUNC.player_client_online_snapshot()
                self.query.assert_called_once()

    def test_failed_refresh_does_not_serve_an_expired_snapshot(self):
        ZFUNC.player_client_online_snapshot()
        self.now = 60
        self.query.side_effect = QueryTimeout()
        with self.assertRaises(QueryTimeout):
            ZFUNC.player_client_online_snapshot()
        self.now = 61
        with self.assertRaises(ZAPI.PlayerClientRateLimited):
            ZFUNC.player_client_online_snapshot()
        self.assertIsNone(DYNAMIC.player_client_online_cache['snapshot'])
        self.assertEqual(self.query.call_count, 2)

    def test_account_change_invalidates_the_old_snapshot_and_disabled_client_does_not_serve_it(self):
        ZFUNC.player_client_online_snapshot()
        self.fingerprint.return_value = 'account-b'
        self.query.return_value = snapshot('新账号好友')
        self.assertEqual(ZFUNC.player_client_online_snapshot()['players'][0]['name'], '新账号好友')
        self.assertEqual(self.query.call_count, 2)
        self.settings['enabled'] = False
        with self.assertRaises(ValueError):
            ZFUNC.player_client_online_snapshot()
        self.assertEqual(self.query.call_count, 2)

    def test_zero_ttl_disables_the_cache_and_busy_slot_never_sends_another_request(self):
        self.settings['online_cache_ttl_seconds'] = 0
        ZFUNC.player_client_online_snapshot()
        ZFUNC.player_client_online_snapshot()
        self.assertEqual(self.query.call_count, 2)
        self.settings['rate_limit']['max_wait_seconds'] = 0
        with DYNAMIC.player_client_online_lock:
            with self.assertRaises(ZAPI.PlayerClientRateLimited):
                ZFUNC.player_client_online_snapshot()
        self.assertEqual(self.query.call_count, 2)

    def test_steam_refreshes_and_main_player_filter_is_applied_again_on_every_cache_hit(self):
        with patch.object(ONLINE, 'userlist', {'a': 1}), \
             patch.object(ONLINE, 'player_client_config', {'players': {'a': {'uid': 1, 'logic_world_id': 100}}}), \
             patch.object(ONLINE, 'steam_userlist', {'steam': 's'}), \
             patch.dict(ONLINE.confs, {'Steam': {'api_key': 'test'}}), \
             patch.object(ZAPI, 'steam_api_user_status', side_effect=[
                 {'personaname': 'Steam昵称', 'personastate': 1},
                 {'personaname': 'Steam昵称', 'personastate': 1, 'gameextrainfo': '新游戏'}]) as steam:
            first, errors = ZFUNC.online_process()
            self.assertEqual(errors, '')
            self.assertIn('在线 1 人', first)
            ONLINE.player_client_config['players']['a']['logic_world_id'] = 101
            second, errors = ZFUNC.online_process()
            self.assertEqual(errors, '')
            self.assertNotIn('• 玩家', second)
            self.assertIn('新游戏', second)
        self.query.assert_called_once_with('friend_states')
        self.assertEqual(steam.call_count, 2)


class AccountFingerprintTests(unittest.TestCase):
    def test_current_session_and_route_changes_do_not_reuse_another_accounts_connection_or_online_cache(self):
        settings = {'platform_id': 21, 'server_id': 1, 'tree_index': 0}
        with patch.object(ZFUNC, 'player_client_config', settings), \
             patch.object(ZFILE, 'refresh_login_credentials', return_value='session-a') as refresh:
            original = ZFUNC._player_client_account_fingerprint()
            for key, value in (('platform_id', 22), ('server_id', 2), ('tree_index', 1)):
                previous = settings[key]
                settings[key] = value
                self.assertNotEqual(original, ZFUNC._player_client_account_fingerprint())
                settings[key] = previous
            refresh.return_value = 'session-b'
            self.assertNotEqual(original, ZFUNC._player_client_account_fingerprint())
        self.assertNotIn('session', original)


if __name__ == '__main__':
    unittest.main()

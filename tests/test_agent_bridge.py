"""Exercise real RPC streams through worker exits, cancellation and recovery."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi.testclient import TestClient

from agent_console.remote import BridgeUnavailable, RemoteBridge
from agent_console.tool_errors import RemoteToolError
from agent_console.server import create_app
from agent_console import remote_worker


WORKER = r'''
import json, os, sys, time
from pathlib import Path
ready = False
for line in sys.stdin:
    args = json.loads(line)
    op = args['op']
    if op == 'bootstrap':
        ready = True
        data = {'private': {'api_key': 'test-secret'}, 'public': {}}
    elif not ready:
        raise RuntimeError('bootstrap required')
    elif op == 'lose_reply':
        with Path(sys.argv[1]).open('a') as log:
            log.write('applied\n')
        break
    elif op == 'invalid_reply':
        print('invalid JSON', flush=True)
        continue
    elif op == 'reject':
        print(json.dumps({'ok': False, 'error': 'rejected test-secret', 'type': 'ValueError',
            'error_details': {'phase': 'worker_dispatch', 'operation': op, 'error_type': 'ValueError',
                              'message': 'rejected test-secret',
                              'causes': [{'error_type': 'KeyError', 'message': 'cause test-secret'}]}}), flush=True)
        continue
    elif op == 'reject_legacy':
        print(json.dumps({'ok': False, 'error': 'old rejection', 'type': 'ValueError'}), flush=True)
        continue
    elif op == 'health':
        data = {'connected': True}
    else:
        time.sleep(args.get('delay', 0))
        data = {'pid': os.getpid(), 'value': args.get('value')}
    print(json.dumps({'ok': True, 'data': data}), flush=True)
'''


class WorkerBootstrapTests(unittest.TestCase):
    def test_full_bootstrap_returns_actual_compilation_mode_without_database_view_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.yaml').write_text(json.dumps({'Redis': {'REDIS_HOST': 'test', 'REDIS_PORT': 6379}}))
            shared = Path(__file__).parents[1] / 'shared/agent'
            bridge = RemoteBridge('test', str(root), sys.executable, shared)
            bridge.kpl_config = {'enabled': True, 'api_base_url': 'https://example.invalid/api',
                'site_url': 'https://example.invalid', 'timeout_seconds': 1, 'max_response_bytes': 1024,
                'max_rows': 10, 'max_nested_items': 10, 'max_observation_chars': 1000}
            args = {**bridge._bootstrap_arguments(), 'use_process_environment': True}
            model = {'api_key': 'test-key', 'model': 'test', 'base_url': 'https://example.invalid', 'proxy_url': ''}
            def functions(path, names, namespace):
                namespace.update({name: Mock() for name in names})
                namespace.update(_apply_secret_environment=lambda cfg, env: cfg,
                                 _build_chat_api_config=lambda cfg, env: model,
                                 _build_deepseek_search_config=lambda cfg, env: {'api_key': ''})
            db, store = MagicMock(), Mock()
            cursor = db.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = ('hok_chat_reader', False, False, False, False, False)
            with patch.dict(remote_worker.CONTEXT, {}, clear=True), patch.dict(remote_worker.os.environ, {}, clear=True), \
                 patch.object(remote_worker, 'dotenv_values', return_value={'HOK_CHAT_READONLY_DSN': 'test-dsn'}), \
                 patch.object(remote_worker, 'extracted_functions', side_effect=functions), \
                 patch.object(remote_worker.psycopg, 'connect', return_value=db), \
                 patch.object(remote_worker.redis, 'Redis', return_value=store):
                result = remote_worker.bootstrap(args)
            self.assertEqual(result['public']['views_mode'], 'trusted_cte')
            self.assertEqual(result['public']['model'], 'test')
            store.ping.assert_called_once()
            self.assertNotIn('information_schema.views', str(cursor.execute.call_args_list))


class ScriptBridge(RemoteBridge):
    def __init__(self, root):
        super().__init__('test', str(root), sys.executable, root)
        self.spawns = 0

    def _bootstrap_arguments(self):
        return {}

    async def _spawn_worker(self):
        self.spawns += 1
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, '-u', '-c', WORKER, str(self.shared_path / 'writes'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = ScriptBridge(Path(self.tmp.name))
        self.addAsyncCleanup(self.bridge.close)
        await self.bridge.start()

    async def test_idle_disconnect_restores_once_for_concurrent_requests(self):
        old_pid = self.bridge.process.pid
        self.bridge.process.terminate()
        await self.bridge.process.wait()
        replies = await asyncio.gather(*(self.bridge.call('read', value=i) for i in range(8)))
        self.assertEqual([r['value'] for r in replies], list(range(8)))
        self.assertEqual(len({r['pid'] for r in replies}), 1)
        self.assertNotEqual(replies[0]['pid'], old_pid)
        self.assertEqual(self.bridge.spawns, 2)
        self.assertEqual(await self.bridge.health(), {'connected': True})

    async def test_lost_reply_does_not_replay_applied_write(self):
        with self.assertRaises(BridgeUnavailable):
            await self.bridge.call('lose_reply')
        self.assertIsNone(self.bridge.process)
        self.assertEqual(self.bridge.spawns, 1)
        self.assertEqual(await self.bridge.call('read', value='after'),
                         {'pid': self.bridge.process.pid, 'value': 'after'})
        self.assertEqual((Path(self.tmp.name) / 'writes').read_text(), 'applied\n')

    async def test_timeout_discards_stream_before_following_request(self):
        self.bridge.response_timeout = 0.02
        with self.assertRaises(BridgeUnavailable):
            await self.bridge.call('read', delay=0.2, value='late')
        self.bridge.response_timeout = 190
        reply = await self.bridge.call('read', value='next')
        self.assertEqual(reply['value'], 'next')
        self.assertEqual(self.bridge.spawns, 2)

    async def test_only_image_rpc_uses_longer_deadline(self):
        self.bridge.response_timeout = 0.02
        with patch('agent_console.remote.IMAGE_RPC_TIMEOUT_SECONDS', 0.3):
            result = await self.bridge.call('image', delay=0.05, value='picture')
            self.assertEqual(result['value'], 'picture')
            with self.assertRaises(BridgeUnavailable):
                await self.bridge.call('read', delay=0.05)

    async def test_cancelled_caller_cannot_shift_next_response(self):
        request = asyncio.create_task(self.bridge.call('read', delay=0.1, value='cancelled'))
        await asyncio.sleep(0.01)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        reply = await self.bridge.call('read', value='next')
        self.assertEqual(reply['value'], 'next')
        self.assertEqual(self.bridge.spawns, 1)

    async def test_bad_protocol_resets_but_application_rejection_does_not(self):
        with self.assertRaisesRegex(RemoteToolError, r'rejected \[redacted\]') as failure:
            await self.bridge.call('reject')
        self.assertEqual(failure.exception.error_details['error_type'], 'ValueError')
        self.assertEqual(failure.exception.error_details['causes'][0]['message'], 'cause [redacted]')
        self.assertEqual((await self.bridge.call('read'))['pid'], self.bridge.process.pid)
        self.assertEqual(self.bridge.spawns, 1)
        with self.assertRaises(BridgeUnavailable):
            await self.bridge.call('invalid_reply')
        await self.bridge.call('read')
        self.assertEqual(self.bridge.spawns, 2)

    async def test_old_worker_failures_keep_type_and_operation(self):
        with self.assertRaises(RemoteToolError) as failure:
            await self.bridge.call('reject_legacy')
        self.assertEqual(failure.exception.error_details['error_type'], 'ValueError')
        self.assertEqual(failure.exception.error_details['operation'], 'reject_legacy')

    async def test_closed_bridge_does_not_restart_until_explicit_start(self):
        await self.bridge.close()
        with self.assertRaises(BridgeUnavailable):
            await self.bridge.call('read')
        self.assertEqual(self.bridge.spawns, 1)
        await self.bridge.start()
        self.assertEqual(await self.bridge.health(), {'connected': True})

    async def test_bootstrap_failure_cleans_up_and_next_request_can_recover(self):
        self.bridge.process.terminate()
        await self.bridge.process.wait()
        with patch.object(self.bridge, '_spawn_worker', side_effect=OSError('unavailable')):
            with self.assertRaises(BridgeUnavailable):
                await self.bridge.call('read')
        self.assertIsNone(self.bridge.process)
        self.assertEqual((await self.bridge.call('read', value='recovered'))['value'], 'recovered')


class HealthEndpointTests(unittest.TestCase):
    def test_status_requires_both_live_connections_and_reports_503(self):
        app = create_app()
        app.state.bridge = Mock(health=AsyncMock(return_value={'connected': True}))
        app.state.state_bridge = Mock(health=AsyncMock(side_effect=BridgeUnavailable('连接暂不可用')))
        app.state.local_log = Mock(status={'enabled': True})
        app.state.runtime = Mock(registry=Mock(tools={}))
        client = TestClient(app, raise_server_exceptions=False)
        try:
            client.get('/')
            response = client.get('/api/status')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['detail'], '连接暂不可用')
            app.state.bridge.health.assert_awaited_once()
            app.state.state_bridge.health.assert_awaited_once()
            app.state.state_bridge.health.side_effect = None
            app.state.state_bridge.health.return_value = {'connected': True}
            response = client.get('/api/status')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['connections'], {
                'business': {'connected': True}, 'state': {'connected': True},
            })
        finally:
            client.close()

    def test_role_and_session_disconnects_are_explained_without_generic_500(self):
        app = create_app()
        app.state.principal = Mock(attributes={'identity': {}})
        app.state.roles = Mock(manage=AsyncMock(side_effect=BridgeUnavailable('连接暂不可用')))
        app.state.runtime = Mock(state=Mock(load_events=AsyncMock(side_effect=BridgeUnavailable('连接暂不可用'))))
        client = TestClient(app, raise_server_exceptions=False)
        try:
            client.get('/')
            for path in ('/api/roleplay', '/api/sessions/test'):
                response = client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['detail'], '连接暂不可用')
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()

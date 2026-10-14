"""Error details survive worker/RPC/tool/model boundaries without credentials."""

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from pydantic import BaseModel
import requests

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolResult
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console import remote_worker
from agent_console.remote import BridgeUnavailable
from agent_console.tool_errors import exception_details, redact_error, RemoteToolError
from agent_console.tools.diagnostics import DiagnosticToolRegistry
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call


class Args(BaseModel):
    value: int


class DetailsTests(unittest.TestCase):
    def test_typed_cause_http_status_and_only_compact_locations(self):
        response = requests.Response()
        response.status_code = 503
        response.headers['Authorization'] = 'private-header'
        try:
            try:
                raise requests.HTTPError('unavailable https://example.com/api?signature=private-signature', response=response)
            except requests.HTTPError as cause:
                raise ValueError('unable to read KPL data') from cause
        except ValueError as error:
            result = exception_details(error, phase='worker_dispatch', operation='kpl_query')
        self.assertEqual(result['error_type'], 'ValueError')
        self.assertEqual(result['causes'][0]['error_type'], 'HTTPError')
        self.assertEqual(result['diagnostics']['http_status'], 503)
        self.assertTrue(result['retryable'])
        encoded = json.dumps(result)
        for secret in ('private-header', 'private-signature', str(Path(__file__).parent), 'locals', 'response.headers'):
            self.assertNotIn(secret, encoded)
        self.assertIn('test_agent_tool_errors.py', encoded)

    def test_redaction_precedes_clipping_and_handles_json_credentials_urls_and_malformed_urls(self):
        values = ['api_key="private-key" password=REDACTED_CREDENTIAL',
                  '{"api_key": "json-private-key", "password": "json-REDACTED_CREDENTIAL"}',
                  '{"Authorization": "Basic private-basic-header"}',
                  'Authorization: Bearer private-header', 'postgresql://user:private-pass@host/db',
                  'https://user:private-pass@example.com/api?signed=private-query',
                  'sk-ai-v1-123456789abcdefgh', 'http://[bad']
        encoded = json.dumps(redact_error(values))
        for token in ('private-key', 'REDACTED_CREDENTIAL', 'json-private-key', 'json-REDACTED_CREDENTIAL',
                      'private-header', 'private-basic-header', 'private-pass', 'private-query', 'sk-ai-v1-123456789abcdefgh'):
            self.assertNotIn(token, encoded)
        result = exception_details(ValueError('x' * 3000 + ' exact-secret'), phase='tool_handler',
                                   redactor=lambda v: redact_error(v, ['exact-secret']))
        self.assertLessEqual(len(result['message']), 1200)
        self.assertNotIn('exact-secret', json.dumps(result))

    def test_sql_diagnostics_and_batch_success_are_both_preserved(self):
        error = RuntimeError('unknown column rating, test-secret-value')
        error.sqlstate = '42703'
        error.diag = SimpleNamespace(statement_position='18', message_primary='unknown column rating',
                                     message_detail=None, message_hint='use score', column_name='rating')
        first, second = MagicMock(), MagicMock()
        first.execute.side_effect = error
        second.fetchmany.return_value = [(9,)]
        second.description = [SimpleNamespace(name='score')]
        connection = MagicMock()
        connection.cursor.side_effect = [MagicMock(__enter__=Mock(return_value=first)),
                                         MagicMock(__enter__=Mock(return_value=second))]
        database = MagicMock(__enter__=Mock(return_value=connection))
        from agent_console import tool_errors
        context = {'cfg': {}, 'catalogs': {'hok_sql': {'schema': 'hok', 'tables': [], 'version': 1}},
                   'validation': {'validate_readonly_sql': lambda sql, *a, **kw: sql},
                   'env': {'TEST_KEY': 'test-secret-value'}, 'error_reporting': tool_errors.__dict__}
        with patch.dict(remote_worker.CONTEXT, context, clear=True), \
             patch.object(remote_worker, 'db_connection', return_value=database), \
             patch.object(remote_worker, 'expand_semantic_views', side_effect=lambda sql: sql):
            result = remote_worker.analyze({'domain': 'game', 'principal': {}, 'queries': [
                {'sql': 'SELECT rating', 'intent': 'first'}, {'sql': 'SELECT score', 'intent': 'second'}]})
        failure, success = result['observations']
        self.assertEqual(failure['error_details']['query_index'], 0)
        self.assertEqual(failure['error_details']['diagnostics']['sqlstate'], '42703')
        self.assertEqual(failure['error_details']['diagnostics']['statement_position'], '18')
        self.assertEqual(failure['error_details']['diagnostics']['message_hint'], 'use score')
        self.assertNotIn('test-secret-value', json.dumps(result))
        self.assertTrue(success['ok'])
        self.assertEqual(success['rows'], [[9]])

    def test_worker_wire_retains_error_type_cause_and_stderr_without_secrets(self):
        from agent_console import tool_errors
        def fail(args):
            try:
                raise KeyError('missing score, test-secret-value')
            except KeyError as cause:
                error = RuntimeError('sandbox failed')
                error.stderr, error.exit_code = 'line 7: KeyError score test-secret-value', 1
                raise error from cause
        output = io.StringIO()
        with patch.dict(remote_worker.CONTEXT, error_reporting=tool_errors.__dict__, env={'key': 'test-secret-value'}), \
             patch.object(remote_worker, 'dispatch', side_effect=fail), \
             patch.object(remote_worker.sys, 'stdin', io.StringIO('{"op":"python"}\n')), \
             patch.object(remote_worker.sys, 'stdout', output):
            remote_worker.main()
        result = json.loads(output.getvalue())
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_details']['operation'], 'python')
        self.assertEqual(result['error_details']['causes'][0]['error_type'], 'KeyError')
        self.assertIn('line 7', result['error_details']['diagnostics']['stderr'])
        self.assertNotIn('test-secret-value', output.getvalue())


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    def context(self):
        return ToolContext(RunRequest('test', 'test', Principal('user')), emit=Mock(), disclosed={'probe'})

    def registry(self, handler, **kwargs):
        registry = DiagnosticToolRegistry()
        registry.register(name='probe', description='test', args_model=Args, handler=handler, **kwargs)
        return registry

    async def test_model_receives_details_and_can_correct_a_failed_tool_call(self):
        def handler(args, ctx):
            if args.value == 0:
                try:
                    raise KeyError('score')
                except KeyError as cause:
                    raise ValueError('value must be greater than zero') from cause
            return {'value': args.value}
        model = ScriptedModel([
            {'role': 'assistant', 'content': '', 'tool_calls': [call('probe', {'value': 0}, 'bad')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('probe', {'value': 1}, 'fixed')]},
            {'role': 'assistant', 'content': '1'},
        ])
        state = State()
        runtime = AgentRuntime(model=model, registry=self.registry(handler), state=state, output=Sink(), clock=Clock())
        answer = await runtime.run(RunRequest('calculate', 'test', Principal('u')))
        observation = json.loads(model.requests[1][-1]['content'])
        details = observation['data']['error_details']
        self.assertEqual(details['tool'], 'probe')
        self.assertEqual(details['error_type'], 'ValueError')
        self.assertEqual(details['causes'][0]['error_type'], 'KeyError')
        self.assertEqual(answer['text'], '1')
        events = [e for e in state.events if e['kind'] == 'tool.result']
        self.assertEqual([e['data']['result']['ok'] for e in events], [False, True])

    async def test_remote_diagnostics_are_used_instead_of_runtimeerror_wrapper(self):
        async def handler(args, ctx):
            raise RemoteToolError('website failed', {'phase': 'worker_dispatch', 'operation': 'kpl_query',
                'error_type': 'HTTPError', 'message': 'website failed', 'diagnostics': {'http_status': 429},
                'retryable': True})
        result = await execute(self.registry(handler), call('probe', {'value': 1}), self.context())
        self.assertEqual(result.data['error_details']['error_type'], 'HTTPError')
        self.assertEqual(result.data['error_details']['diagnostics']['http_status'], 429)

    async def test_read_deadline_is_diagnostic_and_write_deadline_blocks_replay(self):
        async def slow(args, ctx):
            await asyncio.sleep(1)
        for effect, code in [('read', 'TOOL_TIMEOUT'), ('write', 'OUTCOME_UNKNOWN')]:
            with self.subTest(effect=effect):
                ctx = self.context()
                result = await execute(self.registry(slow, timeout=.01, effect=effect), call('probe', {'value': 1}), ctx)
                self.assertEqual(result.code, code)
                self.assertIn('0.01', result.error)
                self.assertEqual(result.data['error_details']['diagnostics']['timeout_seconds'], .01)
                self.assertEqual('probe' in ctx.uncertain_tools, effect == 'write')

    async def test_lost_rpc_reply_never_replays_a_write(self):
        calls = []
        async def handler(args, ctx):
            calls.append(args)
            raise BridgeUnavailable('connection lost', error_details={'phase': 'rpc_transport',
                'error_type': 'EOFError', 'message': 'worker closed stdout', 'outcome_unknown': True})
        registry, ctx = self.registry(handler, effect='write'), self.context()
        first = await execute(registry, call('probe', {'value': 1}), ctx)
        second = await execute(registry, call('probe', {'value': 1}), ctx)
        self.assertEqual((first.code, second.code), ('OUTCOME_UNKNOWN', 'OUTCOME_UNKNOWN'))
        self.assertFalse(first.data['error_details']['retryable'])
        self.assertEqual(len(calls), 1)

    async def test_cancellation_propagates_without_becoming_tool_error(self):
        started = asyncio.Event()
        async def handler(args, ctx):
            started.set()
            await asyncio.sleep(1)
        task = asyncio.create_task(execute(self.registry(handler), call('probe', {'value': 1}), self.context()))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_reported_failure_retains_partial_rows_and_success_is_unchanged(self):
        partial = ToolResult(False, data={'observations': [{'ok': True, 'rows': [[1, 'https://example.com/report?year=2026']]}, {'ok': False, 'error': 'missing column'}]},
                             error='partial failure', code='PARTIAL_TOOL_ERROR')
        registry = self.registry(lambda args, ctx: partial)
        result = await execute(registry, call('probe', {'value': 1}), self.context())
        self.assertEqual(result.data['observations'][0]['rows'], [[1, 'https://example.com/report?year=2026']])
        self.assertEqual(result.code, 'PARTIAL_TOOL_ERROR')
        self.assertEqual(result.data['error_details']['phase'], 'tool_result')
        successful = {'value': 42}
        result = await execute(self.registry(lambda args, ctx: successful), call('probe', {'value': 1}), self.context())
        self.assertTrue(result.ok)
        self.assertIs(result.data, successful)


if __name__ == '__main__':
    unittest.main()

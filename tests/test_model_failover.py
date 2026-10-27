"""Availability failover preserves streaming, tool authorization and credentials."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from agent_console.provider import DeepSeekModel, ModelUnavailable, remote_model_options


def frame(delta=None, finish=None):
    return 'data: ' + json.dumps({'choices': [{'delta': delta or {}, 'finish_reason': finish}]}) + '\n\n'


class FailoverTests(unittest.IsolatedAsyncioTestCase):
    def model(self, **options):
        return DeepSeekModel(api_key='primary-secret', base_url='https://primary.invalid', model='primary',
                             first_token_timeout_seconds=.02, timeout_seconds=.1,
                             fallback={'api_key': 'backup-secret', 'base_url': 'https://backup.invalid/v1',
                                       'model': 'kimi-k3', 'vision_model': 'kimi-k3', 'protocol': 'bailian_kimi',
                                       'first_token_timeout_seconds': 1}, **options)

    async def run_model(self, handler, model=None, messages=None, tools=None, choice='auto'):
        original = httpx.AsyncClient
        deltas = []
        async def delta(kind, text):
            deltas.append((kind, text))
        with patch('agent_console.provider.httpx.AsyncClient', side_effect=lambda **kw: original(
                transport=httpx.MockTransport(handler), **kw)):
            result = await (model or self.model()).complete(messages or [{'role': 'user', 'content': 'hi'}],
                                                           tools or [], delta, tool_choice=choice)
        return result, deltas

    async def test_primary_success_never_contacts_backup(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, text=frame({'content': 'primary answer'}, 'stop'))
        result, _ = await self.run_model(respond)
        self.assertEqual(result['model'], 'primary')
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers['authorization'], 'Bearer primary-secret')

    async def test_availability_failures_use_only_backup_key_and_kimi_protocol(self):
        for status in (401, 403, 404, 408, 429, 500, 503):
            with self.subTest(status=status):
                requests = []
                def respond(request):
                    requests.append(request)
                    if request.url.host == 'primary.invalid':
                        return httpx.Response(status, text='unavailable')
                    return httpx.Response(200, text=frame({'reasoning_content': 'reason'}) + frame({'content': 'OK'}, 'stop'))
                result, deltas = await self.run_model(respond)
                self.assertEqual(result['message']['content'], 'OK')
                self.assertEqual(result['message']['reasoning_content'], 'reason')
                self.assertEqual(result['failover']['to_model'], 'kimi-k3')
                self.assertEqual(requests[1].headers['authorization'], 'Bearer backup-secret')
                body = json.loads(requests[1].content)
                self.assertNotIn('thinking', body)
                self.assertTrue(body['enable_thinking'])
                self.assertTrue(body['preserve_thinking'])
                self.assertNotIn('secret', json.dumps(result))

    async def test_keepalives_cannot_extend_first_token_deadline(self):
        class Keepalive(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    yield b': keepalive\n\n'
                    await asyncio.sleep(.005)
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, stream=Keepalive()) if len(requests) == 1 else httpx.Response(
                200, text=frame({'content': 'backup'}, 'stop'))
        result, _ = await self.run_model(respond)
        self.assertEqual(result['message']['content'], 'backup')
        self.assertEqual(result['failover']['reason'], 'TimeoutError')

    async def test_forced_tool_is_restricted_and_reasoning_history_preserved(self):
        bodies = []
        def respond(request):
            if request.url.host == 'primary.invalid':
                raise httpx.ConnectError('offline', request=request)
            bodies.append(json.loads(request.content))
            call = {'index': 0, 'id': 'c', 'function': {'name': 'allowed', 'arguments': '{}'}}
            return httpx.Response(200, text=frame({'reasoning_content': 'reason', 'tool_calls': [call]}, 'tool_calls'))
        tools = [{'type': 'function', 'function': {'name': name}} for name in ('allowed', 'other')]
        messages = [{'role': 'assistant', 'content': '', 'reasoning_content': 'earlier reasoning',
                     'tool_calls': [{'id': 'old'}]}, {'role': 'tool', 'tool_call_id': 'old', 'content': 'result'}]
        result, _ = await self.run_model(respond, tools=tools, messages=messages,
                                         choice={'type': 'function', 'function': {'name': 'allowed'}})
        self.assertEqual(bodies[0]['tool_choice'], 'required')
        self.assertEqual([t['function']['name'] for t in bodies[0]['tools']], ['allowed'])
        metadata = json.loads(bodies[0]['messages'][0]['content'].splitlines()[-1])['runtime_metadata']
        self.assertEqual(metadata['available_tool_count'], 1)
        self.assertEqual(metadata['message_count'], len(bodies[0]['messages']))
        assistant = next(message for message in bodies[0]['messages'] if message['role'] == 'assistant')
        self.assertEqual(assistant['reasoning_content'], 'earlier reasoning')
        self.assertEqual(result['message']['tool_calls'][0]['function']['name'], 'allowed')

    async def test_image_request_uses_backup_vision_model(self):
        bodies = []
        def respond(request):
            if request.url.host == 'primary.invalid':
                return httpx.Response(503)
            bodies.append(json.loads(request.content))
            return httpx.Response(200, text=frame({'content': 'image answer'}, 'stop'))
        messages = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test'}}]}]
        result, _ = await self.run_model(respond, messages=messages)
        self.assertEqual(bodies[0]['model'], 'kimi-k3')
        self.assertEqual([message for message in bodies[0]['messages'] if message['role'] != 'system'], messages)
        self.assertEqual(result['model'], 'kimi-k3')

    async def test_partial_output_does_not_restart_on_backup(self):
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield frame({'content': 'already delivered'}).encode()
                await asyncio.sleep(.09)
                yield frame({'content': 'more'}).encode()
                raise httpx.ReadError('broken stream')
        requests, deltas = [], []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, stream=Broken())
        async def delta(kind, text):
            deltas.append(text)
        original = httpx.AsyncClient
        with patch('agent_console.provider.httpx.AsyncClient', side_effect=lambda **kw: original(
                transport=httpx.MockTransport(respond), **kw)):
            with self.assertRaises(httpx.ReadError):
                await self.model().complete([{'role': 'user', 'content': 'hi'}], [], delta)
        self.assertTrue(deltas)
        self.assertEqual(len(requests), 1)

    async def test_cancellation_and_bad_request_never_switch_providers(self):
        for error in (asyncio.CancelledError(), ModelUnavailable('bad input', 400)):
            with self.subTest(error=type(error).__name__):
                with patch.object(DeepSeekModel, '_complete_once', side_effect=error) as call:
                    with self.assertRaises(type(error)):
                        await self.model().complete([], [], None)
                self.assertEqual(call.call_count, 1)

    def test_bootstrap_keeps_backup_key_in_private_settings(self):
        remote = {'public': {'model_options': {'fallback': {'model': 'kimi-k3', 'base_url': 'https://backup.invalid'}}},
                  'private': {'fallback_api_key': 'backup-secret'}}
        self.assertEqual(remote_model_options(remote)['fallback']['api_key'], 'backup-secret')
        self.assertNotIn('backup-secret', json.dumps(remote['public']))


if __name__ == '__main__':
    unittest.main()

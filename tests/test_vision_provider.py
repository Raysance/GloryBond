"""Dedicated vision requests keep their own endpoint, key and wire protocol."""

import copy
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from agent_console.image_inputs import ImageStore
from agent_console.provider import DeepSeekModel, ModelUnavailable, remote_model_options
from agent_runtime import AgentRuntime, ImageInput, Principal, RunRequest, ToolRegistry
from tests.test_agent_images import png
from tests.test_agent_runtime import Args, Clock, Sink, State


class VisionProviderTests(unittest.IsolatedAsyncioTestCase):
    def model(self, **options):
        return DeepSeekModel(
            api_key='text-secret', base_url='https://text.invalid', model='text-model',
            vision={'api_key': 'vision-secret', 'base_url': 'https://ark.invalid/api/v3',
                    'model': 'doubao-vision', 'protocol': 'ark', 'proxy_url': ''}, **options)

    def transport(self, handler):
        client = httpx.AsyncClient
        self.client_options = []
        def factory(**options):
            self.client_options.append(dict(options))
            options.pop('proxy', None)
            return client(transport=httpx.MockTransport(handler), **options)
        return patch('agent_console.provider.httpx.AsyncClient', side_effect=factory)

    async def test_current_history_and_tool_images_use_ark_while_text_keeps_its_provider(self):
        requests = []
        def respond(request):
            requests.append(request)
            frame = {'model': json.loads(request.content)['model'],
                     'choices': [{'delta': {'content': '红色'}, 'finish_reason': 'stop'}],
                     'usage': {'prompt_tokens': 1280, 'completion_tokens': 2, 'total_tokens': 1282}}
            return httpx.Response(200, text='data: ' + json.dumps(frame) + '\n\ndata: [DONE]\n\n')

        with tempfile.TemporaryDirectory() as directory:
            store = ImageStore(Path(directory))
            saved = store.save(png())
            part = store.inputs([saved['id']])[0].content_part()
            model = self.model(image_store=store, proxy_url='http://text-proxy.invalid:7890')
            current = [{'role': 'system', 'content': 'instructions'},
                       {'role': 'user', 'content': [part]}]
            tools = [{'type': 'function', 'function': {'name': 'read', 'parameters': {'type': 'object'}}}]
            call = {'id': 'one', 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}
            history = current + [{'role': 'assistant', 'content': '', 'reasoning_content': 'earlier reasoning',
                                  'tool_calls': [call]},
                                 {'role': 'tool', 'tool_call_id': 'one', 'content': 'tool result'},
                                 {'role': 'user', 'content': '再解释一下'}]
            original = copy.deepcopy(history)
            with self.transport(respond):
                first = await model.complete(current, [], AsyncMock())
                followup = await model.complete(history, tools, AsyncMock())
                await model.complete([{'role': 'user', 'content': '读取头像'},
                                      {'role': 'user', 'content': [part]}], tools, AsyncMock())
                await model.complete([{'role': 'user', 'content': 'hello'}], [], AsyncMock())
            self.assertEqual([r.url.host for r in requests], ['ark.invalid'] * 3 + ['text.invalid'])
            self.assertEqual([r.headers['authorization'] for r in requests],
                             ['Bearer vision-secret'] * 3 + ['Bearer text-secret'])
            self.assertEqual([options['proxy'] for options in self.client_options],
                             [None, None, None, 'http://text-proxy.invalid:7890'])
            self.assertTrue(all(options['trust_env'] is False for options in self.client_options))
            self.assertEqual(str(requests[0].url), 'https://ark.invalid/api/v3/chat/completions')
            body = json.loads(requests[1].content)
            self.assertEqual(body['model'], 'doubao-vision')
            self.assertEqual(body['tools'], tools)
            self.assertEqual(body['thinking'], {'type': 'enabled'})
            self.assertEqual(body['messages'][1]['content'][0]['image_url']['detail'], 'high')
            self.assertTrue(body['messages'][1]['content'][0]['image_url']['url'].startswith('data:image/png;base64,'))
            self.assertEqual(body['messages'][2]['reasoning_content'], 'earlier reasoning')
            self.assertEqual(history, original)
            self.assertEqual(followup['runtime_metadata']['protocol'], 'ark')
            self.assertEqual(followup['runtime_metadata']['message_count'], len(body['messages']))
            self.assertEqual(first['vision_context']['omitted_history_images'], 0)
            self.assertEqual(first['usage']['total_tokens'], 1282)

    async def test_missing_history_pixels_route_to_text_and_retain_omission_metadata(self):
        store = Mock()
        store.model_messages.return_value = ([{'role': 'user', 'content': '历史图片不可用'}],
                                             {'omitted_history_images': 1})
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, text='data: ' + json.dumps({
                'choices': [{'delta': {'content': '请重新附图'}, 'finish_reason': 'stop'}]}) + '\n\n')
        with self.transport(respond):
            result = await self.model(image_store=store).complete(
                [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'attachment://old'}}]}],
                [], AsyncMock())
        self.assertEqual(requests[0].url.host, 'text.invalid')
        self.assertEqual(result['vision_context'], {'omitted_history_images': 1})

    async def test_runtime_preserves_streamed_ark_ciphertext_through_a_real_tool_round(self):
        bodies = []
        def respond(request):
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                deltas = [({'reasoning_content': '需要计算', 'encrypted_content': 'cipher-'}, None),
                          ({'encrypted_content': 'exact', 'tool_calls': [
                              {'index': 0, 'id': 'one', 'type': 'function',
                               'function': {'name': 'double', 'arguments': '{"value":2}'}}]}, 'tool_calls')]
            else:
                deltas = [({'content': '结果为4'}, 'stop')]
            frames = [{'choices': [{'delta': delta, 'finish_reason': finish}]} for delta, finish in deltas]
            return httpx.Response(200, text=''.join('data: ' + json.dumps(frame) + '\n\n' for frame in frames))
        registry = ToolRegistry()
        registry.register(name='double', description='Double', args_model=Args,
                          handler=lambda args, ctx: {'value': args.value * 2})
        runtime = AgentRuntime(model=self.model(), registry=registry, state=State(), output=Sink(), clock=Clock())
        image = ImageInput('data:image/png;base64,' + base64.b64encode(png()).decode())
        with self.transport(respond):
            result = await runtime.run(RunRequest('计算图里的数量', 'vision', Principal('user'), images=(image,)))
        self.assertEqual(result['text'], '结果为4')
        self.assertEqual(len(bodies), 2)
        self.assertTrue(all(body['model'] == 'doubao-vision' for body in bodies))
        assistant = next(message for message in bodies[1]['messages'] if message['role'] == 'assistant')
        self.assertEqual(assistant['encrypted_content'], 'cipher-exact')
        self.assertEqual(assistant['reasoning_content'], '需要计算')
        self.assertTrue(any(message['role'] == 'tool' and '4' in message['content']
                            for message in bodies[1]['messages']))

    async def test_text_request_omits_ark_ciphertext_without_mutating_history(self):
        messages = [{'role': 'assistant', 'content': '上一轮图片回答', 'encrypted_content': 'cipher-exact'},
                    {'role': 'user', 'content': '继续聊天'}]
        original = copy.deepcopy(messages)
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, text='data: ' + json.dumps({
                'choices': [{'delta': {'content': '继续'}, 'finish_reason': 'stop'}]}) + '\n\n')
        with self.transport(respond):
            await self.model().complete(messages, [], AsyncMock())
        self.assertEqual(requests[0]['model'], 'text-model')
        self.assertNotIn('encrypted_content', json.dumps(requests[0]))
        self.assertEqual(messages, original)

    async def test_vision_failure_is_redacted_and_cannot_trigger_text_failover(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(404, text='ModelNotOpen vision-secret')
        with self.transport(respond), self.assertRaises(ModelUnavailable) as error:
            await self.model(fallback={'api_key': 'backup-secret', 'base_url': 'https://backup.invalid',
                                       'model': 'backup'}).complete([
                {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {
                    'url': 'data:image/png;base64,test'}}]}], [], AsyncMock())
        self.assertEqual([r.url.host for r in requests], ['ark.invalid'])
        self.assertNotIn('vision-secret', str(error.exception))
        self.assertIn('ModelNotOpen', str(error.exception))

    def test_remote_vision_key_stays_private_and_options_are_not_mutated(self):
        remote = {'public': {'model_options': {'vision': {'model': 'vision', 'base_url': 'https://ark.invalid'}}},
                  'private': {'vision_api_key': 'vision-secret'}}
        original = copy.deepcopy(remote)
        self.assertEqual(remote_model_options(remote)['vision']['api_key'], 'vision-secret')
        self.assertEqual(remote, original)

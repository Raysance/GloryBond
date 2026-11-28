"""The text agent decides when to read images; vision only returns descriptions."""
import asyncio
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from agent_runtime import AgentRuntime, ImageInput, Principal, RunRequest, ToolRegistry

from glorybond.agent.image_inputs import ImageStore
from glorybond.agent.image_reader import observe_image_event
from glorybond.agent.model_metadata import observe_model_event
from glorybond.agent.provider import DeepSeekModel, ModelUnavailable, remote_model_options
from glorybond.agent.tools.images import register_image_tool
from tests.test_agent_images import png
from tests.test_agent_runtime import Clock, Sink, State


class ObservingSink(Sink):
    async def publish(self, event):
        observe_model_event(event)
        await super().publish(event)


class VisionProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ImageStore(Path(self.directory.name) / 'images')
        self.saved = self.store.save(png())
        self.part = self.store.inputs([self.saved['id']])[0].content_part()
        observe_image_event({'kind': 'run.start', 'run_id': 'run'})
        self.addCleanup(observe_image_event, {'kind': 'run.end'})

    def model(self, **options):
        return DeepSeekModel(api_key='text-secret', base_url='https://text.invalid', model='text-model',
            image_store=self.store, vision={'api_key': 'vision-secret', 'base_url': 'https://ark.invalid/api/v3',
            'model': 'doubao-vision', 'protocol': 'ark', 'proxy_url': ''}, **options)

    def transport(self, handler):
        client = httpx.AsyncClient
        self.client_options = []
        def factory(**options):
            self.client_options.append(dict(options))
            options.pop('proxy', None)
            return client(transport=httpx.MockTransport(handler), **options)
        return patch('glorybond.agent.provider.httpx.AsyncClient', side_effect=factory)

    @staticmethod
    def response(body, *, content='图上有三个红色方块', calls=None, finish='stop'):
        delta = {'content': content} if calls is None else {'tool_calls': calls}
        frame = {'model': body['model'], 'choices': [{'delta': delta, 'finish_reason': finish}],
                 'usage': {'prompt_tokens': 1280, 'completion_tokens': 2, 'total_tokens': 1282}}
        return httpx.Response(200, text='data: ' + json.dumps(frame) + '\n\ndata: [DONE]\n\n')

    async def test_images_do_not_switch_main_model_or_start_vision_automatically(self):
        bodies = []
        def respond(request):
            body = json.loads(request.content); bodies.append(body)
            self.assertEqual(request.url.host, 'text.invalid')
            return self.response(body)
        model = self.model(proxy_url='http://text-proxy.invalid:7890')
        messages = [{'role': 'system', 'content': 'PRIVATE CHAT INSTRUCTIONS'},
                    {'role': 'user', 'content': [self.part]}]
        original = copy.deepcopy(messages)
        with self.transport(respond):
            result = await model.complete(messages, [], AsyncMock())
        self.assertEqual(result['model'], 'text-model')
        self.assertNotIn('image_url', json.dumps(bodies))
        self.assertNotIn('base64', json.dumps(bodies))
        self.assertIn(self.saved['id'], json.dumps(bodies))
        self.assertEqual(messages, original)
        self.assertFalse(result['vision_context']['image_pixels_in_main_context'])
        self.assertEqual(self.client_options[0]['proxy'], 'http://text-proxy.invalid:7890')

    async def test_runtime_tool_sends_only_pixels_to_vision_and_text_to_main(self):
        bodies = []
        def respond(request):
            body = json.loads(request.content); bodies.append(body)
            if request.url.host == 'ark.invalid':
                self.assertEqual(request.headers['authorization'], 'Bearer vision-secret')
                self.assertNotIn('tools', body)
                self.assertEqual(body['thinking'], {'type': 'disabled'})
                self.assertNotIn('PRIVATE CHAT INSTRUCTIONS', json.dumps(body))
                self.assertNotIn('runtime_metadata', json.dumps(body))
                self.assertNotIn('计算图里的数量', json.dumps(body, ensure_ascii=False))
                self.assertEqual(body['messages'][1]['content'][0]['image_url']['detail'], 'high')
                return self.response(body)
            self.assertNotIn('image_url', json.dumps(body))
            if len(bodies) == 1:
                return self.response(body, calls=[{'index': 0, 'id': 'read', 'type': 'function',
                    'function': {'name': 'read_image', 'arguments': json.dumps({'image_id': self.saved['id']})}}], finish='tool_calls')
            self.assertIn('三个红色方块', json.dumps(body, ensure_ascii=False))
            return self.response(body, content='有3个。')
        model = self.model()
        registry = ToolRegistry(); register_image_tool(registry, model.images)
        runtime = AgentRuntime(model=model, registry=registry, state=State(), output=ObservingSink(), clock=Clock())
        request = RunRequest('计算图里的数量', 's', Principal('u'), system_prompt='PRIVATE CHAT INSTRUCTIONS',
            required_tools=('read_image',), images=(ImageInput('attachment://' + self.saved['id']),))
        with self.transport(respond):
            result = await runtime.run(request)
        self.assertEqual(result['text'], '有3个。')
        self.assertEqual([b['model'] for b in bodies], ['text-model', 'doubao-vision', 'text-model'])

    async def test_history_tool_and_duplicate_images_keep_identity_and_cache_across_reload(self):
        model = self.model()
        original = [{'role': 'user', 'content': [self.part]}, {'role': 'assistant', 'content': '历史'},
                    {'role': 'tool', 'tool_call_id': 'c', 'content': json.dumps({'ok': True, 'data': {
                        'model_images': [self.part], 'source_message_id': '123'}})}]
        snapshot = copy.deepcopy(original)
        projected, _ = model.images.project(original)
        self.assertNotIn('image_url', json.dumps(projected))
        self.assertIn('123', projected[2]['content'])
        self.assertEqual(snapshot, original)
        requests = []
        def respond(request):
            requests.append(request); return self.response(json.loads(request.content))
        with self.transport(respond):
            results = await asyncio.gather(*(model.images.read(self.saved['id'], 'run') for _ in range(2)))
            reloaded = self.model(); reloaded.images.project(original)
            cached = await reloaded.images.read(self.saved['id'], 'run')
        self.assertEqual(len(requests), 1)
        self.assertEqual(sum(not r['cached'] for r in results), 1)
        self.assertTrue(cached['cached']); self.assertIsNone(cached['usage'])
        self.assertEqual(cached['description'], results[0]['description'])

    async def test_access_does_not_follow_an_id_into_another_run(self):
        model = self.model(); model.images.project([{'role': 'user', 'content': [self.part]}])
        with self.assertRaises(PermissionError):
            await model.images.read(self.saved['id'], 'other')
        observe_image_event({'kind': 'run.start', 'run_id': 'other'})
        with self.assertRaises(PermissionError):
            await model.images.read(self.saved['id'], 'other')

    async def test_urls_and_authorized_paths_share_preparation_and_reference_bytes(self):
        model = self.model(); reader = model.images
        root = Path(self.directory.name) / 'allowed'; root.mkdir()
        source = root / 'image.png'; source.write_bytes(png())
        reader.local_roots = (root.resolve(),)
        reader.fetcher = AsyncMock()
        reader.fetcher.download.return_value = {'raw': png()}
        local_id, local = await reader.reference(run_id='run', local_path=str(source))
        remote_id, remote = await reader.reference(run_id='run', url='https://public.invalid/image.png')
        self.assertEqual(local, remote)
        self.assertTrue(local.startswith('data:image/png;base64,'))
        self.assertNotEqual(local_id, remote_id)
        reader.fetcher.download.assert_awaited_once()
        outside = Path(self.directory.name) / 'private.png'; outside.write_bytes(png())
        (root / 'link.png').symlink_to(outside)
        for value in (str(outside), str(root / 'link.png'), 'relative.png'):
            with self.assertRaises((PermissionError, ValueError)):
                await reader.reference(run_id='run', local_path=value)

    async def test_vision_failure_is_redacted_and_not_cached_or_sent_to_text_fallback(self):
        requests = []
        def respond(request):
            requests.append(request); return httpx.Response(404, text='ModelNotOpen vision-secret')
        model = self.model(fallback={'api_key': 'backup-secret', 'base_url': 'https://backup.invalid', 'model': 'backup'})
        model.images.project([{'role': 'user', 'content': [self.part]}])
        with self.transport(respond):
            for _ in range(2):
                with self.assertRaises(ModelUnavailable) as error:
                    await model.images.read(self.saved['id'], 'run')
        self.assertEqual([r.url.host for r in requests], ['ark.invalid', 'ark.invalid'])
        self.assertNotIn('vision-secret', str(error.exception))

    async def test_partial_caption_is_not_cached(self):
        reader = self.model().images
        reader.project([{'role': 'user', 'content': [self.part]}])
        with self.transport(lambda r: self.response(json.loads(r.content), finish='length')):
            with self.assertRaises(ValueError):
                await reader.read(self.saved['id'], 'run')
        self.assertFalse(reader.cache)

    async def test_text_request_omits_ark_ciphertext_without_mutating_history(self):
        messages = [{'role': 'assistant', 'content': '旧图片回答', 'encrypted_content': 'cipher-exact'},
                    {'role': 'user', 'content': '继续聊天'}]
        original = copy.deepcopy(messages); bodies = []
        def respond(request):
            body = json.loads(request.content); bodies.append(body); return self.response(body)
        with self.transport(respond):
            await self.model().complete(messages, [], AsyncMock())
        self.assertNotIn('encrypted_content', json.dumps(bodies))
        self.assertEqual(messages, original)

    def test_remote_vision_key_stays_private_and_options_are_not_mutated(self):
        remote = {'public': {'model_options': {'vision': {'model': 'vision', 'base_url': 'https://ark.invalid'}}},
                  'private': {'vision_api_key': 'vision-secret'}}
        original = copy.deepcopy(remote)
        self.assertEqual(remote_model_options(remote)['vision']['api_key'], 'vision-secret')
        self.assertEqual(remote, original)

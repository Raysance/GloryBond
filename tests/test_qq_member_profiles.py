"""QQ-owned live profiles, authorization and native tool-image observations."""

import base64
from io import BytesIO
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from PIL import Image

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.provider import DeepSeekModel
from local_debugger import import_hok_module
from qq_agent.member_profiles import register_member_profile_tool
from qq_agent.service import QQAgentService, qq_principal
from tests.test_agent_runtime import Clock, Sink, State


PROFILES = import_hok_module('business.qq_profiles')
ADAPTER = import_hok_module('utils.qq_profiles')
API = import_hok_module('api_adapters.qq_profiles')
FUNCS = import_hok_module('zfunc')
RECORD = {'group_id': 200, 'user_id': 100, 'nickname': '昵称', 'card': '群名片',
          'role': 'admin', 'title': '群头衔', 'level': '7', 'age': 0, 'sex': 'unknown',
          'join_time': 123, 'last_sent_time': 456, 'title_expire_time': -1,
          'uid': 'private-uid', 'extra': 'not disclosed'}


def png():
    output = BytesIO()
    Image.new('RGB', (16, 16), 'red').save(output, 'PNG')
    return output.getvalue()


def tool_call(arguments=None):
    return {'id': 'profile-call', 'type': 'function', 'function': {
        'name': 'read_group_member_profile', 'arguments': json.dumps(arguments or {})}}


class QQReadTests(unittest.IsolatedAsyncioTestCase):
    def test_whitelist_and_unknown_values_do_not_fabricate_profile_fields(self):
        profile = PROFILES.normalize_group_member_profile(RECORD, '200', '100')
        self.assertEqual(profile['group_card'], '群名片')
        self.assertIsNone(profile['age'])
        self.assertIsNone(profile['sex'])
        self.assertTrue(profile['title_permanent'])
        self.assertEqual(profile['joined_at'], 123)
        self.assertNotIn('uid', profile)
        self.assertNotIn('extra', profile)
        with self.assertRaises(ValueError):
            PROFILES.normalize_group_member_profile(RECORD, '201', '100')

    async def test_native_lookup_verifies_membership_before_reading_fresh_profile(self):
        bot = Mock(get_group_member_list=AsyncMock(return_value=[RECORD]),
                   get_group_member_info=AsyncMock(return_value=RECORD))
        with patch.object(ADAPTER.nonebot, 'get_bot', return_value=bot):
            self.assertEqual(await ADAPTER.load_group_member_profile('200', '100'), RECORD)
            bot.get_group_member_info.assert_awaited_once_with(group_id=200, user_id=100, no_cache=True)
            with self.assertRaises(ValueError):
                await ADAPTER.load_group_member_profile('200', '999')
            self.assertEqual(bot.get_group_member_info.await_count, 1)

    async def test_avatar_failure_keeps_verified_text_and_no_avatar_read_for_nonmember(self):
        zapi = import_hok_module('zapi')
        with patch.object(ADAPTER, 'load_group_member_profile', AsyncMock(return_value=RECORD)), \
             patch.object(zapi, 'qq_avatar_bytes', side_effect=RuntimeError('unavailable')) as avatar:
            snapshot = await FUNCS.agent_read_group_member_profile(group_id='200', user_id='100')
            self.assertEqual(snapshot['profile']['group_card'], '群名片')
            self.assertIsNone(snapshot['avatar_bytes'])
            self.assertIn('头像读取失败', snapshot['avatar_error'])
            await FUNCS.agent_read_group_member_profile(group_id='200', user_id='100', include_avatar=False)
            self.assertEqual(avatar.call_count, 1)
        with patch.object(ADAPTER, 'load_group_member_profile', AsyncMock(side_effect=ValueError('not a member'))), \
             patch.object(zapi, 'qq_avatar_bytes') as avatar:
            with self.assertRaises(ValueError):
                await FUNCS.agent_read_group_member_profile(group_id='200', user_id='100')
            avatar.assert_not_called()

    def test_avatar_http_is_bounded_and_uses_configured_endpoint_without_proxy(self):
        session = Mock()
        response = Mock(status_code=200)
        response.iter_content.return_value = [b'ab', b'cd']
        session.get.return_value.__enter__ = Mock(return_value=response)
        session.get.return_value.__exit__ = Mock(return_value=False)
        config = {'avatar_endpoint': 'https://avatar.invalid/g', 'avatar_size': 640,
                  'timeout_seconds': 15, 'max_avatar_bytes': 3}
        with patch.object(API.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value = session
            with self.assertRaises(ValueError):
                API.qq_avatar_bytes('100', config=config)
        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with('https://avatar.invalid/g', params={'b': 'qq', 'nk': '100', 's': 640},
            timeout=15, stream=True, allow_redirects=False)


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = QQAgentService(root=self.tmp.name, config={}, admin_id='999',
            sender=None, prepare_reply=None, store_artifact=None, formatter=None)
        self.reader = AsyncMock(return_value={'profile': PROFILES.normalize_group_member_profile(RECORD, '200', '100'),
                                             'avatar_bytes': png()})
        self.registry = ToolRegistry()
        register_member_profile_tool(self.registry, reader=self.reader,
                                     store_image=self.service.store_tool_image, now=Clock().now)
        self.principal = Principal('100', frozenset({'qq.profile.read'}), {'chat': {'group_id': '200'}})

    def context(self, principal=None, **request):
        ctx = ToolContext(RunRequest('看看我的群资料和头像', 's', principal or self.principal, **request), AsyncMock())
        ctx.disclosed.add('read_group_member_profile')
        return ctx

    async def test_default_self_profile_and_native_image_reference(self):
        result = await execute(self.registry, tool_call(), self.context())
        self.assertTrue(result.ok)
        self.reader.assert_awaited_once_with(group_id='200', user_id='100', include_avatar=True)
        self.assertEqual(result.data['avatar']['status'], 'available')
        reference = result.data['model_images'][0]['image_url']['url']
        self.assertEqual(self.service.image_store.load(reference.removeprefix('attachment://'))[1], png())
        self.assertNotIn('avatar_bytes', result.data)

    async def test_cross_group_and_private_denied_before_backend(self):
        result = await execute(self.registry, tool_call({'group_id': '201'}), self.context())
        self.assertFalse(result.ok)
        ordinary = Principal('100', frozenset(), {'chat': {}})
        result = await execute(self.registry, tool_call({'group_id': '200'}), self.context(ordinary))
        self.assertEqual(result.code, 'PERMISSION_DENIED')
        self.reader.assert_not_awaited()
        self.assertNotIn('qq.profile.read', qq_principal('100', None, '', admin_id='999',
                                                       references={'context': {'catalogs': {}}}).scopes)

    async def test_admin_must_choose_one_group_and_reader_identity_must_match(self):
        admin = Principal('999', frozenset({'qq.profile.read', 'chat.cross_group'}), {'chat': {'all_groups': True}})
        self.assertFalse((await execute(self.registry, tool_call(), self.context(admin))).ok)
        self.reader.assert_not_awaited()
        self.assertTrue((await execute(self.registry, tool_call({'group_id': '200', 'user_id': '100'}), self.context(admin))).ok)
        self.reader.return_value['profile']['user_id'] = '101'
        self.assertFalse((await execute(self.registry, tool_call(), self.context())).ok)

    async def test_picture_budget_includes_current_quoted_images_and_keeps_text(self):
        from agent_console.image_inputs import ImageLimits
        self.service.image_store.limits = ImageLimits(max_images=1)
        saved = self.service.image_store.save(png())
        image = self.service.image_store.inputs([saved['id']])[0]
        ctx = self.context(context_messages=({'role': 'user', 'content': [image.content_part()]},))
        result = await execute(self.registry, tool_call(), ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.data['avatar']['status'], 'unavailable')
        self.assertEqual(result.data['profile']['nickname'], '昵称')
        self.assertNotIn('model_images', result.data)
        self.assertEqual(len(list(self.service.image_store.directory.glob('*.image'))), 1)

    def test_image_projection_waits_for_whole_tool_batch_and_ignores_failed_or_remote_images(self):
        saved = self.service.image_store.save(png())
        image = self.service.image_store.inputs([saved['id']])[0].content_part()
        messages = [
            {'role': 'assistant', 'content': '', 'tool_calls': [tool_call(), {**tool_call(), 'id': 'other'}]},
            {'role': 'tool', 'tool_call_id': 'profile-call', 'content': json.dumps({'ok': True, 'data': {'model_images': [image]}})},
            {'role': 'tool', 'tool_call_id': 'other', 'content': json.dumps({'ok': False, 'data': {'model_images': [image]}})},
        ]
        wire, _ = self.service.image_store.model_messages(messages)
        self.assertEqual([m['role'] for m in wire], ['assistant', 'tool', 'tool', 'user'])
        self.assertIn('profile-call', wire[-1]['content'][0]['text'])
        self.assertEqual(messages[-2]['role'], 'tool')
        wire, _ = self.service.image_store.model_messages([{'role': 'tool', 'content': json.dumps({
            'ok': True, 'data': {'model_images': [{'type': 'image_url', 'image_url': {'url': 'https://untrusted.invalid/image'}}]}
        })}])
        self.assertEqual(len(wire), 1)

    async def test_react_tool_observation_reaches_model_as_real_pixels_and_is_not_dialogue(self):
        observed = []
        def transport(request):
            payload = json.loads(request.content)
            observed.append(payload)
            delta = {'tool_calls': [{'index': 0, **tool_call()}]} if len(observed) == 1 else {'content': '资料已读取，头像是红色。'}
            frame = {'choices': [{'delta': delta, 'finish_reason': 'tool_calls' if len(observed) == 1 else 'stop'}]}
            return httpx.Response(200, text='data: ' + json.dumps(frame) + '\n\ndata: [DONE]\n\n')
        state, sink = State(), Sink()
        model = DeepSeekModel(api_key='test', base_url='https://model.invalid', model='text', vision_model='vision',
                              image_store=self.service.image_store)
        client = httpx.AsyncClient
        with patch('agent_console.provider.httpx.AsyncClient', side_effect=lambda **kw: client(transport=httpx.MockTransport(transport), **kw)):
            runtime = AgentRuntime(model=model, registry=self.registry, state=state, output=sink, clock=Clock())
            result = await runtime.run(RunRequest('我的资料和头像', 's', self.principal, required_tools=('read_group_member_profile',)))
        self.assertEqual(result['text'], '资料已读取，头像是红色。')
        self.assertEqual([item['model'] for item in observed], ['text', 'vision'])
        parts = observed[1]['messages'][-1]['content']
        image_url = parts[-1]['image_url']['url']
        self.assertEqual(base64.b64decode(image_url.split(',', 1)[1]), png())
        self.assertEqual(observed[1]['messages'][-2]['role'], 'tool')
        self.assertEqual(len(state.dialogue), 2)
        self.assertIsInstance(state.dialogue[0]['content'], str)
        self.assertEqual([e['kind'] for e in sink.events].count('tool.result'), 1)


if __name__ == '__main__':
    unittest.main()

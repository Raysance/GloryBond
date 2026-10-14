import base64
from io import BytesIO
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from agent_runtime import RunRequest
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.image_inputs import ImageStore
from agent_console.tools.diagnostics import DiagnosticToolRegistry
from agent_console.tools.application import register_application_tools
from local_debugger import import_hok_module
from qq_agent.avatar import register_bot_avatar_tool
from qq_agent.service import qq_principal

ADAPTER = import_hok_module('utils.qq_profiles')
FILES = import_hok_module('zfile')
FUNCS = import_hok_module('zfunc')


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ImageStore(self.tmp.name)
        output = BytesIO()
        Image.new('RGB', (16, 16), 'red').save(output, 'PNG')
        self.raw = output.getvalue()
        self.image = self.store.inputs([self.store.save(self.raw)['id']])[0]
        self.setter = AsyncMock(return_value={'bot_id': '300'})
        self.generated_reader = AsyncMock(return_value={'raw': self.raw, 'width': 16, 'height': 16})
        self.registry = DiagnosticToolRegistry()
        register_bot_avatar_tool(self.registry, setter=self.setter, image_store=self.store,
                                 generated_image_reader=self.generated_reader)

    def context(self, *, user='999', group=None, images=(), quoted=()):
        principal = qq_principal(user, group, '', admin_id='999', bot_id='300',
                                 references={'context': {'catalogs': {}}})
        ctx = ToolContext(RunRequest('把这张图设为你的头像', 's', principal,
                          images=images, context_messages=quoted), AsyncMock())
        ctx.disclosed.add('set_bot_avatar')
        return ctx

    async def call(self, ctx, args=None):
        return await execute(self.registry, {'id': 'avatar', 'type': 'function', 'function': {
            'name': 'set_bot_avatar', 'arguments': json.dumps(args or {})}}, ctx)

    async def test_admin_group_and_private_submit_exact_current_pixels(self):
        for group in (None, '200'):
            result = await self.call(self.context(group=group, images=(self.image,)))
            self.assertTrue(result.ok)
            self.assertTrue(result.data['submitted'])
            self.assertEqual(result.data['bot_id'], '300')
        self.setter.assert_awaited_with(self.raw)

    async def test_generate_then_set_avatar_uses_current_resource_and_saved_pixels(self):
        artifact_id = 'a' * 32
        service = Mock(generate_image=AsyncMock(return_value={'artifact_id': artifact_id, 'mime': 'image/png'}))
        register_application_tools(self.registry, service=service, catalogs={})
        ctx = self.context()
        ctx.disclosed.add('generate_image')

        async def emit(kind, data):
            if kind == 'output.artifact':
                FILES.store_agent_artifact(data['artifact_id'], self.raw)

        ctx.emit = emit
        self.generated_reader.side_effect = FUNCS.agent_read_generated_image
        with patch.object(FILES, 'temp_path', self.tmp.name):
            generated = await execute(self.registry, {'id': 'generate', 'type': 'function', 'function': {
                'name': 'generate_image', 'arguments': json.dumps({'prompt': '一只猫的QQ头像'})}}, ctx)
            self.assertTrue(generated.ok)
            resource_id = generated.data['image_resource_id']
            self.assertNotEqual(resource_id, artifact_id)
            changed = await self.call(ctx, {'image_resource_id': resource_id})
        self.assertTrue(changed.ok)
        self.assertEqual(changed.data['artifact_id'], artifact_id)
        self.generated_reader.assert_awaited_once_with(artifact_id)
        submitted = self.setter.await_args.args[0]
        with Image.open(BytesIO(submitted)) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    async def test_resources_from_other_run_wrong_kind_or_mixed_source_are_rejected(self):
        ctx = self.context(images=(self.image,))
        wrong = ctx.add_resource({'kind': 'dataset', 'artifact_id': 'a' * 32})
        generated = ctx.add_resource({'kind': 'generated_image', 'artifact_id': 'a' * 32})
        for args, context in (
            ({'image_resource_id': wrong}, ctx),
            ({'image_resource_id': generated}, self.context()),
            ({'image_resource_id': generated, 'image_index': 1}, ctx),
            ({'image_resource_id': 'b' * 32}, ctx),
        ):
            self.assertFalse((await self.call(context, args)).ok)
        self.generated_reader.assert_not_awaited()
        self.setter.assert_not_awaited()

    async def test_expired_or_failed_generated_image_never_changes_avatar(self):
        ctx = self.context()
        resource = ctx.add_resource({'kind': 'generated_image', 'artifact_id': 'a' * 32})
        self.generated_reader.side_effect = FileNotFoundError('generated image unavailable')
        result = await self.call(ctx, {'image_resource_id': resource})
        self.assertFalse(result.ok)
        self.setter.assert_not_awaited()

    async def test_failed_generation_does_not_publish_a_reusable_resource(self):
        service = Mock(generate_image=AsyncMock(side_effect=RuntimeError('generation failed')))
        register_application_tools(self.registry, service=service, catalogs={})
        ctx = self.context()
        ctx.disclosed.add('generate_image')
        result = await execute(self.registry, {'id': 'generate', 'type': 'function', 'function': {
            'name': 'generate_image', 'arguments': json.dumps({'prompt': '一只猫'})}}, ctx)
        self.assertFalse(result.ok)
        self.assertEqual(ctx.resources, {})
        self.setter.assert_not_awaited()

    async def test_current_then_quoted_images_and_duplicate_references(self):
        output = BytesIO()
        Image.new('RGB', (16, 16), 'blue').save(output, 'PNG')
        blue = output.getvalue()
        image = self.store.inputs([self.store.save(blue)['id']])[0]
        quote = ({'role': 'user', 'content': [self.image.content_part(), image.content_part()]},)
        result = await self.call(self.context(images=(self.image,), quoted=quote), {'image_index': 2})
        self.assertTrue(result.ok)
        self.setter.assert_awaited_once_with(blue)

    async def test_ordinary_users_denied_before_backend(self):
        for group in (None, '200'):
            result = await self.call(self.context(user='100', group=group, images=(self.image,)))
            self.assertEqual(result.code, 'PERMISSION_DENIED')
        self.setter.assert_not_awaited()

    async def test_missing_image_invalid_index_and_arbitrary_target_rejected(self):
        for args in ({}, {'image_index': 0}, {'image_index': True}, {'file': '/etc/passwd'},
                     {'user_id': '100'}, {'image_index': 2}):
            result = await self.call(self.context(), args)
            self.assertFalse(result.ok)
        self.setter.assert_not_awaited()

    async def test_backend_timeout_marks_outcome_unknown_and_blocks_replay(self):
        self.setter.side_effect = TimeoutError('connection timed out')
        ctx = self.context(images=(self.image,))
        result = await self.call(ctx)
        self.assertEqual(result.code, 'OUTCOME_UNKNOWN')
        self.assertIn('set_bot_avatar', ctx.uncertain_tools)
        self.assertFalse((await self.call(ctx)).ok)
        self.setter.assert_awaited_once()

    async def test_configured_bot_receives_base64_without_local_path(self):
        bot_id = str(ADAPTER.confs['QQBot']['bot_qid'])
        bot = Mock(self_id=bot_id, call_api=AsyncMock(return_value=None))
        with patch.object(ADAPTER.nonebot, 'get_bot', return_value=bot) as lookup:
            result = await ADAPTER.set_bot_avatar(self.raw)
        lookup.assert_called_once_with(bot_id)
        self.assertEqual(result, {'bot_id': bot_id})
        bot.call_api.assert_awaited_once_with('set_qq_avatar',
            file='base64://' + base64.b64encode(self.raw).decode('ascii'))

    async def test_wrong_bot_and_api_failure_never_report_success(self):
        bot = Mock(self_id='wrong', call_api=AsyncMock())
        with patch.object(ADAPTER.nonebot, 'get_bot', return_value=bot):
            with self.assertRaises(ValueError):
                await ADAPTER.set_bot_avatar(self.raw)
        bot.call_api.assert_not_awaited()
        self.setter.side_effect = RuntimeError('QQ rejected image')
        result = await self.call(self.context(images=(self.image,)))
        self.assertFalse(result.ok)
        self.assertIn('QQ rejected image', result.error)
        self.assertIn('error_details', result.data)

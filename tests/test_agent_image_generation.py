"""Slow image jobs keep reporting progress without submitting another job."""

import asyncio
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agent_runtime import Principal, RunRequest
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from glorybond.agent.capabilities import Capabilities
from glorybond.agent import remote_worker
from glorybond.agent.tasks import TaskScheduler, task_request
from glorybond.agent.timeouts import application_budget
from glorybond.agent.tools.application import register_application_tools
from glorybond.agent.tools.diagnostics import DiagnosticToolRegistry
from tests.test_agent_runtime import call


class ImageGenerationTests(unittest.IsolatedAsyncioTestCase):
    def test_gpt_reference_uses_documented_image_urls_wire_field(self):
        replies = [Mock(json=lambda: {'code': 200, 'data': [{'task_id': 'fixture'}]}),
                   Mock(json=lambda: {'code': 200, 'data': {'status': 'completed',
                        'result': {'images': [{'url': ['https://public.invalid/result.png']}]}}})]
        request = Mock(side_effect=replies)
        namespace = {'confs': {'QQBot': {'apimart_key': 'test-key'}},
                     'dmc': SimpleNamespace(EmojiImageModel='gpt-image-2'), 'clash_request': request}
        remote_worker.extracted_functions(Path(__file__).parents[1] / 'src/glorybond/integrations/ai.py',
                                         ['apimart_images_generate'], namespace)
        result = namespace['apimart_images_generate'](prompt='fixture',
            reference_image_url='data:image/png;base64,fixture', size='1:1', resolution='1K')
        payload = request.call_args_list[0].kwargs['json']
        self.assertEqual(payload['image_urls'], ['data:image/png;base64,fixture'])
        self.assertNotIn('image', payload)
        self.assertEqual(result['request']['image_urls'], payload['image_urls'])

    async def test_reference_is_prepared_once_and_forwarded_without_changing_generation(self):
        reader = SimpleNamespace(reference=AsyncMock(return_value=('a' * 32, 'data:image/png;base64,prepared')))
        service = Mock(generate_image=AsyncMock(return_value={'artifact_id': 'b' * 32, 'mime': 'image/png'}))
        registry = DiagnosticToolRegistry()
        register_application_tools(registry, service=service, catalogs={}, image_reader=reader)
        ctx = ToolContext(RunRequest('根据参考图画一张图', 's',
            Principal('u', frozenset({'image.generate', 'web.read'}))), AsyncMock())
        ctx.disclosed.add('generate_image')
        result = await execute(registry, call('generate_image', {
            'prompt': '保持参考图的构图', 'reference_image': {'url': 'https://public.invalid/image.png'}}), ctx)
        self.assertTrue(result.ok)
        reader.reference.assert_awaited_once_with(run_id=ctx.request.run_id, image_id=None,
            url='https://public.invalid/image.png', local_path=None)
        service.generate_image.assert_awaited_once_with('保持参考图的构图', '1:1',
            reference_image_url='data:image/png;base64,prepared', reference_image_id='a' * 32)

    async def test_worker_forwards_reference_and_keeps_pixels_out_of_result(self):
        generate = Mock(return_value={'url': 'https://public.invalid/generated.png',
                                     'request': {'image': 'data:image/png;base64,prepared'}})
        fetch = Mock(return_value=SimpleNamespace(content=b'image', headers={}, raise_for_status=lambda: None))
        async def dispatch(op, **args):
            return remote_worker.dispatch({'op': op, **args})
        with patch.dict(remote_worker.CONTEXT, {'store': Mock(), 'api': {
            'apimart_images_generate': generate, 'clash_request': fetch}}, clear=True):
            result = await Capabilities(Mock(call=dispatch)).generate_image('prompt', '1:1',
                reference_image_url='data:image/png;base64,prepared', reference_image_id='a' * 32)
        self.assertEqual(generate.call_args.kwargs['reference_image_url'], 'data:image/png;base64,prepared')
        self.assertEqual(result['request']['image'], 'attachment://' + 'a' * 32)

    def setup_tool(self, generate):
        self.service = Mock(generate_image=AsyncMock(side_effect=generate))
        self.registry = DiagnosticToolRegistry()
        register_application_tools(self.registry, service=self.service, catalogs={})
        self.events = []
        self.progress = asyncio.Event()

        async def emit(kind, data):
            self.events.append((kind, data))
            if sum(item[0] == "output.message" for item in self.events) >= 3:
                self.progress.set()

        self.ctx = ToolContext(RunRequest("画一张图", "s",
            Principal("100", scopes=frozenset({"image.generate"}))), emit)
        self.ctx.disclosed.add("generate_image")

    async def image_call(self):
        return await execute(self.registry, call("generate_image", {"prompt": "一只猫"}), self.ctx)

    async def test_slow_success_reports_repeated_progress_then_delivers_once(self):
        ready = asyncio.Event()

        async def generate(*args):
            await ready.wait()
            return {"artifact_id": "a" * 32, "mime": "image/png"}

        self.setup_tool(generate)
        with patch("glorybond.agent.tools.application.IMAGE_PROGRESS_INTERVAL_SECONDS", 0.01):
            pending = asyncio.create_task(self.image_call())
            await asyncio.wait_for(self.progress.wait(), 1)
            ready.set()
            result = await pending
            count = len(self.events)
            await asyncio.sleep(0.03)
        self.assertTrue(result.ok)
        self.assertEqual(len(self.events), count)
        self.assertEqual(sum(kind == "output.artifact" for kind, _ in self.events), 1)
        self.service.generate_image.assert_awaited_once()
        self.assertEqual(self.ctx.resource(result.data["image_resource_id"])["kind"], "generated_image")

    async def test_failure_stops_progress_and_unknown_outcome_cannot_resubmit(self):
        async def generate(*args):
            await self.progress.wait()
            raise TimeoutError("upstream timed out")

        self.setup_tool(generate)
        with patch("glorybond.agent.tools.application.IMAGE_PROGRESS_INTERVAL_SECONDS", 0.01):
            result = await self.image_call()
            count = len(self.events)
            await asyncio.sleep(0.03)
            again = await self.image_call()
        self.assertEqual(result.code, "OUTCOME_UNKNOWN")
        self.assertEqual(again.code, "OUTCOME_UNKNOWN")
        self.assertEqual(len(self.events), count)
        self.assertFalse(any(kind == "output.artifact" for kind, _ in self.events))
        self.service.generate_image.assert_awaited_once()

    async def test_cancellation_cleans_up_local_waiter_and_progress(self):
        stopped = asyncio.Event()

        async def generate(*args):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        self.setup_tool(generate)
        with patch("glorybond.agent.tools.application.IMAGE_PROGRESS_INTERVAL_SECONDS", 0.01):
            pending = asyncio.create_task(self.image_call())
            await asyncio.wait_for(self.progress.wait(), 1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            await asyncio.wait_for(stopped.wait(), 1)
            count = len(self.events)
            await asyncio.sleep(0.03)
        self.assertEqual(len(self.events), count)
        self.service.generate_image.assert_awaited_once()

    async def test_long_poll_budget_reaches_worker_and_background_budget_covers_it(self):
        generate = Mock(return_value={"url": "https://example.test/image", "request": {}})
        request = Mock(return_value=SimpleNamespace(content=b"image", headers={}, raise_for_status=lambda: None))

        async def dispatch(op, **args):
            return remote_worker.dispatch({"op": op, **args})

        with patch.dict(remote_worker.CONTEXT, {"store": Mock(), "api": {
            "apimart_images_generate": generate, "clash_request": request}}, clear=True):
            await Capabilities(Mock(call=dispatch)).generate_image("cat", "1:1")
        self.assertEqual(generate.call_args.kwargs["task_timeout_seconds"], 600)
        generate.assert_called_once()
        budget = application_budget()
        self.assertGreater(budget.timeout_seconds, self.registry_timeout())
        task = task_request({"principal": {"user_id": "100", "scopes": []}, "session_id": "s"})
        self.assertEqual(task.budget, budget)
        bridge = Mock(call=AsyncMock(return_value=[]))
        scheduler = TaskScheduler(runtime=None, bridge=bridge, state=None, output=None,
                                  clock=None, prompt_factory=None, budget=application_budget({"timeout_seconds": 1800}))
        await scheduler.tick()
        self.assertEqual(bridge.call.await_args.kwargs["lease_seconds"], 2100)

    def registry_timeout(self):
        registry = DiagnosticToolRegistry()
        register_application_tools(registry, service=Mock(), catalogs={})
        return registry.tools["generate_image"].timeout

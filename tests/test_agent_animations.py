"""Animated pixels reach the provider through a bounded, auditable PNG projection."""
import base64
from io import BytesIO
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

from agent_console.image_inputs import ImageLimits, ImageStore
from agent_console.provider import DeepSeekModel


def animation():
    frames = [Image.new("RGB", (24,16), color) for color in
              ["red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink"]]
    buffer = BytesIO()
    frames[0].save(buffer, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0, optimize=False)
    return buffer.getvalue()


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ImageStore(self.tmp.name)

    def test_sampling_preserves_original_and_records_exact_ordered_model_pixels(self):
        original = animation()
        saved = self.store.save(original, "QQ动态表情")
        image = self.store.inputs([saved["id"]])[0]
        messages = [{"role":"user", "content":[image.content_part()]}]
        wire, stats = self.store.model_messages(messages)
        self.assertEqual(messages[0]["content"][0]["image_url"]["url"], image.url)
        self.assertEqual(wire[0]["content"][0]["type"], "text")
        self.assertIn("原动画 8 帧", wire[0]["content"][0]["text"])
        source = wire[0]["content"][1]["image_url"]["url"]
        self.assertTrue(source.startswith("data:image/png;base64,"))
        pixels = base64.b64decode(source.split(",", 1)[1])
        with Image.open(BytesIO(pixels)) as sheet:
            colors = set(sheet.getdata())
            for color in [(255,0,0), (255,255,0), (0,0,255), (255,192,203)]:
                self.assertIn(color, colors)
        event = self.store.project_event({"kind":"model.response", "data":{"request_payload":{"messages":wire}}})
        reference = event["data"]["request_payload"]["messages"][0]["content"][1]["image_url"]["url"]
        self.assertNotEqual(reference, image.url)
        info, stored = self.store.load(reference.removeprefix("attachment://"))
        self.assertEqual(stored, pixels)
        self.assertEqual(info["projection"]["sampled_frames"], [0,2,5,7])
        self.assertEqual(info["projection"]["source_image_id"], saved["id"])
        self.assertEqual(self.store.load(saved["id"])[1], original)
        self.assertEqual(stats["image_bytes"], len(pixels))
        second, _ = self.store.model_messages(messages)
        self.assertEqual(second, wire)

    def test_animation_limits_and_older_metadata_are_handled(self):
        limited = ImageStore(self.tmp.name, ImageLimits(max_animation_frames=4))
        with self.assertRaisesRegex(ValueError, "帧数"):
            limited.save(animation())
        saved = self.store.save(animation())
        metadata = self.store._path(saved["id"], ".json")
        info = json.loads(metadata.read_text())
        info.pop("frames")
        metadata.write_text(json.dumps(info))
        reopened = ImageStore(self.tmp.name)
        wire, _ = reopened.model_messages([{"role":"user", "content":[self.store.inputs([saved["id"]])[0].content_part()]}])
        self.assertTrue(wire[0]["content"][1]["image_url"]["url"].startswith("data:image/png;"))


class AnimationProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_vision_provider_receives_png_frames_instead_of_a_single_gif(self):
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"颜色在变化"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        client_type = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as directory:
            store = ImageStore(directory)
            saved = store.save(animation())
            model = DeepSeekModel(api_key="test", base_url="https://example.invalid", model="text",
                                  vision_model="deepseek-v4-flash", image_store=store)
            with patch("agent_console.provider.httpx.AsyncClient", side_effect=lambda **kw: client_type(transport=httpx.MockTransport(respond), **kw)):
                await model.complete([{"role":"user", "content":[store.inputs([saved["id"]])[0].content_part()]}], [], AsyncMock())
        self.assertEqual(requests[0]["model"], "deepseek-v4-flash")
        self.assertTrue(requests[0]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;"))

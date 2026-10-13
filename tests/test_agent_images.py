"""Native multimodal context, local uploads and wire protocol contracts."""

import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from agent_runtime import AgentRuntime, ImageInput, Principal, RunRequest, ToolRegistry
from agent_console.image_inputs import ImageLimits, ImageStore
from agent_console.provider import DeepSeekModel
from agent_console.server import create_app
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, Args, call


def png(color="red", size=(24, 16)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


class RuntimeImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_survives_tools_persistence_and_followup(self):
        model = ScriptedModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [call("double", {"value": 2})],
                },
                {"role": "assistant", "content": "图片里有两个物体"},
                {"role": "assistant", "content": "上一张图片里的物体是红色"},
            ]
        )
        state, sink, registry = State(), Sink(), ToolRegistry()
        registry.register(
            name="double",
            description="double",
            args_model=Args,
            handler=lambda args, ctx: {"value": args.value * 2},
        )
        runtime = AgentRuntime(
            model=model, state=state, output=sink, registry=registry, clock=Clock()
        )
        image = ImageInput(
            "data:image/png;base64," + base64.b64encode(png()).decode(), "测试.png"
        )
        request = RunRequest("数一数", "session", Principal("user"), images=(image,))
        result = await runtime.run(request)
        self.assertIn("两个", result["text"])
        for messages in model.requests:
            user = next(m for m in messages if m["role"] == "user")
            self.assertEqual(user["content"][1], image.content_part())
        self.assertEqual(state.dialogue[0]["content"][1], image.content_part())
        await runtime.run(RunRequest("它们什么颜色", "session", Principal("user")))
        self.assertEqual(model.requests[-1][1]["content"][1], image.content_part())
        starts = [e for e in state.events if e["kind"] == "run.start"]
        self.assertEqual(starts[0]["data"]["images"][0]["name"], "测试.png")
        self.assertNotIn("images", starts[1]["data"])
        self.assertEqual(state.dialogue[-2]["content"], "它们什么颜色")

    async def test_image_only_input_is_native_and_not_a_text_placeholder(self):
        model = ScriptedModel([{"role": "assistant", "content": "图片已读取"}])
        state = State()
        runtime = AgentRuntime(
            model=model,
            state=state,
            output=Sink(),
            registry=ToolRegistry(),
            clock=Clock(),
        )
        image = ImageInput("https://example.org/image.png", detail="original")
        await runtime.run(RunRequest("", "s", Principal("u"), images=[image]))
        self.assertEqual(model.requests[0][-1]["content"], [image.content_part()])
        self.assertEqual(state.dialogue[0]["content"], [image.content_part()])

    def test_bad_input_contract_is_rejected_without_io(self):
        with self.assertRaises(ValueError):
            ImageInput("")
        with self.assertRaises(ValueError):
            ImageInput("https://example.org/a.png", detail="invalid")
        with self.assertRaises(TypeError):
            RunRequest("x", "s", Principal("u"), images=("image.png",))


class ImageStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ImageStore(Path(self.tmp.name))

    def test_sniffing_recovery_and_exact_blob_trace_references(self):
        raw = png()
        saved = self.store.save(raw, "../../假名字.jpg")
        self.assertEqual(saved["mime"], "image/png")
        self.assertEqual(saved["name"], "假名字.jpg")
        reopened = ImageStore(self.tmp.name)
        self.assertEqual(reopened.load(saved["id"])[1], raw)
        image = reopened.inputs([saved["id"]])[0]
        original = [{"role": "user", "content": [image.content_part()]}]
        wire, context = reopened.model_messages(original)
        self.assertEqual(original[0]["content"][0]["image_url"]["url"], image.url)
        self.assertEqual(
            base64.b64decode(
                wire[0]["content"][0]["image_url"]["url"].split(",", 1)[1]
            ),
            raw,
        )
        event = {
            "kind": "model.response",
            "data": {"request_payload": {"messages": wire}},
        }
        projected = reopened.project_event(event)
        self.assertEqual(projected["data"]["request_payload"]["messages"], original)
        self.assertIn("image_payload_storage", projected["data"])
        self.assertTrue(
            event["data"]["request_payload"]["messages"][0]["content"][0]["image_url"][
                "url"
            ].startswith("data:")
        )
        self.assertEqual(context["omitted_history_images"], 0)

    def test_invalid_files_paths_corrupt_blobs_and_limits_are_rejected(self):
        for raw in [
            b"",
            b"not a picture",
            b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.store.save(raw, "valid.png")
        with self.assertRaises(ValueError):
            self.store.load("../config.yaml")
        saved = self.store.save(png())
        self.store._path(saved["id"], ".image").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.store.load(saved["id"])
        limited = ImageStore(self.tmp.name, ImageLimits(max_image_bytes=10))
        with self.assertRaises(ValueError):
            limited.save(png())
        limited = ImageStore(self.tmp.name, ImageLimits(max_side=10))
        with self.assertRaises(ValueError):
            limited.save(png())

    def test_context_budget_keeps_current_images_and_notices_omitted_history(self):
        raw = png()
        store = ImageStore(
            self.tmp.name,
            ImageLimits(
                max_images=1, max_total_bytes=len(raw), max_context_bytes=len(raw)
            ),
        )
        old, new = store.save(raw), store.save(raw)
        older = store.inputs([old["id"]])[0]
        current = store.inputs([new["id"]])[0]
        messages = [
            {"role": "user", "content": [older.content_part()]},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": [current.content_part()]},
        ]
        wire, context = store.model_messages(messages)
        self.assertEqual(wire[0]["content"][0]["type"], "text")
        self.assertIn("未提供其像素", wire[0]["content"][0]["text"])
        self.assertEqual(wire[-1]["content"][0]["type"], "image_url")
        self.assertEqual(context["omitted_history_images"], 1)
        with self.assertRaises(ValueError):
            store.inputs([old["id"], new["id"]])
        with self.assertRaises(ValueError):
            self.store.inputs([old["id"], old["id"]])


class ImageAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ImageStore(self.tmp.name, ImageLimits(max_image_bytes=1024))
        with patch("agent_console.server.ImageStore", return_value=self.store):
            self.app = create_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.client.get("/")

    def upload(self, data=None):
        return self.client.post(
            "/api/images?name=test.png",
            content=data if data is not None else png(),
            headers={"X-Local-UI": "1", "Content-Type": "image/png"},
        )

    def test_upload_download_and_authentication(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        downloaded = self.client.get(response.json()["url"])
        self.assertEqual(downloaded.content, png())
        self.assertEqual(downloaded.headers["content-type"], "image/png")
        self.assertEqual(
            self.client.post("/api/images", content=png()).status_code, 403
        )

    def test_invalid_oversized_and_unknown_input_rejected(self):
        self.assertEqual(self.upload(b"not a PNG").status_code, 422)
        self.assertEqual(self.upload(b"x" * 1025).status_code, 413)
        self.assertEqual(self.client.get("/api/images/" + "f" * 32).status_code, 404)
        self.assertEqual(
            self.client.post(
                "/api/chat",
                json={"session_id": "s", "message": "", "image_ids": []},
                headers={"X-Local-UI": "1"},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/api/chat",
                json={"session_id": "s", "image_ids": ["f" * 32]},
                headers={"X-Local-UI": "1"},
            ).status_code,
            422,
        )

    def test_image_only_request_reaches_runtime_as_native_attachment(self):
        image = self.upload().json()
        request_holder = []
        run_task = Mock()
        runtime = Mock(active={"accepted-run": run_task})
        runtime.submit.side_effect = lambda req: (
            request_holder.append(req) or "accepted-run"
        )
        self.app.state.runtime = runtime
        self.app.state.local_log = Mock(record=AsyncMock())
        self.app.state.principal = Principal("u")
        self.app.state.current_prompt = AsyncMock(return_value="test prompt")
        self.app.state.roles = Mock(
            manage=AsyncMock(return_value={"selected": {"name": "test"}})
        )
        response = self.client.post(
            "/api/chat",
            json={"session_id": "s", "image_ids": [image["id"]]},
            headers={"X-Local-UI": "1"},
        )
        self.assertEqual(response.status_code, 200)
        request = request_holder[0]
        self.assertEqual(request.images[0].url, "attachment://" + image["id"])
        self.assertEqual(request.user_message, "请分析这些图片。")
        run_task.add_done_callback.assert_called_once()


class ProviderImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_protocol_selects_vision_for_current_and_historical_images(
        self,
    ):
        observed = []

        def transport(request):
            payload = json.loads(request.content)
            observed.append(payload)
            frame = {
                "choices": [{"delta": {"content": "红色"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 2,
                    "total_tokens": 102,
                },
            }
            return httpx.Response(
                200, text="data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n"
            )

        client_type = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as directory:
            store = ImageStore(directory)
            saved = store.save(png())
            image = store.inputs([saved["id"]])[0]
            model = DeepSeekModel(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="text-model",
                vision_model="deepseek-v4-flash",
                image_store=store,
            )
            factory = lambda **kw: client_type(
                transport=httpx.MockTransport(transport), **kw
            )
            with patch("agent_console.provider.httpx.AsyncClient", side_effect=factory):
                delta = AsyncMock()
                current = [{"role": "user", "content": [image.content_part()]}]
                result = await model.complete(current, [], delta)
                await model.complete(
                    current
                    + [
                        {"role": "assistant", "content": "红色"},
                        {"role": "user", "content": "为什么"},
                    ],
                    [],
                    delta,
                )
                await model.complete([{"role": "user", "content": "hello"}], [], delta)
            self.assertEqual(
                [p["model"] for p in observed],
                ["deepseek-v4-flash", "deepseek-v4-flash", "text-model"],
            )
            self.assertTrue(
                observed[0]["messages"][0]["content"][0]["image_url"]["url"].startswith(
                    "data:image/png;base64,"
                )
            )
            self.assertEqual(current[0]["content"][0]["image_url"]["url"], image.url)
            self.assertEqual(result["usage"]["total_tokens"], 102)
            self.assertEqual(result["message"]["content"], "红色")
            self.assertEqual(result["model"], "deepseek-v4-flash")
            delta.assert_awaited()


if __name__ == "__main__":
    unittest.main()

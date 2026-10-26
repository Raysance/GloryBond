"""Rule media stays bound to current QQ input and retains original pixels."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import unquote, urlparse

from PIL import Image
from agent_runtime import RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.image_inputs import ImageStore
from local_debugger import import_hok_module
from qq_agent.automation import register_automation_tools
from tests.test_agent_animations import animation
from tests.test_automation import principal, definition


FILES = import_hok_module("zfile")
FUNCS = import_hok_module("zfunc")
BUSINESS = import_hok_module("business.automation")
with patch("nonebot.get_driver", return_value=Mock()):
    SENDER = import_hok_module("utils.message_sender")


def media_definition(arguments, **changes):
    return definition(action={"type": "send_media", "arguments": arguments}, **changes)


class MediaToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ImageStore(Path(self.tmp.name) / "inputs")
        self.original = animation()
        saved = self.store.save(self.original)
        self.image_id = saved["id"]
        self.sources = [{"kind": "face", "face_id": "14", "source": "message"},
                        {"kind": "image", "image_id": self.image_id, "source": "quote", "animated": True}]
        self.backend = AsyncMock(return_value={"actions": BUSINESS.build_actions().describe({"automation.use"})})
        self.storer = Mock(side_effect=FILES.store_automation_media)
        self.registry = ToolRegistry()
        register_automation_tools(self.registry, operation=self.backend, image_store=self.store, media_storer=self.storer)
        data_patch = patch.object(FILES, "data_root", self.tmp.name)
        data_patch.start()
        self.addCleanup(data_patch.stop)

    def context(self, sources=None, **metadata):
        ctx = ToolContext(RunRequest("他发话之后发这个表情", "qq_g_200_100", principal(),
            metadata={"automation_media": self.sources if sources is None else sources, **metadata}), AsyncMock())
        ctx.disclosed = set(self.registry.tools)
        return ctx

    async def call(self, ctx, name, args):
        return await execute(self.registry, {"id": name, "function": {"name": name, "arguments": json.dumps(args)}}, ctx)

    async def disclose(self, ctx):
        result = await self.call(ctx, "list_automation_actions", {})
        self.assertTrue(result.ok)
        return result.data

    async def save(self, ctx, arguments, **args):
        return await self.call(ctx, "save_automation_rule", {"definition": media_definition(arguments), **args})

    async def test_catalog_exposes_current_indices_and_no_persisted_ids_or_paths(self):
        result = await self.disclose(self.context())
        self.assertEqual(result["input_media"][1], {"media_index": 2, "kind": "image", "source": "quote", "animated": True})
        self.assertNotIn(self.image_id, json.dumps(result))
        params = next(x["parameters"] for x in result["actions"] if x["type"] == "send_media")
        self.assertEqual(set(params["properties"]), {"media_index"})
        self.assertFalse(params["additionalProperties"])

    async def test_native_face_is_bound_by_index_and_forged_sources_are_rejected(self):
        ctx = self.context()
        self.assertFalse((await self.save(ctx, {"media_index": 1})).ok)
        await self.disclose(ctx)
        self.assertTrue((await self.save(ctx, {"media_index": 1})).ok)
        sent = self.backend.await_args.args[1]["definition"]["action"]["arguments"]
        self.assertEqual(sent, {"kind": "face", "id": "14", "animated": False})
        self.storer.assert_not_called()
        self.backend.reset_mock()
        for arguments in ({"media_index": 3}, {"media_index": True}, {"id": "66", "kind": "face"},
                          {"url": "https://example.invalid/image"}, {"path": "/tmp/other.gif"}, {}):
            self.assertFalse((await self.save(ctx, arguments)).ok)
        self.backend.assert_not_awaited()

    async def test_quoted_animation_is_copied_once_and_survives_input_removal(self):
        ctx = self.context()
        await self.disclose(ctx)
        for _ in range(2):
            self.assertTrue((await self.save(ctx, {"media_index": 2})).ok)
        self.storer.assert_called_once_with(self.original)
        asset = self.backend.await_args.args[1]["definition"]["action"]["arguments"]
        self.assertTrue(asset["animated"])
        self.store._path(self.image_id, ".image").unlink()
        path = Path(unquote(urlparse(FILES.automation_media_uri(asset["id"])).path))
        self.assertEqual(path.read_bytes(), self.original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with Image.open(path) as image:
            self.assertEqual(image.n_frames, 8)
        public = FUNCS._automation_public({"id": "rule", "owner_id": "100", "definition": media_definition(asset)})
        self.assertEqual(public["creator"]["user_id"], "100")
        self.assertEqual(public["definition"]["action"]["arguments"], {})
        self.assertEqual(public["media"], {"kind": "image", "animated": True})
        self.assertNotIn(asset["id"], json.dumps(public))

    async def test_new_run_background_and_bad_media_never_persist_or_save_rule(self):
        ctx = self.context(sources=[])
        await self.disclose(ctx)
        self.assertFalse((await self.save(ctx, {"media_index": 2})).ok)
        background = self.context(origin="background")
        background._automation_actions_described = {"send_media"}
        self.assertFalse((await self.save(background, {"media_index": 2})).ok)
        ctx = self.context()
        await self.disclose(ctx)
        self.store._path(self.image_id, ".image").write_bytes(b"corrupted")
        self.backend.reset_mock()
        self.assertFalse((await self.save(ctx, {"media_index": 2})).ok)
        self.storer.assert_not_called()
        self.backend.assert_not_awaited()

    async def test_existing_media_can_be_retained_for_edit_without_new_input(self):
        ctx = self.context(sources=[])
        await self.disclose(ctx)
        self.assertTrue((await self.save(ctx, {}, rule_id="a" * 32)).ok)
        self.assertEqual(self.backend.await_args.args[1]["definition"]["action"]["arguments"], {})
        self.storer.assert_not_called()


class MediaDeliveryTests(unittest.TestCase):
    def test_native_face_and_gif_use_trusted_queue_and_original_asset(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(FILES, "data_root", directory):
            image = FILES.store_automation_media(animation())
            for scope, asset in (("group:200", {"kind": "face", "id": "14"}), ("private:100", image)):
                job = {"id": "job", "rule": {"scope": scope, "owner_id": "100"}}
                with patch.object(FUNCS, "automation_enqueue_action", return_value=1) as enqueue:
                    SENDER.add_automation_media(job, asset)
                payload = enqueue.call_args.args[1]
                self.assertEqual(payload["type"] + ":" + str(payload["toid"]), scope)
                self.assertEqual(payload["automation_executions"], ["job"])
                segment = SENDER.Message(payload["content"])[0]
                self.assertEqual(segment.type, asset["kind"])
                self.assertNotIn("[CQ:at", payload["content"])
                if asset["kind"] == "image":
                    self.assertEqual(Path(unquote(urlparse(segment.data["file"]).path)).read_bytes(), animation())
                else:
                    self.assertEqual(str(segment.data["id"]), "14")

    def test_invalid_missing_and_changed_assets_fail_before_enqueue(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(FILES, "data_root", directory), \
                patch.object(FUNCS, "automation_enqueue_action") as enqueue:
            for asset in ({"kind": "image", "id": "../other"}, {"kind": "image", "id": "a" * 32},
                          {"kind": "face", "id": "[CQ:at,qq=all]"}):
                with self.assertRaises(ValueError):
                    SENDER.add_automation_media({"id": "job", "rule": {"scope": "group:200"}}, asset)
            asset = FILES.store_automation_media(animation())
            store = FILES._automation_media_store()
            store._path(asset["id"], ".image").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                FILES.automation_media_uri(asset["id"])
            enqueue.assert_not_called()

    def test_static_images_and_invalid_bytes_use_existing_input_limits(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(FILES, "data_root", directory):
            image = BytesIO()
            Image.new("RGB", (16, 16), "red").save(image, "PNG")
            asset = FILES.store_automation_media(image.getvalue())
            self.assertFalse(asset["animated"])
            path = Path(unquote(urlparse(FILES.automation_media_uri(asset["id"])).path))
            self.assertEqual(path.read_bytes(), image.getvalue())
            with self.assertRaises(ValueError):
                FILES.store_automation_media(b"not an image")

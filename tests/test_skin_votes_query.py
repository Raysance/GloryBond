import ast
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import ImageDraw

from local_debugger import import_hok_module


BUSINESS = import_hok_module("business.skin_votes")
API = import_hok_module("api_adapters.tianyuanzhiyi")
RENDER = import_hok_module("tools.gen_skin_votes")
ZFILE = import_hok_module("zfile")
ZFUNC = import_hok_module("zfunc")
HANDLER = import_hok_module("event_handlers.skin_votes")


def payload():
    return {"success": True, "updatedAt": "2026-10-16T03:27:22Z",
            "times": ["2026-10-16T01:00:00Z", "2026-10-16T02:00:00Z", "2026-10-16T03:00:00Z"],
            "series": [
                {"skinId": i, "heroName": f"英雄{i}", "skinName": f"皮肤{i}",
                 "latestRank": i, "latestVotes": 1000000 - i * 10000,
                 "latestAddNum": 123 - i, "votes": [900000 - i * 10000, None, 1000000 - i * 10000]}
                for i in range(1, 13)]}


class SkinVotesTests(unittest.TestCase):
    def test_normalizes_published_ranks_nulls_growth_and_beijing_time(self):
        data = payload()
        data["series"].reverse()
        result = BUSINESS.normalize_skin_votes(data)
        self.assertEqual(result["updated"], "2026-10-16 11:27:22")
        self.assertEqual(result["rows"][0]["rank"], 1)
        self.assertEqual(result["rows"][0]["history"], [890000, None, 990000])
        self.assertEqual(result["rows"][0]["growth"], 100000)
        self.assertIsNone(result["rows"][0]["gap"])
        self.assertEqual(result["rows"][1]["gap"], 10000)

    def test_unknown_latest_values_stay_unknown(self):
        data = payload()
        data["series"][0].update(latestVotes=None, latestRank=None, latestAddNum=None)
        row = BUSINESS.normalize_skin_votes(data)["rows"][-1]
        self.assertIsNone(row["votes"])
        self.assertIsNone(row["rank"])
        self.assertIsNone(row["growth"])
        self.assertIsNone(row["gap"])

    def test_rejects_malformed_snapshots_instead_of_fabricating_a_ranking(self):
        variants = []
        for field, value in (("latestVotes", -1), ("latestVotes", float("nan")),
                             ("latestVotes", True), ("latestRank", 1.5), ("votes", [1])):
            data = payload()
            data["series"][0][field] = value
            variants.append(data)
        data = payload()
        data["series"][1]["skinId"] = 1
        variants.append(data)
        data = payload()
        data["times"].reverse()
        variants.append(data)
        variants.append({"success": False})
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ValueError):
                BUSINESS.normalize_skin_votes(data)

    def test_query_text_top_five_and_image_top_ten_share_one_snapshot(self):
        with patch.object(BUSINESS.zapi, "tianyuanzhiyi_skin_votes_api", return_value=payload()) as api, \
             patch.object(BUSINESS.zapi, "tianyuanzhiyi_skin_icons_api", return_value={}) as icons, \
             patch.object(RENDER, "render_skin_votes_image", return_value=object()) as render, \
             patch.object(ZFILE, "save_skin_votes_image", return_value="/tmp/skin.png"):
            result = ZFUNC.skin_votes_query_process()
        api.assert_called_once()
        self.assertEqual(len(icons.call_args.args[0]), 10)
        self.assertEqual(len(render.call_args.args[1]), 10)
        self.assertIn("1. 英雄1·皮肤1  990,000票", result["text"])
        self.assertIn("5. 英雄5·皮肤5", result["text"])
        self.assertNotIn("6. 英雄6", result["text"])
        for value in ("来源", "tianyuanzhiyi", "91m.top", "天元之弈"):
            self.assertNotIn(value, result["text"])
        self.assertEqual(result["image_path"], "/tmp/skin.png")

    def test_empty_data_does_not_render_an_image(self):
        with patch.object(BUSINESS.zapi, "tianyuanzhiyi_skin_votes_api",
                          return_value={"success": True, "times": [], "series": []}), \
             patch.object(RENDER, "render_skin_votes_image") as render:
            result = ZFUNC.skin_votes_query_process()
        self.assertIn("暂无榜单", result["text"])
        self.assertIsNone(result["image_path"])
        render.assert_not_called()

    def test_image_failure_keeps_successful_text_ranking(self):
        with patch.object(BUSINESS.zapi, "tianyuanzhiyi_skin_votes_api", return_value=payload()), \
             patch.object(BUSINESS.zapi, "tianyuanzhiyi_skin_icons_api", return_value={}), \
             patch.object(RENDER, "render_skin_votes_image", side_effect=ValueError("bad font")):
            result = ZFUNC.skin_votes_query_process()
        self.assertIn("990,000票", result["text"])
        self.assertIn("图片生成失败", result["text"])
        self.assertIsNone(result["image_path"])

    def test_renderer_handles_missing_icons_points_and_single_timestamp_without_source_labels(self):
        drawn = []
        original = ImageDraw.ImageDraw.text

        def record(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original(draw, xy, text, *args, **kwargs)

        for mode in ("normal", "single", "missing", "zero", "larger_table"):
            data = copy.deepcopy(payload())
            if mode == "single":
                data["times"] = data["times"][:1]
            for row in data["series"]:
                if mode == "single":
                    row["votes"] = row["votes"][:1]
                if mode in ("missing", "zero"):
                    row["votes"] = [None if mode == "missing" else 0] * len(data["times"])
            normalized = BUSINESS.normalize_skin_votes(data)
            rows = normalized["rows"] if mode == "larger_table" else normalized["rows"][:10]
            with self.subTest(mode=mode), patch.object(ImageDraw.ImageDraw, "text", record):
                image = RENDER.render_skin_votes_image(normalized, rows, {"1": b"bad"})
                self.assertEqual(image.size, (1600, 1135 + 90 * len(rows)))
        text = "\n".join(drawn)
        for value in ("来源", "tianyuanzhiyi", "91m.top", "天元之弈"):
            self.assertNotIn(value, text)

    def test_output_paths_are_unique_and_use_existing_cleanup_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ZFILE, "temp_path", directory):
            image = RENDER.Image.new("RGB", (10, 10))
            first, second = ZFILE.save_skin_votes_image(image), ZFILE.save_skin_votes_image(image)
            self.assertNotEqual(first, second)
            self.assertEqual(Path(first).parent, Path(directory) / "temp_files")
            self.assertTrue(Path(first).is_file())

    def test_vote_lines_stop_at_real_samples_and_preserve_actual_declines(self):
        data = payload()
        data["series"][0]["votes"] = [990000, 980000, 985000]
        normalized = BUSINESS.normalize_skin_votes(data)
        lines = []
        original = ImageDraw.ImageDraw.line

        def record(draw, xy, *args, **kwargs):
            if kwargs.get("fill") in RENDER.COLORS:
                lines.append((kwargs["fill"], list(xy)))
            return original(draw, xy, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "line", record):
            RENDER.render_skin_votes_image(normalized, normalized["rows"][:10])
        self.assertTrue(lines)
        for _, points in lines:
            self.assertTrue(all(isinstance(point, tuple) and point[0] <= 1300 for point in points))
        first = next(points for color, points in lines if color == RENDER.COLORS[0])
        self.assertEqual(len(first), 3)
        self.assertGreater(first[1][1], first[0][1])
        self.assertLess(first[2][1], first[1][1])

    def test_adapter_rejects_unsuccessful_and_invalid_json_payloads(self):
        for value in ({"success": False}, [], {"success": True, "series": {}, "times": []}):
            with self.subTest(value=value), patch.object(API, "_skin_votes_get_bytes",
                    return_value=API.json.dumps(value).encode()), self.assertRaises(ValueError):
                API.tianyuanzhiyi_skin_votes_api()

    def test_http_has_time_and_size_limits_and_disables_environment_proxy(self):
        session = MagicMock()
        session.__enter__.return_value = session
        response = session.get.return_value.__enter__.return_value
        response.is_redirect = False
        response.iter_content.return_value = [b"1234", b"5678"]
        with patch.object(API.requests, "Session", return_value=session), self.assertRaisesRegex(
                ValueError, "response_too_large"):
            API._skin_votes_get_bytes("https://example.com", 3, 5)
        self.assertFalse(session.trust_env)
        self.assertEqual(session.get.call_args.kwargs["timeout"], 3)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_icon_failure_or_untrusted_host_does_not_abort_rankings(self):
        items = [{"skin_id": "1", "icon": "https://127.0.0.1/private"},
                 {"skin_id": "2", "icon": "https://game-1255653016.file.myqcloud.com/a.jpg"}]
        with patch.object(API, "_skin_votes_get_bytes", side_effect=TimeoutError) as fetch:
            self.assertEqual(API.tianyuanzhiyi_skin_icons_api(items), {})
        fetch.assert_called_once()


class SkinVotesHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_deprecated_handler_does_not_query_business(self):
        with patch.object(ZFUNC, "skin_votes_query_process") as query:
            self.assertEqual(await HANDLER.skin_votes_reply(),
                             {"text": "功能已经废弃", "image_path": None})
        query.assert_not_called()

    async def test_entry_sends_deprecation_text_to_original_event(self):
        from nonebot.adapters.onebot.v11 import MessageSegment

        tree = ast.parse((Path(__file__).parents[1] / "hok/zevent.py").read_text())
        matcher = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "_skin_votes" for t in node.targets))
        commands = ast.literal_eval(matcher.args[0])
        self.assertEqual(matcher.func.id, "on_fullmatch")
        self.assertIn("#皮肤返场", commands)
        self.assertIn("＃返场排行", commands)
        self.assertNotIn("#皮肤返场怎么查询", commands)
        self.assertEqual(next(k.value.id for k in matcher.keywords if k.arg == "rule"), "judge_to_me")
        node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "f_skin_votes")
        node.decorator_list = []
        sent = MagicMock()
        namespace = {"__package__": "hok", "MessageSegment": MessageSegment,
                     "add_msg": sent, "log_message": MagicMock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "handler", "exec"), namespace)
        event = object()
        with patch.object(ZFILE, "existing_absolute_path") as image_path:
            await namespace["f_skin_votes"](event)
        image_path.assert_not_called()
        sent.assert_called_once()
        self.assertIs(sent.call_args.kwargs["event"], event)
        self.assertEqual(sent.call_args.args[0].type, "text")
        self.assertEqual(str(sent.call_args.args[0]), "功能已经废弃")


if __name__ == "__main__":
    unittest.main()

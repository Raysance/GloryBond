"""Regression coverage for bounded hero images and short forward previews."""
import ast
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from local_debugger import import_hok_module

BUSINESS = import_hok_module("business.player_client")
HANDLER = import_hok_module("event_handlers.player_client")
RENDER = import_hok_module("tools.gen_player_client")
ZFUNC = import_hok_module("zfunc")
ZFILE = import_hok_module("zfile")
with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module("utils.message_sender")
STATIC = import_hok_module("zstatic")


def hero_result():
    return {"scope": "season", "heroes": [
        {"hero_id": 106 + i, "name": f"英雄{i}", "games": 60 - i * 5,
         "wins": 40 - i * 4, "losses": 20 - i, "win_rate_percent": (40 - i * 4) / (60 - i * 5) * 100,
         "fight_value": 8000 - i * 600, "highest_fight_value": 12000 - i * 500,
         "raw": {"large_private_protocol_record": "should not be displayed" * 1000}}
        for i in range(8)]}


class HeroReportTests(unittest.TestCase):
    def setUp(self):
        self.settings = {**STATIC.player_client_config, "display_hero_limit": 5}

    def test_top_five_are_sorted_and_projected_before_rendering_without_raw_fields(self):
        data = hero_result()
        data["heroes"].reverse()
        before = copy.deepcopy(data)
        report = BUSINESS.hero_report("测试玩家", data, self.settings, {"106": "小乔"})
        self.assertEqual([r["hero_id"] for r in report["rows"]], [str(i) for i in range(106, 111)])
        self.assertEqual(report["rows"][0]["name"], "小乔")
        self.assertIn("5/8", report["summary"])
        self.assertNotIn("raw", repr(report))
        self.assertNotIn("large_private_protocol_record", repr(report))
        self.assertEqual(data, before)

    def test_missing_values_and_no_games_do_not_invent_zero_win_rates_or_power(self):
        report = BUSINESS.hero_report("甲", {"heroes": [{"hero_id": 106, "games": 0,
            "win_rate_percent": 0}], "scope": "all"}, self.settings, {"106": "小乔"})
        self.assertIsNone(report["rows"][0]["win_rate_percent"])
        self.assertIsNone(report["rows"][0]["fight_value"])
        self.assertIn("当前战力—", report["text"])

    def test_empty_list_sends_a_readable_message_without_rendering(self):
        with patch.object(ZFUNC, "player_client_config", self.settings), \
             patch.object(RENDER, "render_hero_report") as render:
            result = ZFUNC.player_client_hero_report("甲", {"scope": "year", "heroes": []})
        render.assert_not_called()
        self.assertIsNone(result["image_path"])
        self.assertIn("没有返回英雄数据", result["text"])

    def test_render_failure_falls_back_to_only_the_selected_heroes_without_querying_again(self):
        with patch.object(ZFUNC, "player_client_config", self.settings), \
             patch.object(RENDER, "render_hero_report", side_effect=OSError("font unavailable")), \
             patch.object(ZFUNC, "player_client_query") as query:
            result = ZFUNC.player_client_hero_report("甲", hero_result())
        self.assertIsNone(result["image_path"])
        self.assertIn("60场", result["text"])
        self.assertNotIn("英雄7", result["text"])
        self.assertLess(len(result["text"]), 1000)
        query.assert_not_called()

    def test_real_renderer_persists_distinct_valid_pngs_for_concurrent_queries(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ZFILE, "temp_path", directory), \
             patch.object(ZFUNC, "player_client_config", self.settings):
            first = ZFUNC.player_client_hero_report("测试玩家", hero_result())
            second = ZFUNC.player_client_hero_report("测试玩家", hero_result())
            self.assertNotEqual(first["image_path"], second["image_path"])
            for result in (first, second):
                image = ZFILE.pil_image_from_bytes(Path(result["image_path"]).read_bytes())
                self.assertEqual(image.format, "PNG")
                self.assertLess(image.width * image.height, 2_000_000)
                self.assertNotIn("should not be displayed", result["text"])


class ClientDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_uses_the_configured_names_and_hero_image_facade_once(self):
        event = SimpleNamespace(get_plaintext=lambda: "#客户端 英雄 alice season", get_user_id=lambda: "1")
        with patch.object(STATIC, "player_client_config", {"players": {"alice": {"uid": 7}}}), \
             patch.object(STATIC, "qid", {"alice": "1"}), patch.object(STATIC, "namenick", {"alice": "甲"}), \
             patch.object(ZFUNC, "player_client_query", return_value=hero_result()) as query, \
             patch.object(ZFUNC, "player_client_hero_report", return_value={"text": "结果", "image_path": "/tmp/card.png"}) as report:
            result = await HANDLER.command_reply(event)
        query.assert_called_once_with("heroes", player={"uid": 7}, scope="season")
        report.assert_called_once_with("甲", query.return_value)
        self.assertEqual(result["image_path"], "/tmp/card.png")

    async def test_entry_sends_image_or_fallback_to_the_original_event(self):
        tree = ast.parse((Path(__file__).parents[1] / "hok/zevent.py").read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "f_player_client")
        handler.decorator_list = []
        namespace = {"__package__": "hok", "MessageEvent": object, "add_msg": MagicMock()}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "client-entry", "exec"), namespace)
        event = SimpleNamespace(user_id=456)
        for path in ("/tmp/card.png", None):
            with patch.object(HANDLER, "command_reply", AsyncMock(return_value={"text": "摘要", "image_path": path})), \
                 patch.object(SENDER, "add_text_image_msg") as image, patch.object(SENDER, "add_forward_msg") as forward:
                await namespace["f_player_client"](event)
            forward.assert_not_called()
            if path:
                image.assert_called_once_with("摘要", path, event=event)
            else:
                image.assert_not_called()
                namespace["add_msg"].assert_called_once_with("摘要", event=event)

    async def test_forward_preview_survives_queue_for_both_destinations_without_replacing_body(self):
        for event, kind, target in ((SimpleNamespace(group_id=123, user_id=456), "group", 123),
                                    (SimpleNamespace(user_id=456), "private", 456)):
            with self.subTest(kind=kind), patch.object(SENDER, "_enqueue_payload") as queue:
                SENDER.add_forward_msg(["长正文" * 10000], event=event, title="客户端", preview="点击查看")
                payload = queue.call_args.args[0]
                self.assertEqual(payload["messages"][0]["data"]["content"][0]["data"]["text"], "长正文" * 10000)
                bot = SimpleNamespace(send_group_forward_msg=AsyncMock(return_value={"message_id": 1}),
                                      send_private_forward_msg=AsyncMock(return_value={"message_id": 2}))
                await SENDER._handle_forward_msg(bot, payload)
                sender = getattr(bot, f"send_{kind}_forward_msg")
                sender.assert_awaited_once_with(**{f"{'group' if kind == 'group' else 'user'}_id": target},
                    messages=payload["messages"], source="客户端", prompt="客户端", news=[{"text": "点击查看"}])

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
        cache = patch.object(ZFILE, "load_hero_tier_avatar_cache", return_value=({}, []))
        cache.start()
        self.addCleanup(cache.stop)
        artwork = patch.object(ZFUNC, "player_client_artwork", return_value={})
        artwork.start()
        self.addCleanup(artwork.stop)

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

    def test_downloads_only_missing_selected_hero_avatars_and_keeps_cached_bytes(self):
        api = import_hok_module("zapi")
        with patch.object(ZFUNC, "player_client_config", self.settings), \
             patch.object(ZFILE, "load_hero_tier_avatar_cache", return_value=({"106": b"cached"}, [{"heroId": "107"}])) as load, \
             patch.object(api, "tianyuanzhiyi_hero_avatars_api", return_value={"107": b"downloaded"}) as fetch, \
             patch.object(ZFILE, "save_hero_tier_avatar_cache") as save, \
             patch.object(RENDER, "render_hero_report") as render, \
             patch.object(ZFILE, "save_player_client_report", return_value="/tmp/card.png"):
            result = ZFUNC.player_client_hero_report("甲", hero_result())
        self.assertEqual(len(load.call_args.args[0]), 5)
        self.assertEqual([v["heroId"] for v in load.call_args.args[0]], [str(i) for i in range(106, 111)])
        fetch.assert_called_once_with([{"heroId": "107"}])
        save.assert_called_once_with([{"heroId": "107"}], {"107": b"downloaded"})
        self.assertEqual(render.call_args.kwargs["avatar_bytes"], {"106": b"cached", "107": b"downloaded"})
        self.assertEqual(result["image_path"], "/tmp/card.png")

    def test_avatar_failure_does_not_discard_the_statistics_image(self):
        with patch.object(ZFUNC, "player_client_config", self.settings), \
             patch.object(ZFILE, "load_hero_tier_avatar_cache", side_effect=OSError("cache unavailable")), \
             patch.object(RENDER, "render_hero_report") as render, \
             patch.object(ZFILE, "save_player_client_report", return_value="/tmp/card.png"):
            result = ZFUNC.player_client_hero_report("甲", hero_result())
        render.assert_called_once()
        self.assertEqual(result["image_path"], "/tmp/card.png")

    def test_portrait_fallback_is_not_downloaded_when_card_art_is_available(self):
        artwork={str(i):b'card' for i in range(106,111)}
        with patch.object(ZFUNC,'player_client_artwork',return_value=artwork), \
             patch.object(ZFILE,'load_hero_tier_avatar_cache') as avatars, \
             patch.object(RENDER,'render_hero_report') as render, \
             patch.object(ZFILE,'save_player_client_report',return_value='card.png'):
            ZFUNC.player_client_hero_report('甲',hero_result())
        avatars.assert_not_called()
        self.assertEqual(render.call_args.kwargs['artwork'],artwork)

    def test_single_hero_illustration_and_portrait_load_concurrently(self):
        import threading
        ready=threading.Barrier(2,timeout=2)
        def artwork(ids,variant='illustration'):
            ready.wait()
            return {ids[0]:variant.encode()}
        with patch.object(ZFUNC,'player_client_artwork',side_effect=artwork), \
             patch.object(RENDER,'render_screen') as render, \
             patch.object(ZFILE,'save_player_client_report',return_value='hero.png'):
            result=ZFUNC.player_client_screen_report('hero','甲',{'hero_id':112})
        self.assertEqual(result['image_path'],'hero.png')
        self.assertEqual(render.call_args.kwargs['artwork'],{'112':b'illustration','portrait':b'avatar'})

    def test_win_rate_colors_distinguish_low_mid_high_and_missing_values(self):
        bands = self.settings["win_rate_bands"]
        low, mid, high = [RENDER.win_rate_color(rate, bands) for rate in (49.9, 50, 60)]
        self.assertEqual(len({low, mid, high}), 3)
        self.assertEqual(RENDER.win_rate_color(100, bands), high)
        self.assertEqual(RENDER.win_rate_color(0, bands), low)
        self.assertNotIn(RENDER.win_rate_color(None, bands), {low, mid, high})

    def test_renderer_draws_avatars_and_names_without_any_hero_ids(self):
        from PIL import Image, ImageDraw
        report = BUSINESS.hero_report("甲", hero_result(), self.settings, STATIC.HeroList)
        original = ImageDraw.ImageDraw.text
        drawn = []
        def track(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original(draw, xy, text, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            avatar_path = ZFILE.save_pil_image(Image.new("RGB", (72, 72), "#123abc"), directory + "/avatar.png")
            avatars = {"106": Path(avatar_path).read_bytes()}
            with patch.object(ImageDraw.ImageDraw, "text", track):
                image = RENDER.render_hero_report(report, ZFILE.player_client_report_font,
                    avatar_bytes=avatars, win_rate_bands=self.settings["win_rate_bands"])
        self.assertIn("小乔", drawn)
        self.assertFalse(any("ID" in value or value in {str(i) for i in range(106, 111)} for value in drawn))
        self.assertFalse(any(word in value for value in drawn for word in ("待补齐", "缺失", "本图", "官方默认", "预览")))
        self.assertEqual(image.getpixel((400, 268)), (18, 58, 188))

    def test_each_hero_picture_stays_in_its_own_reference_card(self):
        from PIL import Image
        report = BUSINESS.hero_report("甲", hero_result(), self.settings, STATIC.HeroList)
        report["rows"] = report["rows"][:2]
        colors = [(220,20,30), (20,150,220)]
        with tempfile.TemporaryDirectory() as directory:
            artwork = {}
            for row,color in zip(report["rows"],colors):
                path = ZFILE.save_pil_image(Image.new("RGB",(600,410),color),directory+'/'+row["hero_id"]+'.png')
                artwork[row["hero_id"]] = Path(path).read_bytes()
            image = RENDER.render_hero_report(report,ZFILE.player_client_report_font,
                artwork=artwork,win_rate_bands=self.settings["win_rate_bands"])
        self.assertEqual(image.getpixel((400,300)),colors[0])
        self.assertEqual(image.getpixel((677,300)),colors[1])
        self.assertNotIn(image.getpixel((541,300)),colors)

    def test_game_and_single_hero_images_do_not_draw_the_outside_explanation(self):
        from PIL import ImageDraw
        project = import_hok_module("business.player_client_screens")
        original,drawn = ImageDraw.ImageDraw.text,[]
        def track(draw,xy,text,*args,**kwargs):
            drawn.append(str(text))
            return original(draw,xy,text,*args,**kwargs)
        for kind in ("game","hero"):
            report = project.screen_report(kind,"甲",dict(scope="season",hero_id=106),STATIC.HeroList)
            report["notice"] = "这段解释只能在图外显示"
            with patch.object(ImageDraw.ImageDraw,"text",track):
                RENDER.render_screen(report,ZFILE.player_client_report_font,win_rate_bands=self.settings["win_rate_bands"])
        self.assertFalse(any(word in value for value in drawn for word in
                             ("解释", "缺失", "待补齐", "本图", "默认形象", "预览", "未取得")))


class ClientDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_and_client_start_together_and_keep_reply_order(self):
        import asyncio
        from contextlib import aclosing
        started=asyncio.Event()
        async def client(event):
            started.set()
            return {'text':'客户端图片','image_path':'card.png'}
        async def original(event):
            await asyncio.wait_for(started.wait(),timeout=1)
            return '原有统计'
        with patch.object(HANDLER,'command_reply',side_effect=client), \
             patch.object(HANDLER,'original_hero_reply',side_effect=original):
            async with aclosing(HANDLER.reply_stream(object())) as replies:
                self.assertEqual(await anext(replies),'原有统计')
                self.assertEqual((await anext(replies))['text'],'客户端图片')

    async def test_cancelled_request_cleans_up_its_concurrent_client_task(self):
        import asyncio
        from contextlib import aclosing
        started,cancelled=asyncio.Event(),asyncio.Event()
        async def client(event):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        async def original(event):
            await asyncio.Event().wait()
        async def consume():
            async with aclosing(HANDLER.reply_stream(object())) as replies:
                async for reply in replies:
                    pass
        with patch.object(HANDLER,'command_reply',side_effect=client), \
             patch.object(HANDLER,'original_hero_reply',side_effect=original):
            task=asyncio.create_task(consume())
            await asyncio.wait_for(started.wait(),timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(cancelled.is_set())

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
                 patch.object(HANDLER, "original_hero_reply", AsyncMock(return_value=None)), \
                 patch.object(SENDER, "add_text_image_msg") as image, patch.object(SENDER, "add_forward_msg") as forward:
                await namespace["f_player_client"](event)
            forward.assert_not_called()
            if path:
                image.assert_called_once_with("摘要", path, event=event)
            else:
                image.assert_not_called()
                namespace["add_msg"].assert_called_once_with("摘要", event=event)

    async def test_original_reply_is_queued_before_client_result_and_survives_client_failure(self):
        tree = ast.parse((Path(__file__).parents[1] / "hok/zevent.py").read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "f_player_client")
        handler.decorator_list = []
        order = []
        namespace = {"__package__": "hok", "MessageEvent": object,
                     "add_msg": MagicMock(side_effect=lambda *args, **kwargs: order.append(("original", args[0])))}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "client-entry", "exec"), namespace)
        event = SimpleNamespace(user_id=456)
        async def client(_event):
            order.append(("client_query", None))
            return ["客户端资料暂时未能取得。"]
        with patch.object(HANDLER, "original_hero_reply", AsyncMock(return_value="原有统计，近30天")), \
             patch.object(HANDLER, "command_reply", side_effect=client), \
             patch.object(SENDER, "add_forward_msg", side_effect=lambda *args, **kwargs: order.append(("supplement", args[0]))):
            await namespace["f_player_client"](event)
        self.assertEqual(order, [("original", "原有统计，近30天"), ("client_query", None),
                                  ("original", "客户端资料暂时未能取得。")])

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

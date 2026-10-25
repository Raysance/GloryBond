"""Existing hero leaderboards become the first card without changing their scope."""
import ast
import copy
from contextlib import aclosing
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image, ImageDraw
from local_debugger import import_hok_module

BUSINESS = import_hok_module("business.hero_statistics")
HANDLER = import_hok_module("event_handlers.player_client")
STATIC = import_hok_module("zstatic")
ZFUNC = import_hok_module("zfunc")
ZFILE = import_hok_module("zfile")
ZTIME = import_hok_module("ztime")
RENDER = import_hok_module("tools.gen_player_summary")
with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module("utils.message_sender")


def games():
    return [{"HeroName": name, "Result": "胜利" if win else "失败", "GameGrade": grade,
             "GradeMissing": missing, "KillCnt": 2, "DeadCnt": 3, "AssistCnt": 6,
             "Others": "MVP" if win else "", "raw": "PRIVATE_SENTINEL"}
            for name, win, grade, missing in (("小乔", True, 10, False), ("小乔", True, 8, False),
                ("小乔", False, 99, True), ("鲁班七号", True, 7, False), ("鲁班七号", False, 0, False),
                ("亚瑟", True, 12, False), ("海月", False, 99, True), ("海月", False, 99, True))]


def history_report(**options):
    with patch.object(BUSINESS, "userlist", {"alice": 11}), \
         patch.object(BUSINESS, "namenick", {"alice": "配置别名"}), \
         patch.object(BUSINESS, "HeroList", {"106": "小乔", "112": "鲁班七号", "166": "亚瑟", "521": "海月"}), \
         patch.object(BUSINESS.dmc, "herotier", {"小乔": 1.2, "鲁班七号": 1, "亚瑟": 2, "海月": 3}), \
         patch.object(BUSINESS, "fetch_history", return_value=({"alice": games()}, 0)):
        return BUSINESS.single_player_mult_hero_process("alice", as_report=True, **options)


class HistoryModelTests(unittest.TestCase):
    def test_explicit_alternate_account_reads_its_own_history_and_camp_role(self):
        with patch.object(BUSINESS, "userlist", {"alice": 11}), \
             patch.object(BUSINESS, "extra_useridlist", {"alt": 22}), \
             patch.object(BUSINESS, "extra_roleidlist", {"alt": 222}), \
             patch.object(BUSINESS, "extra_namenick", {"alt": "小号"}), \
             patch.object(BUSINESS, "fetch_history", return_value=({"alt": games()}, 0)) as fetch, \
             patch.object(BUSINESS, "wzry_get_official", return_value={}) as official:
            report = BUSINESS.single_player_mult_hero_process("alt", as_report=True)
            self.assertEqual(report["total"], 8)
            self.assertEqual(fetch.call_args.kwargs["userid"], 22)
            text = BUSINESS.single_player_single_hero_process("alt", 106, "小乔")
        official.assert_called_once_with(reqtype="herostatistics", userid=22, roleid=222, heroid=106)
        self.assertIn("小号的小乔", text)

    def test_rankings_counts_kda_and_grade_denominators_match_existing_statistics(self):
        report = history_report()
        self.assertEqual((report["total"], report["hero_count"], report["average_tier"]), (8, 4, 1.7))
        self.assertEqual([row["hero"] for row in report["sections"][0]["rows"]], ["小乔", "鲁班七号", "海月"])
        first = report["sections"][0]["rows"][0]
        self.assertEqual((first["hero_id"], first["count"], first["kda"]), ("106", 3, [2, 3, 6]))
        self.assertEqual(first["avg_grade"], 9)
        self.assertAlmostEqual(first["play_rate"], 3 / 8)
        self.assertAlmostEqual(first["win_rate"], 2 / 3)
        self.assertEqual(report["sections"][0]["rows"][1]["avg_grade"], 3.5)
        self.assertIsNone(report["sections"][0]["rows"][2]["avg_grade"])
        for section in report["sections"][1:]:
            self.assertNotIn("亚瑟", [row["hero"] for row in section["rows"]])
            self.assertEqual(section["minimum_games"], 2)
        self.assertNotIn("PRIVATE_SENTINEL", repr(report))
        self.assertNotIn("配置别名", repr(report))

    def test_one_history_read_keeps_thirty_day_and_explicit_season_windows(self):
        end = ZTIME.str_to_time("2026-10-25")
        with patch.object(BUSINESS, "userlist", {"alice": 11}), patch.object(ZTIME, "time_r", return_value=end), \
             patch.object(BUSINESS, "fetch_history", return_value=({}, 0)) as fetch:
            for season in (False, True):
                fetch.reset_mock()
                report = BUSINESS.single_player_mult_hero_process("alice", this_season=season, as_report=True)
                start = ZTIME.str_to_time(BUSINESS.this_season_start_date) if season else ZTIME.time_delta(end, -30)
                fetch.assert_called_once_with(userid=11, start_date=start, end_date=end)
                self.assertEqual(report["scope"], "本赛季" if season else "近30日")
                self.assertEqual(report["total"], 0)

    def test_existing_text_callers_keep_the_string_return_type(self):
        with patch.object(BUSINESS, "userlist", {"alice": 11}), \
             patch.object(BUSINESS, "namenick", {"alice": "配置别名"}), \
             patch.object(BUSINESS, "fetch_history", return_value=({"alice": games()}, 0)):
            text = BUSINESS.single_player_mult_hero_process("alice")
        self.assertIsInstance(text, str)
        self.assertIn("配置别名的英雄汇总", text)
        self.assertIn("近30日，共 8 场", text)
        self.assertIn("出场率 TOP", text)


class HistoryImageTests(unittest.TestCase):
    def test_same_card_style_avatars_and_all_three_rankings_fit_without_explanations(self):
        report = {**history_report(), "label": "LYG.未央"}
        content = BytesIO()
        Image.new("RGB", (72, 72), "#123abc").save(content, format="PNG")
        drawn, original = [], ImageDraw.ImageDraw.text
        def track(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            box = draw.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor"))
            self.assertGreaterEqual(box[0], 24, (text, box))
            self.assertLessEqual(box[2], 1096, (text, box))
            self.assertGreaterEqual(box[1], 24, (text, box))
            self.assertLess(box[3], draw._image.height - 24, (text, box))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", track):
            image = RENDER.render_summary(report, ZFILE.player_client_report_font,
                avatar_bytes={"106": content.getvalue()}, win_rate_bands=STATIC.player_client_config["win_rate_bands"])
        self.assertEqual(image.size, (1120, 1600))
        self.assertEqual(image.getpixel((100, 356)), (18, 58, 188))
        for text in ("LYG.未央", "出场率 TOP", "胜率 TOP", "评分 TOP", "KDA  2.0 / 3.0 / 6.0", "66.7%", "—"):
            self.assertIn(text, drawn)
        self.assertFalse(any(word in text for text in drawn for word in ("配置别名", "说明", "客户端", "raw", "UID", "暂缺")))

    def test_empty_history_and_empty_eligible_rankings_still_make_valid_images(self):
        empty = history_report(min_games=999)
        for section in empty["sections"][1:]:
            self.assertEqual(section["rows"], [])
        RENDER.render_summary(empty, ZFILE.player_client_report_font)
        empty = {**empty, "total": 0, "hero_count": 0, "average_tier": None}
        for section in empty["sections"]:
            section["rows"] = []
        self.assertEqual(RENDER.render_summary(empty, ZFILE.player_client_report_font).size, (1120, 420))

    def test_facade_uses_game_name_and_returns_only_image_or_the_same_readable_facts(self):
        report = history_report()
        before = copy.deepcopy(report)
        with patch.object(ZFUNC, "player_client_hero_avatars", return_value={}) as avatars, \
             patch.object(ZFILE, "save_player_client_report", return_value="history.png"), \
             patch.object(ZFUNC, "player_client_query") as query:
            result = ZFUNC.hero_history_image_report(report, player_name="LYG.未央")
        self.assertEqual(result, {"text": "", "image_path": "history.png"})
        self.assertEqual(set(avatars.call_args.args[0]), {"106", "112", "521"})
        query.assert_not_called()
        self.assertEqual(report, before)
        with patch.object(ZFUNC, "player_client_hero_avatars", return_value={}), \
             patch.object(RENDER, "render_summary", side_effect=OSError("PRIVATE_SENTINEL")):
            result = ZFUNC.hero_history_image_report(report, player_name="LYG.未央")
        self.assertIsNone(result["image_path"])
        self.assertIn("LYG.未央 · 近30日英雄汇总", result["text"])
        self.assertIn("均分9.0", result["text"])
        self.assertNotIn("PRIVATE_SENTINEL", result["text"])


class TwoImageDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_hero_summary_sends_two_images_in_order_through_the_unified_exit(self):
        tree = ast.parse((Path(__file__).parents[1] / "hok/zevent.py").read_text())
        entry = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "f_player_client")
        entry.decorator_list = []
        namespace = {"__package__": "hok", "MessageEvent": object, "add_msg": Mock()}
        exec(compile(ast.Module(body=[entry], type_ignores=[]), "hero-two-images", "exec"), namespace)
        client = {"text": "", "image_path": "client.png", "player_name": "LYG.未央"}
        report = history_report()
        event = SimpleNamespace(user_id=1)
        with patch.object(HANDLER, "command_reply", AsyncMock(return_value=client)), \
             patch.object(HANDLER, "original_hero_reply", AsyncMock(return_value=report)), \
             patch.object(ZFUNC, "hero_history_image_report", return_value={"text": "", "image_path": "history.png"}) as render, \
             patch.object(SENDER, "add_text_image_msg") as send, patch.object(SENDER, "add_forward_msg") as forward:
            await namespace["f_player_client"](event)
        render.assert_called_once_with(report, player_name="LYG.未央")
        self.assertEqual([call.args for call in send.call_args_list], [("", "history.png"), ("", "client.png")])
        self.assertTrue(all(call.kwargs == {"event": event} for call in send.call_args_list))
        namespace["add_msg"].assert_not_called()
        forward.assert_not_called()

    async def test_client_failure_keeps_the_history_image_without_a_config_name_fallback(self):
        report = history_report()
        with patch.object(HANDLER, "command_reply", AsyncMock(return_value=["客户端查询繁忙"])), \
             patch.object(HANDLER, "original_hero_reply", AsyncMock(return_value=report)), \
             patch.object(ZFUNC, "hero_history_image_report", return_value={"text": "", "image_path": "history.png"}) as render:
            async with aclosing(HANDLER.reply_stream(object())) as replies:
                self.assertEqual((await anext(replies))["image_path"], "history.png")
                self.assertEqual(await anext(replies), ["客户端查询繁忙"])
        render.assert_called_once_with(report, player_name=None)


if __name__ == "__main__":
    unittest.main()

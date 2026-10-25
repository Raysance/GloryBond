"""Self-bound profile cards, concise filters and native statistics; offline only."""
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
from hok_research import PlayerRef, Profile
from hok_research.player_pages import battle_display
from local_debugger import import_hok_module
from tests.test_player_client_pages import battle_row

HANDLER = import_hok_module("event_handlers.player_client")
RULES = import_hok_module("event_rules")
ADAPTER = import_hok_module("api_adapters.player_client")
MODELS = import_hok_module("business.player_client_profile")
RENDER = import_hok_module("tools.gen_player_summary")
STATIC = import_hok_module("zstatic")
ZFUNC = import_hok_module("zfunc")
ZFILE = import_hok_module("zfile")


def profile_result():
    return {"profile": {"szAcntName": {"text": "LYG.未央"}, "dwPvpLevel": 30,
        "dwCreditValue": 100, "dwAchieveMentScore": 7280, "ullPopularity": 58000, "dwWangZheCnt": 16,
        "szSignatureInfo": {"text": "每一局，都认真。"},
        "stMostUsedHero": {"dwTotalHeroNum": 126, "dwTotalSkinNum": 312},
        "stMasterMatchData": {"iMasterMatchScore": 1850, "iMaxSeasonMasterMatchScore": 2040,
                              "iMaxHistoryMasterMatchScore": 2312}},
        "statistics": {"scope": "season", "mode": "all", "player_name": "LYG.未央", "display": battle_display([battle_row()])},
        "branches": {"branches": [{"branch": key, "level": level} for key, level in
            zip(("top", "mid", "bot", "jungle", "assist"), (12, 19, 15, 10, 7))]}}


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.player = {"uid": 7, "logic_world_id": 8, "fake_description_id": 9}
        values = {"player_client_config": {**STATIC.player_client_config, "players": {"alice": self.player}},
                  "namenick": {"alice": "甲"}, "extra_namenick": {}, "nameref": {"alice": ["甲", "ali"]},
                  "qid": {"alice": "1"}, "HeroList": {"106": "小乔"}, "HeroName_replacements": {}}
        for name, value in values.items():
            p = patch.object(STATIC, name, value)
            p.start(); self.addCleanup(p.stop)

    def event(self, text, user="1"):
        return SimpleNamespace(get_plaintext=lambda: text, get_user_id=lambda: user)

    async def test_profile_shortcut_and_explicit_command_use_one_profile_summary_and_image(self):
        for text in ("#我的资料", "＃甲的资料", "#客户端 资料 我"):
            with self.subTest(text=text), patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
                 patch.object(ZFUNC, "player_client_screen_report", return_value={"text": "", "image_path": "card.png"}) as render:
                result = await HANDLER.command_reply(self.event(text))
                query.assert_called_once_with("profile_summary", player=self.player)
                render.assert_called_once_with("profile", "甲", {})
                self.assertEqual(result, {"text": "", "image_path": "card.png"})
                self.assertIsNone(await HANDLER.original_hero_reply(self.event(text)))

    async def test_concise_branch_scope_combinations_preserve_all_filters(self):
        branches = (("中路", "mid"), ("发育路", "bot"), ("对抗路", "top"),
                    ("打野", "jungle"), ("游走", "assist"), ("辅助路", "assist"), ("", None))
        for branch, code in branches:
            for scope, scope_code in (("本赛季", "season"), ("本赛年", "year"), ("全部", "all"), ("", "season")):
                item = scope + branch + "数据"
                with self.subTest(item=item), patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
                     patch.object(ZFUNC, "player_client_screen_report", return_value={}):
                    await HANDLER.command_reply(self.event("#我的" + item))
                    query.assert_called_once_with("game_statistics", player=self.player, scope=scope_code, mode="all", branch=code)

    async def test_optional_data_word_and_filters_on_either_side_of_de(self):
        for text, scope, branch in (("#我的中路", "season", "mid"), ("#我的本赛年", "year", None),
                ("#我本赛年中路的数据", "year", "mid"), ("＃我的发育路本赛季数据", "season", "bot"),
                ("#ali的数据 全部比赛 排位 中路", "all", "mid")):
            tokens = HANDLER.parse_client_request(text)
            operation, params, label = HANDLER.query_parameters(tokens, user_id="1", settings=STATIC.player_client_config,
                qids=STATIC.qid, nicknames=STATIC.namenick, player_aliases=STATIC.nameref)
            self.assertEqual((operation, params["scope"], params["branch"], label), ("game", scope, branch, "甲"))
            self.assertEqual(params["mode"], "ranked" if "排位" in text else "all")

    async def test_missing_de_and_colloquial_scopes_dispatch_to_the_bound_player(self):
        cases = (("#我本赛季对抗路数据", "season", "top"),
                 ("#我游走本赛季数据", "season", "assist"),
                 ("#我打野这个赛季的数据", "season", "jungle"),
                 ("＃我这个赛年发育路数据", "year", "bot"),
                 ("#我的中路这赛季数据", "season", "mid"),
                 ("#甲中路这赛年的数据", "year", "mid"),
                 ("#我全部打野数据", "all", "jungle"),
                 ("#我这个赛季的中路数据", "season", "mid"))
        for text, scope, branch in cases:
            with self.subTest(text=text), patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
                 patch.object(ZFUNC, "player_client_screen_report", return_value={"image_path": "card.png", "text": ""}):
                self.assertTrue(await RULES.judge_player_client(self.event(text)))
                await HANDLER.command_reply(self.event(text))
                query.assert_called_once_with("game_statistics", player=self.player, scope=scope, mode="all", branch=branch)

    async def test_hash_is_required_and_partial_or_conflicting_sentences_do_not_route(self):
        for text in ("我本赛季对抗路数据", "我游走本赛季数据", "我打野这个赛季的数据",
                     "##我本赛季对抗路数据", "＃＃我这个赛季中路数据", "#我本赛季对抗路数据怎么样",
                     "#我不是要查本赛季数据", "#我本赛季本赛年中路数据", "#我中路打野数据",
                     "#群u本赛季中路数据", "#我这个赛季的数据数据", "#我的"):
            with self.subTest(text=text):
                self.assertIsNone(HANDLER.parse_client_request(text))
                self.assertFalse(await RULES.judge_player_client(self.event(text)))

    async def test_unbound_self_ambiguous_self_and_free_text_never_query_a_default_role(self):
        with patch.object(ZFUNC, "player_client_query") as query:
            self.assertIn("尚未绑定", (await HANDLER.command_reply(self.event("#我的资料", user="2")))[0])
            with patch.object(STATIC, "qid", {"alice": "1", "alt": "1"}), \
                 patch.object(STATIC, "player_client_config", {"players": {"alice": self.player, "alt": self.player}}):
                self.assertIn("不唯一", (await HANDLER.command_reply(self.event("#我的资料")))[0])
            query.assert_not_called()
        for text in ("我的资料", "##我的资料", "#我的资料怎么样", "#我的中路厉害吗", "#群u的资料", "#群u的中路数据"):
            self.assertIsNone(HANDLER.parse_client_request(text), text)


class AdapterTests(unittest.TestCase):
    def test_profile_summary_uses_one_paced_profile_and_native_display_without_extra_calls(self):
        raw = {"szAcntName": b"test", "stStatistic": {"stRadarDetail": {"stCurSeason": {
            "stTotal": {"dwCount": 999}, "astBranchTotal": [battle_row()]}}},
            "stPosFightValue": {"astBranchScore": [{"dwPosFightValueScore": score} for score in (0, 14000, 0, 0, 3000)]}}
        adapter = ADAPTER.PlayerClientAdapter.__new__(ADAPTER.PlayerClientAdapter)
        adapter.settings = {"timeout_seconds": 1}
        adapter.client, adapter.gate, adapter.on_error = Mock(), Mock(), Mock()
        target = PlayerRef(7, 8, 9)
        adapter.client.profile.return_value = Profile(target, raw)
        result = adapter.query("profile_summary", player=vars(target))
        again = adapter.query("profile_summary", player=vars(target))
        adapter.client.profile.assert_called_once_with(target, timeout=1)
        adapter.gate.assert_called_once_with("query")
        self.assertEqual(len(adapter.client.method_calls), 1)
        self.assertEqual(result["statistics"]["display"]["games"], 104)
        self.assertAlmostEqual(result["statistics"]["display"]["composite_score"], 73.7, places=4)
        self.assertEqual(result["branches"]["branches"][1]["level"], 19)
        self.assertEqual(result, again)

    def test_profile_without_statistics_retains_available_basic_fields(self):
        adapter = ADAPTER.PlayerClientAdapter.__new__(ADAPTER.PlayerClientAdapter)
        adapter.settings = {"timeout_seconds": 1}
        adapter.client, adapter.gate, adapter.on_error = Mock(), Mock(), Mock()
        adapter.client.profile.return_value = Profile(PlayerRef(7, 8), {"dwPvpLevel": 30})
        result = adapter.query("profile_summary", player={"uid": 7, "logic_world_id": 8, "fake_description_id": 0})
        model = MODELS.profile_report("甲", result)
        self.assertEqual(model["values"]["level"], 30)
        self.assertIsNone(model["statistics"]["games"])
        self.assertEqual([row["level"] for row in model["branches"]], [None] * 5)


class ModelAndImageTests(unittest.TestCase):
    def test_ten_hero_rows_keep_titles_styles_and_numbers_inside_their_rows(self):
        cards = import_hok_module("business.player_client")
        result = {"scope": "season", "player_name": "LYG.未央", "heroes": [
            {"hero_id": 106 + i, "name": f"英雄{i}", "games": 1020, "win_rate_percent": 56.3,
             "fight_value": 4000, "highest_fight_value": 5000 - i,
             "fight_style": {"text": "均衡发展的峡谷财神"},
             "rank_badge": {"ranked": True, "rank": 3, "raw": {"dwAdCode": 340803}}}
            for i in range(12)]}
        report = cards.hero_report("配置昵称", result, STATIC.player_client_config, {},
            district_names={340803: "安徽省安庆市大观区"})
        drawn, original = [], ImageDraw.ImageDraw.text
        def track(draw, xy, text, *args, **kwargs):
            box = draw.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor"))
            self.assertGreaterEqual(box[0], 24, (text, box))
            self.assertLessEqual(box[2], 1096, (text, box))
            self.assertLess(box[3], draw._image.height - 24, (text, box))
            if str(text).startswith("历史称号"):
                self.assertEqual(text, "历史称号  安徽省安庆市大观区 第3名")
                self.assertLess(box[3], 280 + len(drawn) * 132 + 107)
                drawn.append(str(text))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", track):
            image = RENDER.render_summary(report, ZFILE.player_client_report_font)
        self.assertEqual(len(drawn), 10)
        self.assertEqual(image.width, 1120)
        self.assertGreater(image.height, 1660)
        self.assertLess(image.width * image.height, 8_000_000)

    def test_hero_cards_use_real_game_names_and_icons_without_template_backgrounds(self):
        cards = import_hok_module("business.player_client")
        source = {"player_name": {"text": "LYG.未央"}, "hero_id": 106, "scope": "all",
                  "highest_fight_value": 4300, "display": battle_display([battle_row()]),
                  "medals": {"top": 0, "gold": 24, "silver": 28, "bronze": 12}, "mvp": 46, "losing_mvp": 8,
                  "year_labels": {"in_use": [{"name": value} for value in ("团战发动机", "伐木机器", "嗜血闪现")]},
                  "historical_badges": [{"title_type": kind, "count": 2} for kind in (1, 2, 3, 5, 4)],
                  "rank_badge": {"ranked": True, "rank": 3}}
        hero = MODELS.hero_summary_report(source, STATIC.HeroList)
        heroes = cards.hero_report("配置昵称", {"scope": "season", "player_name": "LYG.未央", "heroes": [
            {"hero_id": key, "games": 100, "win_rate_percent": 55, "fight_value": 3000, "highest_fight_value": 4300}
            for key in (106, 112)]}, STATIC.player_client_config, STATIC.HeroList)
        content = BytesIO()
        Image.new("RGB", (72, 72), "#123abc").save(content, format="PNG")
        drawn, original = [], ImageDraw.ImageDraw.text
        def track(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            box = draw.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor"))
            self.assertGreaterEqual(box[0], 24, (text, box))
            self.assertLessEqual(box[2], 1096, (text, box))
            self.assertLess(box[3], draw._image.height - 24, (text, box))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ZFILE, "player_client_reference_image", side_effect=AssertionError("No screenshot templates")), \
             patch.object(ImageDraw.ImageDraw, "text", track):
            one = RENDER.render_summary(hero, ZFILE.player_client_report_font, avatar_bytes={"106": content.getvalue()})
            many = RENDER.render_summary(heroes, ZFILE.player_client_report_font, avatar_bytes={"106": content.getvalue()})
        self.assertEqual(one.getpixel((120, 186)), (18, 58, 188))
        body_y = RENDER._header_plan(heroes, ZFILE.player_client_report_font, {})[3]
        self.assertEqual(many.getpixel((100, body_y + 156)), (18, 58, 188))
        self.assertIn("LYG.未央", drawn)
        self.assertIn("团战发动机", drawn)
        self.assertFalse(any(word in text for text in drawn for word in ("配置昵称", "暂缺", "未取得", "说明", "raw", "UID")))

    def test_missing_game_name_never_falls_back_to_a_configured_alias(self):
        cards = import_hok_module("business.player_client")
        self.assertEqual(MODELS.statistics_report("配置昵称", {})["label"], "—")
        self.assertEqual(MODELS.profile_report("配置昵称", {})["name"], "—")
        self.assertEqual(MODELS.hero_summary_report({}, {})["label"], "—")
        self.assertEqual(cards.hero_report("配置昵称", {"heroes": []}, STATIC.player_client_config, {})["label"], "—")

    def test_only_whitelisted_fields_are_exposed_and_unknown_values_stay_unknown(self):
        source = profile_result()
        source["profile"].update(ullUid=9876543210123456789, szOpenID="PRIVATE_SENTINEL", raw={"private": "PRIVATE_SENTINEL"})
        source["profile"]["dwCreditValue"] = 0
        model = MODELS.profile_report("甲", source)
        self.assertEqual(model["values"]["credit"], 0)
        self.assertNotIn("PRIVATE_SENTINEL", repr(model))
        self.assertNotIn("9876543210123456789", repr(model))
        empty = MODELS.profile_report("甲", {})
        self.assertIsNone(empty["values"]["credit"])
        self.assertIn("信誉 —", empty["text"])
        stats = MODELS.statistics_report("甲", {"scope": "year", "branch": "mid", "mode": "ranked", "display": battle_display([battle_row()])})
        self.assertAlmostEqual(stats["values"]["score"], 73.7, places=4)
        self.assertEqual(stats["branch_label"], "中路")
        self.assertNotIn("暂缺", stats["text"])

    def test_images_are_readable_bounded_and_contain_no_protocol_or_explanation(self):
        models = [MODELS.profile_report("甲", profile_result()),
                  MODELS.statistics_report("甲", {"scope": "year", "mode": "ranked", "branch": "mid", "display": battle_display([battle_row()])}),
                  MODELS.profile_report("甲", {}), MODELS.statistics_report("甲", {})]
        original, drawn = ImageDraw.ImageDraw.text, []
        def track(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            box = draw.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor"))
            self.assertGreaterEqual(box[0], 24, (text, box))
            self.assertLessEqual(box[2], 1096, (text, box))
            self.assertGreaterEqual(box[1], 24, (text, box))
            self.assertLess(box[3], draw._image.height - 24, (text, box))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", track):
            for model in models:
                image = RENDER.render_summary(model, ZFILE.player_client_report_font, win_rate_bands=STATIC.player_client_config["win_rate_bands"])
                self.assertEqual(image.width, 1120)
        for value in ("个人资料", "LYG.未央", "信誉积分", "本赛季", "巅峰赛", "19段", "当前赛年", "中路", "51.0%", "73.7"):
            self.assertTrue(any(value in text for text in drawn), value)
        self.assertFalse(any(word in text for text in drawn for word in
            ("缺失", "暂缺", "未取得", "说明", "客户端", "默认", "raw", "UID", "PRIVATE_SENTINEL")))

    def test_long_names_and_large_values_fit_card_columns(self):
        source = profile_result()
        source["profile"].update(szAcntName="很长的昵称" * 30, ullPopularity=2**64 - 1, szSignatureInfo="很长的签名" * 30)
        model = MODELS.profile_report("甲", source)
        next_row_y = 128 + RENDER._header_plan(model, ZFILE.player_client_report_font, {})[2][0]
        original, clipped, names = ImageDraw.ImageDraw.text, [], []
        def track(draw, xy, text, *args, **kwargs):
            box = draw.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor"))
            self.assertGreaterEqual(box[0], 24)
            self.assertLessEqual(box[2], 1096)
            if str(text).endswith("…"):
                clipped.append(str(text))
            if xy[0] == 88 and xy[1] < next_row_y and kwargs['font'].size == 32:
                names.append(str(text))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", track):
            RENDER.render_summary(model, ZFILE.player_client_report_font)
        self.assertEqual(''.join(names), model['name'])
        self.assertFalse(any(value.startswith("很长的昵称") for value in clipped))
        self.assertTrue(any(value.startswith("很长的签名") for value in clipped))

    def test_facade_sends_only_the_image_and_falls_back_to_readable_facts(self):
        source = profile_result()
        for kind, data, fact in (("profile", source, "信誉 100"), ("game", source["statistics"], "场次 104")):
            with self.subTest(kind=kind), patch.object(ZFILE, "save_player_client_report", return_value="/tmp/card.png"), \
                 patch.object(ZFUNC, "player_client_artwork") as artwork:
                result = ZFUNC.player_client_screen_report(kind, "甲", data)
                self.assertEqual(result, {"text": "", "image_path": "/tmp/card.png", "player_name": "LYG.未央", "query_label": "甲"})
                artwork.assert_not_called()
            with patch.object(RENDER, "render_summary", side_effect=OSError("PRIVATE_SENTINEL")):
                result = ZFUNC.player_client_screen_report(kind, "甲", data)
            self.assertIsNone(result["image_path"])
            self.assertIn(fact, result["text"])
            self.assertNotIn("PRIVATE_SENTINEL", result["text"])
            self.assertNotIn("图片生成失败", result["text"])


if __name__ == "__main__":
    unittest.main()

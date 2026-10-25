"""Readable field projections and additive hero-query behavior; no network."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from local_debugger import import_hok_module

BUSINESS = import_hok_module("business.player_client")
HANDLER = import_hok_module("event_handlers.player_client")
HERO = import_hok_module("event_handlers.hero")
ZFUNC = import_hok_module("zfunc")
STATIC = import_hok_module("zstatic")


class TextReportTests(unittest.TestCase):
    def setUp(self):
        self.settings = {**STATIC.player_client_config, "display_item_limit": 2}

    def render(self, operation, result, **kwargs):
        result = {**result, "stResultInfo": {"iResultId": 0, "private": "PRIVATE_SENTINEL"},
                  "raw": {"session": "PRIVATE_SENTINEL"}, "future_unknown_field": "PRIVATE_SENTINEL"}
        text = "".join(BUSINESS.text_report(operation, "测试玩家", result, self.settings, {"106": "小乔"}, **kwargs))
        for forbidden in ("PRIVATE_SENTINEL", "stResultInfo", "future_unknown_field", '"raw"', '"$bytes"'):
            self.assertNotIn(forbidden, text)
        return text

    def test_game_statistics_translate_counts_rates_and_peak_scores_without_inventing_rank_names(self):
        text = self.render("game", {"dwPvpLevel": 30, "dwCurClassOfRank": 999,
            "stStatistic": {"stFiveVsFiveInfo": {"dwTotalNum": 100, "dwWinNum": 61}},
            "stRankInfo": {"dwTotalFightCnt": 20, "dwTotalWinCnt": 13, "dwMaxContinuousWinCnt": 5},
            "stMasterMatchData": {"iMasterMatchScore": 1850, "iMaxHistoryMasterMatchScore": 2100}})
        for phrase in ("客户端游戏统计", "100场，61胜39负，胜率61.0%", "当前排位赛季：20场", "当前巅峰积分：1,850"):
            self.assertIn(phrase, text)
        self.assertNotIn("999", text)
        self.assertNotIn("stStatistic", text)

    def test_missing_and_zero_samples_do_not_become_fabricated_zero_percent(self):
        text = self.render("game", {"stStatistic": {"stFiveVsFiveInfo": {"dwTotalNum": 0, "dwWinNum": 0}}})
        self.assertIn("暂无胜率样本", text)
        self.assertNotIn("胜率0.0%", text)
        text = self.render("game", {"stRankInfo": {"dwTotalFightCnt": 4}})
        self.assertIn("胜负数据未提供", text)

    def test_profile_decodes_text_and_hides_internal_identity(self):
        text = self.render("profile", {"szAcntName": {"$bytes": "616263", "text": "游戏昵称"},
            "dwPvpLevel": 30, "dwCreditValue": 100, "szOpenID": "DO_NOT_SHOW", "ullUid": 999,
            "szSignatureInfo": {"text": "今天也要开心"}, "stMostUsedHero": {"dwTotalHeroNum": 100, "dwTotalSkinNum": 200}})
        self.assertIn("游戏昵称：游戏昵称", text)
        self.assertIn("信誉积分：100", text)
        self.assertIn("皮肤总数：200", text)
        self.assertNotIn("DO_NOT_SHOW", text)
        self.assertNotIn("999", text)

    def test_hero_detail_projects_only_requested_hero_and_semantic_fields(self):
        text = self.render("hero_detail", {"stDetailHeroExtraInfo": {"astDetailHeroExtraData": [
            {"dwHeroID": 106, "stHeroAbilityInfo": {"dwTotalValue": 800, "stAbilityData": {"Value": [123456]}},
             "stHeroBadgeInfo": {"iHeroBadgeNum": 4, "dwHeroBadgeProficiency": 120},
             "stHeroTitleInfo": {"iTitleGroupNum": 3, "stShowTitle": {"dwShowTitleID": 98765}}},
            {"dwHeroID": 112, "stHeroAbilityInfo": {"dwTotalValue": 222222}}]}}, hero_id=106)
        for phrase in ("小乔", "英雄能力总值：800", "徽章记录数：4", "称号记录数：3", "展示称号：已设置"):
            self.assertIn(phrase, text)
        for value in ("123456", "98765", "222222", "stHeroAbilityInfo"):
            self.assertNotIn(value, text)

    def test_history_uses_target_player_identity_and_preserves_partial_scope(self):
        row = {"dwGameStartTime": 1792822073, "bWinCamp": 1, "astPlayerFightData": [
            {"ullPlayerUid": 7, "iPlayerLogicWorldID": 8, "dwHeroID": 106, "bPlayerCamp": 1, "bKill": 8, "bDead": 2, "bAssist": 9},
            {"ullPlayerUid": 9, "iPlayerLogicWorldID": 8, "dwHeroID": 112, "bPlayerCamp": 2}]}
        text = self.render("history", {"records": [row] * 3, "complete": False}, player={"uid": 7, "logic_world_id": 8})
        self.assertIn("展示最近2场", text)
        self.assertIn("小乔  胜利  击杀/死亡/助攻 8/2/9", text)
        self.assertIn("尚未确认结束", text)
        self.assertIn("不代表全部历史", text)
        text = self.render("history", {"records": [row], "complete": True}, player={"uid": 7, "logic_world_id": 999})
        self.assertIn("不推断胜负和英雄", text)
        self.assertNotIn("胜利", text)

    def test_homepage_keeps_available_profile_when_history_is_private(self):
        text = self.render("homepage", {"profile": {"dwPvpLevel": 30}, "game": {}, "history": None,
                                        "errors": {"history": {"code": 32002}}})
        self.assertIn("对战等级：30", text)
        self.assertIn("战绩未能取得", text)
        self.assertNotIn("32002", text)

    def test_collections_skins_assets_titles_and_brief_use_counts_and_names(self):
        cases = (
            ("collections", {"stEmojiList": {"wEmojiCnt": 12}, "stSkyScreenList": {"dwNum": 2}}, "表情：12"),
            ("hero_assets", {"stHeroInfo": {"stHeroList": {"astHeroIDMasks": [{"dwHeroID": 106, "dwMaskBits": 4294967295}]}}}, "小乔"),
            ("hero_road_brief", {"stHeroRoadBriefInfo": {"astHeroRoadBriefData": [{"dwHeroID": 106, "dwUnLockBadgeNum": 5}]}}, "已解锁徽章5个"),
            ("hero_titles", {"stHistoryHeroLbsTitleInfo": {"astHeroLbsTitleData": [{"dwHeroID": 106, "dwMaxFightScore": 10000, "dwTitleTypeCnt": 3}]}}, "历史最高战力10,000"),
            ("displayed_skins", {"stShowSkinInfo": {"astShowSkinData": [{"dwSkinID": 999}]}}, "小乔·测试皮肤"),
        )
        for operation, result, expected in cases:
            with self.subTest(operation=operation):
                text = self.render(operation, result, skin_names={"999": "小乔·测试皮肤"})
                self.assertIn(expected, text)
                self.assertNotIn("4294967295", text)

    def test_search_preserves_exact_game_uid_for_disambiguation_without_raw_metadata(self):
        uid = 18446744073709551614
        text = self.render("search", {"candidates": [{"nickname": "同名玩家", "platform": 1, "pvp_level": 30,
            "uid": uid, "logic_world_id": 1234, "fake_description_id": 98765}]})
        self.assertIn("安卓", text)
        self.assertIn(str(uid), text)
        self.assertNotIn("98765", text)
        self.assertIn("不会自动绑定", text)

    def test_unknown_shapes_never_fall_back_to_raw_json_or_zero_statistics(self):
        for operation in ("game", "profile", "hero_detail", "collections"):
            with self.subTest(operation=operation):
                text = self.render(operation, {"future_shape": {"arbitrary": 123}})
                self.assertIn("没有可展示的已识别资料", text)
                self.assertNotIn("123", text)


class AdditiveHeroTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in {"player_client_config": {**STATIC.player_client_config, "players": {"alice": {"uid": 7}}},
                            "namenick": {"alice": "甲"}, "extra_namenick": {}, "nameref": {"alice": ["甲", "alice"]},
                            "qid": {"alice": "1"}, "HeroList": {"106": "小乔"}}.items():
            patcher = patch.object(STATIC, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def event(self, text):
        return SimpleNamespace(get_plaintext=lambda: text, get_user_id=lambda: "1")

    async def test_natural_queries_pass_original_event_unchanged_to_the_original_handler(self):
        for text in ("#我的小乔", "#甲的英雄", "#甲本赛季的英雄"):
            event = self.event(text)
            with self.subTest(text=text), patch.object(HERO, "hero_statistics_reply", AsyncMock(return_value="原有全部内容")) as original:
                self.assertEqual(await HANDLER.original_hero_reply(event), "原有全部内容")
                original.assert_awaited_once_with(event, **({"as_report": True} if "英雄" in text else {}))

    async def test_explicit_client_data_and_group_queries_do_not_duplicate_original_content(self):
        with patch.object(HERO, "hero_statistics_reply", AsyncMock()) as original:
            for text in ("#客户端 英雄 alice season", "#甲的数据", "#群u的小乔"):
                self.assertIsNone(await HANDLER.original_hero_reply(self.event(text)))
            original.assert_not_called()

    async def test_legacy_window_stays_thirty_days_unless_original_message_selects_season(self):
        with patch.object(ZFUNC, "extract_name", return_value="alice"), patch.object(ZFUNC, "qid2nick", return_value="甲"), \
             patch.object(ZFUNC, "single_player_mult_hero_process", return_value="原统计") as aggregate:
            await HANDLER.original_hero_reply(self.event("#甲的英雄"))
            aggregate.assert_called_once_with("alice", this_season=False, as_report=True)

    async def test_legacy_failure_is_readable_and_cancellation_is_not_swallowed(self):
        with patch.object(HERO, "hero_statistics_reply", AsyncMock(side_effect=RuntimeError("PRIVATE_SENTINEL"))):
            result = await HANDLER.original_hero_reply(self.event("#甲的小乔"))
            self.assertIn("继续查询客户端", result)
            self.assertNotIn("PRIVATE_SENTINEL", result)
        with patch.object(HERO, "hero_statistics_reply", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await HANDLER.original_hero_reply(self.event("#甲的小乔"))

    async def test_missing_client_binding_keeps_original_statistics_available(self):
        with patch.object(STATIC, "player_client_config", {**STATIC.player_client_config, "players": {}}), \
             patch.object(HERO, "hero_statistics_reply", AsyncMock(return_value="原有统计仍可使用")):
            self.assertEqual(await HANDLER.original_hero_reply(self.event("#甲的英雄")), "原有统计仍可使用")

    async def test_ambiguous_player_does_not_issue_a_legacy_query_before_client_validation(self):
        with patch.object(STATIC, "nameref", {"alice": ["同名"], "other": ["同名"]}), \
             patch.object(HERO, "hero_statistics_reply", AsyncMock()) as original:
            self.assertIsNone(await HANDLER.original_hero_reply(self.event("#同名的英雄")))
            original.assert_not_called()

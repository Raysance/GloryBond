import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "intent_router_under_test", ROOT / "hok" / "tools" / "intent_router.py"
)
INTENT_ROUTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INTENT_ROUTER)


class ControlledEmbedder:
    model_name = "controlled-test-model"

    def __init__(self, normalizer, query_intents=None):
        self.query_intents = query_intents or {}
        self.intents = list(INTENT_ROUTER.INTENT_EXAMPLES)
        self.example_intents = {}
        for intent, examples in INTENT_ROUTER.INTENT_EXAMPLES.items():
            for example in examples:
                prepared = normalizer.normalize(example.lstrip("#＃").strip()).text
                self.example_intents[prepared] = intent

    def encode(self, texts, batch_size=32):
        vectors = []
        for text in texts:
            intent = self.query_intents.get(text, self.example_intents.get(text))
            vector = [0.0] * len(self.intents)
            if intent in self.intents:
                vector[self.intents.index(intent)] = 1.0
            else:
                vector[-1] = 1.0
            vectors.append(vector)
        return vectors


class IntentRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(ROOT / "variables_static.json", encoding="utf-8") as static_file:
            cls.static = json.load(static_file)
        with open(ROOT / "data" / "honor" / "districts.json", encoding="utf-8") as district_file:
            cls.districts = json.load(district_file)
        cls.players = INTENT_ROUTER.collect_player_aliases(
            cls.static["namenick"],
            cls.static["nameref"],
            cls.static["extra_namenick"],
        )
        cls.heroes = INTENT_ROUTER.collect_hero_aliases(
            cls.static["HeroList"], cls.static["HeroName_replacements"]
        )
        cls.regions = INTENT_ROUTER.EntityNormalizer.district_aliases(cls.districts)
        cls.normalizer = INTENT_ROUTER.EntityNormalizer(
            cls.players, cls.heroes, cls.regions
        )

    def build_router(self, query_intents=None):
        embedder = ControlledEmbedder(self.normalizer, query_intents)
        return INTENT_ROUTER.EmbeddingIntentRouter(
            self.normalizer,
            embedder,
            min_score=0.5,
            min_margin=0.01,
        )

    def test_every_business_intent_has_ten_to_twenty_examples(self):
        for intent, examples in INTENT_ROUTER.INTENT_EXAMPLES.items():
            if intent == INTENT_ROUTER.NONE_INTENT:
                continue
            self.assertGreaterEqual(len(examples), 10, intent)
            self.assertLessEqual(len(examples), 20, intent)

    def test_every_example_passes_its_structural_validator(self):
        router = self.build_router()
        failures = []
        for intent, examples in INTENT_ROUTER.INTENT_EXAMPLES.items():
            if intent == INTENT_ROUTER.NONE_INTENT:
                continue
            for example in examples:
                decision = router.classify(example)
                if decision.intent != intent:
                    failures.append((intent, example, decision.intent))
        self.assertEqual(failures, [])

    def test_all_configured_player_aliases_are_masked_in_player_context(self):
        failures = []
        for alias in self.players:
            result = self.normalizer.normalize(f"查询{alias}最近战绩")
            if "player" not in result.entity_types:
                failures.append((alias, result.text))
        self.assertEqual(failures, [])

    def test_all_configured_hero_aliases_are_masked_in_hero_context(self):
        failures = []
        for alias in self.heroes:
            result = self.normalizer.normalize(f"看看我玩的{alias}数据")
            if "hero" not in result.entity_types:
                failures.append((alias, result.text, result.values))
        self.assertEqual(failures, [])

    def test_hero_pinyin_is_derived_from_static_names(self):
        if "diaochan" not in self.heroes:
            self.skipTest("pypinyin is not installed in this test environment")
        result = self.normalizer.normalize("看看我的diaochan数据")
        self.assertIn("hero", result.entity_types)
        self.assertIn("某英雄", result.text)

    def test_regions_are_loaded_from_district_tree(self):
        for region in ("安徽省", "安庆市", "大观区"):
            result = self.normalizer.normalize(f"查询貂蝉在{region}的战力")
            self.assertIn("region", result.entity_types)
            self.assertIn("某地区", result.text)

    def test_new_entities_need_no_new_intent_examples(self):
        normalizer = INTENT_ROUTER.EntityNormalizer(
            player_aliases={"新玩家阿星"},
            hero_aliases={"新英雄天衡"},
            region_aliases={"新城区"},
        )
        result = normalizer.normalize("查新玩家阿星在新城区玩新英雄天衡的数据")
        self.assertEqual(
            result.text,
            "查某玩家在某地区玩某英雄的数据",
        )
        self.assertEqual(result.entity_types, frozenset({"player", "hero", "region"}))

    def test_one_character_entities_require_business_context(self):
        self.assertNotIn("hero", self.normalizer.normalize("这部电影很好看").entity_types)
        self.assertNotIn("player", self.normalizer.normalize("今天走路脚疼").entity_types)
        self.assertIn("hero", self.normalizer.normalize("我玩的影胜率如何").entity_types)
        self.assertIn("player", self.normalizer.normalize("查脚最近战绩").entity_types)

    def test_my_diaochan_can_only_reach_hero_statistics(self):
        normalized = self.normalizer.normalize("我的貂蝉").text
        router = self.build_router({normalized: "herostatistics"})
        decision = router.classify("我的貂蝉")
        self.assertEqual(decision.intent, "herostatistics")
        self.assertIn("hero", decision.entities.entity_types)

    def test_hero_match_search_is_not_treated_as_hero_statistics(self):
        normalized = self.normalizer.normalize("我的貂蝉的排位赛有哪些").text
        router = self.build_router({normalized: "history_query"})
        self.assertEqual(
            router.classify("我的貂蝉的排位赛有哪些").intent,
            "history_query",
        )

    def test_subscription_validator_rejects_unrelated_short_sentence(self):
        normalized = self.normalizer.normalize("我的貂蝉").text
        router = self.build_router({normalized: "bili_mine"})
        decision = router.classify("我的貂蝉")
        self.assertNotEqual(decision.intent, "bili_mine")

    def test_double_hash_is_never_semantically_routed(self):
        router = self.build_router()
        self.assertIsNone(router.classify("##e print('x')").intent)

    def test_representative_query_still_requires_hash(self):
        normalized = self.normalizer.normalize("看看我昨天的代表局").text
        router = self.build_router({normalized: "representative_battle"})
        self.assertIsNone(router.classify("看看我昨天的代表局").intent)
        self.assertEqual(
            router.classify("#看看我昨天的代表局").intent,
            "representative_battle",
        )


if __name__ == "__main__":
    unittest.main()

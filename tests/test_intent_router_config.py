import ast
from pathlib import Path
import unittest

from tests.test_intent_router import INTENT_ROUTER


ROOT = Path(__file__).resolve().parents[1]
ZEVENT_PATH = ROOT / "hok" / "zevent.py"


class IntentRouterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ZEVENT_PATH.read_text(encoding="utf-8-sig")
        cls.tree = ast.parse(cls.source)

    def test_every_semantic_matcher_has_examples(self):
        routed = set()
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "intent_rule":
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    routed.add(argument.value)
        self.assertEqual(routed - set(INTENT_ROUTER.INTENT_EXAMPLES), set())
        self.assertEqual(
            set(INTENT_ROUTER.INTENT_EXAMPLES) - {INTENT_ROUTER.NONE_INTENT},
            routed,
        )

    def test_business_matchers_no_longer_use_keyword_rules(self):
        forbidden = (
            '_single=on_keyword',
            '_rnk=on_keyword',
            '_heropower=on_keyword',
            '_history_query=on_keyword',
            '_todayhero=on_keyword',
            '_showonline=on_keyword',
            '_watchbattle=on_keyword',
            '_recentpower=on_keyword',
            '_recentgames = on_keyword',
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, self.source)

    def test_double_hash_commands_use_strict_admin_rules(self):
        commands = (
            "##r", "##e", "##t", "##u", "##f", "##srep", "##rep3",
            "##c", "##amnesia", "##memory", "##emoji", "##kpl", "##bili",
        )
        for command in commands:
            self.assertIn(f'strict_admin_rule("{command}"', self.source)

    def test_chat_requires_single_hash_prefix(self):
        self.assertIn("rule=judge_chat_request", self.source)
        self.assertIn('not raw.startswith("##")', self.source)

    def test_remote_handlers_acknowledge_group_requests(self):
        expected_sources = {
            "representative_battle", "hero_tier", "bili_subscribe",
            "bili_unsubscribe", "bili_latest", "bili_mine", "atall",
            "showonline", "battle_view", "battle_detail", "hero_power",
            "honor_power", "hero_statistics", "today_hero", "grade_analyze",
            "watch_battle", "spoiler", "recent_power", "recent_games",
            "history_query",
        }
        found = set()
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "acknowledge_remote_request":
                continue
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                found.add(node.args[1].value)
        self.assertTrue(expected_sources.issubset(found))

    def test_bili_target_extraction_supports_natural_actions(self):
        namespace = {"re": __import__("re")}
        function_node = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_extract_bili_video_target"
        )
        exec(compile(ast.Module(body=[function_node], type_ignores=[]), str(ZEVENT_PATH), "exec"), namespace)
        extract = namespace["_extract_bili_video_target"]
        self.assertEqual(extract("帮我关注一下影视飓风这个UP"), "影视飓风")
        self.assertEqual(extract("#订阅B站影视飓风的最新视频"), "影视飓风")
        self.assertEqual(extract("别再推送影视飓风的视频了", unsubscribe=True), "影视飓风")


if __name__ == "__main__":
    unittest.main()

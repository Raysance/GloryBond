import ast
import unittest
from pathlib import Path


class WebAnalyzeAiTests(unittest.TestCase):
    def assert_entry_disables_lineup_commentary(self, source_path, handler_name):
        source = source_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        handler = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == handler_name
        )

        power_call = next(
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "battle_power_process"
        )
        ai_keyword = next(
            keyword for keyword in power_call.keywords if keyword.arg == "with_ai_analysis"
        )

        self.assertIsInstance(ai_keyword.value, ast.Name)
        self.assertEqual(ai_keyword.value.id, "with_ai_analysis")
        disabled_assignment = next(
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "with_ai_analysis" for target in node.targets)
        )
        self.assertIsInstance(disabled_assignment.value, ast.Constant)
        self.assertIs(disabled_assignment.value.value, False)
        handler_source = ast.get_source_segment(source, handler)
        image_offset = handler_source.index("MessageSegment.image(pic_path)")
        commentary_offset = handler_source.index(
            'with_ai_analysis and power_data.get("aiAnalysis")',
            image_offset,
        )
        self.assertLess(image_offset, commentary_offset)

    def test_web_analyze_keeps_lineup_commentary_disabled_by_parameter(self):
        source_path = Path(__file__).resolve().parents[1] / "hok" / "zscheduler.py"
        self.assert_entry_disables_lineup_commentary(source_path, "run_web_analyze_btls_processor")

    def test_poke_keeps_lineup_commentary_disabled_by_parameter(self):
        source_path = (
            Path(__file__).resolve().parents[1]
            / "hok"
            / "event_handlers"
            / "poke.py"
        )
        source = source_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        handler = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "group_poke_reply"
        )
        power_call = next(
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "battle_power_process"
        )
        ai_keyword = next(
            keyword
            for keyword in power_call.keywords
            if keyword.arg == "with_ai_analysis"
        )
        self.assertIsInstance(ai_keyword.value, ast.Constant)
        self.assertIs(ai_keyword.value.value, False)

        event_source = (
            Path(__file__).resolve().parents[1] / "hok" / "zevent.py"
        ).read_text(encoding="utf-8-sig")
        image_offset = event_source.index(
            'MessageSegment.image(result["image_path"])',
            event_source.index("async def f_group_poke"),
        )
        commentary_offset = event_source.index(
            'result["with_ai_analysis"] and result["analysis"]',
            image_offset,
        )
        self.assertLess(image_offset, commentary_offset)


if __name__ == "__main__":
    unittest.main()

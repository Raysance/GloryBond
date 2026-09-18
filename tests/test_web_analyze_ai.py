import ast
import unittest
from pathlib import Path


class WebAnalyzeAiTests(unittest.TestCase):
    def test_web_analyze_enables_and_sends_lineup_commentary_after_image(self):
        scheduler_path = Path(__file__).resolve().parents[1] / "hok" / "zscheduler.py"
        source = scheduler_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "run_web_analyze_btls_processor"
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

        self.assertIsInstance(ai_keyword.value, ast.Constant)
        self.assertIs(ai_keyword.value.value, True)
        handler_source = ast.get_source_segment(source, handler)
        image_offset = handler_source.index("snd_msg += MessageSegment.image(pic_path)")
        commentary_offset = handler_source.index('power_data.get("aiAnalysis")', image_offset)
        self.assertLess(image_offset, commentary_offset)


if __name__ == "__main__":
    unittest.main()

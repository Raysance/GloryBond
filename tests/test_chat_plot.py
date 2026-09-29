import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from local_debugger import import_hok_module


PLOT = import_hok_module("tools.chat_plot")
WORKER = import_hok_module("plot_runtime.worker")
ZFILE = import_hok_module("zfile")


def chart_fixtures():
    return {
        "bar": [{"label": name, "value": value} for name, value in [("玩家 A", 84), ("玩家 B", 71), ("玩家 C", 64), ("玩家 D", 55)]],
        "line": [{"x": day, "series": name, "value": value} for name, values in [("玩家 A", [7.2, 8.1, 7.8, 8.7]), ("玩家 B", [6.8, 7.4, 7.7, 8.1])] for day, value in zip(["09-20", "09-21", "09-22", "09-23"], values)],
        "scatter": [{"x": x, "value": value, "series": name, "size": size} for x, value, name, size in [(52, 7.2, "射手", 32), (62, 8.5, "射手", 50), (55, 7.9, "打野", 28), (69, 9.0, "打野", 47), (60, 8.0, "中路", 31)]],
        "heatmap": [{"label": label, "x": x, "value": value} for label, values in [("玩家 A", [61, 48, 73]), ("玩家 B", [55, 68, 59]), ("玩家 C", [72, 60, 64])] for x, value in zip(["射手", "打野", "中路"], values)],
        "distribution": [{"value": value, "series": name} for name, values in [("玩家 A", [5.2, 7.3, 8.1, 9.2, 8.7, 8.1, 7.5, 6.2, 8.5]), ("玩家 B", [6.2, 6.5, 7.1, 8.2, 7.7, 7.1, 6.5, 7.2, 7.5])] for value in values],
    }


class ChatPlotValidationTests(unittest.TestCase):
    def test_templates_publish_real_code_and_shape(self):
        definitions = PLOT.chat_plot_templates()["templates"]
        self.assertEqual({item["name"] for item in definitions}, set(chart_fixtures()))
        for item in definitions:
            WORKER.validate_plot_code(item["code"])
            self.assertTrue(item["columns"])

    def test_templates_map_sql_columns_without_mutating_source(self):
        rows = [{"player_name": "玩家 A", "win_rate": 72.5}]
        request = PLOT.prepare_chat_plot(rows, template="bar", options={"columns": {"label": "player_name", "value": "win_rate"}})
        self.assertEqual(request["data"][0]["value"], 72.5)
        self.assertEqual(set(rows[0]), {"player_name", "win_rate"})

    def test_custom_code_rejects_missing_mapped_source(self):
        with self.assertRaisesRegex(ValueError, "真实字段不存在"):
            PLOT.prepare_chat_plot([{"player": "A", "wins": 3}], code="ax.plot(df['value'])",
                                   options={"columns": {"value": "missing"}})

    def test_rejects_io_reflection_dynamic_code_and_loops(self):
        attempts = [
            "import os", "open('/etc/passwd')", "eval('1')", "exec('1')",
            "pd.read_csv('/etc/passwd')", "np.load('/etc/passwd')",
            "df.to_csv('/tmp/pwn')", "sns.load_dataset('iris')",
            "plt.savefig('/tmp/pwn')", "ax.figure.savefig('/tmp/pwn')",
            "ax.__class__", "getattr(ax, 'figure')", "while True: pass",
            "for x in data: ax.plot(x)", "[x for x in data]",
            "f = lambda: 1", "np = df", "data = []", "ax.foo = 1",
            "ax.plot(**data)", "(df['x'])(1)",
        ]
        for code in attempts:
            with self.subTest(code=code), self.assertRaises(ValueError):
                WORKER.validate_plot_code(code)

    def test_limits_and_template_validation(self):
        for data, options in [([], {}), ([{"value": float("nan"), "label": "x"}], {}), ([{"label": "x"}], {}), ([{"label": "x", "value": 1}], {"path": "/tmp/pwn"})]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                PLOT.prepare_chat_plot(data, options=options)
        with self.assertRaisesRegex(ValueError, "超过 1 行"):
            PLOT.prepare_chat_plot(chart_fixtures()["bar"], config={"max_rows": 1})

    def test_worker_environment_excludes_application_secrets(self):
        with patch.dict(ZFILE.os.environ, {"HOK_CHAT_API_KEY": "secret", "HOK_DATABASE_DSN": "secret", "PYTHONPATH": "/sensitive"}):
            command, environment, _ = ZFILE._chat_plot_worker_command("/worker.py", "/tmp/job", {})
        self.assertNotIn("HOK_CHAT_API_KEY", environment)
        self.assertNotIn("HOK_DATABASE_DSN", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertIn("-I", command)


class ChatPlotRuntimeTests(unittest.TestCase):
    def test_templates_render_readable_pngs_in_subprocess(self):
        with tempfile.TemporaryDirectory() as output_dir, patch.object(ZFILE, "temp_path", output_dir):
            for name, rows in chart_fixtures().items():
                with self.subTest(template=name):
                    request = PLOT.prepare_chat_plot(rows, template=name, title="对局表现 · 示例", options={"subtitle": "演示数据，用于检验布局和中文显示"})
                    result = ZFILE.render_chat_plot_worker(request, {"timeout_seconds": 30})
                    self.assertGreater(result["bytes"], 10000)
                    self.assertEqual((result["width"], result["height"]), (1456, 936))
                    with Image.open(result["path"]) as picture:
                        self.assertEqual(picture.format, "PNG")

    def test_custom_python_code_aggregates_observation_data(self):
        code = "import pandas as pd\nimport seaborn as sns\nsummary = df.groupby('series')['value'].mean().reset_index()\nsns.barplot(data=summary, x='series', y='value', ax=ax)\nax.set_ylabel('平均评分')"
        with tempfile.TemporaryDirectory() as output_dir, patch.object(ZFILE, "temp_path", output_dir):
            request = PLOT.prepare_chat_plot(chart_fixtures()["distribution"], code=code, title="自定义 Python")
            result = ZFILE.render_chat_plot_worker(request, {"timeout_seconds": 30})
            self.assertGreater(result["bytes"], 10000)

    def test_template_python_example_honors_column_mapping(self):
        code = next(item["code"] for item in PLOT.chat_plot_templates()["templates"] if item["name"] == "bar")
        rows = [{"player_name": "玩家 A", "win_rate": 72.5}]
        with tempfile.TemporaryDirectory() as output_dir, patch.object(ZFILE, "temp_path", output_dir):
            request = PLOT.prepare_chat_plot(rows, code=code, title="自定义代码字段映射",
                                            options={"columns": {"label": "player_name", "value": "win_rate"}})
            self.assertEqual(request["data"][0]["label"], "玩家 A")
            self.assertEqual(request["data"][0]["value"], 72.5)
            self.assertEqual(set(rows[0]), {"player_name", "win_rate"})
            result = ZFILE.render_chat_plot_worker(request, {"timeout_seconds": 30})
            self.assertGreater(result["bytes"], 10000)

    def test_pandas_string_dispatch_and_nested_tex_are_blocked(self):
        for code in ("x = df.agg('to_csv')", "x = df.groupby('label').agg('to_csv')", "ax.set_title('x', fontdict={'usetex': True})"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as output_dir, patch.object(ZFILE, "temp_path", output_dir):
                request = PLOT.prepare_chat_plot(chart_fixtures()["bar"], code=code)
                with self.assertRaisesRegex(RuntimeError, "(聚合函数|TeX)"):
                    ZFILE.render_chat_plot_worker(request, {"timeout_seconds": 30})

    def test_invalid_image_and_worker_failure_never_publish(self):
        from types import SimpleNamespace

        request = PLOT.prepare_chat_plot(chart_fixtures()["bar"])
        with tempfile.TemporaryDirectory() as output_dir, patch.object(ZFILE, "temp_path", output_dir), patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"not a PNG", stderr=b"")):
            with self.assertRaisesRegex(ValueError, "有效的限长 PNG"):
                ZFILE.render_chat_plot_worker(request)

    def test_worker_timeout_is_reported(self):
        import subprocess

        request = PLOT.prepare_chat_plot(chart_fixtures()["bar"])
        with tempfile.TemporaryDirectory() as output_dir, patch.object(ZFILE, "temp_path", output_dir), patch("subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 3)):
            with self.assertRaisesRegex(RuntimeError, "超过 3 秒，进程已终止"):
                ZFILE.render_chat_plot_worker(request, {"timeout_seconds": 3})


if __name__ == "__main__":
    unittest.main()

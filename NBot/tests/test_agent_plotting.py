import copy
import json
from pathlib import Path
import unittest

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from agent_console.plot_renderer import render_chart
from agent_console.tools.plotting import PlotArgs, build_plot_code


CATALOG = json.loads(
    (Path(__file__).parents[1] / "shared/agent/plots/catalog.json").read_text()
)


class PlotTests(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_parameters_are_data_and_theme_default_is_declarative(self):
        args = PlotArgs(
            dataset_id="d",
            x="name",
            y="count",
            title="'; __import__('os').system('false'); '",
        )
        dataset = {
            "rows": [{"name": "A", "count": 3}],
            "columns": ["name", "count"],
            "truncated": True,
        }
        catalog = copy.deepcopy(CATALOG)
        catalog["default_theme"] = "midnight"
        captured = []
        namespace = {
            "df": dataset["rows"],
            "plot_themes": catalog["themes"],
            "render_chart": lambda *values: captured.append(values),
        }
        exec(build_plot_code(args, dataset, catalog), namespace)
        self.assertEqual(captured[0][1]["title"], args.title)
        self.assertEqual(captured[0][2]["name"], "霓虹夜色")
        self.assertTrue(captured[0][1]["caption"].startswith("查询结果已截断"))

    def test_unknown_fields_and_themes_fail_before_execution(self):
        dataset = {"rows": [{"x": 1, "y": 2}], "columns": ["x", "y"]}
        for args in [
            PlotArgs(dataset_id="d", x="x", y="y", value="missing"),
            PlotArgs(dataset_id="d", x="x", y="y", theme="missing"),
        ]:
            with self.assertRaises(ValueError):
                build_plot_code(args, dataset, CATALOG)

    def test_heatmap_missing_values_stay_missing_and_duplicate_cells_reject(self):
        data = pd.DataFrame(
            [
                {"day": "Mon", "hour": 0, "count": 4},
                {"day": "Tue", "hour": 1, "count": 2},
            ]
        )
        p = {"kind": "heatmap", "x": "hour", "y": "day", "value": "count"}
        result = render_chart(data, p, CATALOG["themes"]["aurora"])
        self.assertEqual(result["missing_cells"], 2)
        shown = plt.gcf().axes[0].images[0].get_array()
        self.assertEqual(int(np.ma.getmaskarray(shown).sum()), 2)
        with self.assertRaisesRegex(ValueError, "重复"):
            render_chart(pd.concat([data, data]), p, CATALOG["themes"]["aurora"])

    def test_heatmap_fills_and_aggregates_only_when_explicit(self):
        data = pd.DataFrame(
            [
                {"day": "Mon", "hour": 0, "count": 4},
                {"day": "Mon", "hour": 0, "count": 3},
                {"day": "Tue", "hour": 1, "count": 2},
            ]
        )
        result = render_chart(
            data,
            {
                "kind": "heatmap",
                "x": "hour",
                "y": "day",
                "value": "count",
                "aggregation": "sum",
                "fill_value": 0,
            },
            CATALOG["themes"]["midnight"],
        )
        self.assertEqual(result["missing_cells"], 0)
        self.assertEqual(float(plt.gcf().axes[0].images[0].get_array()[0, 0]), 7.0)

    def test_line_sorts_dates_and_preserves_actual_values_without_smoothing(self):
        data = pd.DataFrame(
            [
                {"date": "2026-10-03", "score": 4},
                {"date": "2026-10-01", "score": 2},
                {"date": "2026-10-02", "score": 8},
            ]
        )
        original = data.copy(deep=True)
        render_chart(
            data,
            {"kind": "line", "x": "date", "y": "score"},
            CATALOG["themes"]["sunset"],
        )
        self.assertEqual(
            plt.gcf().axes[0].lines[0].get_ydata().tolist(), [2.0, 8.0, 4.0]
        )
        pd.testing.assert_frame_equal(data, original)

    def test_non_finite_metrics_and_invalid_donut_are_rejected(self):
        for kind, value in [
            ("bar", float("nan")),
            ("line", float("inf")),
            ("donut", -1),
        ]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                render_chart(
                    pd.DataFrame([{"name": "A", "value": value}]),
                    {"kind": kind, "x": "name", "y": "value"},
                    CATALOG["themes"]["aurora"],
                )


if __name__ == "__main__":
    unittest.main()

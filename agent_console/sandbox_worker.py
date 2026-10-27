"""Runs inside the isolated filesystem/network namespace, without app imports."""

import json
import sys

# Append instead of PYTHONPATH: server packages must not shadow stdlib modules.
sys.path.append("/opt/site-packages")

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main():
    payload = json.load(sys.stdin)
    fonts = []
    for path in payload.get("font_paths", []):
        fm.fontManager.addfont(path)
        fonts.append(fm.FontProperties(fname=path).get_name())
    plt.rcParams.update(
        {
            "font.family": fonts + ["DejaVu Sans"],
            "font.sans-serif": fonts + ["DejaVu Sans"],
            "axes.unicode_minus": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    datasets = payload.get("data", {})
    namespace = {
        "pd": pd,
        "np": np,
        "plt": plt,
        "df": pd.DataFrame(next(iter(datasets.values()), [])),
        "datasets": datasets,
        "plot_themes": payload["plot_catalog"]["themes"],
    }
    exec(
        compile(payload["plot_renderer"], "<trusted_plot_renderer>", "exec"), namespace
    )
    namespace["apply_plot_style"](
        payload["plot_catalog"]["themes"][payload["plot_catalog"]["default_theme"]]
    )
    exec(compile(payload["code"], "<generated>", "exec"), namespace)
    if plt.get_fignums():
        plt.savefig(
            "/work/plot.png",
            dpi=180,
            bbox_inches="tight",
            facecolor=plt.gcf().get_facecolor(),
        )
    with open("/work/result.json", "w") as file:
        json.dump(namespace.get("result"), file, default=str, ensure_ascii=False)


if __name__ == "__main__":
    main()

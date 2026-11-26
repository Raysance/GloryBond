"""Trusted chart library executed inside the sandbox; no IO or app imports."""

import re
import textwrap

import matplotlib as mpl
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.patches import FancyBboxPatch, Polygon
from matplotlib.ticker import MaxNLocator
import matplotlib.patheffects as effects
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def apply_plot_style(theme):
    plt.rcParams.update(
        {
            "figure.facecolor": theme["background"],
            "axes.facecolor": theme["card"],
            "text.color": theme["text"],
            "axes.labelcolor": theme["muted"],
            "xtick.color": theme["muted"],
            "ytick.color": theme["text"],
            "axes.edgecolor": theme["grid"],
            "grid.color": theme["grid"],
            "axes.prop_cycle": mpl.cycler(color=theme["palette"]),
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "font.size": 10,
            "axes.labelsize": 10,
            "legend.frameon": False,
            "savefig.facecolor": theme["background"],
            "axes.unicode_minus": False,
        }
    )


def _number(value, unit=""):
    value = float(value)
    text = (
        f"{value:,.0f}"
        if value.is_integer()
        else f"{value:,.2f}".rstrip("0").rstrip(".")
    )
    return text + unit


def _label(value):
    if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        number = float(value)
        if np.isfinite(number) and number.is_integer():
            return str(int(number))
    return str(value)


def _numeric(frame, field):
    values = pd.to_numeric(frame[field], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{field}包含缺失、非数值或非有限值，请先清理数据")
    return values


def _canvas(params, theme, rows, height):
    fig = plt.figure(figsize=(11.5, height), dpi=180, facecolor=theme["background"])
    card = FancyBboxPatch(
        (0.018, 0.025),
        0.964,
        0.95,
        transform=fig.transFigure,
        boxstyle="round,pad=0,rounding_size=0.025",
        facecolor=theme["card"],
        edgecolor="none",
        zorder=-2,
    )
    card.set_path_effects(
        [effects.SimplePatchShadow(offset=(2, -3), alpha=0.08), effects.Normal()]
    )
    fig.add_artist(card)
    titles = textwrap.wrap(params.get("title") or params["y"], width=32)[:3]
    fig.text(
        0.07,
        0.931,
        "DATA  /  "
        + {
            "bar": "OVERVIEW",
            "line": "TREND",
            "scatter": "RELATIONSHIP",
            "heatmap": "MATRIX",
            "donut": "COMPOSITION",
        }[params["kind"]],
        fontsize=8,
        weight="bold",
        color=theme["accent"],
    )
    for i, title in enumerate(titles):
        fig.text(
            0.07,
            0.875 - i * 0.048,
            title,
            fontsize=19,
            weight="bold",
            color=theme["text"],
        )
    top = 0.795 - max(0, len(titles) - 1) * 0.048
    subtitle = params.get("subtitle", "")
    if subtitle:
        fig.text(0.07, top + 0.032, subtitle[:100], fontsize=9, color=theme["muted"])
    bottom = 0.16
    ax = fig.add_axes([0.16, bottom, 0.77, top - bottom])
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(length=0, pad=9)
    ax.grid(axis="x" if params["kind"] == "bar" else "y", alpha=0.7, linewidth=0.7)
    footer = f"显示 {rows} 个数据点"
    if params.get("caption"):
        footer += "  ·  " + params["caption"]
    for i, line in enumerate(textwrap.wrap(footer, width=65)[:2]):
        fig.text(0.07, 0.065 - i * 0.026, line, fontsize=8, color=theme["muted"])
    return fig, ax


def _bar(frame, p, theme, ax):
    if len(frame) > 30:
        raise ValueError("条形图最多30条，请在查询中明确筛选")
    values = _numeric(frame, p["y"])
    names = ["\n".join(textwrap.wrap(str(v), 13)) for v in frame[p["x"]]]
    spread = max(float(np.ptp(values)), float(np.abs(values).max()), 1.0)
    ax.set_xlim(
        min(0.0, values.min()) - 0.08 * spread, max(0.0, values.max()) + 0.23 * spread
    )
    ax.set_ylim(len(frame) - 0.35, -0.8)
    ax.set_yticks(range(len(frame)), names, fontsize=10)
    ax.spines["bottom"].set_visible(False)
    ax.axvline(0, color=theme["grid"], linewidth=0.8)
    for i, value in enumerate(values):
        color = theme["palette"][i % len(theme["palette"])]
        left = min(0.0, value)
        patch = FancyBboxPatch(
            (left, i - 0.29),
            abs(value),
            0.58,
            boxstyle="round,pad=0,rounding_size=0.11",
            facecolor=color,
            edgecolor="none",
            zorder=3,
        )
        if value:
            ax.add_patch(patch)
        if value:
            cmap = LinearSegmentedColormap.from_list(
                "bar", [(0.65 + 0.35 * np.array(to_rgb(color))).tolist(), color]
            )
            image = ax.imshow(
                np.linspace(0, 1, 256)[None, :],
                extent=[left, left + abs(value), i + 0.29, i - 0.29],
                cmap=cmap,
                aspect="auto",
                interpolation="bilinear",
                zorder=4,
            )
            image.set_clip_path(patch)
        if p.get("annotate", True):
            ax.text(
                value + (0.025 * spread if value >= 0 else -0.025 * spread),
                i,
                _number(value, p.get("unit", "")),
                ha="left" if value >= 0 else "right",
                va="center",
                fontsize=11,
                weight="bold",
                color=theme["text"],
            )
    ax.set_xlabel(p.get("y_label") or p["y"])


def _line(frame, p, theme, ax):
    _numeric(frame, p["y"])
    series = (
        [
            (str(key), part.copy())
            for key, part in frame.groupby(p["group"], sort=False, dropna=False)
        ]
        if p.get("group")
        else [("", frame.copy())]
    )
    if len(series) > 8:
        raise ValueError("折线图最多8个系列，请先筛选")
    dates = (
        frame[p["x"]].map(lambda v: bool(re.match(r"^\d{4}-\d{2}-\d{2}", str(v)))).all()
    )
    numeric_x = pd.api.types.is_numeric_dtype(frame[p["x"]])
    categories = list(dict.fromkeys(str(v) for v in frame[p["x"]]))
    all_x, all_y = [], []
    for index, (name, part) in enumerate(series):
        if part[p["x"]].duplicated().any():
            raise ValueError("同一折线系列包含重复x，请先在SQL明确聚合")
        if dates:
            part = part.assign(
                _date=pd.to_datetime(part[p["x"]], errors="raise")
            ).sort_values("_date")
            x = mdates.date2num(part["_date"].to_numpy())
        elif numeric_x:
            part = part.sort_values(p["x"])
            x = _numeric(part, p["x"])
        else:
            x = np.array([categories.index(str(v)) for v in part[p["x"]]])
        y = _numeric(part, p["y"])
        all_x.extend(x)
        all_y.extend(y)
        color = theme["palette"][index % len(theme["palette"])]
        ax.plot(
            x,
            y,
            color=color,
            linewidth=2.7,
            linestyle="-" if index < len(theme["palette"]) else "--",
            marker="o",
            markersize=4.5,
            markeredgecolor=theme["card"],
            markeredgewidth=1,
            label=name or p["y"],
            zorder=3,
        )
        if len(series) == 1 and len(x) > 1 and np.ptp(x) > 0:
            lower = float(y.min()) - max(
                float(np.ptp(y)) * 0.25, abs(float(y.mean())) * 0.03, 1e-6
            )
            upper = float(y.max())
            if upper > lower:
                rgba = np.zeros((256, 1, 4))
                rgba[:, :, :3] = to_rgb(color)
                rgba[:, :, 3] = np.linspace(0.015, 0.25, 256)[:, None]
                image = ax.imshow(
                    rgba,
                    extent=[x.min(), x.max(), lower, upper],
                    aspect="auto",
                    origin="lower",
                    zorder=1,
                )
                polygon = Polygon(
                    np.vstack([[x[0], lower], np.column_stack([x, y]), [x[-1], lower]]),
                    closed=True,
                    transform=ax.transData,
                )
                image.set_clip_path(polygon)
        if p.get("annotate", True):
            for i in sorted(set([int(np.argmax(y)), len(y) - 1])):
                ax.scatter(
                    [x[i]],
                    [y[i]],
                    s=90,
                    color=color,
                    edgecolor=theme["card"],
                    linewidth=2,
                    zorder=4,
                )
                ax.annotate(
                    _number(y[i], p.get("unit", "")),
                    (x[i], y[i]),
                    xytext=(0, 11),
                    textcoords="offset points",
                    ha="center",
                    fontsize=9,
                    color=color,
                    weight="bold",
                )
    if dates:
        locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    elif not numeric_x:
        ticks = np.unique(
            np.linspace(0, len(categories) - 1, min(8, len(categories)), dtype=int)
        )
        ax.set_xticks(ticks, [categories[i] for i in ticks])
    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    x_pad = max((x_max - x_min) * 0.07, 0.5)
    y_pad = max((y_max - y_min) * 0.2, abs(float(np.mean(all_y))) * 0.03, 1e-6)
    ax.set_xlim(x_min - x_pad, x_max + x_pad)
    ax.set_ylim(y_min - y_pad, y_max + 1.5 * y_pad)
    if len(series) > 1:
        ax.legend(
            loc="upper left",
            ncol=min(3, len(series)),
            fontsize=9,
            labelcolor=theme["text"],
        )
    ax.set_xlabel(p.get("x_label") or p["x"])
    ax.set_ylabel(p.get("y_label") or p["y"])


def _scatter(frame, p, theme, ax):
    x, y = _numeric(frame, p["x"]), _numeric(frame, p["y"])
    sizes = np.full(len(frame), 100.0)
    if p.get("value"):
        weights = _numeric(frame, p["value"])
        if (weights < 0).any():
            raise ValueError("气泡面积不能使用负值")
        sizes = 65 + 280 * weights / max(float(weights.max()), 1.0)
    if p.get("group"):
        groups = list(dict.fromkeys(str(v) for v in frame[p["group"]]))
        if len(groups) > 12:
            raise ValueError("散点分组最多12类")
        for i, key in enumerate(groups):
            mask = frame[p["group"]].astype(str).to_numpy() == key
            ax.scatter(
                x[mask],
                y[mask],
                s=sizes[mask],
                color=theme["palette"][i % len(theme["palette"])],
                label=key,
                marker="o" if i < len(theme["palette"]) else "D",
                alpha=0.85,
                edgecolor=theme["card"],
                linewidth=1.8,
                zorder=3,
            )
        ax.legend(fontsize=9, labelcolor=theme["text"])
    else:
        cmap = LinearSegmentedColormap.from_list(
            "scatter", [theme["palette"][0], theme["accent"]]
        )
        ax.scatter(
            x,
            y,
            s=sizes,
            c=y,
            cmap=cmap,
            alpha=0.85,
            edgecolor=theme["card"],
            linewidth=1.8,
            zorder=3,
        )
    if p.get("annotate", True) and p.get("label"):
        for i in np.argsort(y)[-min(5, len(y)) :]:
            ax.annotate(
                str(frame.iloc[i][p["label"]]),
                (x[i], y[i]),
                xytext=(7, 8),
                textcoords="offset points",
                fontsize=9,
                color=theme["text"],
            )
    ax.margins(0.18)
    ax.set_xlabel(p.get("x_label") or p["x"])
    ax.set_ylabel(p.get("y_label") or p["y"])


def _heatmap(frame, p, theme, ax, fig):
    if p.get("value"):
        frame = frame.assign(**{p["value"]: _numeric(frame, p["value"])})
        if frame.duplicated([p["x"], p["y"]]).any() and not p.get("aggregation"):
            raise ValueError("热力图格子存在重复值，请先聚合或显式指定aggregation")
        matrix = (
            frame.pivot_table(
                index=p["y"],
                columns=p["x"],
                values=p["value"],
                aggfunc=p["aggregation"],
            )
            if p.get("aggregation")
            else frame.pivot(index=p["y"], columns=p["x"], values=p["value"])
        )
    else:
        matrix = (
            frame.select_dtypes(include="number")
            .drop(columns=[p["x"]], errors="ignore")
            .copy()
        )
        matrix.index = frame[p["x"]].astype(str)
        if matrix.empty:
            raise ValueError("宽表热力图没有数值列")
        if p["y"] not in matrix.columns:
            raise ValueError("宽表热力图的y必须是数值列")
        if matrix.index.duplicated().any():
            raise ValueError("宽表行标签重复，请明确区分或先聚合")
    if p.get("fill_value") is not None:
        matrix = matrix.fillna(p["fill_value"])
    if max(matrix.shape) > 40:
        raise ValueError("热力图最多40行/列，请明确筛选")
    values = matrix.to_numpy(dtype=float)
    if np.isinf(values).any():
        raise ValueError("热力图不能包含无穷值")
    if not np.isfinite(values).any():
        raise ValueError("热力图没有有效值")
    cmap = LinearSegmentedColormap.from_list("heatmap", theme["heatmap"]).with_extremes(
        bad=theme["grid"]
    )
    image = ax.imshow(
        np.ma.masked_invalid(values), cmap=cmap, aspect="auto", interpolation="nearest"
    )
    ax.grid(False)
    ax.spines[:].set_visible(False)
    ax.set_xticks(
        range(len(matrix.columns)),
        [_label(c) for c in matrix.columns],
        rotation=45,
        ha="right",
        fontsize=9,
    )
    ax.set_yticks(
        range(len(matrix.index)), [_label(c) for c in matrix.index], fontsize=9
    )
    ax.set_xticks(np.arange(-0.5, len(matrix.columns), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(matrix.index), 1), minor=True)
    ax.grid(which="minor", color=theme["card"], linewidth=2)
    ax.tick_params(which="minor", length=0)
    if p.get("annotate", True) and values.size <= 120:
        for row, col in np.ndindex(values.shape):
            if not np.isfinite(values[row, col]):
                continue
            rgb = cmap(image.norm(values[row, col]))[:3]
            ink = (
                "#FFFFFF" if np.dot(rgb, [0.2126, 0.7152, 0.0722]) < 0.52 else "#26314B"
            )
            ax.text(
                col,
                row,
                _number(values[row, col]),
                ha="center",
                va="center",
                fontsize=8,
                color=ink,
            )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.035)
    colorbar.outline.set_visible(False)
    colorbar.set_label(
        p.get("unit") or p.get("value") or p["y"], fontsize=8, color=theme["muted"]
    )
    ax.set_xlabel(p.get("x_label") or p["x"])
    ax.set_ylabel(p.get("y_label") or (p["y"] if p.get("value") else p["x"]))
    return {
        "matrix_rows": len(matrix.index),
        "matrix_columns": len(matrix.columns),
        "missing_cells": int(np.isnan(values).sum()),
    }


def _donut(frame, p, theme, ax):
    values = _numeric(frame, p["y"])
    if len(frame) > 10 or (values < 0).any() or values.sum() <= 0:
        raise ValueError("环形图需1–10类非负数值且合计大于零")
    labels = frame[p["x"]].astype(str).tolist()
    ax.grid(False)
    ax.set_position([0.12, 0.15, 0.77, 0.59])
    wedges, _, texts = ax.pie(
        values,
        colors=[
            theme["palette"][i % len(theme["palette"])] for i in range(len(values))
        ],
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.28, "edgecolor": theme["card"], "linewidth": 4},
        autopct=lambda pct: f"{pct:.1f}%" if pct >= 5 else "",
        pctdistance=0.85,
        textprops={"fontsize": 9, "weight": "bold"},
    )
    for wedge, text in zip(wedges, texts):
        luminance = np.dot(wedge.get_facecolor()[:3], [0.2126, 0.7152, 0.0722])
        text.set_color("#26314B" if luminance > 0.55 else "#FFFFFF")
    ax.text(
        0,
        0.07,
        _number(values.sum(), p.get("unit", "")),
        ha="center",
        va="center",
        fontsize=24,
        weight="bold",
        color=theme["text"],
    )
    ax.text(
        0,
        -0.15,
        "返回数据合计",
        ha="center",
        va="center",
        fontsize=9,
        color=theme["muted"],
    )
    ax.legend(
        wedges,
        [f"{label}  {_number(value)}" for label, value in zip(labels, values)],
        loc="center left",
        bbox_to_anchor=(1, 0.5),
        fontsize=10,
        labelcolor=theme["text"],
    )


def render_chart(frame, params, theme):
    frame = pd.DataFrame(frame).copy()
    if frame.empty:
        raise ValueError("没有可绘制的数据")
    required = {
        params["x"],
        params["y"],
        *[params[k] for k in ("group", "label", "value") if params.get(k)],
    }
    if required - set(frame.columns):
        raise ValueError("绘图字段不存在")
    kind = params["kind"]
    heights = {
        "bar": max(5.8, 3.6 + len(frame) * 0.38),
        "heatmap": 7,
        "line": 6.3,
        "scatter": 6.3,
        "donut": 6.3,
    }
    if kind not in heights:
        raise ValueError("未知图表类型")
    with plt.rc_context():
        apply_plot_style(theme)
        fig, ax = _canvas(params, theme, len(frame), min(15, heights[kind]))
        try:
            extra = {}
            if kind == "bar":
                _bar(frame, params, theme, ax)
            elif kind == "line":
                _line(frame, params, theme, ax)
            elif kind == "scatter":
                _scatter(frame, params, theme, ax)
            elif kind == "heatmap":
                extra = _heatmap(frame, params, theme, ax, fig)
            else:
                _donut(frame, params, theme, ax)
            if kind in {"line", "scatter"}:
                ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
        except Exception:
            plt.close(fig)
            raise
    return {"kind": kind, "theme": theme["name"], "rows": len(frame), **extra}

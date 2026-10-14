"""Plot contracts and trusted code generation, outside the ReAct kernel."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class PlotArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    kind: Literal["bar", "line", "scatter", "heatmap", "donut"] = "bar"
    x: str
    y: str
    title: str = Field(default="", max_length=120)
    theme: str | None = Field(
        default=None,
        max_length=40,
        description="主题：aurora / midnight / sunset；省略时使用目录default_theme，目录可独立扩展",
    )
    subtitle: str = Field(default="", max_length=300)
    x_label: str = Field(default="", max_length=100)
    y_label: str = Field(default="", max_length=100)
    unit: str = Field(default="", max_length=20)
    group: str | None = Field(default=None, description="折线/散点分系列的列名")
    label: str | None = Field(default=None, description="散点中对象名称的列名")
    value: str | None = Field(
        default=None, description="热力图长表的数值列；散点气泡面积的数值列"
    )
    aggregation: Literal["sum", "mean", "max", "min"] | None = None
    fill_value: float | None = Field(default=None, allow_inf_nan=False)
    annotate: bool = True
    caption: str = Field(default="", max_length=300)


def build_plot_code(args, dataset, catalog):
    theme = args.theme or (catalog or {}).get("default_theme")
    if not catalog or theme not in catalog["themes"]:
        raise ValueError("未知绘图主题，请先读取list_plot_templates")
    if not dataset.get("rows"):
        raise ValueError("数据集没有可绘制的数据")
    fields = {args.x, args.y, *[v for v in (args.group, args.label, args.value) if v]}
    missing = fields - set(dataset["columns"])
    if missing:
        raise ValueError("绘图字段不存在：" + ", ".join(sorted(missing)))
    params = args.model_dump(exclude={"dataset_id", "theme"})
    if dataset.get("truncated"):
        params["caption"] = (
            "查询结果已截断，图表仅展示返回数据 · " + params["caption"]
        ).strip(" ·")
    return f"result = render_chart(df, {params!r}, plot_themes[{theme!r}])"

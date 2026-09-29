"""Build chart requests without exposing application IO to generated Python."""

import json
import math

from ..plot_runtime.worker import validate_plot_code


_TEMPLATES = {
    "bar": {
        "description": "横向排名条形图，适合玩家、英雄、底蕴和胜率排名。",
        "columns": {"label": "玩家/英雄名", "value": "数值"},
        "code": "df = df.sort_values('value', ascending=False).head(20)\nsns.barplot(data=df, x='value', y='label', color='#24A69A', ax=ax)\nax.set_xlabel('数值')\nax.set_ylabel('')",
    },
    "line": {
        "description": "多序列趋势图，适合按日期比较玩家评分、胜率或时长。",
        "columns": {"x": "日期/有序时间点", "value": "数值", "series": "玩家/英雄/指标"},
        "code": "sns.lineplot(data=df, x='x', y='value', hue='series', marker='o', linewidth=2.8, errorbar=None, ax=ax)\nax.tick_params(axis='x', rotation=30)\nax.set_xlabel('日期')\nax.set_ylabel('数值')",
    },
    "scatter": {
        "description": "气泡散点图，适合比较出场数、胜率、评分、贡献等两个指标。",
        "columns": {"x": "横轴指标", "value": "纵轴指标", "series": "分组", "size": "气泡大小（出场数等）"},
        "code": "sns.scatterplot(data=df, x='x', y='value', hue='series', size='size', sizes=(70, 420), alpha=0.82, edgecolor='white', linewidth=1.2, ax=ax)\nax.set_xlabel('横轴指标')\nax.set_ylabel('纵轴指标')",
    },
    "heatmap": {
        "description": "矩阵热力图，适合共玩组合、玩家英雄交叉表现或分路对位。",
        "columns": {"label": "行分组", "x": "列分组", "value": "数值；重复组合取均值"},
        "code": "matrix = df.pivot_table(index='label', columns='x', values='value', aggfunc='mean')\nsns.heatmap(matrix, annot=True, fmt='.1f', cmap='YlGnBu', linewidths=2, linecolor='#F5F7FA', cbar=True, ax=ax)\nax.set_xlabel('')\nax.set_ylabel('')",
    },
    "distribution": {
        "description": "分组分布图，适合展示评分、底蕴、时长等分布，避免均值掩盖离散程度。",
        "columns": {"value": "单条观测数值", "series": "玩家/英雄/分组"},
        "code": "sns.histplot(data=df, x='value', hue='series', bins=16, element='step', alpha=0.30, stat='count', common_norm=False, ax=ax)\nax.set_xlabel('数值')\nax.set_ylabel('场次')",
    },
}


def chat_plot_templates():
    """Return examples copied into the model's plotting tool documentation."""
    return {
        "templates": [dict(name=name, **item) for name, item in _TEMPLATES.items()],
        "python_contract": (
            "data 是当前对话 SQL observation 的 rows；df=pd.DataFrame(data)，fig、ax 已创建；"
            "可用 pd、np、sns、plt 的受限绘图/数值函数，无需 import。"
            "支持变量赋值、列访问、算术、DataFrame.sort_values/head/pivot_table/groupby/agg、"
            "Series 统计以及 ax 标题/标签/刻度/图例。禁止文件/网络/进程/反射、函数定义和循环；"
            "不要 savefig/show，harness 自动保存 PNG。SQL 可直接 AS 成模板字段，"
            "或用 options.columns 传绘图字段到真实字段的映射（模板和自定义代码均生效）。不得编造数据。"
        ),
    }


def prepare_chat_plot(data, code=None, template="bar", title="", options=None, config=None):
    """Validate JSON-sized data and code before starting an isolated worker."""
    config = config or {}
    max_rows = min(2000, max(1, int(config.get("max_rows", 500))))
    if not isinstance(data, list) or not data:
        raise ValueError("chat_plot: data 必须是非空 SQL rows 数组")
    if len(data) > max_rows:
        raise ValueError(f"chat_plot: 数据超过 {max_rows} 行，请先在 SQL 中聚合或限制行数")
    for row in data:
        if not isinstance(row, dict) or len(row) > 50:
            raise ValueError("chat_plot: 每行必须是最多 50 列的对象")
        for key, value in row.items():
            if not isinstance(key, str) or len(key) > 120:
                raise ValueError("chat_plot: 列名必须是短字符串")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError("chat_plot: 请在 SQL 中展开嵌套 JSON 字段")
            if isinstance(value, str) and len(value) > 1000:
                raise ValueError("chat_plot: 单元格文本超过 1000 字符")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("chat_plot: 数值必须是有限数或 null")
    if not isinstance(title, str) or len(title) > 160:
        raise ValueError("chat_plot: 标题最多 160 字符")
    options = options or {}
    if not isinstance(options, dict) or set(options) - {"columns", "subtitle", "xlabel", "ylabel"}:
        raise ValueError("chat_plot: options 仅支持 columns/subtitle/xlabel/ylabel")
    columns = options.get("columns", {})
    if not isinstance(columns, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in columns.items()):
        raise ValueError("chat_plot: columns 必须是绘图字段到真实字段的映射")
    if len(columns) > 50 or any(len(key) > 120 or len(value) > 120 for key, value in columns.items()):
        raise ValueError("chat_plot: columns 最多 50 项，字段名最多 120 字符")
    missing_sources = sorted({source for source in columns.values() if any(source not in row for row in data)})
    if missing_sources:
        raise ValueError(f"chat_plot: columns 映射的真实字段不存在 {missing_sources!r}")
    for key in ("subtitle", "xlabel", "ylabel"):
        if key in options and (not isinstance(options[key], str) or len(options[key]) > 200):
            raise ValueError(f"chat_plot: {key} 最多 200 字符")
    if code is None or code == "":
        if template not in _TEMPLATES:
            raise ValueError(f"chat_plot: 未知模板 {template!r}")
        definition = _TEMPLATES[template]
        required = set(definition["columns"])
        if set(columns) - required:
            raise ValueError("chat_plot: columns 包含非模板字段")
        available = set(data[0])
        missing = [name for name in required if columns.get(name, name) not in available]
        if missing:
            raise ValueError(f"chat_plot: 模板缺少字段 {missing!r}；请使用 SQL AS 或 options.columns")
        code = definition["code"]
    if columns:
        data = [{**row, **{name: row[source] for name, source in columns.items()}} for row in data]
    max_code = min(12000, max(100, int(config.get("max_code_chars", 12000))))
    validate_plot_code(code, max_code_chars=max_code)
    payload = {"data": data, "code": code, "title": title, "options": options}
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
        raise ValueError("chat_plot: 请求超过 1 MiB，请减少数据")
    return payload


def render_chat_plot(data, code=None, template="bar", title="", options=None):
    from .. import zfile
    from .. import zstatic

    config = getattr(zstatic, "chat_plot_config", {})
    payload = prepare_chat_plot(data, code=code, template=template, title=title, options=options, config=config)
    result = zfile.render_chat_plot_worker(payload, config=config)
    return dict(result, template="python" if code else template, row_count=len(data))

"""Trusted standalone worker; model Python is interpreted, never passed to exec.

Only documented plotting/data capabilities are dispatched. The worker has no
application imports, secrets, database handles, or user-controlled output paths.
Its stdin/stdout and resource setup are a deliberate runtime IO boundary.
"""

import ast


_MODULE_FUNCTIONS = {
    "np": {"array", "arange", "linspace", "mean", "median", "std", "sum", "min", "max", "abs", "round", "sqrt", "log", "log10", "clip", "percentile", "quantile", "where", "isnan", "isfinite", "unique", "histogram", "corrcoef"},
    "pd": {"DataFrame", "Series", "to_numeric", "to_datetime", "concat", "crosstab"},
    "sns": {"barplot", "lineplot", "scatterplot", "heatmap", "histplot", "boxplot", "violinplot", "stripplot", "pointplot", "despine"},
    "plt": {"subplots", "plot", "bar", "barh", "scatter", "hist", "boxplot", "violinplot", "xlabel", "ylabel", "title", "legend", "xticks", "yticks", "xlim", "ylim", "grid", "tight_layout", "axhline", "axvline"},
}
_METHODS = {
    "frame": {"head", "tail", "sort_values", "sort_index", "rename", "fillna", "dropna", "reset_index", "set_index", "pivot", "pivot_table", "groupby", "agg", "aggregate", "mean", "median", "sum", "min", "max", "std", "count", "round", "clip", "astype", "drop", "corr", "nlargest", "nsmallest"},
    "series": {"head", "tail", "sort_values", "sort_index", "fillna", "dropna", "reset_index", "value_counts", "mean", "median", "sum", "min", "max", "std", "count", "round", "clip", "astype", "tolist", "unique", "nunique", "nlargest", "nsmallest", "isin", "between"},
    "group": {"mean", "median", "sum", "min", "max", "std", "count", "size", "agg", "aggregate"},
    "array": {"tolist", "mean", "sum", "min", "max", "std", "round", "reshape", "flatten"},
    "axes": {"plot", "bar", "barh", "scatter", "hist", "boxplot", "violinplot", "set_title", "set_xlabel", "set_ylabel", "set_xlim", "set_ylim", "set_xticks", "set_yticks", "set_xticklabels", "set_yticklabels", "tick_params", "legend", "grid", "axhline", "axvline", "invert_yaxis", "text", "annotate", "fill_between", "set_xscale", "set_yscale"},
    "figure": {"suptitle", "supxlabel", "supylabel", "tight_layout", "subplots_adjust", "text"},
}
_ATTRIBUTES = {
    "frame": {"columns", "index", "shape", "values", "T"},
    "series": {"index", "shape", "values"},
    "array": {"shape", "T", "size"},
    "axes": {"transAxes"},
}
_BUILTINS = {"len": len, "min": min, "max": max, "sum": sum, "abs": abs, "round": round, "str": str, "int": int, "float": float, "list": list, "tuple": tuple}
_ALLOWED_AST = (
    ast.Module, ast.Assign, ast.Expr, ast.Import, ast.ImportFrom, ast.alias,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Dict,
    ast.Call, ast.keyword, ast.Attribute, ast.Subscript, ast.Slice,
    ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.BitAnd, ast.BitOr, ast.USub, ast.UAdd, ast.Invert,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)
_IMPORTS = {"numpy": "np", "pandas": "pd", "seaborn": "sns", "matplotlib.pyplot": "plt"}
_RESERVED = set(_MODULE_FUNCTIONS) | set(_BUILTINS) | {"data"}
_AGGREGATIONS = {"mean", "median", "sum", "min", "max", "std", "count", "size", "nunique", "first", "last"}


def validate_plot_code(code, max_code_chars=12000):
    if not isinstance(code, str) or not code.strip() or len(code) > max_code_chars:
        raise ValueError(f"chat_plot: Python 代码不能为空且最多 {max_code_chars} 字符")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"chat_plot: Python 语法错误，行 {exc.lineno}: {exc.msg}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 1500:
        raise ValueError("chat_plot: Python AST 超过 1500 节点")
    for node in nodes:
        if not isinstance(node, _ALLOWED_AST):
            raise ValueError(f"chat_plot: 不支持的 Python 语法 {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("chat_plot: 禁止私有名称")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("chat_plot: 禁止私有属性/反射")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in _MODULE_FUNCTIONS:
                if node.attr not in _MODULE_FUNCTIONS[node.value.id]:
                    raise ValueError(f"chat_plot: 不允许 {node.value.id}.{node.attr}")
            elif node.attr not in set().union(*_METHODS.values(), *_ATTRIBUTES.values()):
                raise ValueError(f"chat_plot: 不允许属性/方法 {node.attr}")
        if isinstance(node, ast.Assign):
            targets = node.targets
            for target in targets:
                items = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]
                if any(not isinstance(item, ast.Name) or item.id in _RESERVED for item in items):
                    raise ValueError("chat_plot: 仅允许赋值到局部变量，不能修改能力/属性/原始数据")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, (ast.Name, ast.Attribute)):
                raise ValueError("chat_plot: 禁止动态调用")
            if isinstance(node.func, ast.Name) and node.func.id not in _BUILTINS:
                raise ValueError(f"chat_plot: 不允许函数 {node.func.id}")
            if any(item.arg is None or item.arg.startswith("_") for item in node.keywords):
                raise ValueError("chat_plot: 禁止动态关键字参数")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 2000:
            raise ValueError("chat_plot: 字符串常量过长")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in _IMPORTS or _IMPORTS[alias.name] != alias.asname:
                    raise ValueError("chat_plot: import 仅支持 numpy as np / pandas as pd / seaborn as sns / matplotlib.pyplot as plt")
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module != "matplotlib" or len(node.names) != 1 or node.names[0].name != "pyplot" or node.names[0].asname != "plt":
                raise ValueError("chat_plot: 不支持此 from import")
    return tree


class PlotInterpreter:
    """Interpret data expressions using an explicit, typed capability dispatch."""

    def __init__(self, data, fig, ax, modules):
        self.modules = modules
        self.values = dict(data=data, df=modules["pd"].DataFrame(data), fig=fig, ax=ax)
        self.steps = 0

    def _kind(self, obj):
        from matplotlib.axes import Axes
        from matplotlib.figure import Figure
        from pandas.core.groupby.generic import DataFrameGroupBy, SeriesGroupBy

        pd, np = self.modules["pd"], self.modules["np"]
        for typ, name in ((pd.DataFrame, "frame"), (pd.Series, "series"), (np.ndarray, "array"), (Axes, "axes"), (Figure, "figure"), (DataFrameGroupBy, "group"), (SeriesGroupBy, "group")):
            if isinstance(obj, typ):
                return name
        return None

    def _aggregation(self, value):
        if isinstance(value, str):
            return value in _AGGREGATIONS
        if isinstance(value, (list, tuple)):
            return all(self._aggregation(item) for item in value)
        if isinstance(value, dict):
            return all(self._aggregation(item) for item in value.values())
        return False

    def _check_options(self, value):
        if isinstance(value, dict):
            if any(str(key).lower() in {"usetex", "text.usetex"} and item for key, item in value.items()):
                raise ValueError("chat_plot: 禁止外部 TeX")
            for item in value.values():
                self._check_options(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._check_options(item)

    def _call(self, node):
        args = [self.evaluate(item) for item in node.args]
        kwargs = {item.arg: self.evaluate(item.value) for item in node.keywords}
        self._check_options(kwargs)
        if isinstance(node.func, ast.Name):
            return _BUILTINS[node.func.id](*args, **kwargs)
        target = node.func.value
        name = node.func.attr
        if isinstance(target, ast.Name) and target.id in self.modules:
            module_name = target.id
            if name not in _MODULE_FUNCTIONS[module_name]:
                raise ValueError(f"chat_plot: 不允许 {module_name}.{name}")
            obj = self.modules[module_name]
        else:
            obj = self.evaluate(target)
            kind = self._kind(obj)
            if name not in _METHODS.get(kind, set()):
                raise ValueError(f"chat_plot: 不允许 {kind or type(obj).__name__}.{name}")
        # Pandas can dispatch arbitrary methods by a string aggregation name.
        if name in {"agg", "aggregate", "pivot_table"}:
            function = kwargs.get("aggfunc", kwargs.get("func", args[0] if args and name != "pivot_table" else "mean"))
            if not self._aggregation(function):
                raise ValueError("chat_plot: 聚合函数仅允许内置数值统计")
            if name in {"agg", "aggregate"} and not args and "func" not in kwargs:
                raise ValueError("chat_plot: agg 必须显式指定 func")
            if name == "pivot_table" and args:
                raise ValueError("chat_plot: pivot_table 仅允许关键字参数")
        if name in {"subplots"}:
            if len(args) > 2 or any(not isinstance(item, int) or not 1 <= item <= 4 for item in args):
                raise ValueError("chat_plot: subplots 最多 4×4")
            if any(not isinstance(kwargs[key], int) or not 1 <= kwargs[key] <= 4 for key in ("nrows", "ncols") if key in kwargs):
                raise ValueError("chat_plot: subplots 最多 4×4")
        if "figsize" in kwargs:
            size = kwargs["figsize"]
            if not isinstance(size, (tuple, list)) or len(size) != 2 or any(not isinstance(v, (int, float)) or not 2 <= v <= 16 for v in size):
                raise ValueError("chat_plot: figsize 范围为 2–16 英寸")
        if "dpi" in kwargs and (not isinstance(kwargs["dpi"], (int, float)) or not 50 <= kwargs["dpi"] <= 160):
            raise ValueError("chat_plot: dpi 范围为 50–160")
        if kwargs.get("usetex") or kwargs.get("text.usetex"):
            raise ValueError("chat_plot: 禁止外部 TeX")
        # Restrict formatting/transform callbacks to in-memory literal values.
        if "formatter" in kwargs and kwargs["formatter"] is not None:
            raise ValueError("chat_plot: 禁止格式化回调")
        return getattr(obj, name)(*args, **kwargs)

    def evaluate(self, node):
        self.steps += 1
        if self.steps > 10000:
            raise ValueError("chat_plot: 操作预算耗尽")
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.values:
                raise ValueError(f"chat_plot: 未定义变量 {node.id}")
            return self.values[node.id]
        if isinstance(node, ast.List):
            return [self.evaluate(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self.evaluate(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {self.evaluate(k): self.evaluate(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.Attribute):
            obj = self.evaluate(node.value)
            if node.attr not in _ATTRIBUTES.get(self._kind(obj), set()):
                raise ValueError(f"chat_plot: 不允许属性 {node.attr}")
            return getattr(obj, node.attr)
        if isinstance(node, ast.Subscript):
            obj = self.evaluate(node.value)
            key = self.evaluate(node.slice)
            if not isinstance(obj, (list, tuple, dict, str)) and self._kind(obj) not in {"frame", "series", "array", "group"}:
                raise ValueError("chat_plot: 对象不可索引")
            return obj[key]
        if isinstance(node, ast.Slice):
            return slice(*(self.evaluate(item) if item is not None else None for item in (node.lower, node.upper, node.step)))
        if isinstance(node, ast.BinOp):
            import operator

            operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.BitAnd: operator.and_, ast.BitOr: operator.or_}
            left, right = self.evaluate(node.left), self.evaluate(node.right)
            if isinstance(node.op, ast.Mult):
                for seq, count in ((left, right), (right, left)):
                    if isinstance(seq, (str, list, tuple)) and isinstance(count, int) and len(seq) * max(count, 0) > 100000:
                        raise ValueError("chat_plot: 序列扩展超过限制")
            return operations[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            import operator

            return {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Invert: operator.invert}[type(node.op)](self.evaluate(node.operand))
        if isinstance(node, ast.Compare):
            import operator

            if len(node.ops) != 1:
                raise ValueError("chat_plot: 请将链式比较拆成逐项比较")
            operations = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
            return operations[type(node.ops[0])](self.evaluate(node.left), self.evaluate(node.comparators[0]))
        raise ValueError(f"chat_plot: 不支持表达式 {type(node).__name__}")

    def run(self, tree):
        for statement in tree.body:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                continue  # Capabilities were injected by trusted runtime code.
            if isinstance(statement, ast.Expr):
                self.evaluate(statement.value)
            elif isinstance(statement, ast.Assign):
                result = self.evaluate(statement.value)
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        self.values[target.id] = result
                    else:
                        if not isinstance(result, (list, tuple)) or len(result) != len(target.elts):
                            raise ValueError("chat_plot: 元组赋值数量不匹配")
                        self.values.update((name.id, value) for name, value in zip(target.elts, result))
        return self.values


def _limits(payload):
    import resource
    import sys

    cpu = min(45, max(3, int(payload.get("cpu_seconds", 15))))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith("linux"):
        memory = min(2048, max(512, int(payload.get("memory_mb", 1024)))) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))


def render(payload):
    import io

    _limits(payload)
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import seaborn as sns
    from matplotlib import font_manager

    if payload.get("font_path"):
        font_manager.fontManager.addfont(payload["font_path"])
        font_name = font_manager.FontProperties(fname=payload["font_path"]).get_name()
    else:
        font_name = next((item for item in ("Noto Sans CJK SC", "Noto Sans CJK JP", "WenQuanYi Micro Hei", "Microsoft YaHei", "SimHei", "PingFang SC", "Arial Unicode MS", "DejaVu Sans") if any(font.name == item for font in font_manager.fontManager.ttflist)), "DejaVu Sans")
    sns.set_theme(style="whitegrid", font=font_name, palette=["#229C91", "#5168BC", "#E89C45", "#C76787", "#64A4CC", "#8C80AC"], rc={"axes.facecolor": "#F5F7FA", "figure.facecolor": "#F5F7FA", "axes.edgecolor": "#DDE3EA", "grid.color": "#E1E7ED", "grid.linewidth": 0.7, "axes.spines.top": False, "axes.spines.right": False, "axes.labelcolor": "#46556C", "text.color": "#17263D", "xtick.color": "#62718A", "ytick.color": "#46556C", "font.size": 12, "axes.labelsize": 12, "xtick.labelsize": 11, "ytick.labelsize": 11, "axes.unicode_minus": False, "text.usetex": False, "text.parse_math": False})
    fig, ax = plt.subplots(figsize=(11.2, 7.2), dpi=130)
    interpreter = PlotInterpreter(payload["data"], fig, ax, {"np": np, "pd": pd, "sns": sns, "plt": plt})
    values = interpreter.run(validate_plot_code(payload["code"]))
    fig = values.get("fig", fig)
    from matplotlib.figure import Figure

    if not isinstance(fig, Figure):
        raise ValueError("chat_plot: fig 必须是 matplotlib Figure")
    if len(plt.get_fignums()) > 5:
        raise ValueError("chat_plot: 最多创建 5 个 figure")
    if any(not 2 <= size <= 16 for size in fig.get_size_inches()):
        raise ValueError("chat_plot: 图像尺寸超过限制")
    title = payload.get("title") or "对局数据观察"
    fig.suptitle(title, x=0.08, y=0.97, ha="left", fontsize=22, fontweight="bold", color="#17263D")
    subtitle = payload.get("options", {}).get("subtitle")
    if subtitle:
        fig.text(0.08, 0.90, subtitle, ha="left", fontsize=11, color="#718097")
    fig.text(0.08, 0.025, f"HOK  /  DATA OBSERVATIONS     ·     {len(payload['data'])} ROWS", ha="left", fontsize=9, color="#8895A8")
    for axis in fig.axes:
        if "xlabel" in payload.get("options", {}):
            axis.set_xlabel(payload["options"]["xlabel"])
        if "ylabel" in payload.get("options", {}):
            axis.set_ylabel(payload["options"]["ylabel"])
    fig.tight_layout(rect=(0.035, 0.055, 0.97, 0.88 if subtitle else 0.93), pad=1.4)
    output = io.BytesIO()
    fig.savefig(output, format="png", dpi=130, facecolor="#F5F7FA", metadata={"Software": "HOK Chat Plot Harness"})
    plt.close("all")
    return output.getvalue()


def main():
    import json
    import sys

    try:
        payload = json.loads(sys.stdin.buffer.read(1024 * 1024 + 1))
        content = render(payload)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("chat_plot: PNG 超过 8 MiB")
        sys.stdout.buffer.write(content)
    except Exception as exc:
        sys.stderr.write(f"chat_plot_worker: {type(exc).__name__}: {str(exc)[:1000]}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

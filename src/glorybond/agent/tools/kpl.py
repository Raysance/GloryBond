"""KPL tool schema/disclosure and data resources; no HTTP or kernel coupling."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model


def register_kpl_tool(registry, *, service, catalog):
    config = catalog["config"]
    if not config.get("enabled", True):
        return
    class Arguments(BaseModel):
        model_config = ConfigDict(extra="forbid")
        params: dict[str, Any] = Field(default_factory=dict, description="依 kpl 目录填写本网站参数；不得填 URL、SQL、QQ 或营地 ID")
        search: str = Field(default="", max_length=100, description="对返回列表的名称筛选，不用于详情；分页榜单禁止使用")
        offset: int = Field(default=0, ge=0, le=100000, strict=True)
        date_from: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", description="matches赛程的起始日期（含），带时区时间按Asia/Shanghai日历筛选，无时区时间保留原日期")
        date_to: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", description="matches赛程的结束日期（含）；今天查询将date_from与date_to设为当前日期")
        fields: list[str] = Field(default_factory=list, max_length=40, description="可选返回字段名，过大详情可只取需要的字段")
    model = create_model("KPLQueryArgs", __base__=Arguments,
        action=(Literal[tuple(catalog["actions"])], Field(description="先选赛事/对象列表取得本网站 ID，再读取详情；参数规范见 kpl 目录")),
        limit=(int, Field(default=min(20, config["max_rows"]), ge=1, le=config["max_rows"], strict=True)),
        nested_limit=(int, Field(default=min(20, config["max_nested_items"]), ge=1, le=config["max_nested_items"], strict=True)))

    async def query(args, ctx):
        result = await service.kpl_query(args.model_dump())
        rows = result["data"] if isinstance(result["data"], list) else [result["data"]]
        if rows and all(isinstance(row, dict) for row in rows):
            columns = list(dict.fromkeys(key for row in rows for key in row))
            result["dataset_id"] = ctx.add_resource({"rows": rows, "columns": columns,
                "row_count": len(rows), "truncated": result["truncated"], "source_url": result["source_url"]})
        return result

    registry.register(name="query_kpl", description=(
        "只读查询 kplll.online 的 KPL 赛事、比赛/单局详情、战队、选手、英雄、积分和榜单、英雄组合。"
        "先发现 kpl 目录，按本网站赛事与对象 ID 查询，不能混用营地、王者英雄或B站比赛ID。"
        "返回真实结构化数据、来源、范围、截断和 dataset_id，可交给 Python/绘图工具。"
        "日期/当前赛季由赛事列表核对；胜率要附样本，列表截断不等于完整统计，第三方收录不等于官方实时。"),
        args_model=model, handler=query, category="kpl", scopes=("web.read",),
        timeout=config["timeout_seconds"] + 10, effect="read", initially_visible=False)

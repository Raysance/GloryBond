"""On-demand page reading uses the channel's existing public-web adapter."""
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.models import ToolResult


class ReadWebPageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048, description="要读取的公开 HTTP/HTTPS 网页地址")
    offset: int = Field(default=0, ge=0, le=8388608, strict=True, description="正文读取起点；长页按返回 next_offset 继续")
    link_offset: int = Field(default=0, ge=0, le=1000000, strict=True, description="链接列表读取起点；按返回 next_link_offset 继续，链接只是候选，尚未访问")


def register_webpage_tool(registry, *, fetcher):
    if not fetcher.limits.enabled:
        return

    async def read(args, ctx):
        result = await fetcher.read(**args.model_dump())
        ok = result["status"] == "ok"
        return ToolResult(ok, data=result, error=result.get("error"),
                          code=None if ok else "WEBPAGE_UNAVAILABLE")

    registry.register(name="read_webpage", description=(
        "读取一个公开网页，返回可读正文、来源和链接地址/标签；长页与链接列表提供续读位置。"
        "每次只读指定页面，不自动跟随链接或解析二进制文档。"),
        args_model=ReadWebPageArgs, handler=read, category="internet", scopes=("web.read",),
        timeout=fetcher.limits.timeout_seconds + 2, effect="read", initially_visible=False)

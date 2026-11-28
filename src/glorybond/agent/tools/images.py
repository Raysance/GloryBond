"""Image reading uses the same discovery and execution contract as other tools."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadImageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_id: str | None = Field(default=None, pattern=r"^(?:[a-f0-9]{32}|[a-f0-9]{64})$",
                          description="当前、引用、入选历史或工具结果提供的图片附件编号")
    url: str | None = Field(default=None, min_length=1, max_length=2048, description="公开图片直链")
    local_path: str | None = Field(default=None, min_length=1, max_length=4096,
                                   description="授权图片目录内的绝对路径")

    @model_validator(mode="after")
    def one_source(self):
        if sum(bool(value) for value in (self.image_id, self.url, self.local_path)) != 1:
            raise ValueError("image_id、url、local_path 须且仅须提供一个")
        return self


def register_image_tool(registry, reader):
    async def read(args, ctx):
        if args.url and "web.read" not in ctx.principal.scopes:
            raise PermissionError("当前调用者没有网页读取权限")
        return await reader.read(run_id=ctx.request.run_id, **args.model_dump())

    registry.register(name="read_image", description=(
        "读取图片附件、公开图片直链或授权本地图片，通过独立视觉模型转写可见内容、文字、数字及位置关系，返回文字资料和实际用量。"
        "相同图片的完整转写可复用；动图只读取已抽取的画面。授权本地目录："
        + ("、".join(map(str, reader.local_roots)) or "未配置")),
        args_model=ReadImageArgs, handler=read, category="images", effect="read",
        timeout=reader.timeout_seconds + (reader.fetcher.limits.timeout_seconds if reader.fetcher else 0) + 5,
        initially_visible=False)

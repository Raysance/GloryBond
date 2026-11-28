"""Media inspection is a regular discovered read tool, with channel-bound inputs."""
import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadMediaArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$",
        description="本轮或同一会话提供的音视频附件编号；与 url、local_path 三选一")
    url: str | None = Field(default=None, min_length=1, max_length=2048,
        description="公开音视频文件直链，不是播放器网页；与 attachment_id、local_path 三选一")
    local_path: str | None = Field(default=None, min_length=1, max_length=4096,
        description="授权音视频目录内的绝对文件路径；与 attachment_id、url 三选一")
    question: str = Field(min_length=1, max_length=4000, description="本次需要从音视频中了解的问题")

    @model_validator(mode="after")
    def one_source(self):
        if sum(bool(value) for value in (self.attachment_id, self.url, self.local_path)) != 1:
            raise ValueError("须且仅须提供一种音视频来源")
        return self


def read_local_media(value, roots, max_bytes):
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError("请使用已确认的绝对路径")
    path = candidate.resolve()
    if not any(path.is_relative_to(Path(root).resolve()) for root in roots):
        raise PermissionError("文件不在授权音视频目录内")
    if not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
        raise ValueError("文件不存在、不是普通文件或超过音视频大小限制")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("文件超过音视频大小限制")
    return raw


def register_media_tool(registry, *, media, fetcher, local_roots=()):
    if not media.enabled:
        return
    roots = tuple(Path(root).expanduser().resolve() for root in local_roots)

    async def read(args, ctx):
        if args.attachment_id:
            result = await media.read_attachment(args.attachment_id, ctx.request.conversation_id, args.question)
        elif args.url:
            async def load():
                return (await fetcher.download(args.url, max_bytes=media.limits.max_bytes))["raw"]
            result = await media.read(source_key="url:" + args.url, loader=load, question=args.question)
        else:
            # Check authorization even on cache hits; local files can change.
            raw = await asyncio.to_thread(read_local_media, args.local_path, roots, media.limits.max_bytes)
            import hashlib
            async def load():
                return raw
            result = await media.read(source_key="local:" + hashlib.sha256(raw).hexdigest(), loader=load, question=args.question)
        # The analysis model received every transcript segment. Bound the observation
        # while explicitly preserving how much source text was returned.
        transcript = result["transcript"]
        return {**result, "transcript": transcript[:32000], "transcript_chars": len(transcript),
                "transcript_truncated": len(transcript) > 32000,
                "notice": "语音转写已完整供分析模型读取；画面仅为注明间隔的采样，不能证明采样间的动作细节。"}

    registry.register(name="read_media", description=(
        "按问题读取当前会话的音视频附件、公开媒体文件直链或授权本地文件。"
        "视频抽帧与完整第一音轨的分段转写一起交给内容理解模型；纯音频仅转写与分析。"
        f"最多{media.limits.max_bytes}字节、{media.limits.max_duration_seconds}秒，缓存复用，返回采样范围、转写、分析和实际用量。"
        "ASR不保留背景音效或语气。授权本地目录：" + ("、".join(str(root) for root in roots) or "未配置")),
        args_model=ReadMediaArgs, handler=read, category="media", scopes=("web.read",), effect="read",
        timeout=media.limits.timeout_seconds + 5, initially_visible=False)

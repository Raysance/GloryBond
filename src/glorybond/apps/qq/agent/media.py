"""Resolve only native media sources supplied by the validated QQ event/quote."""
from pathlib import Path
from urllib.parse import unquote, urlsplit

from glorybond.agent.tools.media import read_local_media


async def read_qq_media(source, *, fetcher, max_bytes, local_roots=(), bot=None):
    import asyncio

    url = source.get("url") or source.get("file") or ""
    if source["kind"] == "audio" and bot is not None:
        # OneBot converts native QQ voice formats into an ordinary WAV file.
        result = await bot.get_record(file=source.get("file") or url, out_format="wav")
        url = result.get("url") or result.get("file") or ""
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return (await fetcher.download(url, max_bytes=max_bytes))["raw"]
    if isinstance(url, str) and url.startswith("file://"):
        parts = urlsplit(url)
        if parts.netloc not in {"", "localhost"}:
            raise ValueError("QQ 媒体文件地址不可用")
        url = unquote(parts.path)
    if isinstance(url, str) and Path(url).is_absolute():
        return await asyncio.to_thread(read_local_media, url, local_roots, max_bytes)
    raise ValueError("QQ 未提供可读取的音视频地址，请重新发送或提供媒体文件")

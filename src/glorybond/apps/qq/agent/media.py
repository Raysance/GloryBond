"""Resolve only native media sources supplied by the validated QQ event/quote."""
from pathlib import Path
from urllib.parse import unquote, urlsplit

from glorybond.agent.tools.media import read_local_media


def _media_size(value):
    if value in (None, "", 0, "0"):
        return None
    if type(value) not in (str, int) or not str(value).isdigit() or int(value) <= 0:
        raise ValueError("QQ 媒体大小无效，无法核对文件")
    return int(value)


async def read_qq_media(source, *, fetcher, max_bytes, local_roots=(), bot=None,
                        prefer_cached_video=False):
    import asyncio

    expected_size = _media_size(source.get("file_size"))
    if expected_size and expected_size > max_bytes:
        raise ValueError("QQ 音视频超过读取大小限制")

    def checked(raw):
        if expected_size is not None and len(raw) != expected_size:
            raise ValueError("QQ 返回的音视频与消息记录的文件大小不一致，未读取内容")
        return raw

    # Only a verified quote authored by this bot can resolve a bare filename
    # against the bot's own media roots. Other senders cannot claim local files.
    filename = source.get("file")
    if (prefer_cached_video and source["kind"] == "video" and expected_size
            and isinstance(filename, str) and filename not in {"", ".", ".."}
            and Path(filename).name == filename and "\\" not in filename):
        for root in local_roots:
            path = Path(root) / filename
            if path.is_file():
                return checked(await asyncio.to_thread(read_local_media, str(path), local_roots, max_bytes))

    url = source.get("url") or source.get("file") or ""
    if source["kind"] == "audio" and bot is not None:
        # OneBot converts native QQ voice formats into an ordinary WAV file.
        result = await bot.get_record(file=source.get("file") or url, out_format="wav")
        url = result.get("url") or result.get("file") or ""
        # Conversion changes the byte size; the original SILK size cannot be
        # used to validate the resulting WAV.
        expected_size = _media_size(result.get("file_size"))
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        raw = (await fetcher.download(url, max_bytes=min(max_bytes, expected_size or max_bytes)))["raw"]
        return checked(raw)
    if isinstance(url, str) and url.startswith("file://"):
        parts = urlsplit(url)
        if parts.netloc not in {"", "localhost"}:
            raise ValueError("QQ 媒体文件地址不可用")
        url = unquote(parts.path)
    if isinstance(url, str) and Path(url).is_absolute():
        return checked(await asyncio.to_thread(read_local_media, url, local_roots, max_bytes))
    raise ValueError("QQ 未提供可读取的音视频地址，请重新发送或提供媒体文件")

"""Read attachments identified by QQ's native message, within the current chat."""
import asyncio
from pathlib import PurePath
import time
from weakref import WeakValueDictionary
from urllib.parse import urljoin

import httpx

from glorybond.agent.document_inputs import DeepSeekDocuments, MAX_DOCUMENT_BYTES, document_name, read_document_bytes
from glorybond.agent.webpages import public_address


async def read_qq_document(bot, group_id, source):
    document_name(source["name"])
    if int(source.get("size") or 0) > MAX_DOCUMENT_BYTES:
        raise ValueError("单份文件超过 16 MiB")
    async with asyncio.timeout(35):
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            if not source.get("id"):
                raise ValueError("QQ 未提供文件下载信息")
            if group_id is None:
                response = await bot.get_private_file_url(file_id=source["id"])
            else:
                response = await bot.get_group_file_url(group_id=group_id, file_id=source["id"],
                                                        busid=source.get("busid") or 0)
            url = response.get("url")
        for _ in range(4):
            original = httpx.URL(url or "")
            if original.scheme not in {"http", "https"} or not original.host or original.userinfo:
                break
            ip = await public_address(original.host, original.port or (443 if original.scheme == "https" else 80))
            async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
                async with client.stream("GET", original.copy_with(host=ip),
                        headers={"Host": original.netloc.decode("ascii"), "Accept-Encoding": "identity"},
                        extensions={"sni_hostname": original.host}) as response:
                    if response.is_redirect and response.headers.get("location"):
                        url = urljoin(str(original), response.headers["location"])
                        continue
                    if response.status_code != 200 or response.headers.get("content-encoding", "identity") != "identity":
                        break
                    return await read_document_bytes(response.aiter_raw())
    raise ValueError("QQ 文件下载失败或链接已失效")


class QQDocuments:
    def __init__(self, remote):
        self.provider = DeepSeekDocuments(remote)
        self.cache = {}
        self.locks = WeakValueDictionary()

    async def _load(self, source, name, key, read_file):
        async with self.locks.setdefault(key, asyncio.Lock()):
            cached = self.cache.get(key)
            if cached and cached["expires_at"] > time.time():
                return cached
            try:
                raw = await read_file(source)
            except Exception:
                # Adapter exceptions can contain signed download URLs.
                raise ValueError("QQ 文件下载失败、已过期或超过大小限制") from None
            part = await self.provider.upload(name, raw)
            if len(self.cache) >= 512:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = part
            return part

    async def prepare(self, sources, scope, message_id, read_file):
        parts = []
        for index, source in enumerate(sources):
            name = PurePath(str(source["name"]).replace("\\", "/")).name[:200]
            try:
                name = document_name(source["name"])
                key = (scope, str(message_id), index, name) if message_id is not None else object()
                parts.append(await self._load(source, name, key, read_file))
            except ValueError as exc:
                parts.append({"type": "text", "text": f"附件未读取：{name}（{exc}）"})
        return parts

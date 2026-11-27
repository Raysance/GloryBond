"""Official Search and Fetch protocols, independent of the model provider."""
import asyncio
import json
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class SearchRequest:
    endpoint: str
    payload: dict
    timeout: float
    result_type: str
    text_limit: int


def prepare_search(settings, query, max_results=5, result_type=None):
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 128:
        raise ValueError("deepseek_web_search: query must contain 1 to 128 characters")
    if type(max_results) is not int or not 1 <= max_results <= 10:
        raise ValueError("deepseek_web_search: max_results must be an integer from 1 to 10")
    if not settings.get("api_key"):
        raise RuntimeError("deepseek_web_search unavailable: configure .env "
                           + str(settings.get("api_key_env", "HOK_DEEPSEEK_API_KEY")))
    endpoint = str(settings.get("endpoint") or "").strip()
    parsed = urlparse(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise RuntimeError("deepseek_web_search: DeepSeekSearch.endpoint must be a valid HTTPS URL")
    mode = result_type or settings.get("result_type") or ("content" if settings.get("need_content") else "summary")
    if mode not in {"snippet", "summary", "content"}:
        raise ValueError("deepseek_web_search: result_type must be snippet, summary or content")
    timeout = float(settings.get("timeout_seconds", 30))
    ceiling = int(settings.get("max_result_chars", 6000))
    limit = int(settings.get(mode + "_chars", {"snippet": 400, "summary": 1200, "content": 6000}[mode]))
    if not 0 < timeout <= 40 or not 1 <= ceiling <= 6000 or not 1 <= limit <= 6000:
        raise ValueError("deepseek_web_search: invalid timeout or excerpt limit")
    return SearchRequest(endpoint, {"query": query.strip(), "count": max_results, "need_content": mode == "content"},
                         timeout, mode, min(ceiling, limit))


def search_result(payload, request):
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("provider returned no results list")
    sources, blocks, seen = [], [], set()
    order = {"snippet": ("snippet", "summary"), "summary": ("summary", "snippet"),
             "content": ("content", "summary", "snippet")}[request.result_type]
    for item in payload["results"]:
        if len(sources) >= request.payload["count"]:
            break
        if not isinstance(item, dict):
            continue
        link = str(item.get("url") or "").strip()
        try:
            url = urlparse(link)
            valid = (url.scheme in {"http", "https"} and url.hostname
                     and url.username is None and url.password is None)
        except ValueError:
            valid = False
        if not valid or link in seen:
            continue
        seen.add(link)
        title = str(item.get("title") or link).strip()[:300]
        field = next((key for key in order if isinstance(item.get(key), str) and item[key].strip()), None)
        full = item[field].strip() if field else "无摘要"
        text = full[:request.text_limit]
        truncated = len(full) > len(text)
        published = str(item.get("date") or "").strip()[:100]
        source = {"title": title, "url": link, "excerpt_type": field, "truncated": truncated}
        for key in ("authority", "rerank_score"):
            if type(item.get(key)) in (int, float):
                source[key] = item[key]
        sources.append(source)
        date_line = f"\n发布时间：{published}" if published else ""
        label = {"snippet": "短摘要", "summary": "摘要", "content": "正文摘录"}.get(field, "摘要")
        suffix = "\n[摘录已截断]" if truncated else ""
        blocks.append(f"[{len(sources)}] {title}{date_line}\n链接：{link}\n{label}：{text}{suffix}")
    return {"query": request.payload["query"],
            "answer": "\n\n".join(blocks) or "DeepSeek 联网搜索未返回可核验的网页结果。",
            "sources": sources, "provider": "deepseek_search", "search_requests": 1, "usage": {},
            "result_type": request.result_type, "max_result_chars": request.text_limit}


def search_error(status, error):
    detail = f"HTTP {status}" if status is not None and status != 200 else type(error).__name__
    return RuntimeError(f"deepseek_web_search unavailable: {detail}")


class _WebToolClient:
    """Two independent HTTP requests; credentials are injected by the host."""

    def __init__(self, settings, *, client_factory=httpx.AsyncClient):
        self.settings = dict(settings)
        self.client_factory = client_factory
        self._gate = asyncio.Semaphore(2)
        self._active = set()
        self._closed = False

    async def post(self, endpoint, payload, *, timeout, operation, max_bytes=8 * 1024 * 1024):
        if self._closed:
            raise RuntimeError("联网工具连接已关闭")
        task = asyncio.current_task()
        self._active.add(task)
        try:
            async with self._gate:
                if self._closed:
                    raise RuntimeError("联网工具连接已关闭")
                status = None
                try:
                    async with self.client_factory(trust_env=False, follow_redirects=False,
                                                   timeout=timeout) as client:
                        async with client.stream("POST", endpoint, json=payload,
                                headers={"Authorization": "Bearer " + self.settings["api_key"]}) as response:
                            status = response.status_code
                            if status != 200:
                                raise RuntimeError("Request failed")
                            raw = bytearray()
                            async for chunk in response.aiter_bytes():
                                raw.extend(chunk)
                                if len(raw) > max_bytes:
                                    raise ValueError("Response too large")
                    return json.loads(raw)
                except Exception as exc:
                    detail = f"HTTP {status}" if status is not None and status != 200 else type(exc).__name__
                    raise RuntimeError(f"deepseek_web_{operation} unavailable: {detail}") from None
        finally:
            self._active.discard(task)

    async def close(self):
        self._closed = True
        tasks = [task for task in self._active if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class DeepSeekSearchClient(_WebToolClient):
    async def search(self, query, max_results=5, result_type=None):
        request = prepare_search(self.settings, query, max_results, result_type)
        payload = await self.post(request.endpoint, request.payload, timeout=request.timeout, operation="search")
        try:
            return search_result(payload, request)
        except Exception as exc:
            raise search_error(None, exc) from None


class DeepSeekFetchClient(_WebToolClient):
    async def fetch(self, url, *, max_bytes=1048576, timeout_seconds=12):
        if not self.settings.get("api_key"):
            raise RuntimeError("DeepSeek Fetch 未配置官方 API 密钥")
        endpoint = str(self.settings.get("endpoint") or "https://api.deepseek.com/v1/tools/fetch").strip()
        parsed = urlparse(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise RuntimeError("DeepSeekFetch.endpoint 必须是 HTTPS URL")
        payload = await self.post(endpoint, {"url": url}, timeout=timeout_seconds,
                                  operation="fetch", max_bytes=max_bytes)
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str) or not payload["content"].strip():
            raise RuntimeError("DeepSeek Fetch 未返回有效正文")
        return {"title": str(payload.get("title") or "")[:300], "content": payload["content"]}

"""Bounded, inert discovery of X's public x-web modules and Relay queries."""

import asyncio
import re
from collections import OrderedDict
from threading import Lock
from urllib.parse import urljoin, urlparse


class XWebError(RuntimeError):
    """Only credential-free diagnostics may cross the QQ command boundary."""


_LITERAL = r'''["'`]([^"'`\s]+)["'`]'''
_IMPORT = re.compile(r'(?:\bfrom\s*|\bimport\s*\(\s*)' + _LITERAL)
_QUERY = re.compile(
    r'params\s*:\s*\{\s*id\s*:\s*' + _LITERAL
    + r'\s*,\s*metadata\s*:\s*\{[^{}]*\}\s*,\s*name\s*:\s*' + _LITERAL
    + r'\s*,\s*operationKind\s*:\s*["\'`]query["\'`]'
    + r'\s*,\s*text\s*:\s*null(?:\s*,\s*providedVariables\s*:\s*\{([^{}]*)\})?'
)
_CACHE = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_BYTES = 16 * 1024 * 1024


def _asset_url(value, base="https://x.com"):
    url = urljoin(base, value)
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "abs.twimg.com"
            or not re.fullmatch(r'/x-web/x-web/(?:assets/)?[\w.-]+\.js', parsed.path)
            or parsed.query or parsed.fragment):
        raise XWebError("X 网页脚本地址结构变化，本次保留游标")
    return url


class XWebAssets:
    def __init__(self, entry, session, headers):
        self.entry = _asset_url(entry)
        self.session, self.headers = session, headers
        self.sources, self.queries = {}, {}
        self._requested = set()
        self._bytes = 0

    async def load(self, url):
        url = _asset_url(url)
        if url in self.sources:
            return self.sources[url]
        self._requested.add(url)
        if len(self._requested) > 24:
            raise XWebError("X 网页脚本发现超过预算，本次保留游标")
        with _CACHE_LOCK:
            source = _CACHE.get(url)
            if source is not None:
                _CACHE.move_to_end(url)
        if source is None:
            # No cookies or authenticated page/API responses enter this cache.
            async with self.session.stream("GET", url, headers=self.headers, follow_redirects=False) as response:
                if response.status_code != 200:
                    raise XWebError(f"X 网页脚本获取失败（HTTP {response.status_code}），本次保留游标")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 4 * 1024 * 1024:
                        raise XWebError("X 网页脚本超过大小预算，本次保留游标")
                source = chunks.decode("utf-8")
            with _CACHE_LOCK:
                _CACHE[url] = source
                while len(_CACHE) > 48 or sum(len(s.encode("utf-8")) for s in _CACHE.values()) > _CACHE_BYTES:
                    _CACHE.popitem(last=False)
        self._bytes += len(source.encode("utf-8"))
        if self._bytes > 12 * 1024 * 1024:
            raise XWebError("X 网页脚本发现超过大小预算，本次保留游标")
        self.sources[url] = source
        for query_id, name, providers in _QUERY.findall(source):
            self.queries[name] = (query_id, re.findall(r'(__relay_internal__pv__\w+)\s*:', providers))
        return source

    def imports(self, source, base):
        return list(dict.fromkeys(_asset_url(path, base) for path in _IMPORT.findall(source)))

    async def bootstrap(self):
        source = await self.load(self.entry)
        # Only entry dependencies, not its entire lazy route graph.
        static = re.findall(r'\bfrom\s*' + _LITERAL, source)
        urls = list(dict.fromkeys(_asset_url(path, self.entry) for path in static))
        if len(urls) > 12:
            raise XWebError("X 网页入口依赖结构变化，本次保留游标")
        await asyncio.gather(*(self.load(url) for url in urls))

    async def signature_source(self):
        for url, source in list(self.sources.items()):
            for marker in re.finditer(r'["\'`]x-client-transaction-id["\'`]', source):
                imports = re.findall(r'\bimport\s*\(\s*' + _LITERAL, source[max(0, marker.start()-2000):marker.start()])
                if imports:
                    return await self.load(_asset_url(imports[-1], url))
        raise XWebError("X 网页缺少 transaction 资源映射，本次保留游标")

    async def query(self, name):
        if name in self.queries:
            return self.queries[name]
        routes = {"UserOriginalsTimeline": "/$username/_profile/", "UserTweets": "/$username/_profile/all"}
        seed = None
        for url, source in list(self.sources.items()):
            if name in routes:
                marker = re.search(r'["\'`]' + re.escape(routes[name]) + r'["\'`]', source)
                if marker:
                    imports = re.findall(r'\bimport\s*\(\s*' + _LITERAL, source[max(0, marker.start()-1200):marker.start()])
                    if imports:
                        seed = _asset_url(imports[-1], url)
            elif name == "TweetDetail":
                marker = re.search(r'\{\s*preloadConversation\s*:\s*\w+\s*\}\s*=\s*await\s+import\s*\(\s*' + _LITERAL, source)
                if marker:
                    seed = _asset_url(marker[1], url)
            if seed:
                break
        if seed:
            pending, visited = [seed], set(self.sources)
            for _ in range(4):
                next_urls = []
                for url in pending:
                    if url in visited:
                        continue
                    visited.add(url)
                    source = await self.load(url)
                    if name in self.queries:
                        return self.queries[name]
                    next_urls.extend(self.imports(source, url))
                pending = list(dict.fromkeys(u for u in next_urls if u not in visited))
        raise XWebError(f"X 网页操作标识缺失（{name}），请更新网页适配；本次保留游标")

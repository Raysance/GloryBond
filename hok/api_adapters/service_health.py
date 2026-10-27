"""Bounded read-only probes: no generation, search, login, retries or redirects."""

import json
import asyncio
from urllib.parse import urlsplit

import httpx


async def service_health_http(target, timeout):
    if not target.get("enabled", True):
        return "skip", "配置已禁用"
    url = target.get("url", "")
    parts = urlsplit(url)
    if target["check"] == "proxy":
        if parts.scheme not in {"http", "https", "socks5", "socks5h"} or not parts.hostname:
            return "warn", "代理地址配置无效"
        port = parts.port or (443 if parts.scheme == "https" else 1080 if parts.scheme.startswith("socks") else 80)
        _, writer = await asyncio.wait_for(asyncio.open_connection(parts.hostname, port), timeout)
        writer.close()
        await writer.wait_closed()
        return "reachable", "TCP 监听可达；转发能力见代理外部 API 检验"
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return "warn", "未配置有效 HTTP 地址"
    if target.get("requires_proxy") and not target.get("proxy"):
        return "warn", "缺少 Clash 代理配置，未回退直连"
    check = target["check"]
    headers = {"User-Agent": "HOK_QQBot-ServiceHealth/1.0"}
    params = None
    if check in {"models", "steam"}:
        if not target.get("api_key"):
            return "warn", "缺少 API 凭据，未调用接口"
        if check == "models":
            headers["Authorization"] = "Bearer " + target["api_key"]
        else:
            # Empty player list is a minimal authenticated, read-only API request.
            params = {"key": target["api_key"], "steamids": ""}
    method = "HEAD" if check == "reachability" else "GET"
    async with httpx.AsyncClient(proxy=target.get("proxy") or None, trust_env=False,
                                 timeout=timeout, follow_redirects=False) as client:
        async with client.stream(method, url, headers=headers, params=params) as response:
            code = response.status_code
            if code >= 500 or code == 407:
                return "error", f"HTTP {code}，服务或代理异常"
            if check == "reachability":
                suffix = "；缺少业务凭据" if target.get("configured") is False else "；鉴权/业务未验证"
                if code == 429:
                    return "warn", "HTTP 429，接口限流，未重试"
                return "reachable", f"HTTP {code}{suffix}"
            if not 200 <= code < 300:
                if code in {401, 403}:
                    return "warn", f"HTTP {code}，鉴权或访问被拒绝"
                return "warn", f"HTTP {code}，连接可达，最小 API 检验未通过"
            if check == "http":
                return "ok", f"HTTP {code} 健康端点响应"
            raw = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=16384):
                raw.extend(chunk)
                if len(raw) > 262144:
                    return "warn", "响应超出 256KiB 检查预算"
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                return "warn", f"HTTP {code}，响应非有效 JSON"
            if not isinstance(data, dict):
                return "warn", "API 响应结构未通过校验"
            if check == "models":
                rows = data.get("data")
                if not isinstance(rows, list):
                    return "warn", "模型列表结构未知；生成能力未验证"
                model = target.get("model")
                if model and not any(isinstance(row, dict) and row.get("id") == model for row in rows):
                    return "warn", "鉴权通过，目标模型未出现在列表；生成能力未验证"
                return "ok", "鉴权及模型列表通过；生成未测试"
            if check == "steam":
                if isinstance(data.get("response", {}).get("players"), list):
                    return "ok", "最小玩家列表 API 通过"
            elif check == "bilibili":
                if data.get("code") in {0, -101}:
                    return "ok", "API 响应正常（无需登录）"
            elif check == "web_health":
                status = data.get("status")
                if status in {"ok", "healthy"}:
                    return "ok", "健康接口正常"
                if status in {"down", "error", "unhealthy"}:
                    return "error", "健康接口报告服务异常"
                return "warn", "健康接口报告降级或状态未知"
            return "warn", "API 响应结构未通过校验"

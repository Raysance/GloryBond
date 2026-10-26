"""Validation and rendering for expiring, public chat execution records."""

import asyncio
import json
import re

from fastapi.responses import HTMLResponse


TRACE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                 "X-Robots-Tag": "noindex, nofollow", "X-Content-Type-Options": "nosniff"}


def valid_trace_key(key):
    # New artifacts share the 16-character key format; old links retain their TTL.
    return isinstance(key, str) and re.fullmatch(r"(?:[0-9a-f]{16}|[0-9a-f]{48})", key) is not None


def parse_chat_trace(raw):
    if not raw:
        raise ValueError("missing chat trace")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("kind") != "chat_trace" or payload.get("version") != 1:
        raise ValueError("invalid chat trace version")
    rounds = payload.get("rounds")
    if not isinstance(rounds, list) or any(not isinstance(turn, dict) or not isinstance(turn.get("tools"), list)
                                            for turn in rounds):
        raise ValueError("invalid chat trace rounds")
    payload["artifacts"] = [item for item in payload.get("artifacts", [])
                            if isinstance(item, dict) and isinstance(item.get("url"), str)
                            and re.fullmatch(r"/file_transfer/chat_plot_[0-9a-f]{32}\.png", item["url"])]
    return payload


def _render(templates, name, context, *, status_code=200, headers=None):
    # Explicit Jinja rendering works across the project's supported Starlette versions.
    return HTMLResponse(templates.get_template(name).render(context), status_code=status_code, headers=headers)


async def chat_trace_response(request, key, *, load_artifact, templates, admin_view=False):
    """Keep token validation before Redis access and share no data via another API."""
    if not valid_trace_key(key):
        return _render(templates, "ErrorPages/illegal.html",
                                          {"request": request, "message": "运行记录链接无效"},
                                          status_code=400, headers=TRACE_HEADERS)
    try:
        raw = await asyncio.to_thread(load_artifact, key)
    except Exception:
        return _render(templates, "ErrorPages/illegal.html",
                                          {"request": request, "message": "运行记录暂时无法读取，请稍后重试"},
                                          status_code=503, headers=TRACE_HEADERS)
    try:
        trace = parse_chat_trace(raw)
    except (ValueError, TypeError, UnicodeError):
        return _render(templates, "ErrorPages/expired.html", {"request": request},
                                          status_code=410, headers=TRACE_HEADERS)
    return _render(templates, "CommonPages/ChatTrace/index.html",
                                      {"request": request, "trace": trace, "admin_view": admin_view},
                                      headers=TRACE_HEADERS)

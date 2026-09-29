"""Bounded, public execution records. Never serialize model context or reasoning."""

import re


PRIVATE_TOOLS = {
    "recall_memory", "remember_memory", "forget_memory", "search_chat_history",
    "fetch_chat_context", "fetch_chat_reply_thread",
}
PRIVATE_FIELDS = {
    "reasoning", "reasoning_content", "chain_of_thought", "system_prompt",
    "api_key", "authorization", "password", "secret", "token", "dsn", "path",
}


def public_value(value, *, secrets=(), depth=0):
    """Scrub known credentials/paths and bound previews before sharing a record."""
    if depth > 18:
        return "[预览层级已截断]"
    if isinstance(value, dict):
        return {str(key): public_value(child, secrets=secrets, depth=depth + 1)
                for key, child in list(value.items())[:80]
                if str(key).lower() not in PRIVATE_FIELDS}
    if isinstance(value, (list, tuple)):
        result = [public_value(child, secrets=secrets, depth=depth + 1) for child in value[:200]]
        if len(value) > 200:
            result.append({"preview_truncated": True, "total_items": len(value)})
        return result
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(str(secret), "[凭据已隐藏]")
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[凭据已隐藏]", value)
        value = re.sub(r"(?i)(?:postgres(?:ql)?|socks5h?)://\S+", "[连接信息已隐藏]", value)
        value = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[凭据已隐藏]", value)
        value = re.sub(r"(?<!\w)/(?:srv|tmp|Users|home|etc|opt|var|QQBot)/[^\s\"'<>]+", "[本地路径已隐藏]", value)
        return value[:20000] + ("\n[预览已截断]" if len(value) > 20000 else "")
    return value if value is None or isinstance(value, (bool, int, float)) else public_value(str(value), secrets=secrets)


def tool_record(call, arguments, result, *, start_ms, duration_ms, executed):
    """Keep every call/outcome, including failed SQL in a successful batch."""
    name = str(call.get("name") or "")
    data = result.get("data")
    observations = data.get("observations", []) if isinstance(data, dict) else []
    failed = not result.get("ok", False) or (isinstance(data, dict) and data.get("ok") is False)
    partial = any(item.get("ok") is False for item in observations if isinstance(item, dict))
    if name in PRIVATE_TOOLS:
        arguments = {"redacted": "记忆与群聊检索参数不在分享页公开"}
        # Only retain bounded diagnostic labels, never exception messages or data.
        diagnostic = {}
        error = result.get("error", "")
        if failed and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}(?:Error|Exception)", str(error)):
            diagnostic["error"] = error
        if result.get("code") == "group_context_required":
            diagnostic["code"] = "group_context_required"
        result = {"ok": not failed, **diagnostic, "redacted": "记忆与群聊正文不在分享页公开"}
    return {"call_id": str(call.get("call_id") or call.get("id") or ""), "name": name,
            "arguments": arguments, "observation": result, "start_ms": start_ms,
            "duration_ms": duration_ms, "executed": executed,
            "status": "skipped" if not executed else "error" if failed else "partial" if partial else "ok"}


def trace_summary(rounds):
    calls = [call for turn in rounds for call in turn["tools"]]
    return {"model_calls": len(rounds), "tool_calls": sum(call["executed"] for call in calls),
            "skipped_calls": sum(not call["executed"] for call in calls),
            "tool_errors": sum(call["status"] in {"error", "partial"} for call in calls)}

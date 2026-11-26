"""Credential scrubbing for the shared agent execution-record publisher."""

import re


def trace_index_entry(payload, token, created_at):
    """Small admin listing row; complete payloads stay in their expiring artifact."""
    session = str(payload.get("session_id") or "")
    match = re.fullmatch(r"qq_(?:g_([0-9]+)_([0-9]+)|p_([0-9]+))", session)
    summary = payload.get("summary") or {}
    usages = [(row.get("response_meta") or {}).get("usage") or
              (row.get("response_payload") or {}).get("usage") or {} for row in payload.get("rounds", [])]
    tokens = [usage["total_tokens"] for usage in usages if type(usage.get("total_tokens")) is int]
    total_tokens = sum(tokens) if tokens else None if usages else (summary.get("token_usage") or {}).get("total_tokens")
    return {"key": token, "created_at": created_at,
            "expires_at": created_at + payload["expires_in_seconds"],
            "started_at": payload.get("started_at", ""), "run_id": payload.get("run_id", ""),
            "session_id": session, "group_id": match[1] if match else None,
            "user_id": (match[2] or match[3]) if match else None,
            "channel": "group" if match and match[1] else "private" if match else "unknown",
            "question": str(payload.get("question", ""))[:240],
            "status": payload.get("status", "unknown"), "model": payload.get("model", ""),
            "duration_ms": payload.get("duration_ms", 0), "tool_calls": summary.get("tool_calls"),
            "total_tokens": total_tokens, "usage_incomplete": len(tokens) < len(usages)}


PRIVATE_FIELDS = {
    "reasoning", "reasoning_content", "chain_of_thought",
    "api_key", "authorization", "password", "secret", "token", "dsn", "path",
}


def public_value(value, *, secrets=(), payload=False):
    """Preserve complete provider payloads; never capture HTTP headers or credentials."""
    if isinstance(value, dict):
        private = {"api_key", "authorization", "password", "secret", "headers", "api-key", "x-api-key"} if payload else PRIVATE_FIELDS | {"headers"}
        return {str(key): public_value(child, secrets=secrets,
                                      payload=payload or key in {"request_payload", "response_payload", "tool_definitions"})
                for key, child in value.items() if str(key).lower() not in private}
    if isinstance(value, (list, tuple)):
        return [public_value(child, secrets=secrets, payload=payload) for child in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(str(secret), "[凭据已隐藏]")
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[凭据已隐藏]", value)
        value = re.sub(r"(?i)(?:postgres(?:ql)?|socks5h?)://\S+", "[连接信息已隐藏]", value)
        value = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[凭据已隐藏]", value)
        if not payload:
            value = re.sub(r"(?<!\w)/(?:srv|tmp|Users|home|etc|opt|var|QQBot)/[^\s\"'<>]+", "[本地路径已隐藏]", value)
        return value
    return value if value is None or isinstance(value, (bool, int, float)) else public_value(str(value), secrets=secrets, payload=payload)

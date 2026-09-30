"""Body-only execution records, credential scrubbing and error diagnostics."""

import re


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


def error_record(error, stage):
    """Keep cause chains and stack locations without frame locals or HTTP objects."""
    chain, seen = [], set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frames, frame = [], current.__traceback__
        while frame is not None:
            frames.append({"module": frame.tb_frame.f_globals.get("__name__", ""),
                           "function": frame.tb_frame.f_code.co_name, "line": frame.tb_lineno})
            frame = frame.tb_next
        item = {"type": type(current).__name__, "detail": str(current), "frames": frames}
        for key in ("status_code", "request_id"):
            if getattr(current, key, None) is not None:
                item[key] = getattr(current, key)
        chain.append(item)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return {"stage": stage, "causes": chain}


def failed_request_payloads(error):
    """Find adapter body snapshots through an existing compatibility wrapper."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if hasattr(error, "request_payload"):
            return {"request_payload": error.request_payload, "response_payload": error.response_payload}
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return {}


def tool_record(call, arguments, result, *, start_ms, duration_ms, executed):
    """Keep every call/outcome, including failed SQL in a successful batch."""
    name = str(call.get("name") or "")
    data = result.get("data")
    observations = data.get("observations", []) if isinstance(data, dict) else []
    failed = not result.get("ok", False) or (isinstance(data, dict) and data.get("ok") is False)
    partial = any(item.get("ok") is False for item in observations if isinstance(item, dict))
    return {"call_id": str(call.get("call_id") or call.get("id") or ""), "name": name,
            "arguments": arguments, "observation": result, "start_ms": start_ms,
            "duration_ms": duration_ms, "executed": executed,
            "status": "skipped" if not executed else "error" if failed else "partial" if partial else "ok"}


def trace_summary(rounds):
    calls = [call for turn in rounds for call in turn["tools"]]
    usages = [
        (turn.get("response_meta") or {}).get("usage") or {}
        for turn in rounds
    ]
    prompt_tokens = sum(int(item.get("prompt_tokens") or item.get("input_tokens") or 0)
                        for item in usages if isinstance(item, dict))
    completion_tokens = sum(int(item.get("completion_tokens") or item.get("output_tokens") or 0)
                            for item in usages if isinstance(item, dict))
    total_tokens = sum(int(item.get("total_tokens") or 0)
                       for item in usages if isinstance(item, dict))
    cache_hit_tokens = sum(int(
        item.get("prompt_cache_hit_tokens")
        or (item.get("input_tokens_details") or {}).get("cached_tokens")
        or 0
    ) for item in usages if isinstance(item, dict))
    cache_miss_tokens = sum(int(item.get("prompt_cache_miss_tokens") or 0)
                            for item in usages if isinstance(item, dict))
    return {"model_calls": len(rounds), "tool_calls": sum(call["executed"] for call in calls),
            "skipped_calls": sum(not call["executed"] for call in calls),
            "tool_errors": sum(call["status"] in {"error", "partial"} for call in calls),
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens or prompt_tokens + completion_tokens,
                "prompt_cache_hit_tokens": cache_hit_tokens,
                "prompt_cache_miss_tokens": cache_miss_tokens,
            }}

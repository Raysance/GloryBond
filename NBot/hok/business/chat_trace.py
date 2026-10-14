"""Credential scrubbing for the shared agent execution-record publisher."""

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

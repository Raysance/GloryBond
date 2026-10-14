"""Portable, bounded exception diagnostics. No engine, IO or credential lookup."""

import re
import traceback
from urllib.parse import urlsplit, urlunsplit


def redact_error(value, secrets=()):
    """Sanitize before clipping, including errors raised before bootstrap completes."""
    if isinstance(value, dict):
        return {str(key): ("[redacted]" if re.search(
            r"api[_-]?key|password|authorization|credential|secret|dsn", str(key), re.I
        ) else redact_error(item, secrets)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_error(item, secrets) for item in value]
    if not isinstance(value, str):
        return value
    for secret in sorted((s for s in secrets if isinstance(s, str) and s), key=len, reverse=True):
        value = value.replace(secret, "[redacted]")
    value = re.sub(r"\b(?:sk-|AKIA)[A-Za-z0-9_-]{8,}", "[redacted]", value)
    value = re.sub(r"(?i)\bBearer\s+[^\s,;'\"]+", "Bearer [redacted]", value)
    value = re.sub(r"(?i)(\bauthorization[\"']?\s*[=:]\s*)"
                   r"(?:\"[^\"]*\"|'[^']*'|[^\r\n,;]+)", r"\1[redacted]", value)
    value = re.sub(r"(?i)(\b(?:api[_-]?key|password|token|secret|dsn)[\"']?\s*[=:]\s*)"
                   r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1[redacted]", value)

    def clean_url(match):
        try:
            parsed = urlsplit(match.group())
        except ValueError:
            return "[redacted malformed URL]"
        if parsed.scheme.lower() in {"postgres", "postgresql", "mysql", "redis", "rediss"}:
            return "[redacted connection URL]"
        host = parsed.netloc.rsplit("@", 1)[-1]
        # Query strings may contain signed tokens or keys under arbitrary names.
        return urlunsplit((parsed.scheme, host, parsed.path, "[redacted]" if parsed.query else "", ""))

    return re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+", clean_url, value)


def exception_details(exc, *, phase, operation=None, redactor=None):
    """Keep useful causes and whitelisted diagnostics, never locals or headers."""
    sanitize = redactor or redact_error

    def text(value, limit=1200):
        return str(sanitize(str(value)))[:limit]

    chain, seen, current = [], set(), exc
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        item = {"error_type": type(current).__name__, "message": text(current)}
        frames = list(traceback.walk_tb(current.__traceback__))
        if frames:
            item["locations"] = [{"file": frame.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1],
                                  "function": frame.f_code.co_name, "line": lineno}
                                 for frame, lineno in frames[-4:]]
        chain.append(item)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)

    diagnostics = {}
    for error in _exceptions(exc):
        sqlstate = getattr(error, "sqlstate", None)
        if sqlstate:
            diagnostics["sqlstate"] = text(sqlstate, 5)
            diag = getattr(error, "diag", None)
            for key in ("statement_position", "message_primary", "message_detail", "message_hint", "column_name"):
                value = getattr(diag, key, None)
                if value:
                    diagnostics[key] = text(value)
        response = getattr(error, "response", None)
        status = getattr(error, "status_code", None)
        if status is None and response is not None:
            status = getattr(response, "status_code", None)
        if type(status) is int:
            diagnostics["http_status"] = status
        for key, limit in (("stderr", 4000), ("exit_code", 20)):
            value = getattr(error, key, None)
            if value is not None:
                diagnostics[key] = text(value, limit)

    transient = any(isinstance(error, (TimeoutError, ConnectionError)) or
                    type(error).__name__ in {"Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError", "OperationalError"}
                    for error in _exceptions(exc))
    status = diagnostics.get("http_status")
    retryable = transient if status is None else status in {408, 429} or status >= 500
    if diagnostics.get("sqlstate", "").startswith(("28", "3D", "42")):
        retryable = False
    recovery = ("读取操作可在本轮预算内有限重试；仍失败时改用其他来源或说明限制。" if retryable else
                "根据错误核对参数、已披露的目录和字段；修正后再调用，勿原样反复重试。")
    return sanitize({"phase": phase, "operation": operation, "error_type": type(exc).__name__,
                     "message": text(exc) or type(exc).__name__, "causes": chain[1:],
                     "locations": chain[0].get("locations", []) if chain else [],
                     "diagnostics": diagnostics, "retryable": retryable, "recovery": recovery})


def _exceptions(exc):
    seen = set()
    while exc is not None and id(exc) not in seen and len(seen) < 4:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)


class RemoteToolError(RuntimeError):
    """A failed RPC whose remote exception details survive the transport."""

    def __init__(self, message, error_details):
        super().__init__(message)
        self.error_details = error_details

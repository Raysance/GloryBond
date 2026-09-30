"""Manual, read-only diagnostics for the configured chat provider.

This module is deliberately not part of application startup.  It is invoked by
an authenticated Web administrator action or directly from the command line.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Callable
from urllib.parse import urlparse


PROBE_TOOL = {
    "type": "function",
    "name": "health_probe",
    "description": "Return the fixed health probe observation.",
    "parameters": {
        "type": "object",
        "properties": {
            "token": {
                "type": "string",
                "description": "The fixed token HOK_TOOL_PROBE.",
            },
        },
        "required": ["token"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _safe_error(error: BaseException, api_key: str = "") -> str:
    """Return a bounded error string with credential-shaped values removed."""
    message = f"{type(error).__name__}: {error}"
    if api_key:
        message = message.replace(api_key, "[redacted]")
    message = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted]", message)
    return message[:1000]


def _check(name: str, started: float, *, status: str, **details) -> dict:
    return {
        "name": name,
        "status": status,
        "duration_ms": _elapsed_ms(started),
        **details,
    }


def configuration_check(config: dict) -> dict:
    """Validate the production chat contract without revealing credentials."""
    started = time.perf_counter()
    hostname = urlparse(str(config.get("base_url") or "")).hostname or ""
    model = str(config.get("model") or "")
    key_configured = bool(str(config.get("api_key") or "").strip())
    proxy_disabled = not bool(str(config.get("proxy_url") or "").strip())
    expected_provider = hostname == "api.deepseek.com"
    expected_model = model == "deepseek-flash"
    passed = all((expected_provider, expected_model, key_configured, proxy_disabled))
    return _check(
        "configuration",
        started,
        status="ok" if passed else "failed",
        provider_host=hostname,
        model=model,
        key_configured=key_configured,
        direct_connection=proxy_disabled,
        expected_provider=expected_provider,
        expected_model=expected_model,
    )


def text_completion_check(ai_create: Callable, api_key: str = "") -> dict:
    """Make one minimal request through the same adapter used by chat."""
    started = time.perf_counter()
    try:
        response = ai_create([
            {"role": "system", "content": "You are a health probe. Follow the requested output exactly."},
            {"role": "user", "content": "Reply with exactly HOK_HEALTH_OK."},
        ], tools=None, tool_choice="none", network=False)
        content = str(response.get("content") or "").strip()
        passed = bool(content)
        return _check(
            "text_completion",
            started,
            status="ok" if passed else "failed",
            model=str(response.get("model") or ""),
            response_received=passed,
            content_length=len(content),
        )
    except Exception as error:
        return _check(
            "text_completion",
            started,
            status="failed",
            error=_safe_error(error, api_key),
        )


def tool_continuation_check(ai_create: Callable, api_key: str = "") -> dict:
    """Exercise the forced-tool -> observation -> auto continuation protocol."""
    started = time.perf_counter()
    input_items = [
        {
            "role": "system",
            "content": (
                "You are a protocol health probe. Call health_probe once. After its observation, "
                "reply with a short final confirmation and do not call it again."
            ),
        },
        {"role": "user", "content": "Run the protocol health probe."},
    ]
    forced_choice = {"type": "function", "function": {"name": "health_probe"}}
    try:
        first = ai_create(
            input_items,
            tools=[PROBE_TOOL],
            tool_choice=forced_choice,
            network=False,
        )
        calls = list(first.get("tool_calls") or [])
        if not calls or calls[0].get("name") != "health_probe":
            raise RuntimeError("provider did not return the forced health_probe tool call")
        call_id = str(calls[0].get("call_id") or calls[0].get("id") or "")
        if not call_id:
            raise RuntimeError("provider tool call did not include a call id")

        continuation_input = [
            *input_items,
            *list(first.get("output_items") or []),
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps({"ok": True, "token": "HOK_TOOL_PROBE"}),
            },
        ]
        second = ai_create(
            continuation_input,
            tools=[PROBE_TOOL],
            tool_choice="auto",
            network=False,
        )
        content = str(second.get("content") or "").strip()
        repeated_calls = len(second.get("tool_calls") or [])
        passed = bool(content) and repeated_calls == 0
        return _check(
            "tool_continuation",
            started,
            status="ok" if passed else "failed",
            model=str(second.get("model") or first.get("model") or ""),
            forced_call_received=True,
            continuation_received=True,
            final_content_received=bool(content),
            repeated_tool_calls=repeated_calls,
        )
    except Exception as error:
        return _check(
            "tool_continuation",
            started,
            status="failed",
            error=_safe_error(error, api_key),
        )


def run_diagnostics(config: dict, ai_create: Callable) -> dict:
    """Run all manual chat checks and return a JSON-serializable report."""
    started = time.perf_counter()
    checks = [configuration_check(config)]
    if checks[0]["status"] == "ok":
        api_key = str(config.get("api_key") or "")
        checks.append(text_completion_check(ai_create, api_key))
        checks.append(tool_continuation_check(ai_create, api_key))
    status = "ok" if checks and all(item["status"] == "ok" for item in checks) else "failed"
    return {
        "version": 1,
        "status": status,
        "duration_ms": _elapsed_ms(started),
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the configured chat API and tool-continuation smoke checks.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON report for interactive use.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    from local_debugger import import_hok_module

    zapi = import_hok_module("zapi")
    zstatic = import_hok_module("zstatic")
    report = run_diagnostics(zstatic.chat_api_config, zapi.ai_response_create)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

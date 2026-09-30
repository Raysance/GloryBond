"""Manual, read-only diagnostics for the configured chat provider.

This module is deliberately not part of application startup.  It is invoked by
an authenticated Web administrator action or directly from the command line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
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
    expected_credential = str(os.environ.get("HOK_DIAGNOSTIC_EXPECTED_KEY_SHA256") or "").strip()
    actual_credential = hashlib.sha256(str(config.get("api_key") or "").encode()).hexdigest()
    credential_comparison_available = bool(expected_credential)
    credential_matches_running_process = (
        actual_credential == expected_credential if credential_comparison_available else None
    )
    passed = all((expected_provider, expected_model, key_configured, proxy_disabled))
    if credential_comparison_available:
        passed = passed and credential_matches_running_process
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
        credential_comparison_available=credential_comparison_available,
        credential_matches_running_process=credential_matches_running_process,
    )


def dependency_configuration_check(
    search_config: dict,
    readonly_dsn: str,
    redis_db,
) -> dict:
    """Check configuration presence without returning endpoints or credentials."""
    started = time.perf_counter()
    search_configured = all(str(search_config.get(key) or "").strip()
                            for key in ("endpoint", "api_key", "workspace", "service_id"))
    readonly_sql_configured = bool(str(readonly_dsn or "").strip())
    redis_db_zero = str(redis_db) == "0"
    passed = all((search_configured, readonly_sql_configured, redis_db_zero))
    return _check(
        "dependency_configuration",
        started,
        status="ok" if passed else "failed",
        aliyun_search_configured=search_configured,
        aliyun_search_direct=True,
        readonly_sql_configured=readonly_sql_configured,
        redis_db_zero=redis_db_zero,
    )


def tool_runtime_check(tool_factory: Callable, plot_templates: Callable) -> dict:
    """Validate progressive disclosure, tool schemas and plot prerequisites."""
    started = time.perf_counter()
    try:
        registry = tool_factory()
        initial_names = {item["name"] for item in registry.initial_schemas()}
        history_ready = registry.require_automatic_history_search()
        registry.execute("discover_tools", {
            "categories": ["game_data", "plots", "internet"],
            "reason": "manual health diagnostic",
        })
        registry.execute("discover_tools", {
            "categories": ["memory", "roleplay"],
            "reason": "manual health diagnostic",
        })
        disclosed_names = {item["name"] for item in registry.model_schemas()}
        required = {
            "discover_tools", "search_chat_history", "get_game_database_schema",
            "check_game_database_query", "query_game_database", "list_plot_templates",
            "render_python_plot", "web_search", "recall_memory", "remember_memory",
            "forget_memory", "manage_roleplay",
        }
        templates = plot_templates()
        template_count = len(templates.get("templates") or [])
        bubblewrap_required = platform.system() == "Linux"
        bubblewrap_available = bool(shutil.which("bwrap"))
        passed = (
            initial_names == {"discover_tools"}
            and history_ready
            and required <= disclosed_names
            and template_count >= 5
            and (bubblewrap_available or not bubblewrap_required)
        )
        return _check(
            "tool_runtime",
            started,
            status="ok" if passed else "failed",
            initial_tools=sorted(initial_names),
            progressive_disclosure_ready=required <= disclosed_names,
            mandatory_history_search_ready=history_ready,
            disclosed_tool_count=len(disclosed_names),
            plot_template_count=template_count,
            bubblewrap_required=bubblewrap_required,
            bubblewrap_available=bubblewrap_available,
        )
    except Exception as error:
        return _check("tool_runtime", started, status="failed", error=_safe_error(error))


def redis_storage_check(redis_client, zfunc) -> dict:
    """Exercise the read-only paths used by direct dialogue, facts and roles."""
    started = time.perf_counter()
    try:
        ping = bool(redis_client.ping())
        connection_db = redis_client.connection_pool.connection_kwargs.get("db")
        dialogue = zfunc.chat_active_dialogue_load("__health_probe__", limit=1)
        memories = zfunc.chat_memory_list("__health_probe__", limit=1)
        role = zfunc.chat_roleplay_get("__health_probe__")
        passed = ping and str(connection_db) == "0"
        return _check(
            "redis_chat_storage",
            started,
            status="ok" if passed else "failed",
            ping=ping,
            redis_db_zero=str(connection_db) == "0",
            active_dialogue_readable=isinstance(dialogue, list),
            fact_memory_readable=isinstance(memories, dict),
            roleplay_readable=role is None or isinstance(role, dict),
        )
    except Exception as error:
        return _check("redis_chat_storage", started, status="failed", error=_safe_error(error))


def game_database_check(schema_loader: Callable, query_checker: Callable, query_executor: Callable) -> dict:
    """Use the exact schema/check/least-privileged execution chain exposed to the model."""
    started = time.perf_counter()
    try:
        schema = schema_loader()
        sql = (
            "SELECT player_key, snapshot_date, player_index "
            "FROM hok.history_players ORDER BY snapshot_date DESC, player_index DESC LIMIT 1"
        )
        checked = query_checker(sql)
        result = query_executor(sql, limit=1) if checked.get("ok") else {"ok": False}
        table_count = len(schema.get("tables") or {})
        passed = bool(schema.get("ok")) and table_count >= 10 and bool(checked.get("ok")) and bool(result.get("ok"))
        return _check(
            "game_database_readonly",
            started,
            status="ok" if passed else "failed",
            schema_table_count=table_count,
            sql_ast_check=bool(checked.get("ok")),
            readonly_query=bool(result.get("ok")),
            returned_rows=int(result.get("row_count") or 0),
            truncated=bool(result.get("truncated")),
            error=None if result.get("ok") else str(result.get("error") or "query_failed")[:500],
        )
    except Exception as error:
        return _check("game_database_readonly", started, status="failed", error=_safe_error(error))


def group_history_check(primary_group_lister: Callable, merged_group_lister: Callable,
                        history_search: Callable) -> dict:
    """Verify PostgreSQL archive discovery and the real BM25/RRF retrieval path."""
    started = time.perf_counter()
    try:
        primary_groups = list(primary_group_lister() or [])
        merged_groups = list(merged_group_lister() or [])
        archived_messages = sum(int(item.get("message_count") or 0) for item in primary_groups)
        search_executed = False
        hit_count = 0
        candidates = [item for item in merged_groups if int(item.get("message_count") or 0) > 0]
        if candidates:
            selected = min(candidates, key=lambda item: int(item.get("message_count") or 0))
            hits = history_search(
                selected["group_id"],
                ["王者 游戏", "一起 对局"],
                limit=1,
            )
            search_executed = True
            hit_count = len(hits or [])
        return _check(
            "group_history_retrieval",
            started,
            status="ok",
            postgres_group_count=len(primary_groups),
            merged_group_count=len(merged_groups),
            archived_message_count=archived_messages,
            bm25_rrf_search_executed=search_executed,
            hit_count=hit_count,
        )
    except Exception as error:
        return _check("group_history_retrieval", started, status="failed", error=_safe_error(error))


def web_search_check(web_search: Callable, api_key: str = "") -> dict:
    """Make one real direct Alibaba Cloud OpenSearch request."""
    started = time.perf_counter()
    try:
        result = web_search("OpenAI 官方网站 ChatGPT 产品页面", max_results=1)
        sources = list(result.get("sources") or [])
        search_requests = int(result.get("search_requests") or 0)
        passed = bool(str(result.get("answer") or "").strip()) and (search_requests > 0 or bool(sources))
        return _check(
            "aliyun_web_search",
            started,
            status="ok" if passed else "failed",
            provider=str(result.get("provider") or ""),
            service_id=str(result.get("service_id") or ""),
            search_requests=search_requests,
            source_count=len(sources),
            answer_received=bool(str(result.get("answer") or "").strip()),
        )
    except Exception as error:
        return _check("aliyun_web_search", started, status="failed", error=_safe_error(error, api_key))


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


def run_diagnostics(config: dict, ai_create: Callable, *, additional_checks=()) -> dict:
    """Run all manual chat checks and return a JSON-serializable report."""
    started = time.perf_counter()
    checks = [configuration_check(config), *[check() for check in additional_checks]]
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
    zfunc = import_hok_module("zfunc")
    zdb = import_hok_module("zdb")
    zdynamic = import_hok_module("zdynamic")
    chat_tools = import_hok_module("chat_tools")
    report = run_diagnostics(
        zstatic.chat_api_config,
        zapi.ai_response_create,
        additional_checks=(
            lambda: dependency_configuration_check(
                zstatic.aliyun_search_config,
                zstatic.chat_readonly_dsn,
                zstatic.REDIS_DB,
            ),
            lambda: tool_runtime_check(
                lambda: chat_tools.HOKChatTools(
                    group_id="1",
                    current_message_id="health-probe",
                    original_query="检查数据库、可视化、联网、记忆、群聊历史和角色扮演",
                    user_id="__health_probe__",
                    use_memory=True,
                ),
                zfunc.chat_plot_templates,
            ),
            lambda: redis_storage_check(zdynamic.redis_deamon, zfunc),
            lambda: game_database_check(
                zfunc.chat_database_schema,
                zfunc.chat_check_database_query,
                zfunc.chat_query_database,
            ),
            lambda: group_history_check(
                zdb.list_group_chat_history_groups,
                zfunc.list_chat_history_groups,
                zfunc.search_group_chat_history,
            ),
            lambda: web_search_check(
                zapi.aliyun_web_search,
                zstatic.aliyun_search_config.get("api_key", ""),
            ),
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

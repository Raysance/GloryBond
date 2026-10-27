"""Model-visible run facts, isolated from concurrent chats and credentials."""

from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import time


_current = ContextVar("chat_model_metadata", default=None)
_PHASES = {"model": "reasoning", "reply.model": "reply", "roleplay.model": "role_creation"}


def token_usage(raw):
    """Keep reported counters; cache and reasoning details do not add to totals."""
    raw = raw if isinstance(raw, dict) else {}
    counters = {}
    for name, value in raw.items():
        if name in {"prompt_tokens", "completion_tokens", "total_tokens",
                    "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "reasoning_tokens"}:
            if type(value) is int and value >= 0:
                counters[name] = value
    for parent, child, name in (
        ("prompt_tokens_details", "cached_tokens", "prompt_cache_hit_tokens"),
        ("completion_tokens_details", "reasoning_tokens", "reasoning_tokens"),
    ):
        detail = raw.get(parent)
        value = detail.get(child) if isinstance(detail, dict) else None
        if name not in counters and type(value) is int and value >= 0:
            counters[name] = value
    return counters


@dataclass
class RunMetadata:
    run_id: str
    started_at: str
    channel: str
    origin: str
    started: float = field(default_factory=time.monotonic)
    phase: str = "reasoning"
    round: int | None = None
    tool_calls: int = 0
    completed_calls: int = 0
    usage_reported_calls: int = 0
    totals: dict = field(default_factory=dict)
    counter_calls: dict = field(default_factory=dict)
    last_response: dict | None = None


def observe_model_event(event):
    kind = event["kind"]
    if kind == "run.start":
        metadata = event.get("metadata", {})
        delivery = metadata.get("delivery", {})
        channel = ("qq_" + delivery.get("channel", "unknown")
                   if delivery.get("platform") == "qq" else "local_console")
        origin = metadata.get("origin", "foreground")
        _current.set(RunMetadata(event["run_id"], event.get("time", ""), channel,
                                 origin if origin in {"background", "event"} else "foreground"))
        return
    state = _current.get()
    if state is None or state.run_id != event["run_id"]:
        return
    if kind == "run.end":
        _current.set(None)
    elif kind == "tool.call":
        state.tool_calls += 1
    else:
        prefix, _, action = kind.rpartition(".")
        if prefix not in _PHASES:
            return
        data = event.get("data", {})
        if action == "request":
            state.phase = _PHASES[prefix]
            state.round = data.get("round", data.get("attempt"))
        elif action == "response":
            usage = token_usage(data.get("usage"))
            state.completed_calls += 1
            state.usage_reported_calls += bool(usage)
            for name, value in usage.items():
                state.totals[name] = state.totals.get(name, 0) + value
                state.counter_calls[name] = state.counter_calls.get(name, 0) + 1
            state.last_response = {"model": data.get("model"), "usage": usage or None,
                                   "finish_reason": data.get("finish_reason")}


def model_metadata(*, model, protocol, max_tokens, messages, tools):
    state = _current.get()
    merges_system = bool(messages and messages[0].get("role") == "system"
                         and isinstance(messages[0].get("content"), str))
    return {
        "model": model, "protocol": protocol, "max_output_tokens": max_tokens,
        "message_count": len(messages) + int(not merges_system), "available_tool_count": len(tools),
        "run": None if state is None else {
            "run_id": state.run_id, "started_at": state.started_at,
            "channel": state.channel, "origin": state.origin, "phase": state.phase,
            "round": state.round, "elapsed_seconds": round(time.monotonic() - state.started, 2),
            "tool_calls": state.tool_calls, "completed_model_calls": state.completed_calls,
            "usage_reported_calls": state.usage_reported_calls,
            "usage_missing_calls": state.completed_calls - state.usage_reported_calls,
            "cumulative_usage": dict(state.totals) or None,
            "usage_counter_calls": dict(state.counter_calls),
            "last_response": state.last_response,
        },
    }


def metadata_messages(messages, metadata):
    instruction = (
        "本次模型运行元信息由应用提供，供理解模型与执行状态，日常回答无需复述或附统计尾注。"
        "用户询问时使用已知字段；model为当前请求选用的标识，last_response.model为上次响应报告的标识，"
        "按各自时点理解，不从角色或历史猜测模型身份。"
        "用量覆盖本次运行已完成且返回统计的调用，缺失统计为null；当前请求用量在返回后更新。"
        "usage_counter_calls给出各项用量的已报告调用数，累计值按各项实际覆盖范围理解。"
        "缓存与推理token属于明细，不重复计入total_tokens；不推测未报告的用量、费用或上下文窗口。\n"
        + json.dumps({"runtime_metadata": metadata}, ensure_ascii=False)
    )
    result = list(messages)
    if result and result[0].get("role") == "system" and isinstance(result[0].get("content"), str):
        result[0] = {**result[0], "content": result[0]["content"] + "\n\n" + instruction}
    else:
        result.insert(0, {"role": "system", "content": instruction})
    return result

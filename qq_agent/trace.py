"""Project native runtime events into the existing QQ trace-page contract."""

import json
from datetime import datetime

from agent_console.tool_errors import redact_error


def build_trace(events, *, answer="", status="ok"):
    rounds, calls, schemas = [], {}, {}
    current = None
    first_time = events[0].get("time") if events else None

    def offset(event):
        try:
            return max(0, (datetime.fromisoformat(event["time"]) - datetime.fromisoformat(first_time)).total_seconds() * 1000)
        except (ValueError, TypeError, KeyError):
            return 0

    model = ""
    for event in events:
        kind, data = event["kind"], event["data"]
        if kind in {"model.request", "reply.model.request", "roleplay.model.request"}:
            messages = data.get("messages", [])
            tools = data.get("tools", [])
            current = {
                "index": len(rounds) + 1, "phase": kind.split(".")[0],
                "status": "running", "tools": [], "start_ms": offset(event),
                "context_injection": {
                    "messages": messages,
                    "system_messages": [m for m in messages if m.get("role") == "system"],
                    "context_messages": [m for m in messages if m.get("role") != "system"],
                    "tool_definitions": tools, "tool_choice": data.get("tool_choice", "none"),
                },
            }
            rounds.append(current)
            schemas.update({t["function"]["name"]: t for t in tools})
        elif kind in {"model.response", "reply.model.response", "roleplay.model.response"} and current:
            model = data.get("model") or (data.get("request_payload") or {}).get("model") or model
            current.update(status="ok", request_payload=data.get("request_payload"),
                           response_payload=data.get("response_payload"),
                           duration_ms=max(0, offset(event) - current["start_ms"]),
                           response_meta={"usage": data.get("usage"), "finish_reason": data.get("finish_reason")})
        elif kind == "tool.call" and current:
            function = data["function"]
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except ValueError:
                arguments = function.get("arguments")
            call = {"call_id": data["id"], "name": function["name"], "arguments": arguments,
                    "status": "running", "executed": True, "observation": {}, "start_ms": offset(event)}
            current["tools"].append(call)
            calls[data["id"]] = call
        elif kind == "tool.result" and data.get("call_id") in calls:
            calls[data["call_id"]].update(
                observation=data["result"], status="ok" if data["result"].get("ok") else "error",
                duration_ms=data.get("duration", 0) * 1000,
            )
        elif kind == "run.error" and current:
            current.update(status="error", error=data.get("error") or data.get("type") or "未知错误")
    start = next((e for e in events if e["kind"] == "run.start"), {})
    end = next((e for e in reversed(events) if e["kind"] == "run.end"), {})
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}
    for turn in rounds:
        for key in usage:
            usage[key] += int((turn.get("response_meta", {}).get("usage") or {}).get(key) or 0)
    return {
        "kind": "chat_trace", "version": 1, "engine": "agent_runtime", "model": model,
        "question": start.get("data", {}).get("message", ""), "answer": answer,
        "run_id": start.get("run_id", ""), "session_id": start.get("session_id", ""),
        "started_at": start.get("time", ""), "status": status,
        "duration_ms": end.get("data", {}).get("duration", offset(end) / 1000) * 1000,
        "rounds": rounds, "schemas": schemas, "events": events,
        "context": {"transport": "qq"},
        "summary": {"model_calls": len(rounds), "model_requests": len(rounds), "tool_calls": len(calls),
                    "tool_errors": sum(c["status"] == "error" for c in calls.values()),
                    "token_usage": usage},
    }


def failure_summary(trace):
    """Describe recorded failure facts without another model call or raw context."""
    events = trace["events"]
    error = next((e["data"] for e in reversed(events) if e["kind"] == "run.error"), {})
    error_type = str(error.get("type") or "未知错误")
    reason = str(error.get("error") or "").strip()
    if not reason:
        reason = ("处理超时，未取得完整结果。" if "Timeout" in error_type
                  else "未记录具体错误信息，请查看本轮运行记录。")
    stages = {
        "run.start": "准备请求", "model.request": "等待模型完整响应",
        "model.response": "处理模型响应", "tool.call": "执行工具",
        "tool.result": "处理工具结果", "reply.model.request": "整理回复",
        "reply.model.response": "处理回复整理结果", "roleplay.model.request": "生成角色",
        "roleplay.model.response": "处理角色生成结果", "output.message": "交付回复",
    }
    stage_event = next((e for e in reversed(events) if e["kind"] in stages
                        and (e["kind"] != "output.message" or e["data"].get("kind") == "final")), None)
    stage = stages[stage_event["kind"]] if stage_event else "未记录"
    if stage_event and stage_event["kind"] == "tool.call":
        stage += "（" + str(stage_event["data"].get("function", {}).get("name") or "未知工具") + "）"
    lines = ["本次AI任务未完成。", "", "错误类型：" + redact_error(error_type)[:100],
             "错误信息：" + redact_error(reason)[:1200], "失败阶段：" + redact_error(stage)[:200]]
    if trace.get("duration_ms", 0) > 0:
        lines.append(f"已耗时：{trace['duration_ms'] / 1000:.1f}秒")
    if trace.get("run_id"):
        lines.append("运行ID：" + str(trace["run_id"]))
    return "\n".join(lines)

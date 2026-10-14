"""Project native runtime events into the existing QQ trace-page contract."""

import json
from datetime import datetime


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
            current.update(status="error", error=data.get("error"))
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
        "started_at": start.get("time", ""), "status": status,
        "duration_ms": end.get("data", {}).get("duration", 0) * 1000,
        "rounds": rounds, "schemas": schemas, "events": events,
        "context": {"transport": "qq"},
        "summary": {"model_calls": len(rounds), "model_requests": len(rounds), "tool_calls": len(calls),
                    "tool_errors": sum(c["status"] == "error" for c in calls.values()),
                    "token_usage": usage},
    }

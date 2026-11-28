"""Bounded, scope-checked metadata projections of existing private run journals."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import re

from glorybond.agent.model_metadata import token_usage
from glorybond.agent.run_costs import model_cost, image_cost, number, total_cost, SNAPSHOT_DATE, SOURCES

COMPONENT = r"[a-zA-Z0-9_-]{1,80}"
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_LINE_BYTES = 8 * 1024 * 1024


def seconds(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None


def elapsed(start, end):
    a, b = seconds(start), seconds(end)
    return round(max(0, b - a), 3) if a is not None and b is not None else None


def union_seconds(intervals):
    end, total = None, 0
    for left, right in sorted(intervals):
        total += max(0, right - max(left, end if end is not None else left))
        end = max(right, end if end is not None else right)
    return round(total, 3)


def project_run(events):
    start = next((e for e in events if e["kind"] == "run.start"), {})
    end = next((e for e in reversed(events) if e["kind"] == "run.end"), {})
    models, tools, pending, calls, costs, usage_rows, intervals = [], [], {}, {}, [], [], []
    errors = 0
    batch_start = None
    for event in events:
        kind, data, at = event["kind"], event.get("data", {}), event.get("time")
        phase, _, action = kind.rpartition(".")
        if phase in {"model", "reply.model", "roleplay.model"}:
            if action == "request":
                row = {"phase": phase, "round": data.get("round", data.get("attempt")),
                       "started_at": at, "status": "incomplete", "duration_seconds": None,
                       "first_token_seconds": None, "usage": None}
                models.append(row)
                pending[phase] = row
            elif action == "delta" and phase in pending and data.get("text"):
                row = pending[phase]
                if row["first_token_seconds"] is None:
                    row["first_token_seconds"] = elapsed(row["started_at"], at)
            elif action == "response":
                row = pending.pop(phase, None)
                if row is None:
                    row = {"phase": phase, "started_at": None, "first_token_seconds": None}
                    models.append(row)
                usage = token_usage(data.get("usage"))
                model = data.get("model") or (data.get("request_payload") or {}).get("model")
                host = data.get("provider_host")
                cost = model_cost(model, usage, provider_host=host, at=row["started_at"], raw_usage=data.get("usage"))
                row.update(model=model, provider_host=host, status="completed", ended_at=at,
                           duration_seconds=elapsed(row["started_at"], at), usage=usage or None,
                           finish_reason=data.get("finish_reason"), cost=cost)
                usage_rows.append(usage)
                costs.append(cost)
        elif kind == "tool.call":
            if batch_start is None:
                batch_start = seconds(at)
            row = {"call_id": data["id"], "name": data.get("function", {}).get("name"),
                   "round": data.get("round"), "requested_at": at, "status": "incomplete",
                   "duration_seconds": None}
            tools.append(row)
            calls[data["id"]] = row
        elif kind == "tool.result":
            row = calls.get(data.get("call_id"))
            if row is None:
                row = {"call_id": data.get("call_id"), "name": data.get("name"), "requested_at": None}
                tools.append(row)
            result = data.get("result") or {}
            value = result.get("data")
            value = value if isinstance(value, dict) else {}
            duration = number(data.get("duration"))
            row.update(status="completed" if result.get("ok") else "error", result_recorded_at=at,
                       duration_seconds=duration, error_code=result.get("code"))
            stamp = seconds(at)
            # Runtime emits results in call order after the entire concurrent batch.
            # Result event times are not individual task completion timestamps.
            if stamp is not None and batch_start is not None:
                intervals.append((batch_start, stamp))
                batch_start = None
            if row["name"] in {"read_image", "read_media"}:
                cached = value.get("cached") is True or value.get("cache_hit") is True
                raw_usage = value.get("usage") if row["name"] == "read_image" else value.get("new_model_usage")
                usage = {} if cached else token_usage(raw_usage)
                row.update(model=value.get("model"), cached=cached, usage=usage or None)
                if not cached:
                    cost = model_cost(value.get("model"), usage, provider_host=value.get("provider_host"),
                                      at=row.get("requested_at"), raw_usage=raw_usage)
                    row["cost"] = cost
                    costs.append(cost)
                    usage_rows.append(usage)
                if row["name"] == "read_media":
                    audio = 0 if cached else number(value.get("new_asr_seconds"))
                    row["new_asr_seconds"] = audio
                    row['asr_model'] = value.get('asr_model', 'deepseek-asr')
                    if audio is not None and row['asr_model'] == 'gpt-transcribe':
                        cost = {'kind': 'estimated', 'currency': 'USD', 'min': round(audio * .0045 / 60, 8),
                                'max': round(audio * .0045 / 60, 8), 'price_date': SNAPSHOT_DATE,
                                'source': 'https://developers.openai.com/api/docs/models/gpt-transcribe',
                                'assumptions': ['按已提交音频时长估算，非账单']}
                    elif audio is not None and row['asr_model'] == 'deepseek-asr':
                        cost = {"kind": "estimated", "currency": "CNY", "min": round(audio * .39 / 3600, 8),
                                "max": round(audio * .78 / 3600, 8), "price_date": SNAPSHOT_DATE,
                                "source": SOURCES["deepseek"], "assumptions": ["ASR限时优惠到标准价格范围，非账单"]}
                    else:
                        cost = {"kind": "unknown", "reason": "没有新消费音频秒数"}
                    row["asr_cost"] = cost
                    costs.append(cost)
            elif row['name'] == 'generate_image':
                row.update(model=value.get('model'), usage=value.get('usage'))
                cost = image_cost(value.get('model'), value.get('usage'), provider_host=value.get('provider_host'))
                row['cost'] = cost
                costs.append(cost)
            elif row["name"] in {"search_web", "read_webpage", "read_document"}:
                cost = {"kind": "unknown", "reason": "工具未记录可核对的计费请求数、页数或金额"}
                row["cost"] = cost
                costs.append(cost)
        elif kind == "run.error":
            errors += 1
    for row in models:
        if row["status"] == "incomplete":
            row["cost"] = {"kind": "unknown", "reason": "请求未记录完整响应"}
            costs.append(row["cost"])
            usage_rows.append({})
    for row in tools:
        if row["status"] == "incomplete":
            row["cost"] = {"kind": "unknown", "reason": "工具没有完整结果，内部消耗未确认"}
            costs.append(row["cost"])
    usage, coverage = {}, {}
    for row in usage_rows:
        for key, value in row.items():
            usage[key] = usage.get(key, 0) + value
            coverage[key] = coverage.get(key, 0) + 1
    record = start.get("metadata", {}).get("chat_context", {}).get("record", {})
    duration = number(end.get("data", {}).get("duration"))
    return {"run_id": start.get("run_id"), "session_id": start.get("session_id"),
            "started_at": start.get("time"), "ended_at": end.get("time"),
            "status": end.get("data", {}).get("status", "incomplete"),
            "duration_seconds": duration if duration is not None else elapsed(start.get("time"), end.get("time")),
            "requester_id": record.get("user_id"),
            "question": str(start.get("metadata", {}).get("reply_question", {}).get("text", ""))[:240],
            "models": models, "tools": tools,
            "summary": {"model_calls": len(models), "tool_calls": len(tools), "run_errors": errors,
                        "tool_model_usage_calls": sum(row.get("usage") is not None for row in tools),
                        "tool_errors": sum(row["status"] == "error" for row in tools),
                        "model_seconds": round(sum(row.get("duration_seconds") or 0 for row in models), 3),
                        "tool_work_seconds": round(sum(row.get("duration_seconds") or 0 for row in tools), 3),
                        "tool_wall_seconds": union_seconds(intervals), "usage": usage or None,
                        "usage_counter_calls": coverage, "usage_missing_calls": sum(not row for row in usage_rows)},
            "cost": total_cost(costs),
            "notice": "耗时来自已记录事件和执行器；并发工具工作时长可重叠，墙钟时长按整批首个调用到首个结果记录的区间并集统计。"
                      "同批结果按调用顺序记录，结果记录时间不代表各工具实际完成时间。"
                      "工具内部模型执行与工具耗时重叠，阶段时长不能直接相加为总时长。"
                      "缓存/推理token是输入/输出的子集，不重复相加。运行耗时不包含QQ排队和实际送达。"}


def load_events(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("运行记录超过128MiB读取上限")
    events, seen, malformed, consumed = [], set(), 0, 0
    with path.open("rb") as stream:
        while line := stream.readline(MAX_LINE_BYTES + 1):
            consumed += len(line)
            if len(line) > MAX_LINE_BYTES or consumed > MAX_FILE_BYTES:
                raise ValueError("运行记录超过读取上限")
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or not isinstance(event.get("kind"), str) or not isinstance(event.get("data"), dict):
                    raise ValueError("invalid event")
                if event.get("id") in seen:
                    continue
                seen.add(event.get("id"))
                # Discard prompt, response, tool arguments and result bodies immediately.
                kind, data = event["kind"], event["data"]
                if kind.endswith(".request"):
                    data = {key: data[key] for key in ("round", "attempt") if key in data}
                elif kind.endswith(".response"):
                    data = {key: data[key] for key in ("round", "usage", "finish_reason", "model", "provider_host") if key in data}
                elif kind.endswith(".delta"):
                    data = {"text": bool(data.get("text"))}
                elif kind == "tool.call":
                    data = {"id": data["id"], "round": data.get("round"), "function": {"name": data.get("function", {}).get("name")}}
                elif kind == "tool.result":
                    result = data.get("result") or {}
                    value = result.get("data") or {}
                    keep = ("model", "provider_host", "usage", "new_model_usage", "new_asr_seconds", "asr_model", "new_asr_usage", "cached", "cache_hit")
                    data = {key: data.get(key) for key in ("call_id", "name", "duration")}
                    data["result"] = {"ok": result.get("ok"), "code": result.get("code"),
                                      "data": {key: value[key] for key in keep if key in value} if isinstance(value, dict) else {}}
                elif kind not in {"run.start", "run.end", "run.error"}:
                    continue
                else:
                    data = {key: data[key] for key in ("status", "duration") if key in data}
                metadata = {}
                if kind == "run.start":
                    original = event.get("metadata") or {}
                    record = original.get("chat_context", {}).get("record", {})
                    metadata = {"delivery": original.get("delivery", {}),
                                "chat_context": {"record": {key: record.get(key) for key in ("bot_id", "user_id")}},
                                "reply_question": {"text": str(original.get("reply_question", {}).get("text", ""))[:240]}}
                events.append({key: event.get(key) for key in ("kind", "time", "run_id", "session_id")} | {"data": data, "metadata": metadata})
            except (ValueError, TypeError, KeyError):
                malformed += 1
    return events, malformed


class RunHistory:
    def __init__(self, log, bridge=None):
        self.log, self.bridge = log, bridge

    async def read(self, args, ctx):
        request, principal = ctx.request, ctx.principal
        message_id = args.message_id
        record = request.metadata.get("chat_context", {}).get("record", {})
        bot_id = principal.attributes.get("bot", {}).get("user_id")
        if not args.run_id and message_id is None and args.use_quote:
            if bot_id and str(record.get("quote_sender_id")) == str(bot_id):
                message_id = record.get("quote_message_id")
        reference = None
        if message_id is not None:
            if not self.bridge:
                raise ValueError("当前渠道没有QQ回执查询服务")
            reference = await self.bridge.call("run_receipt_lookup", message_id=message_id,
                principal={"user_id": principal.user_id, "attributes": principal.attributes})
            if not reference:
                return {"runs": [], "matched": False, "message_id": message_id,
                        "reason": "该消息没有可验证的运行关联，可能早于功能上线、已超过7天或不属于当前会话；不会按相似文字猜测。"}
        result = await asyncio.to_thread(self._read, args, request, reference)
        if message_id is not None:
            result["message_id"] = message_id
        return result

    def _allowed(self, start, request, *, receipt=False):
        attrs, metadata = request.principal.attributes, start.get("metadata") or {}
        delivery = attrs.get("delivery", {})
        old_delivery = metadata.get("delivery", {})
        record = metadata.get("chat_context", {}).get("record", {})
        if delivery.get("platform") == "qq":
            if any(str(delivery.get(key)) != str(old_delivery.get(key)) for key in ("platform", "channel", "recipient_id")):
                return False
            bot = attrs.get("bot", {}).get("user_id")
            if (record.get("bot_id") is not None or not receipt) and (not bot or str(record.get("bot_id")) != str(bot)):
                return False
            return delivery.get("channel") == "group" or str(record.get("user_id")) == str(request.principal.user_id)
        return (not old_delivery and start.get("session_id") == request.conversation_id
                and str(record.get("user_id")) == str(request.principal.user_id))

    def _read(self, args, request, reference):
        root = self.log.directory
        session = (reference or {}).get("session_id", request.conversation_id)
        run = (reference or {}).get("run_id", args.run_id)
        if not re.fullmatch(COMPONENT, session) or (run and not re.fullmatch(COMPONENT, run)):
            raise ValueError("无效的运行记录标识")
        if run:
            paths = [root / session / "runs" / (run + ".jsonl")]
            delivery = request.principal.attributes.get("delivery", {})
            group = str(delivery.get("recipient_id", ""))
            if not reference and delivery.get("channel") == "group" and group.isdigit():
                paths = list(root.glob("qq_g_" + group + "_*/runs/" + run + ".jsonl"))
        else:
            paths = sorted((root / session / "runs").glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:50]
        reports, read_bytes = [], 0
        for path in paths:
            if not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            if path.stem == request.run_id:
                continue
            read_bytes += path.stat().st_size
            if read_bytes > MAX_FILE_BYTES:
                raise ValueError("本次记录读取超过128MiB，请指定run_id或消息ID缩小范围")
            events, malformed = load_events(path)
            start = next((event for event in events if event["kind"] == "run.start"), {})
            if start.get("run_id") != path.stem or start.get("session_id") != path.parent.parent.name:
                continue
            if not self._allowed(start, request, receipt=bool(reference)):
                continue
            report = project_run(events)
            report["malformed_event_lines"] = malformed
            if malformed or report["status"] != "completed":
                report["cost"]["coverage"] = "partial"
            reports.append(report)
            if not run and len(reports) >= args.offset + args.limit + 1:
                break
        reports.sort(key=lambda row: row.get("started_at") or "", reverse=True)
        return {"runs": reports[args.offset:args.offset + args.limit], "matched": bool(reports),
                "has_more": len(reports) > args.offset + args.limit,
                "scope": "指定运行" if run else "当前本人会话按本地文件更新时间选择的最近记录，最多检查50个文件（不含本次查询）",
                "notice": "公开轨迹链接过期不代表本地日志已删除；日志缺失或未授权均不返回。"}

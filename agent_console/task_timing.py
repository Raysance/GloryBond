"""Pure application scheduling rules, shared with the remote task store."""

from datetime import datetime


def parse_task_run_at(value):
    """Accept an explicit date/time with an offset, never a host-local time."""
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("run_at必须是含日期、时间和时区的ISO 8601字符串")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("run_at日期时间无效") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("run_at必须指定时区，例如2026-10-15T21:30:00+08:00")
    return moment.timestamp()


def normalized_task_action(args, now):
    kind = args.get("kind", "agent")
    if kind not in {"agent", "message"}:
        raise ValueError("未知任务类型")
    instruction = args.get("instruction", "")
    message = args.get("message")
    if kind == "agent" and not str(instruction).strip():
        raise ValueError("agent任务缺少instruction")
    if kind == "message" and not (isinstance(message, str) and message.strip()):
        raise ValueError("message任务缺少message")
    interval = args.get("interval_seconds")
    if interval is not None and (
        not isinstance(interval, int)
        or isinstance(interval, bool)
        or not 1 <= interval <= 31536000
    ):
        raise ValueError("周期必须为1到31536000秒")
    delay = args.get("delay_seconds")
    run_at = args.get("run_at")
    if run_at is not None:
        if delay is not None:
            raise ValueError("run_at与delay_seconds只能选择一种")
        next_run_at = parse_task_run_at(run_at)
        if not now < next_run_at <= now + 31536000:
            raise ValueError("run_at必须在未来一年内；已过期时间不会自动改到明天")
    else:
        if delay is None:
            delay = interval or 0
        if (
            not isinstance(delay, int)
            or isinstance(delay, bool)
            or not 0 <= delay <= 31536000
        ):
            raise ValueError("无效的首次延迟")
        next_run_at = now + delay
    runs = args.get("max_runs", 1)
    if not isinstance(runs, int) or isinstance(runs, bool) or not 1 <= runs <= 1000:
        raise ValueError("执行次数必须为1到1000")
    if runs > 1 and interval is None:
        raise ValueError("多次执行必须提供interval_seconds")
    return {
        "kind": kind,
        "instruction": instruction,
        "message": message,
        "interval_seconds": interval,
        "max_runs": runs,
        "next_run_at": next_run_at,
    }


def next_task_time(task, now):
    # Keep the cadence anchored to the schedule, not the previous completion.
    interval = task["interval_seconds"]
    due = task["next_run_at"] + interval
    if due <= now:
        due += (int((now - due) // interval) + 1) * interval
    return due

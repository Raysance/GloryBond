"""Pure application scheduling rules, shared with the remote task store."""


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
    if delay is None:
        delay = interval or 0
    if (
        not isinstance(delay, int)
        or isinstance(delay, bool)
        or not 0 <= delay <= 31536000
    ):
        raise ValueError("无效的首次延迟")
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
        "next_run_at": now + delay,
    }


def next_task_time(task, now):
    # Keep the cadence anchored to the schedule, not the previous completion.
    interval = task["interval_seconds"]
    due = task["next_run_at"] + interval
    if due <= now:
        due += (int((now - due) // interval) + 1) * interval
    return due

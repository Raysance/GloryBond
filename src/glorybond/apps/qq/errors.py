"""Bounded, literal-text error records for trusted QQ destinations."""
from collections import OrderedDict
from datetime import datetime
import logging
import os
import re
from threading import Lock
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from glorybond.agent.tool_errors import exception_details, redact_error


_recent = OrderedDict()
_lock = Lock()
_SECRET_KEY = re.compile(r"key|token|password|passwd|secret|cookie|credential|authorization|dsn|session", re.I)


def _secret_values(config):
    values = [v for k, v in os.environ.items() if _SECRET_KEY.search(k) and len(v) >= 4]

    def visit(node, private=False):
        if isinstance(node, dict):
            for key, value in node.items():
                visit(value, private or bool(_SECRET_KEY.search(str(key))))
        elif isinstance(node, (list, tuple)):
            for value in node:
                visit(value, private)
        elif private and isinstance(node, str) and len(node) >= 4:
            values.append(node)
    visit(config)
    return values


def sanitize(text, secrets=()):
    text = str(redact_error(str(text), secrets))
    text = re.sub(r"(?i)(cookie|set-cookie|session(?:_id)?|passwd)\s*[:=].*", r"\1=[redacted]", text)
    text = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+", "[URL已隐藏]", text)
    text = re.sub(r"(?<![\w])(?:[A-Za-z]:[\\/]|/)[\w.~/\\-]+", "[路径已隐藏]", text)
    # Response bodies, request parameters and headers are private diagnostics.
    text = re.sub(r"(?is)\b(?:response(?:_body)?|body|headers|payload|params|query)\s*[=:].*", "[原始内容已隐藏]", text)
    text = re.sub(r"(?s)[{\[].*[}\]]", "[结构化内容已隐藏]", text)
    return text[:600]


def readable_reason(details):
    kinds = {details["error_type"], *(c["error_type"] for c in details.get("causes", []))}
    status = details.get("diagnostics", {}).get("http_status")
    if status in {401, 403}:
        return f"外部服务拒绝了访问（HTTP {status}），需要核对该服务的登录状态或访问权限。"
    if status == 429:
        return "外部服务正在限流（HTTP 429），本次请求未能完成。"
    if isinstance(status, int) and status >= 500:
        return f"外部服务返回服务器错误（HTTP {status}）。"
    if any("Timeout" in k for k in kinds):
        return "等待服务响应超时，本次操作未能确认完成。"
    if any(k in {"ConnectionError", "ConnectError", "ProxyError", "NetworkError", "ConnectionRefusedError", "gaierror"} for k in kinds):
        return "连接服务失败，可能涉及网络、代理或目标服务；具体故障点尚未确认。"
    if "ActionFailed" in kinds:
        return "QQ 接口拒绝了本次操作。"
    if "FileNotFoundError" in kinds:
        return "操作需要的文件或资源不存在。"
    if "PermissionError" in kinds:
        return "当前操作缺少所需权限。"
    if any(k in {"JSONDecodeError", "ParseError", "ValidationError"} for k in kinds):
        return "收到的数据格式不符合当前接口要求，无法继续解析。"
    if "ValueError" in kinds:
        return "输入或返回数据未通过校验。"
    return "处理过程中发生异常，本次操作未能完整完成。"


def build_report(error, *, operation, report_id, secrets=(), partial=False):
    details = exception_details(error, phase=operation, redactor=lambda value: redact_error(value, secrets))
    reason = readable_reason(details)
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    nodes = [f"{operation}异常\n{reason}\n"
             + ("已有结果继续保留，其余部分未完成。\n" if partial else "")
             + f"时间：{timestamp}\n报告编号：{report_id}"]
    causes = []
    current = error
    for item in [details, *details.get("causes", [])]:
        message = sanitize(item.get("message") or item["error_type"], secrets).splitlines()[0]
        # HTTP/adapter exceptions commonly embed server bodies or request input.
        external = type(current).__module__.startswith(("requests", "httpx", "httpcore", "nonebot", "hok_camp_client", "hok_research", "psycopg", "redis"))
        if (item["error_type"] in {"ActionFailed", "CampError", "OSError", "ConnectionError", "ConnectError", "ProxyError", "NetworkError"}
                or external or "Timeout" in item["error_type"] or details.get("diagnostics", {}).get("http_status")):
            message = reason
        causes.append(f"{item['error_type']}：{message}")
        if current is not None:
            current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    nodes.append("错误原因（已脱敏）\n" + "\n由以下异常引起：\n".join(causes))
    locations = [f"{v['file']}:{v['line']} · {v['function']}"
                 for v in details.get("locations", [])]
    if locations:
        nodes.append("诊断位置\n" + "\n".join(locations))
    return nodes


def _claim(key, *, interval):
    now = time.monotonic()
    with _lock:
        if key in _recent and now - _recent[key] < interval:
            return False
        _recent[key] = now
        _recent.move_to_end(key)
        while len(_recent) > 512:
            _recent.popitem(last=False)
    return True


def report_exception(error, *, operation, event=None, group_id=None, private=False, partial=False):
    """Report once; reporting failures never replace the original exception.

    Foreground reports stay in their actual conversation. Background failures
    use the configured group unless the operation is explicitly private.
    """
    if not isinstance(error, Exception) or getattr(error, "_qq_reported", False):
        return False
    try:
        from glorybond.config.settings import confs
        from glorybond.apps.qq.message_sender import add_forward_msg, add_group_forward_msg, add_msg
        from nonebot.adapters.onebot.v11 import MessageSegment

        if event is not None:
            target = ("group", getattr(event, "group_id")) if getattr(event, "group_id", None) else ("private", event.get_user_id())
        else:
            target = ("private", confs["QQBot"]["super_qid"]) if private else ("group", group_id or confs["QQBot"]["group_qid"])
        message_id = getattr(event, "message_id", None)
        key = (target, operation, type(error).__name__, str(message_id or "background"))
        if not _claim(key, interval=300):
            return False
        report_id = uuid4().hex[:10]
        nodes = build_report(error, operation=operation, report_id=report_id,
                             secrets=_secret_values(confs), partial=partial)
        logging.getLogger(__name__).error("QQ_ERROR_REPORT %s", "\n\n".join(nodes))
        options = {"sender_name": "机器人诊断", "title": operation + "异常", "preview": nodes[0].splitlines()[1],
                   "metadata": {"source": "diagnostic", "error_report_id": report_id}}
        published = False
        try:
            if event is not None:
                add_forward_msg(nodes, event=event, **options)
            elif target[0] == "group":
                add_group_forward_msg(nodes, group_qid=target[1], **options)
            else:
                add_msg(MessageSegment.text("\n\n".join(nodes)), msg_type="private", to_id=target[1], metadata=options["metadata"])
            published = True
            try:
                error._qq_reported = True
            except (AttributeError, TypeError):
                pass
        finally:
            if target[0] != "private" or str(target[1]) != str(confs["QQBot"]["super_qid"]):
                add_msg(MessageSegment.text("\n\n".join(nodes)), msg_type="private", to_id=confs["QQBot"]["super_qid"], metadata=options["metadata"])
        return published
    except Exception as notice_error:
        logging.getLogger(__name__).error("QQ_ERROR_REPORT_FAILED error_type=%s", type(notice_error).__name__)
        return False


def report_error_text(text, **kwargs):
    """Compatibility for partial-result producers that already return a summary."""
    lines = str(text).splitlines()
    reasons = [line.partition("err=")[2] for line in lines if "err=" in line]
    if not reasons:
        reasons = [lines[-1] if lines else "未提供错误详情"]
    return report_exception(RuntimeError("；".join(reasons[:8])), **kwargs)


def register_error_hooks(scheduler):
    from nonebot.message import run_postprocessor
    from nonebot.matcher import Matcher
    from nonebot.adapters.onebot.v11 import Event
    from apscheduler.events import EVENT_JOB_ERROR

    @run_postprocessor
    async def unhandled_matcher_error(matcher: Matcher, event: Event, exception: Exception | None):
        if exception is not None and str(getattr(matcher, "module_name", "")).startswith("glorybond.apps.qq"):
            report_exception(exception, operation="消息处理", event=event)

    def unhandled_job_error(event):
        job = scheduler.get_job(event.job_id)
        if job is not None and str(getattr(job.func, "__module__", "")).startswith("glorybond.") and isinstance(event.exception, Exception):
            report_exception(event.exception, operation="后台任务 " + str(event.job_id))

    scheduler.add_listener(unhandled_job_error, EVENT_JOB_ERROR)

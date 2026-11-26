"""Delay subscription diagnostics until repeated failures, independently of retries."""
import asyncio
from contextvars import ContextVar
import logging

from glorybond.storage.notification_state import record_interval_outcome


FAILURE_NOTICE_THRESHOLD = 30
SUBSCRIPTION_JOBS = {
    "bili_video_push": "B站定时推送",
    "x_subscription_push": "X 定时推送",
}
current_interval_job = ContextVar("qq_interval_job", default=None)
logger = logging.getLogger(__name__)


def record_outcome(job_id, *, phase, error=None, group_id=None):
    """One notice per failure streak; storage/reporting failures stay in logs."""
    if job_id not in SUBSCRIPTION_JOBS or phase not in {"poll", "delivery"}:
        return
    from glorybond.config.settings import confs
    from glorybond.apps.qq.errors import report_exception

    target = group_id or confs["QQBot"]["group_qid"]
    try:
        count, notify = record_interval_outcome(
            f"{job_id}:{phase}:{target}", failed=error is not None,
            threshold=FAILURE_NOTICE_THRESHOLD,
        )
    except Exception as state_error:
        logger.error("INTERVAL_FAILURE_STATE_ERROR job=%s phase=%s error_type=%s original_error_type=%s",
                     job_id, phase, type(state_error).__name__, type(error).__name__ if error else "none")
        return
    if error is not None:
        logger.error("INTERVAL_JOB_FAILED job=%s phase=%s consecutive=%s error_type=%s",
                     job_id, phase, count, type(error).__name__)
    if notify:
        stage = "检查" if phase == "poll" else "QQ投递"
        report_exception(error, operation=f"{SUBSCRIPTION_JOBS[job_id]}{stage}（连续{count}次失败）",
                         group_id=target, partial=True)


async def run_subscription_job(job_id, check, **kwargs):
    """Count a failed poll once, even when several subscriptions failed."""
    if job_id not in SUBSCRIPTION_JOBS:
        raise ValueError("Unknown subscription job")
    failures = []

    def on_error(error):
        # Keep one original exception for the eventual sanitized report.
        if not failures:
            failures.append(error)

    result = None
    token = current_interval_job.set(job_id)
    try:
        result = await asyncio.to_thread(check, on_error=on_error, **kwargs)
    except Exception as error:
        on_error(error)
    finally:
        current_interval_job.reset(token)

    if isinstance(result, dict) and result.get("errors") and not failures:
        on_error(RuntimeError("部分订阅检查失败，详细原因已保留在运行日志中"))
    if failures:
        record_outcome(job_id, phase="poll", error=failures[0])
    elif isinstance(result, dict) and result.get("checked", 0) > 0:
        record_outcome(job_id, phase="poll")
    return result

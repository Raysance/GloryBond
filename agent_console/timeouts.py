"""Application deadlines leave room for slow image jobs and final delivery."""

from agent_runtime import Budget


IMAGE_TASK_TIMEOUT_SECONDS = 600
IMAGE_RPC_TIMEOUT_SECONDS = 800
IMAGE_TOOL_TIMEOUT_SECONDS = 810
IMAGE_PROGRESS_INTERVAL_SECONDS = 120
DEFAULT_RUN_TIMEOUT_SECONDS = 1200


def application_budget(config=None):
    return Budget(**{"timeout_seconds": DEFAULT_RUN_TIMEOUT_SECONDS, **(config or {})})

"""Application tool middleware using the engine's existing ToolResult protocol."""

import asyncio
import inspect

from agent_runtime import ToolRegistry, ToolResult
from agent_console.tool_errors import exception_details, redact_error


class DiagnosticToolRegistry(ToolRegistry):
    """Cover built-in and future externally registered handlers in both channels."""

    def __init__(self, *, redactor=None):
        super().__init__()
        self.redactor = redactor or redact_error

    def register(self, *, handler, timeout=30, effect="read", **spec):
        name = spec["name"]

        async def diagnosed(args, ctx):
            try:
                task = handler(args, ctx) if inspect.iscoroutinefunction(handler) else asyncio.to_thread(handler, args, ctx)
                value = await asyncio.wait_for(task, timeout)
                if isinstance(value, ToolResult) and not value.ok:
                    # Preserve partial results and datasets from tools such as batch SQL.
                    value.error = self.redactor(value.error or "工具报告失败")
                    data = dict(value.data) if isinstance(value.data, dict) else {"result": self.redactor(value.data)}
                    if "error_details" in data:
                        data["error_details"] = self.redactor(data["error_details"])
                    if isinstance(data.get("observations"), list):
                        data["observations"] = [item if isinstance(item, dict) and item.get("ok") else self.redactor(item)
                                                for item in data["observations"]]
                    if "error_details" not in data:
                        data = {**data, "error_details": {"phase": "tool_result", "tool": name,
                            "message": value.error, "retryable": False,
                            "recovery": "结合返回的局部结果和诊断修正问题，不能声称失败部分已经成功。"}}
                    value.data = data
                    if value.code == "OUTCOME_UNKNOWN":
                        ctx.uncertain_tools.add(name)
                return value
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                details = getattr(exc, "error_details", None)
                if not isinstance(details, dict):
                    details = exception_details(exc, phase="tool_handler", operation=name, redactor=self.redactor)
                details = self.redactor({**details, "tool": name})
                details.setdefault("message", self.redactor(str(exc)) or type(exc).__name__)
                details.setdefault("phase", "tool_handler")
                details.setdefault("diagnostics", {})
                # Never replay an action whose response was lost or timed out.
                uncertain = effect != "read" and (
                    isinstance(exc, TimeoutError) or details.get("outcome_unknown", False) or
                    details.get("error_type") in {"TimeoutError", "Timeout", "ReadTimeout", "ConnectTimeout"})
                code = "TOOL_TIMEOUT" if isinstance(exc, TimeoutError) else "TOOL_ERROR"
                if isinstance(exc, TimeoutError):
                    details["message"] = self.redactor(str(exc)) or f"工具执行超过 {timeout} 秒时限"
                    details["diagnostics"]["timeout_seconds"] = timeout
                if uncertain:
                    ctx.uncertain_tools.add(name)
                    code = "OUTCOME_UNKNOWN"
                    details.update(retryable=False, outcome_unknown=True,
                                   recovery="操作可能已生效，先检查状态或询问用户，禁止自动重复提交。")
                elif effect != "read":
                    details.update(retryable=False,
                                   recovery="先确认是否产生副作用；核对状态与参数后再决定，不自动重放写操作。")
                return ToolResult(False, error=details["message"], code=code,
                                  data={"error_details": details})

        # The middleware owns the original deadline; the outer executor keeps
        # a small cleanup guard and continues to own authorization/cancellation.
        super().register(handler=diagnosed, timeout=timeout + 1, effect=effect, **spec)

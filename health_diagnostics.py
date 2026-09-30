"""Run the NBot chat smoke test only when an administrator requests it."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import subprocess
import time


def _failure(error: str, *, duration_ms: float = 0, exit_code: int | None = None) -> dict:
    result = {
        "version": 1,
        "status": "failed",
        "duration_ms": round(duration_ms, 2),
        "checks": [],
        "error": error,
    }
    if exit_code is not None:
        result["exit_code"] = exit_code
    return result


def _last_json_object(output: str) -> dict | None:
    """Find the final JSON line while tolerating harmless application log output."""
    for line in reversed(str(output or "").splitlines()):
        try:
            value = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _valid_report(report: dict) -> bool:
    return (
        report.get("version") == 1
        and report.get("status") in {"ok", "failed"}
        and isinstance(report.get("checks"), list)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and item.get("status") in {"ok", "failed"}
            for item in report["checks"]
        )
    )


def run_chat_runtime_diagnostic(nbot_root: str | Path, timeout: float = 100) -> dict:
    """Execute the fixed NBot diagnostic command and parse its safe JSON report."""
    started = time.perf_counter()
    root = Path(nbot_root).resolve()
    python = root / ".venv" / "bin" / "python"
    script = root / "hok" / "tools" / "chat_runtime_diagnostic.py"
    if not python.is_file():
        return _failure("nbot_python_missing")
    if not script.is_file():
        return _failure("chat_diagnostic_tool_missing")

    try:
        process = subprocess.run(
            [str(python), "-m", "local_debugger", str(script)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _failure(
            "chat_diagnostic_timeout",
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as error:
        return _failure(
            f"chat_diagnostic_runner_error:{type(error).__name__}",
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    runner_duration_ms = (time.perf_counter() - started) * 1000
    report = _last_json_object(process.stdout)
    if report is None or not _valid_report(report):
        return _failure(
            "chat_diagnostic_output_invalid",
            duration_ms=runner_duration_ms,
            exit_code=process.returncode,
        )
    report = dict(report)
    report["runner_duration_ms"] = round(runner_duration_ms, 2)
    report["exit_code"] = process.returncode
    report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if process.returncode != 0:
        report["status"] = "failed"
    return report

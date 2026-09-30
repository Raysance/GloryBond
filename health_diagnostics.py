"""Run the NBot chat smoke test only when an administrator requests it."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from dotenv import dotenv_values


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
            and item.get("status") in {"ok", "failed", "skipped"}
            for item in report["checks"]
        )
    )


def _process_start_epoch(pid: int) -> float:
    stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    boot_line = next(
        line for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
        if line.startswith("btime ")
    )
    boot_epoch = int(boot_line.split()[1])
    return boot_epoch + int(stat_fields[21]) / os.sysconf("SC_CLK_TCK")


def inspect_nbot_runtime(nbot_root: str | Path) -> tuple[dict, str, dict]:
    """Compare the deployed checkout with the live systemd process and its key."""
    started = time.perf_counter()
    root = Path(nbot_root).resolve()
    if not shutil.which("systemctl") or not Path("/proc").is_dir():
        return ({
            "name": "deployed_nbot_runtime",
            "status": "skipped",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "reason": "systemd_procfs_unavailable",
        }, "", {})
    try:
        process = subprocess.run(
            [
                "systemctl", "show", "hok-nbot.service",
                "--property=ActiveState", "--property=SubState", "--property=MainPID",
                "--property=ExecMainStartTimestamp", "--property=EnvironmentFiles",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        properties = {}
        environment_files = []
        for line in process.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                if key == "EnvironmentFiles":
                    environment_files.extend(re.findall(
                        r"(\S+)\s+\(ignore_errors=(?:yes|no)\)", value,
                    ))
                else:
                    properties[key] = value
        pid = int(properties.get("MainPID") or 0)
        process_root = Path(f"/proc/{pid}/cwd").resolve() if pid else None
        environ = {}
        if pid:
            for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                key, separator, value = entry.partition(b"=")
                if separator:
                    environ[key.decode(errors="ignore")] = value.decode(errors="ignore")
        credential = str(environ.get("HOK_CHAT_API_KEY") or "")
        credential_hash = hashlib.sha256(credential.encode()).hexdigest() if credential else ""
        configured_environment = {}
        for path in environment_files:
            configured_environment.update({
                str(key): str(value)
                for key, value in dotenv_values(path).items()
                if value is not None
            })
        configured_credential = str(configured_environment.get("HOK_CHAT_API_KEY") or "")
        configured_credential_hash = (
            hashlib.sha256(configured_credential.encode()).hexdigest()
            if configured_credential else ""
        )
        credential_matches_files = bool(
            credential_hash and configured_credential_hash
            and credential_hash == configured_credential_hash
        )
        ref_candidates = [root / ".git" / "refs" / "heads" / "main", root / ".git" / "FETCH_HEAD"]
        ref_mtimes = [path.stat().st_mtime for path in ref_candidates if path.is_file()]
        process_started = _process_start_epoch(pid) if pid else 0
        checkout_updated = max(ref_mtimes) if ref_mtimes else 0
        restarted_after_checkout = bool(process_started and checkout_updated
                                        and process_started + 2 >= checkout_updated)
        active = properties.get("ActiveState") == "active" and properties.get("SubState") == "running"
        cwd_matches = process_root == root
        passed = (
            active and pid > 0 and cwd_matches and restarted_after_checkout
            and bool(credential_hash) and credential_matches_files
        )
        runtime_environment = {
            key: value for key, value in environ.items()
            if key.startswith("HOK_") or key in {"BOT_PATH", "WEB_PATH", "REDIS_CONF"}
        }
        return ({
            "name": "deployed_nbot_runtime",
            "status": "ok" if passed else "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "service_active": active,
            "main_pid_present": pid > 0,
            "working_directory_matches_checkout": cwd_matches,
            "restarted_after_checkout": restarted_after_checkout,
            "running_chat_credential_available": bool(credential_hash),
            "environment_files_loaded": len(environment_files),
            "credential_matches_environment_files": credential_matches_files,
            "service_started_at": properties.get("ExecMainStartTimestamp") or "",
        }, credential_hash, runtime_environment)
    except Exception as error:
        return ({
            "name": "deployed_nbot_runtime",
            "status": "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"runtime_inspection_failed:{type(error).__name__}",
        }, "", {})


def run_chat_runtime_diagnostic(nbot_root: str | Path, timeout: float = 180) -> dict:
    """Execute the fixed NBot diagnostic command and parse its safe JSON report."""
    started = time.perf_counter()
    root = Path(nbot_root).resolve()
    python = root / ".venv" / "bin" / "python"
    script = root / "hok" / "tools" / "chat_runtime_diagnostic.py"
    if not python.is_file():
        return _failure("nbot_python_missing")
    if not script.is_file():
        return _failure("chat_diagnostic_tool_missing")

    runtime_check, running_credential_hash, runtime_environment = inspect_nbot_runtime(root)
    child_environment = os.environ.copy()
    child_environment.update(runtime_environment)
    if running_credential_hash:
        child_environment["HOK_DIAGNOSTIC_EXPECTED_KEY_SHA256"] = running_credential_hash

    try:
        process = subprocess.run(
            [str(python), "-m", "local_debugger", str(script)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=child_environment,
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
    report["checks"] = [runtime_check, *report["checks"]]
    report["runner_duration_ms"] = round(runner_duration_ms, 2)
    report["exit_code"] = process.returncode
    report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if process.returncode != 0 or runtime_check["status"] == "failed":
        report["status"] = "failed"
    return report

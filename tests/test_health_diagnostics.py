import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import health_diagnostics


class HealthDiagnosticsTests(unittest.TestCase):
    def test_runs_only_the_fixed_nbot_tool_and_parses_last_json_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / ".venv" / "bin" / "python"
            script = root / "hok" / "tools" / "chat_runtime_diagnostic.py"
            python.parent.mkdir(parents=True)
            script.parent.mkdir(parents=True)
            python.touch()
            script.touch()
            report = {
                "version": 1,
                "status": "ok",
                "duration_ms": 12.5,
                "checks": [{"name": "configuration", "status": "ok", "duration_ms": 0.1}],
            }
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="application log\n" + json.dumps(report) + "\n", stderr="",
            )
            runtime = ({"name": "deployed_nbot_runtime", "status": "ok", "duration_ms": 1}, "abc123")
            with patch.object(health_diagnostics, "inspect_nbot_runtime", return_value=runtime), \
                    patch.object(health_diagnostics.subprocess, "run", return_value=completed) as run:
                result = health_diagnostics.run_chat_runtime_diagnostic(root)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["checks"][0]["name"], "deployed_nbot_runtime")
        command = run.call_args.args[0]
        resolved_root = root.resolve()
        self.assertEqual(command, [
            str(resolved_root / ".venv" / "bin" / "python"),
            "-m",
            "local_debugger",
            str(resolved_root / "hok" / "tools" / "chat_runtime_diagnostic.py"),
        ])
        self.assertEqual(run.call_args.kwargs["cwd"], resolved_root)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(
            run.call_args.kwargs["env"]["HOK_DIAGNOSTIC_EXPECTED_KEY_SHA256"],
            "abc123",
        )

    def test_missing_runtime_and_invalid_output_fail_without_stderr_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                health_diagnostics.run_chat_runtime_diagnostic(directory)["error"],
                "nbot_python_missing",
            )

            root = Path(directory)
            python = root / ".venv" / "bin" / "python"
            script = root / "hok" / "tools" / "chat_runtime_diagnostic.py"
            python.parent.mkdir(parents=True)
            script.parent.mkdir(parents=True)
            python.touch()
            script.touch()
            completed = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="not json", stderr="secret diagnostic stderr",
            )
            runtime = ({"name": "deployed_nbot_runtime", "status": "skipped", "duration_ms": 0}, "")
            with patch.object(health_diagnostics, "inspect_nbot_runtime", return_value=runtime), \
                    patch.object(health_diagnostics.subprocess, "run", return_value=completed):
                result = health_diagnostics.run_chat_runtime_diagnostic(root)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "chat_diagnostic_output_invalid")
        self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()

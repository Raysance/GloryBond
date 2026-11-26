"""Run the local debugger with its persistent virtual environment."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
ENV_DIR = Path(os.environ.get("HOK_DEBUG_VENV") or ROOT / "local_debugger/.venv")


def _env_python() -> Path:
    if sys.platform == "win32":
        return ENV_DIR / "Scripts" / "python.exe"
    return ENV_DIR / "bin" / "python"


def main() -> int:
    python = _env_python()
    if not python.exists():
        setup = subprocess.run([sys.executable, str(ROOT / "tools/debugger/setup_env.py")], cwd=ROOT)
        if setup.returncode:
            return setup.returncode

    command = [str(python), "-m", "tools.debugger", *sys.argv[1:]]
    if sys.platform == "win32":
        return subprocess.run(command, cwd=ROOT).returncode
    os.execv(str(python), command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

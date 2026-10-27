"""Create or refresh the persistent local debugger virtual environment."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = Path(__file__).resolve().parent / ".venv"


def _env_python() -> Path:
    if sys.platform == "win32":
        return ENV_DIR / "Scripts" / "python.exe"
    return ENV_DIR / "bin" / "python"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create local_debugger/.venv and install the project dependencies into it."
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to create the environment (default: current interpreter)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    uv = shutil.which("uv")
    if not uv:
        print("LOCAL_DEBUGGER_SETUP_ERROR: uv is required but was not found in PATH", file=sys.stderr)
        return 1

    try:
        subprocess.run(
            [uv, "venv", "--allow-existing", "--python", args.python, str(ENV_DIR)],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(_env_python()),
                "--requirements",
                str(ROOT / "pyproject.toml"),
            ],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as err:
        print(
            f"LOCAL_DEBUGGER_SETUP_ERROR: command={err.cmd!r} returncode={err.returncode}",
            file=sys.stderr,
        )
        return err.returncode or 1

    print(f"Persistent local debugger environment ready: {ENV_DIR}")
    print(f"Python: {_env_python()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

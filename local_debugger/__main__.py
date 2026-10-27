"""Run a local debug script after preparing the project debug runtime."""

from __future__ import annotations

import argparse
from pathlib import Path
import runpy
import sys

from .runtime import bootstrap


def build_parser() -> argparse.ArgumentParser:
    """Build the local debugger CLI parser."""
    parser = argparse.ArgumentParser(description="Run a HOK_QQBot debug script with local debugger bootstrap.")
    parser.add_argument("target", help="Debug script path or importable module name")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the target")
    return parser


def main() -> int:
    """Run the requested debug target."""
    parser = build_parser()
    namespace = parser.parse_args()
    root = bootstrap()
    target_path = Path(namespace.target)
    if not target_path.is_absolute():
        target_path = root / target_path
    sys.argv = [str(target_path if target_path.exists() else namespace.target), *namespace.args]
    if target_path.exists():
        runpy.run_path(str(target_path), run_name="__main__")
    else:
        runpy.run_module(namespace.target, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

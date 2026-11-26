"""Source and runtime roots, independent of the current working directory."""
import os
from pathlib import Path


def project_root() -> Path:
    return Path(os.environ.get("BOT_PATH") or Path(__file__).resolve().parents[3]).expanduser().resolve()


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def agent_resources() -> Path:
    return project_root() / "resources" / "agent"


def manual_root() -> Path:
    return project_root() / "docs" / "manual"

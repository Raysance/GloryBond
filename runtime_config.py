"""Resolve portable runtime paths for the HOK web service."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path
    stack_root: Path
    nbot_root: Path
    web_root: Path
    env_file: Path
    config_file: Path
    static_variables_file: Path
    redis_config_file: Path
    data_dir: Path
    file_transfer_dir: Path


def _absolute_path(value: str | os.PathLike[str], base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _first_existing(candidates: list[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return fallback.resolve()


def _first_named_child(parent: Path, names: list[str], fallback: Path) -> Path:
    """Select an exact child name even on case-insensitive development hosts."""
    if parent.is_dir():
        children = {child.name: child for child in parent.iterdir()}
        for name in names:
            if name in children:
                return children[name].resolve()
    return fallback.resolve()


def resolve_runtime_paths(
    environ: Mapping[str, str] | None = None,
    app_root: str | os.PathLike[str] | None = None,
) -> RuntimePaths:
    env = environ if environ is not None else os.environ
    resolved_app_root = _absolute_path(
        app_root or Path(__file__).resolve().parent,
        Path.cwd(),
    )
    stack_root = _absolute_path(
        env.get("HOK_STACK_ROOT") or resolved_app_root.parent,
        resolved_app_root,
    )

    default_nbot_root = _first_named_child(
        stack_root,
        ["nbot", "NBot", "HOK_QQBot"],
        stack_root / "nbot",
    )
    nbot_root = _absolute_path(
        env.get("BOT_PATH") or default_nbot_root,
        stack_root,
    )
    web_root = _absolute_path(
        env.get("WEB_PATH") or resolved_app_root,
        stack_root,
    )

    default_env_file = _first_existing(
        [stack_root / ".env", Path("/QQBot/.env")],
        stack_root / ".env",
    )
    env_file = _absolute_path(
        env.get("HOK_ENV_FILE") or default_env_file,
        stack_root,
    )

    return RuntimePaths(
        app_root=resolved_app_root,
        stack_root=stack_root,
        nbot_root=nbot_root,
        web_root=web_root,
        env_file=env_file,
        config_file=_absolute_path(
            env.get("HOK_CONFIG_FILE") or nbot_root / "config.yaml",
            stack_root,
        ),
        static_variables_file=_absolute_path(
            env.get("HOK_STATIC_VARIABLES_FILE")
            or nbot_root / "variables_static.json",
            stack_root,
        ),
        redis_config_file=_absolute_path(
            env.get("REDIS_CONF") or nbot_root / "redis.json",
            stack_root,
        ),
        data_dir=_absolute_path(
            env.get("HOK_DATA_DIR") or nbot_root / "data",
            stack_root,
        ),
        file_transfer_dir=_absolute_path(
            env.get("HOK_FILE_TRANSFER_DIR") or nbot_root / "file_transfer",
            stack_root,
        ),
    )


def load_runtime_paths() -> RuntimePaths:
    preliminary = resolve_runtime_paths()
    if preliminary.env_file.is_file():
        load_dotenv(preliminary.env_file, override=False)
    return resolve_runtime_paths()


RUNTIME = load_runtime_paths()

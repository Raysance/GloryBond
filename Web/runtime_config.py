"""Resolve portable runtime paths for the HOK web service."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv
import yaml


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path
    stack_root: Path
    nbot_root: Path
    web_root: Path
    napcat_root: Path
    env_file: Path
    config_file: Path
    data_dir: Path
    file_transfer_dir: Path


def _absolute_path(value: str | os.PathLike[str], base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


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

    default_env_file = nbot_root / ".env"
    env_file = _absolute_path(
        env.get("HOK_ENV_FILE") or default_env_file,
        stack_root,
    )

    return RuntimePaths(
        app_root=resolved_app_root,
        stack_root=stack_root,
        nbot_root=nbot_root,
        web_root=web_root,
        napcat_root=_absolute_path(
            env.get("HOK_NAPCAT_ROOT") or stack_root / "napcat",
            stack_root,
        ),
        env_file=env_file,
        config_file=_absolute_path(
            env.get("HOK_CONFIG_FILE") or nbot_root / "config.yaml",
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


def load_shared_config(
    runtime: RuntimePaths = RUNTIME,
    environ: Mapping[str, str] | None = None,
) -> dict:
    """Load the shared non-secret YAML and inject credentials from NBot's .env."""
    env = environ if environ is not None else os.environ
    with runtime.config_file.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    secret_paths = {
        "HOK_DEEPSEEK_API_KEY": ("QQBot", "deepseek_key"),
        "HOK_ARK_API_KEY": ("QQBot", "ark_key"),
        "HOK_ARK_IMAGE_API_KEY": ("QQBot", "ark_image_key"),
        "HOK_APIMART_API_KEY": ("QQBot", "apimart_key"),
        "HOK_STEAM_API_KEY": ("Steam", "api_key"),
        "HOK_WEB_SECRET_KEY": ("WebService", "secret_key"),
        "HOK_WEB_VALID_PATTERN": ("WebService", "valid_pattern"),
        "HOK_WZRY_TOKEN": ("wzry", "token"),
        "HOK_WZRY_ENCODERES": ("wzry", "encoderes"),
        "HOK_DATABASE_DSN": ("PostgreSQL", "dsn"),
    }
    for env_name, (section, key) in secret_paths.items():
        if env_name in env:
            section_values = config.get(section)
            if not isinstance(section_values, dict):
                section_values = {}
                config[section] = section_values
            section_values[key] = str(env[env_name]).strip()
    return config

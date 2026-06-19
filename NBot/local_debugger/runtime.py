"""Prepare a local runtime for importing project modules from debug tools."""

from __future__ import annotations

import datetime
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types


def project_root() -> Path:
    """Return the repository root path."""
    return Path(__file__).resolve().parents[1]


def _ensure_sys_path(root: Path) -> None:
    """Ensure the repository root is importable."""
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)


def _ensure_redis_conf() -> None:
    """Ensure REDIS_CONF points to a readable local config."""
    redis_conf = os.environ.get("REDIS_CONF")
    if redis_conf and Path(redis_conf).exists():
        return
    root = project_root()
    config = {
        "BOT_PATH": str(root),
        "REDIS_HOST": "localhost",
        "REDIS_PORT": 6379,
        "REDIS_DB": 0,
        "REDIS_DB_LIKED_SET": 1,
        "REDIS_DB_SHARE_QUEUE": 2,
        "REDIS_DB_ANALYZE_QUEUE": 3,
        "REDIS_DB_MESSAGE_QUEUE": 4,
        "REDIS_DB_TODAY_HERO_POOL": 5,
        "REDIS_DB_BTL_ANALYZE_EVALUATOR_POOL": 6,
        "REDIS_DB_DIY_CODE": 7,
        "REDIS_DB_CHAT_MEMORY": 8,
        "REDIS_TEXT_EXPIRE_SECONDS": 3600,
    }
    path = Path(tempfile.gettempdir()) / "hok_local_debug_redis_conf.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    os.environ["REDIS_CONF"] = str(path)


def _install_yaml_stub() -> None:
    """Install a minimal yaml stub when PyYAML is unavailable."""
    try:
        import yaml
        return
    except ModuleNotFoundError:
        yaml_module = types.ModuleType("yaml")
    yaml_module.FullLoader = object
    yaml_module.load = lambda stream, Loader=None: {}
    sys.modules["yaml"] = yaml_module


def _install_dotenv_stub() -> None:
    """Install a minimal dotenv stub when python-dotenv is unavailable."""
    try:
        import dotenv
        return
    except ModuleNotFoundError:
        dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module


def _install_apscheduler_stub() -> None:
    """Install minimal apscheduler stubs when apscheduler is unavailable."""
    try:
        import apscheduler.schedulers.background
        import apscheduler.util
        return
    except ModuleNotFoundError:
        apscheduler_module = types.ModuleType("apscheduler")
        schedulers_module = types.ModuleType("apscheduler.schedulers")
        background_module = types.ModuleType("apscheduler.schedulers.background")
        util_module = types.ModuleType("apscheduler.util")

    class BackgroundScheduler:
        """Placeholder scheduler for local imports."""

        pass

    background_module.BackgroundScheduler = BackgroundScheduler
    util_module.timezone = lambda *args, **kwargs: None
    sys.modules["apscheduler"] = apscheduler_module
    sys.modules["apscheduler.schedulers"] = schedulers_module
    sys.modules["apscheduler.schedulers.background"] = background_module
    sys.modules["apscheduler.util"] = util_module


def _install_redis_stub() -> None:
    """Install a minimal redis stub when redis-py is unavailable."""
    try:
        import redis
        if hasattr(redis, "Redis"):
            return
    except ModuleNotFoundError:
        redis_module = types.ModuleType("redis")
    else:
        redis_module = redis

    class Redis:
        """Placeholder Redis client for local imports."""

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.data = {}

        def set(self, key, value, ex=None):
            """Store a value in memory for local debug calls."""
            self.data[key] = value
            return True

    redis_module.Redis = Redis
    sys.modules["redis"] = redis_module


def _install_toon_stub() -> None:
    """Install a minimal toon stub when toon is unavailable."""
    try:
        import toon
        return
    except ModuleNotFoundError:
        sys.modules["toon"] = types.ModuleType("toon")


def _install_wcwidth_stub() -> None:
    """Install a minimal wcwidth stub when wcwidth is unavailable."""
    try:
        import wcwidth
        return
    except ModuleNotFoundError:
        wcwidth_module = types.ModuleType("wcwidth")
    wcwidth_module.wcswidth = lambda value: len(str(value))
    sys.modules["wcwidth"] = wcwidth_module


def _install_dateutil_stub() -> None:
    """Install a minimal dateutil stub when python-dateutil is unavailable."""
    try:
        import dateutil
        import dateutil.parser
        return
    except ModuleNotFoundError:
        dateutil_module = types.ModuleType("dateutil")
        parser_module = types.ModuleType("dateutil.parser")
    parser_module.parse = lambda value: datetime.datetime.fromisoformat(value)
    dateutil_module.parser = parser_module
    sys.modules["dateutil"] = dateutil_module
    sys.modules["dateutil.parser"] = parser_module


def _install_missing_dependency_stubs() -> None:
    """Install stubs for import-time dependencies not needed by local debug scripts."""
    _install_yaml_stub()
    _install_dotenv_stub()
    _install_apscheduler_stub()
    _install_redis_stub()
    _install_toon_stub()
    _install_wcwidth_stub()
    _install_dateutil_stub()


def _prepare_hok_namespace(root: Path) -> None:
    """Prepare the hok namespace without executing hok/__init__.py."""
    existing = sys.modules.get("hok")
    if existing and getattr(existing, "__path__", None):
        return
    package = types.ModuleType("hok")
    package.__path__ = [str(root / "hok")]
    sys.modules["hok"] = package


def bootstrap() -> Path:
    """Prepare environment variables, dependency stubs, import paths, and the hok namespace."""
    root = project_root()
    os.environ["BOT_PATH"] = str(root)
    _ensure_sys_path(root)
    _ensure_redis_conf()
    _install_missing_dependency_stubs()
    _prepare_hok_namespace(root)
    return root


def import_hok_module(module_name: str):
    """Import a hok submodule after preparing the local debug runtime."""
    bootstrap()
    normalized = module_name if module_name.startswith("hok.") else f"hok.{module_name}"
    return importlib.import_module(normalized)

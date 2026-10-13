"""Trusted external adapter sent over SSH; never installed in the remote app.

It reads deployed configuration/code and uses the existing isolated SQL role.
Generated Python is executed only inside bubblewrap, never in this worker.
"""

import ast
import base64
from collections import Counter
import contextlib
import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import redis
import requests
from dotenv import dotenv_values
import yaml
from sqlglot import exp, parse_one


STATE_PREFIX = "hok:agent_runtime:console:"
CONTEXT = {}


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def extracted_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    if {node.name for node in nodes} != set(names):
        raise RuntimeError("服务器 API 源码接口发生变化，请检查适配器")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


def bootstrap(args):
    root = Path(args["root"])
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    env = dict(dotenv_values(root / ".env"))
    pid = subprocess.check_output(
        ["systemctl", "show", "hok-nbot.service", "-p", "MainPID", "--value"], text=True
    ).strip()
    if pid != "0":
        env.update(
            dict(
                part.split("=", 1)
                for part in Path(f"/proc/{pid}/environ")
                .read_bytes()
                .decode()
                .split("\0")
                if "=" in part
            )
        )
    namespace = {"urlparse": urlparse}
    extracted_functions(
        root / "hok/zstatic.py",
        ["_build_chat_api_config", "_apply_secret_environment"],
        namespace,
    )
    cfg = namespace["_apply_secret_environment"](cfg, env)
    model = namespace["_build_chat_api_config"](cfg, env)
    if not env.get("HOK_CHAT_READONLY_DSN"):
        raise RuntimeError("运行进程缺少独立只读数据库配置，禁止回退写账号")
    with psycopg.connect(env["HOK_CHAT_READONLY_DSN"], connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_user, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
            identity = cur.fetchone()
            if identity[0] != "hok_chat_reader" or any(identity[1:]):
                raise RuntimeError("数据库不是独立无特权只读账号")
            cur.execute(
                "SELECT table_name FROM information_schema.views WHERE table_schema='hok'"
            )
            views = {row[0] for row in cur.fetchall()}
    rcfg = cfg["Redis"]
    store = redis.Redis(
        host=rcfg["REDIS_HOST"],
        port=rcfg["REDIS_PORT"],
        db=0,
        decode_responses=True,
        socket_timeout=10,
    )
    store.ping()
    validation = {}
    exec(compile(args["validator"], "portable_sql_validator", "exec"), validation)
    search_cfg = dict(cfg.get("AliyunSearch", {}))
    search_cfg["api_key"] = env.get("HOK_ALIYUN_SEARCH_API_KEY", "")
    for key in ["endpoint", "workspace", "service_id", "content_type", "way"]:
        search_cfg[key] = env.get("HOK_ALIYUN_SEARCH_" + key.upper()) or search_cfg.get(
            key
        )
    api_namespace = {
        "urlparse": urlparse,
        "quote": quote,
        "json": json,
        "aliyun_search_config": search_cfg,
        "confs": cfg,
        "dmc": SimpleNamespace(**cfg.get("DynamicVariables", {})),
        "sleep_seconds": time.sleep,
    }

    def request(method, url, **kwargs):
        with requests.Session() as session:
            session.trust_env = False
            return session.request(method, url, **kwargs)

    def proxied_request(method, url, **kwargs):
        proxy = env.get("HOK_CLASH_PROXY_URL") or cfg.get("Proxy", {}).get("clash_url")
        if not proxy:
            raise RuntimeError("服务器没有配置图片服务所需的 Clash 代理")
        return request(method, url, proxies={"http": proxy, "https": proxy}, **kwargs)

    api_namespace.update(direct_request=request, clash_request=proxied_request)
    extracted_functions(
        root / "hok/api_adapters/ai.py",
        ["aliyun_web_search", "apimart_images_generate"],
        api_namespace,
    )
    mem_namespace = {
        "json": json,
        "datetime": datetime,
        "math": math,
        "re": re,
        "hashlib": hashlib,
        "Counter": Counter,
        "List": List,
        "Dict": Dict,
        "Optional": Optional,
        "_HISTORY_TOKEN_RE": re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+"),
    }
    extracted_functions(
        root / "hok/zmemory.py",
        [
            "_validate_fact_content",
            "prepare_fact_memory",
            "parse_fact_memories",
            "search_fact_memories",
            "tokenize_history_text",
            "_bm25_scores",
            "search_history_records",
        ],
        mem_namespace,
    )
    CONTEXT.update(
        sandbox_runner=args["sandbox_runner"],
        plot_renderer=args["plot_renderer"],
        plot_catalog=args["plot_catalog"],
        root=root,
        cfg=cfg,
        env=env,
        model=model,
        store=store,
        validation=validation,
        catalogs=args["catalogs"],
        definitions=args["definitions"],
        views=views,
        api=api_namespace,
        memory=mem_namespace,
    )
    task_timing = {}
    exec(compile(args["task_timing"], "task_timing", "exec"), task_timing)
    CONTEXT["task_timing"] = task_timing
    role_models = ModuleType("console_roleplay_models")
    sys.modules[role_models.__name__] = role_models
    exec(
        compile(args["roleplay_models"], "console_roleplay_models", "exec"),
        role_models.__dict__,
    )
    role_store = {}
    exec(
        compile(
            args["roleplay_store"].replace(
                "from agent_console.roleplay_models import",
                "from console_roleplay_models import",
            ),
            "console_roleplay_store",
            "exec",
        ),
        role_store,
    )
    CONTEXT["roleplay_store"] = role_store["roleplay_operation"]
    CONTEXT["roles"] = args["roles"]
    static = cfg.get("StaticVariables", {})
    reference_namespace = {}
    exec(
        compile(args["reference_builder"], "portable_reference_data", "exec"),
        reference_namespace,
    )
    CONTEXT["reference_class"] = reference_namespace["ReferenceData"]
    CONTEXT["reference_manifest"] = args["reference_manifest"]
    references = reference_snapshot()
    font_candidates = [
        Path(
            cfg.get("ChatPlot", {}).get("font_path")
            or "/usr/share/fonts/chinese/simhei.ttf"
        ),
        Path("/usr/share/fonts/google-noto-emoji/NotoEmoji-Regular.ttf"),
    ]
    CONTEXT["fonts"] = [str(path) for path in font_candidates if path.is_file()]
    return {
        "private": {"api_key": model["api_key"]},
        "public": {
            "model": model["model"],
            "base_url": model["base_url"],
            "database": "PostgreSQL / hok_chat_reader",
            "memory": "Redis DB0",
            "sandbox": "bubblewrap / Linux",
            "views_mode": "native" if "chat_player_battles" in views else "trusted_cte",
            "season_start": static.get("this_season_start_date"),
            "sql_limits": cfg.get("ChatSQL", {}),
            "references": references,
            "source": "运行进程环境 + 服务器 config.yaml / API 源码",
            "search": bool(search_cfg["api_key"]),
            "images": bool(cfg.get("QQBot", {}).get("apimart_key")),
        },
    }


def reference_data():
    # The trusted shared manifest selects public mappings, never whole config.
    source = CONTEXT["reference_manifest"]["source"]
    path = Path(source["path"])
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("参考数据源必须位于项目根目录内")
    root = CONTEXT["root"]
    content = (root / path).read_text()
    document = (
        yaml.safe_load(content) if source["format"] == "yaml" else json.loads(content)
    )
    values = document.get(source["section"], {}) if source.get("section") else document
    return CONTEXT["reference_class"](
        CONTEXT["reference_manifest"],
        values,
        source=source["path"]
        + ("#" + source["section"] if source.get("section") else ""),
    )


def reference_snapshot():
    references = reference_data()
    return {"directory": references.directory(), "context": references.context()}


def db_connection(scope=None):
    conn = psycopg.connect(
        CONTEXT["env"]["HOK_CHAT_READONLY_DSN"],
        connect_timeout=5,
        row_factory=dict_row,
        options="-c default_transaction_read_only=on -c search_path=pg_catalog,hok -c timezone=Asia/Shanghai",
    )
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT set_config('statement_timeout','5000',true)")
        cur.execute("SELECT set_config('lock_timeout','5000',true)")
        if scope is not None:
            cur.execute("SELECT set_config('hok.chat_group_scope',%s,true)", (scope,))
    return conn


def trusted_scope(principal):
    if principal.get("all_groups") and "chat.cross_group" in principal.get(
        "scopes", []
    ):
        return "*"
    if principal.get("group_id"):
        return str(principal["group_id"])
    raise PermissionError("请求没有可信群聊范围")


def expand_semantic_views(sql):
    """Compile trusted view definitions as CTEs when the server predates them.

    Model input has already been validated against the semantic catalogue.
    No DDL is run, and storage names are never disclosed to the model.
    """
    tree = parse_one(sql, read="postgres")
    required = {}
    definitions = CONTEXT["definitions"]

    def expand(expression):
        for table in list(expression.find_all(exp.Table)):
            name = table.name
            if (
                table.db == "hok"
                and name in definitions
                and name not in CONTEXT["views"]
            ):
                if name not in required:
                    view = parse_one(definitions[name], read="postgres")
                    expand(view)
                    required[name] = view
                table.set("db", None)

    expand(tree)
    if required:
        current = tree.args.get("with_")
        ctes = [
            exp.CTE(this=value, alias=exp.TableAlias(this=exp.to_identifier(name)))
            for name, value in required.items()
        ]
        if current:
            ctes.extend(current.expressions)
        tree.set("with_", exp.With(expressions=ctes))
    return tree.sql(dialect="postgres")


def analyze(args):
    domain = args["domain"]
    catalog = CONTEXT["catalogs"]["hok_sql" if domain == "game" else "chat_sql"]
    owners = {
        k: {tuple(v) for v in values}
        for k, values in catalog.get("json_root_owners", {}).items()
    }
    normalized = []
    # All statements are validated before the first connection is opened.
    for query in args["queries"]:
        normalized.append(
            CONTEXT["validation"]["validate_readonly_sql"](
                query["sql"],
                query.get("params"),
                allowed_tables=catalog["tables"],
                column_usage=catalog.get("column_usage", {}),
                schema_name=catalog["schema"],
                json_root_owners=owners,
            )
        )
    scope = trusted_scope(args["principal"]) if domain == "chat" else None
    results = []
    limits = CONTEXT["cfg"].get("ChatSQL", {})
    row_limit = min(500, limits.get("max_rows", 200))
    with db_connection(scope) as conn:
        for query, sql in zip(args["queries"], normalized):
            try:
                with conn.transaction():
                    with conn.cursor(name="agent_" + uuid4().hex) as cur:
                        executed = (
                            expand_semantic_views(sql) if domain == "game" else sql
                        )
                        cur.execute(
                            f"SELECT * FROM ({executed}) AS agent_result LIMIT {row_limit + 1}"
                        )
                        rows = cur.fetchmany(row_limit + 1)
                        columns = [column.name for column in cur.description]
                        if len(columns) > limits.get("max_columns", 40):
                            raise ValueError("结果列数超过上限")
                        bounded = []
                        size = 0
                        truncated = len(rows) > row_limit
                        for row in rows[:row_limit]:
                            clean = json.loads(
                                json.dumps(
                                    row, default=json_default, ensure_ascii=False
                                )
                            )
                            size += len(json.dumps(clean, ensure_ascii=False).encode())
                            if size > limits.get("max_bytes", 60000):
                                truncated = True
                                break
                            bounded.append(clean)
                        results.append(
                            {
                                "ok": True,
                                "intent": query.get("intent"),
                                "columns": columns,
                                "rows": bounded,
                                "row_count": len(bounded),
                                "truncated": truncated,
                                "source": "postgresql_archive",
                            }
                        )
            except Exception as exc:
                results.append(
                    {
                        "ok": False,
                        "intent": query.get("intent"),
                        "error": str(exc)[:1500],
                    }
                )
    return {"observations": results, "catalog_version": catalog["version"]}


def search_history(args):
    with db_connection(trusted_scope(args["principal"])) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT group_id,message_id,user_id,reply_to_message_id,source_timestamp AS timestamp,message_text AS text FROM hok.chat_history_messages ORDER BY source_timestamp"
            )
            rows = cur.fetchall()
    queries = list(dict.fromkeys([args["original_query"], *args.get("queries", [])]))
    hits = CONTEXT["memory"]["search_history_records"](rows, queries, limit=8)
    return {
        "messages": hits,
        "archive_messages": len(rows),
        "queries": queries,
        "scope": "all_saved_groups"
        if args["principal"].get("all_groups")
        else "current_group",
    }


def memory(args):
    key = "hok:memory:facts:" + args["user_id"]
    store = CONTEXT["store"]
    action = args["action"]
    if action == "recall":
        records = CONTEXT["memory"]["parse_fact_memories"](store.hvals(key))
        return {
            "memories": CONTEXT["memory"]["search_fact_memories"](
                records, args.get("query", ""), limit=20
            ),
            "total": len(records),
        }
    if action == "forget":
        return {"deleted": bool(store.hdel(key, args["memory_id"]))}
    memory_id = args.get("memory_id") or uuid4().hex
    for _ in range(3):
        with store.pipeline() as pipe:
            try:
                pipe.watch(key)
                existing = pipe.hget(key, memory_id)
                if args.get("memory_id") and not existing:
                    raise ValueError("记忆不存在")
                if not existing and pipe.hlen(key) >= 100:
                    raise ValueError("记忆数量已到上限")
                record = CONTEXT["memory"]["prepare_fact_memory"](
                    args["content"],
                    memory_id=memory_id,
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    existing=json.loads(existing) if existing else None,
                )
                pipe.multi()
                pipe.hset(key, memory_id, json.dumps(record, ensure_ascii=False))
                pipe.execute()
                return {"saved": True, "memory": record}
            except redis.WatchError:
                continue
    raise RuntimeError("记忆并发更新，请重试")


def sandbox(args):
    code = args["code"]
    if len(code) > 20000:
        raise ValueError("代码超过长度上限")
    interpreter = os.path.realpath(sys.executable)
    base = Path(sys.base_prefix)
    packages = (
        Path(sys.prefix)
        / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    runner = CONTEXT["sandbox_runner"]
    with tempfile.TemporaryDirectory(prefix="agent-sandbox-") as work:
        command = [
            "/usr/bin/bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
        ]
        for path in ["/usr", "/lib", "/lib64", str(base / "lib")]:
            if Path(path).exists():
                command.extend(["--ro-bind", path, path])
        command.extend(
            [
                "--ro-bind",
                interpreter,
                interpreter,
                "--ro-bind",
                str(packages),
                "/opt/site-packages",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--bind",
                work,
                "/work",
                "--chdir",
                "/work",
                interpreter,
                "-c",
                runner,
            ]
        )
        if not Path("/usr/bin/systemd-run").is_file():
            raise RuntimeError("缺少 systemd cgroup 资源隔离，拒绝运行生成代码")
        command = [
            "/usr/bin/systemd-run",
            "--scope",
            "--quiet",
            "--unit=agent-sandbox-" + uuid4().hex,
            "--property=TasksMax=64",
            "--property=MemoryMax=1073741824",
            "--",
            *command,
        ]
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp",
            "MPLCONFIGDIR": "/tmp/mpl",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }

        def limits():
            resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
            resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
            resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))

        # File-backed bounded output prevents a generated print loop exhausting
        # the trusted worker's memory through communicate().
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                env=env,
                preexec_fn=limits,
                start_new_session=True,
            )
            try:
                proc.communicate(
                    json.dumps(
                        {
                            **args,
                            "font_paths": CONTEXT["fonts"],
                            "plot_renderer": CONTEXT["plot_renderer"],
                            "plot_catalog": CONTEXT["plot_catalog"],
                        },
                        ensure_ascii=False,
                    ).encode(),
                    timeout=25,
                )
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise TimeoutError("隔离 Python 超时，整个进程组已结束")
            stdout.seek(0)
            stderr.seek(0)
            out, err = stdout.read(5000), stderr.read(8000)
        if proc.returncode:
            raise RuntimeError(
                "隔离 Python 失败：" + err.decode(errors="replace")[-1800:]
            )
        result_path = Path(work) / "result.json"
        value = (
            json.loads(result_path.read_text())
            if result_path.is_file() and not result_path.is_symlink()
            else None
        )
        artifacts = []
        for path in list(Path(work).glob("*.png"))[:4]:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > 4 * 1024**2
            ):
                continue
            raw = path.read_bytes()
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                continue
            artifact_id = uuid4().hex
            CONTEXT["store"].setex(
                STATE_PREFIX + "artifact:" + artifact_id,
                604800,
                base64.b64encode(raw).decode(),
            )
            artifacts.append(
                {"artifact_id": artifact_id, "mime": "image/png", "name": path.name}
            )
        return {
            "stdout": out.decode(errors="replace")[:5000],
            "result": value,
            "artifacts": artifacts,
        }


def dispatch(args):
    op = args["op"]
    if op == "bootstrap":
        return bootstrap(args)
    store = CONTEXT["store"]
    session = str(args.get("session_id", ""))
    if op.startswith(("state_", "dialogue_")) and not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,80}", session
    ):
        raise ValueError("invalid session")
    if op == "analyze":
        return analyze(args)
    if op == "search_history":
        return search_history(args)
    if op == "reference_snapshot":
        return reference_snapshot()
    if op in {"reference_catalogs", "reference_lookup"}:
        if "reference.read" not in args.get("principal", {}).get("scopes", []):
            raise PermissionError("请求没有参考数据读取权限")
        references = reference_data()
        return (
            references.directory()
            if op == "reference_catalogs"
            else references.lookup(**args["query"])
        )
    if op == "memory":
        return memory(args)
    if op == "roleplay":
        return CONTEXT["roleplay_store"](
            store,
            builtins=CONTEXT["roles"],
            **{k: v for k, v in args.items() if k != "op"},
        )
    if op == "python":
        return sandbox(args)
    if op == "web_search":
        return CONTEXT["api"]["aliyun_web_search"](
            args["query"], args.get("max_results", 5)
        )
    if op == "image":
        result = CONTEXT["api"]["apimart_images_generate"](
            prompt=args["prompt"],
            reference_image_url="",
            size=args.get("size", "1:1"),
            resolution="1K",
        )
        response = CONTEXT["api"]["clash_request"]("GET", result["url"], timeout=60)
        response.raise_for_status()
        raw = response.content
        if len(raw) > 8 * 1024**2:
            raise ValueError("图片超过大小上限")
        artifact_id = uuid4().hex
        store.setex(
            STATE_PREFIX + "artifact:" + artifact_id,
            604800,
            base64.b64encode(raw).decode(),
        )
        return {
            "artifact_id": artifact_id,
            "mime": response.headers.get("content-type", "image/png"),
            "request": result["request"],
        }
    if op == "artifact":
        return store.get(STATE_PREFIX + "artifact:" + args["artifact_id"])
    if op == "task_create":
        task_id = uuid4().hex
        action = CONTEXT["task_timing"]["normalized_task_action"](args, time.time())
        task = {
            "task_id": task_id,
            "session_id": session,
            "principal": args["principal"],
            "required_tools": args.get("required_tools", []),
            "runs": 0,
            "status": "scheduled",
            "revision": 1,
            **action,
        }
        with store.pipeline(transaction=True) as pipe:
            pipe.set(STATE_PREFIX + "task:" + task_id, json.dumps(task))
            pipe.zadd(STATE_PREFIX + "tasks", {task_id: task["next_run_at"]})
            pipe.execute()
        return task
    if op == "task_list":
        tasks = []
        for key in store.scan_iter(STATE_PREFIX + "task:*"):
            task = json.loads(store.get(key) or "{}")
            if task.get("session_id") == session:
                tasks.append(task)
        return {"tasks": tasks}
    if op == "task_cancel":
        key = STATE_PREFIX + "task:" + args["task_id"]
        with store.pipeline() as pipe:
            pipe.watch(key)
            task = json.loads(pipe.get(key) or "{}")
            if task.get("session_id") != session:
                raise PermissionError("任务不属于当前会话")
            task.update(status="cancelled", revision=task["revision"] + 1)
            pipe.multi()
            pipe.set(key, json.dumps(task))
            pipe.zrem(STATE_PREFIX + "tasks", args["task_id"])
            pipe.execute()
        return {"cancelled": True}
    if op == "task_active":
        task = json.loads(store.get(STATE_PREFIX + "task:" + args["task_id"]) or "{}")
        return (
            task.get("status") == "running"
            and task.get("lease_token") == args["lease_token"]
        )
    if op == "task_due":
        tasks = []
        for task_id in store.zrangebyscore(
            STATE_PREFIX + "tasks", 0, time.time(), start=0, num=4
        ):
            key = STATE_PREFIX + "task:" + task_id
            with store.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    task = json.loads(pipe.get(key) or "{}")
                    if task.get("status") not in ["scheduled", "running"]:
                        continue
                    if task.get("lease_until", 0) > time.time():
                        continue
                    task.update(
                        status="running",
                        lease_until=time.time() + 600,
                        lease_token=uuid4().hex,
                    )
                    pipe.multi()
                    pipe.set(key, json.dumps(task))
                    pipe.execute()
                    tasks.append(task)
                except redis.WatchError:
                    continue
        return tasks
    if op == "task_finish":
        key = STATE_PREFIX + "task:" + args["task_id"]
        with store.pipeline() as pipe:
            pipe.watch(key)
            task = json.loads(pipe.get(key) or "{}")
            if (
                task.get("lease_token") != args["lease_token"]
                or task.get("status") == "cancelled"
            ):
                return False
            task["runs"] += 1
            task["lease_until"] = 0
            interval = task.get("interval_seconds")
            repeat = (
                interval and task["runs"] < task["max_runs"] and not args.get("failed")
            )
            task["status"] = (
                "scheduled"
                if repeat
                else ("failed" if args.get("failed") else "completed")
            )
            pipe.multi()
            pipe.set(key, json.dumps(task))
            if repeat:
                task["next_run_at"] = CONTEXT["task_timing"]["next_task_time"](
                    task, time.time()
                )
                pipe.set(key, json.dumps(task))
                pipe.zadd(
                    STATE_PREFIX + "tasks", {args["task_id"]: task["next_run_at"]}
                )
            else:
                pipe.zrem(STATE_PREFIX + "tasks", args["task_id"])
            pipe.execute()
        return True
    if op == "state_append":
        key = STATE_PREFIX + "events:" + session
        with store.pipeline(transaction=True) as pipe:
            pipe.rpush(key, json.dumps(args["event"], ensure_ascii=False))
            pipe.expire(key, 604800)
            pipe.execute()
        return True
    if op == "state_events":
        return [
            json.loads(raw)
            for raw in store.lrange(STATE_PREFIX + "events:" + session, 0, -1)
        ]
    if op == "dialogue_load":
        return [
            json.loads(raw)
            for raw in store.lrange(STATE_PREFIX + "dialogue:" + session, 0, -1)
        ]
    if op == "dialogue_save":
        key = STATE_PREFIX + "dialogue:" + session
        with store.pipeline(transaction=True) as pipe:
            pipe.rpush(
                key,
                json.dumps(
                    {"role": "user", "content": args["question"]}, ensure_ascii=False
                ),
                json.dumps(
                    {"role": "assistant", "content": args["answer"]}, ensure_ascii=False
                ),
            )
            pipe.ltrim(key, -20, -1)
            pipe.expire(key, 604800)
            pipe.execute()
        return True
    raise ValueError("未知适配器操作")


def main():
    wire = sys.stdout
    for line in sys.stdin:
        try:
            args = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                result = dispatch(args)
            response = {"ok": True, "data": result}
        except Exception as exc:
            error = str(exc)
            for value in CONTEXT.get("env", {}).values():
                if isinstance(value, str) and len(value) > 12:
                    error = error.replace(value, "[redacted]")
            response = {"ok": False, "error": error[:1800], "type": type(exc).__name__}
        wire.write(
            json.dumps(response, ensure_ascii=False, default=json_default) + "\n"
        )
        wire.flush()


if __name__ == "__main__":
    main()

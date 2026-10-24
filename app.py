from fastapi import FastAPI, Request, HTTPException, Query, Body, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.templating import Jinja2Templates

import redis
import asyncio
import os
import json
import sys
import logging
import datetime
import secrets
import yaml
import time
import subprocess
import shutil
from urllib.parse import urlencode
from runtime_config import RUNTIME, load_shared_config
from utils import *
from request_analytics import (
    analytics_payload,
    build_request_event,
    cache_ip_geography,
    enrich_request_event,
    should_track_request,
    store_request_event,
)
from health_diagnostics import run_chat_runtime_diagnostic

# 引入变量
confs = load_shared_config()
variables_to_import = ["userlist", "roleidlist", "qid", "namenick", "nameref", "extra_useridlist", "extra_roleidlist", "extra_namenick"]
config_file_path = str(RUNTIME.config_file)

def reload_variables():
    data = load_shared_config().get("StaticVariables", {})
    for var_name in variables_to_import:
        if var_name in data:
            globals()[var_name] = data[var_name]
        else:
            globals()[var_name] = {}

reload_variables()

templates = Jinja2Templates(directory=str(RUNTIME.app_root / "templates"))
# 引入Redis变量
file_path_root = str(RUNTIME.file_transfer_dir)
varia = confs.get("Redis", {})
globals().update(varia)

# 初始化fastapi与redis
app = FastAPI()
APP_STARTED_AT = time.time()
r_com = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
r_liked_set = r_com
r_share_queue = r_com
r_analyze_queue = r_com
r_chat = r_com
analytics_tasks = set()
manual_health_check_lock = asyncio.Lock()

WEB_ARTIFACT_PREFIX = "hok:web:artifact:"
BATTLE_LIKED_IDS_KEY = "hok:battle:liked_ids"
BATTLE_SHARE_QUEUE_KEY = "hok:queue:battle:share"
BATTLE_ANALYZE_QUEUE_KEY = "hok:queue:battle:analyze"
MEMORY_PREFIX = "hok:memory:"


def web_artifact_storage_key(key: str) -> str:
    return f"{WEB_ARTIFACT_PREFIX}{key}"


def get_web_artifact(key: str):
    return r_com.get(web_artifact_storage_key(key))


def web_artifact_exists(key: str) -> bool:
    return bool(r_com.exists(web_artifact_storage_key(key)))

SECRET_KEY = confs["WebService"]["secret_key"]
VALID_PATTERN = [int(item) for item in str(confs["WebService"]["valid_pattern"])]


@app.middleware("http")
async def collect_request_analytics(request: Request, call_next):
    user_agent = str(request.headers.get("user-agent") or "")
    track_request = should_track_request(request.url.path, request.method, user_agent)
    started = time.perf_counter()
    response = await call_next(request)
    if track_request:
        try:
            event = build_request_event(
                request,
                response_status=response.status_code,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            enrich_request_event(r_com, event, request.query_params.get("key"))
            store_request_event(r_com, event)
            if event.get("ip"):
                task = asyncio.create_task(asyncio.to_thread(cache_ip_geography, r_com, event["ip"]))
                analytics_tasks.add(task)
                task.add_done_callback(analytics_tasks.discard)
        except Exception as exc:
            logging.warning("REQUEST_ANALYTICS_STORE_FAILED path=%s error=%r", request.url.path, exc)
    return response

def key_to_filename(key: str, reqtype: str):
    try:
        content = json.loads(get_web_artifact(key).decode('utf-8'))
        local_path=os.path.join("file_transfer","temp_files",content["filename"]+".json")
        return content,local_path
    except:
        raise Exception()
        ret_json={}
        filepath=os.path.join("btldefaultjson",reqtype+".json")
        ret_json["filename"]=filepath
        ret_json["caller"]={"PlayerName":"链接已失效，这是历史对局条件查询的模板页面"}
        ret_json["DateFrom"]="模拟DateFrom"
        ret_json["DateTo"]="模拟DateTo"
        ret_json["time"]="模拟time"
        return ret_json,filepath

def is_mobile_request(request: Request):
    user_agent = str(request.headers.get("user-agent") or "").lower()
    mobile_tokens = (
        "android",
        "iphone",
        "ipad",
        "ipod",
        "mobile",
        "windows phone",
        "mqqbrowser",
        "micromessenger",
    )
    return any(token in user_agent for token in mobile_tokens)

def health_service_names(env_name: str, defaults: list[str]) -> list[str]:
    raw = os.environ.get(env_name)
    if not raw:
        return defaults
    names = [item.strip() for item in raw.split(",") if item.strip()]
    return names or defaults

def run_health_command(command: list[str], timeout: float = 1.5) -> dict:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "error": "command_not_found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}

def systemd_service_state(service_names: list[str]) -> dict:
    if not shutil.which("systemctl"):
        return {"available": False, "state": "unavailable"}

    checked = {}
    for service_name in service_names:
        result = run_health_command(["systemctl", "is-active", service_name])
        state = result.get("stdout") or result.get("stderr") or result.get("error") or "unknown"
        checked[service_name] = state
        if result.get("ok") and state == "active":
            return {"available": True, "state": "active", "matched": service_name, "checked": checked}

    return {"available": True, "state": "inactive", "checked": checked}

def process_snapshot() -> list[dict]:
    result = run_health_command(["ps", "-eo", "pid=,comm=,args="])
    if not result.get("ok"):
        result = run_health_command(["ps", "-axo", "pid=,comm=,args="])
    if not result.get("ok"):
        return []

    processes = []
    current_pid = os.getpid()
    for line in result.get("stdout", "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == current_pid:
            continue
        processes.append({
            "pid": pid,
            "command": os.path.basename(parts[1]),
            "args": parts[2] if len(parts) > 2 else parts[1],
        })
    return processes

def summarize_processes(processes: list[dict], matcher) -> dict:
    shell_commands = {"bash", "dash", "fish", "sh", "zsh"}
    matches = [proc for proc in processes if proc["command"] not in shell_commands and matcher(proc)]
    return {
        "count": len(matches),
        "pids": [proc["pid"] for proc in matches[:5]],
        "commands": sorted({proc["command"] for proc in matches})[:5],
    }

def git_repository_info(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {"status": "missing", "path": path}
    if not shutil.which("git"):
        return {"status": "unknown", "path": path, "error": "git_command_not_found"}

    root_result = run_health_command(["git", "-C", path, "rev-parse", "--show-toplevel"])
    if not root_result.get("ok"):
        return {
            "status": "unknown",
            "path": path,
            "error": root_result.get("stderr") or root_result.get("error") or "not_a_git_repository",
        }

    repo_root = root_result.get("stdout") or path
    head_result = run_health_command(["git", "-C", repo_root, "rev-parse", "HEAD"])
    short_head_result = run_health_command(["git", "-C", repo_root, "rev-parse", "--short", "HEAD"])
    branch_result = run_health_command(["git", "-C", repo_root, "rev-parse", "--abbrev-ref", "HEAD"])
    if not head_result.get("ok"):
        return {
            "status": "unknown",
            "path": path,
            "root": repo_root,
            "error": head_result.get("stderr") or head_result.get("error") or "head_unavailable",
        }

    return {
        "status": "ok",
        "path": path,
        "root": repo_root,
        "head": head_result.get("stdout"),
        "short_head": short_head_result.get("stdout") if short_head_result.get("ok") else None,
        "branch": branch_result.get("stdout") if branch_result.get("ok") else None,
    }

def check_redis_health(processes: list[dict]) -> dict:
    started = time.time()
    systemd = systemd_service_state(health_service_names("HEALTH_REDIS_SERVICES", ["redis", "redis-server"]))
    process_info = summarize_processes(
        processes,
        lambda proc: proc["command"] == "redis-server" or "redis-server" in proc["args"].lower(),
    )
    try:
        r_com.ping()
        latency_ms = round((time.time() - started) * 1000, 2)
        info = {}
        try:
            raw_info = r_com.info(section="server")
            info["redis_version"] = raw_info.get("redis_version")
        except Exception:
            pass
        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "systemd": systemd,
            "processes": process_info,
            "dbs": {
                "hok": REDIS_DB,
            },
            "queues": {
                BATTLE_SHARE_QUEUE_KEY: r_share_queue.llen(BATTLE_SHARE_QUEUE_KEY),
                BATTLE_ANALYZE_QUEUE_KEY: r_analyze_queue.llen(BATTLE_ANALYZE_QUEUE_KEY),
            },
            **info,
        }
    except Exception as exc:
        return {
            "status": "down",
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "systemd": systemd,
            "processes": process_info,
            "error": repr(exc),
        }

def check_nginx_health(processes: list[dict]) -> dict:
    service_names = health_service_names("HEALTH_NGINX_SERVICES", ["nginx"])
    systemd = systemd_service_state(service_names)
    process_info = summarize_processes(
        processes,
        lambda proc: proc["command"] == "nginx" or "nginx:" in proc["args"].lower(),
    )
    status = "ok" if systemd.get("state") == "active" or process_info["count"] > 0 else "down"
    return {
        "status": status,
        "systemd": systemd,
        "processes": process_info,
    }

def qqbot_path_candidates() -> list[str]:
    candidates = [
        os.environ.get("QQBOT_PATH"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "HOK_QQBot")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "NBot")),
    ]
    deduped = []
    for path in candidates:
        if path and path not in deduped:
            deduped.append(path)
    return deduped

def check_qqbot_health(processes: list[dict]) -> dict:
    service_names = health_service_names(
        "HEALTH_QQBOT_SERVICES",
        ["hok-nbot", "hok-qqbot", "hok_qqbot", "HOK_QQBot", "qqbot", "nonebot"],
    )
    systemd = systemd_service_state(service_names)
    path_candidates = qqbot_path_candidates()
    existing_paths = [path for path in path_candidates if os.path.exists(path)]
    normalized_paths = [path.lower() for path in path_candidates]

    def matches_qqbot_process(proc: dict) -> bool:
        args = proc["args"].lower()
        if "hok_qqbot_web" in args or "hok_qqbot_web" in proc["command"].lower():
            return False
        if "nb run" in args or "nonebot" in args:
            return True
        return any(path and path in args for path in normalized_paths)

    process_info = summarize_processes(processes, matches_qqbot_process)
    status = "ok" if systemd.get("state") == "active" or process_info["count"] > 0 else "down"
    if status == "down" and existing_paths:
        status = "degraded"
    repository_path = existing_paths[0] if existing_paths else (path_candidates[0] if path_candidates else "")

    return {
        "status": status,
        "systemd": systemd,
        "processes": process_info,
        "repository": git_repository_info(repository_path),
        "paths": {
            "configured": path_candidates,
            "existing": existing_paths,
        },
    }

def onebot_path_candidates() -> list[str]:
    candidates = [
        os.environ.get("ONEBOT_PATH"),
        os.environ.get("NAPCAT_PATH"),
        str(RUNTIME.napcat_root),
    ]
    deduped = []
    for path in candidates:
        if path and path not in deduped:
            deduped.append(path)
    return deduped

def check_onebot_health(processes: list[dict]) -> dict:
    service_names = health_service_names(
        "HEALTH_ONEBOT_SERVICES",
        ["hok-napcat", "napcat", "NapCat", "onebot", "qq"],
    )
    systemd = systemd_service_state(service_names)
    path_candidates = onebot_path_candidates()
    existing_paths = [path for path in path_candidates if os.path.exists(path)]
    normalized_paths = [path.lower() for path in path_candidates]

    def matches_onebot_process(proc: dict) -> bool:
        args = proc["args"].lower()
        command = proc["command"].lower()
        if "napcat" in args or "onebot" in args:
            return True
        if command == "qq" and any(path and path in args for path in normalized_paths):
            return True
        return False

    process_info = summarize_processes(processes, matches_onebot_process)
    status = "ok" if systemd.get("state") == "active" or process_info["count"] > 0 else "down"
    if status == "down" and existing_paths:
        status = "degraded"

    return {
        "status": status,
        "systemd": systemd,
        "processes": process_info,
        "paths": {
            "configured": path_candidates,
            "existing": existing_paths,
        },
    }

def service_overall_status(services: dict) -> str:
    if any(services[name]["status"] == "down" for name in ("web", "redis", "postgres")):
        return "down"
    if any(item["status"] != "ok" for item in services.values()):
        return "degraded"
    return "ok"

def compact_repository_info(repository: dict) -> dict:
    if repository.get("status") != "ok":
        return {"status": repository.get("status", "unknown")}
    return {
        "commit": repository.get("short_head"),
        "branch": repository.get("branch"),
    }

def compact_process_info(processes: dict) -> dict:
    return {
        "count": processes.get("count", 0),
        "commands": processes.get("commands", []),
    }

def compact_service_state(service: dict) -> str:
    systemd = service.get("systemd", {})
    if systemd.get("matched"):
        return f"{systemd.get('matched')}:{systemd.get('state')}"
    return systemd.get("state", "unknown")

def remove_empty_health_fields(value):
    if isinstance(value, dict):
        return {
            key: remove_empty_health_fields(item)
            for key, item in value.items()
            if item is not None and item != []
        }
    return value

def compact_health_payload(services: dict) -> dict:
    overall_status = service_overall_status(services)
    if overall_status == "ok":
        return {"status": "ok"}

    return remove_empty_health_fields({
        "status": overall_status,
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "web": {
            "status": services["web"]["status"],
            "pid": services["web"]["pid"],
            "uptime_seconds": services["web"]["uptime_seconds"],
            **compact_repository_info(services["web"]["repository"]),
        },
        "redis": {
            "status": services["redis"]["status"],
            "service": compact_service_state(services["redis"]),
            "processes": compact_process_info(services["redis"].get("processes", {})),
            "latency_ms": services["redis"].get("latency_ms"),
            "version": services["redis"].get("redis_version"),
            "queues": services["redis"].get("queues"),
            "error": services["redis"].get("error"),
        },
        "postgres": services["postgres"],
        "nginx": {
            "status": services["nginx"]["status"],
            "service": compact_service_state(services["nginx"]),
            "processes": compact_process_info(services["nginx"].get("processes", {})),
        },
        "qqbot": {
            "status": services["qqbot"]["status"],
            "service": compact_service_state(services["qqbot"]),
            "processes": compact_process_info(services["qqbot"].get("processes", {})),
            **compact_repository_info(services["qqbot"]["repository"]),
        },
        "onebot": {
            "status": services["onebot"]["status"],
            "service": compact_service_state(services["onebot"]),
            "processes": compact_process_info(services["onebot"].get("processes", {})),
        },
    })

def collect_health_services() -> dict:
    processes = process_snapshot()
    return {
        "web": {
            "status": "ok",
            "pid": os.getpid(),
            "uptime_seconds": int(time.time() - APP_STARTED_AT),
            "repository": git_repository_info(os.path.dirname(os.path.abspath(__file__))),
        },
        "redis": check_redis_health(processes),
        "postgres": check_postgres_health(),
        "nginx": check_nginx_health(processes),
        "qqbot": check_qqbot_health(processes),
        "onebot": check_onebot_health(processes),
    }

def manual_health_service_summary(services: dict) -> dict:
    return {
        name: {
            "status": item.get("status", "unknown"),
            **({"latency_ms": item.get("latency_ms")} if item.get("latency_ms") is not None else {}),
            **(
                {"commit": item.get("repository", {}).get("short_head")}
                if item.get("repository", {}).get("short_head") else {}
            ),
        }
        for name, item in services.items()
    }

@app.get("/health")
async def health_check():
    services = collect_health_services()
    return Response(
        json.dumps(compact_health_payload(services), ensure_ascii=False, indent=2),
        media_type="application/json",
    )

@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "ErrorPages/illegal.html",
        {"request": request},
        status_code=404
    )

@app.get("/all", response_class=HTMLResponse)
async def show_btlist(request:Request,key: str):
    # raise HTTPException(
    #     status_code=404,
    #     detail={"template": "404_a.html", "context": {"message": ""}}
    # )
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content,jsonpath = key_to_filename(key=key,reqtype="btlist")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/AllBattleList.html",
        {
            "request": request,
            "filename": jsonpath,
            "time": text_content["time"],
            "caller": text_content["caller"],
            "key": key,
        }
    )
@app.get("/person", response_class=HTMLResponse)
async def show_btlperson(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content,jsonpath = key_to_filename(key=key,reqtype="btlperson")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/SingleBattleList.html",
        {
            "request": request,
            "filename": jsonpath,
            "key": key,
        }
    )
@app.get("/period", response_class=HTMLResponse)
async def show_btlperiod(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content,jsonpath = key_to_filename(key=key,reqtype="btlperiod")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/SinglePeriodBattleList.html",
        {
            "request": request,
            "filename": jsonpath,
            "key": key,
            "DateFrom":text_content["DateFrom"],
            "DateTo":text_content["DateTo"],
        }
    )
@app.get("/battle", response_class=HTMLResponse)
async def show_btldetail(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content,jsonpath = key_to_filename(key=key,reqtype="btldetail")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/BattleDetail.html",
        {
            "request": request,
            "filename": jsonpath,
            "key": key,
        }
    )
@app.get("/query", response_class=HTMLResponse)
async def show_btldetail(request:Request,key: str):
    today_date=datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        text_content,jsonpath = key_to_filename(key=key,reqtype="btlquery")
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )
    return templates.TemplateResponse(
        "CommonPages/BattleQuery.html",
        {
            "request": request,
            "filename": jsonpath,
            "query_target":text_content["caller"],
            "key": key,
        }
    )

@app.get("/benefit", response_class=HTMLResponse)
async def show_benefit_visualizer(request: Request, key: str):
    filename = os.path.basename(key)
    if filename != key or filename in ("", ".", ".."):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key非法"}
        )
    if not filename.endswith(".json"):
        filename = filename + ".json"

    return templates.TemplateResponse(
        "CommonPages/BenefitVisualizer/index.html",
        {
            "request": request,
            "filename": os.path.join("file_transfer", "temp_files", filename),
        }
    )

@app.get("/chat-trace", response_class=HTMLResponse)
async def show_chat_trace(request: Request, key: str = ""):
    from chat_trace import chat_trace_response

    return await chat_trace_response(request, key, load_artifact=get_web_artifact, templates=templates,
                                     admin_authorized=request.cookies.get("AdminKey") == SECRET_KEY)


@app.get("/bili-video")
async def show_bili_video(request: Request, key: str):
    if os.path.basename(key) != key or key in ("", ".", ".."):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key非法"}
        )
    try:
        raw = get_web_artifact(key)
        if not raw:
            raise ValueError("empty bili video payload")
        video = json.loads(raw.decode("utf-8"))
        if not isinstance(video, dict):
            raise ValueError("invalid bili video payload")
    except Exception:
        return templates.TemplateResponse(
            "ErrorPages/expired.html",{"request": request,}
        )

    bvid = str(video.get("bvid") or "").strip()
    aid = str(video.get("aid") or video.get("avid") or "").strip()
    if not bvid:
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"视频参数非法"}
        )

    video_url = str(video.get("url") or f"https://www.bilibili.com/video/{bvid}").replace("http://", "https://", 1)
    if not is_mobile_request(request):
        return RedirectResponse(url=video_url, status_code=302)

    mobile_url = str(video.get("mobile_url") or f"https://m.bilibili.com/video/{bvid}").replace("http://", "https://", 1)
    app_url = str(video.get("app_url") or "")
    if aid:
        app_url = f"bilibili://video/{aid}?page=0"
    if not app_url:
        app_url = mobile_url
    yyb_url = "https://a.app.qq.com/o/simple.jsp?" + urlencode({
        "pkgname": "tv.danmaku.bili",
        "ckey": "CK1474482145968",
        "android_schema": app_url,
    }) if app_url.startswith("bilibili://") else mobile_url
    return RedirectResponse(url=yyb_url, status_code=302)

def check_key_valid(key:str, reqtype:str):
    if key is None:
        return False
    return key==SECRET_KEY or web_artifact_exists(key)


@app.get("/battle-data/{game_seq}")
async def battle_data(game_seq: str, roleid: str = Query("0")):
    if not valid_battle_identifier(game_seq) or not str(roleid).isascii() or not str(roleid).isdigit():
        raise HTTPException(status_code=400, detail="invalid battle identifier")
    payload = fetch_battle(game_seq, int(roleid))
    if not payload:
        raise HTTPException(status_code=404, detail="battle detail not found")
    return JSONResponse(content=payload)


def valid_battle_identifier(value):
    number = str(value)
    digits = number[1:] if number.startswith('-') else number
    return bool(digits) and digits.isascii() and digits.isdigit() and len(digits) <= 19 and -(2**63) < int(number) < 2**63


@app.get("/jump-person", response_class=HTMLResponse)
async def jump_btlperson(request:Request,userid: str,roleid: str,key:str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(key=final_key,reqtype="jump_btlperson")):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key失效"}
        )
    try:
        profile_res=wzry_get_official(reqtype="profile",userid=userid,roleid=roleid)
        btlist_res=wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    except Exception as e:
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":f"网络参数错误 {str(e)}"}
        )
    res={"btlist":btlist_res,"profile":profile_res}
    file_name=secrets.token_hex(8)+".json"
    save_path=os.path.join(file_path_root,"temp_files", file_name)
    writerl(save_path,res)
    return templates.TemplateResponse(
        "CommonPages/SingleBattleList.html",
        {
            "request": request,
            "filename": os.path.join("file_transfer","temp_files",file_name),
            "key": final_key,
        }
    )
@app.get("/jump-battle", response_class=HTMLResponse)
async def jump_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,key:str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(key=final_key,reqtype="jump_btldetail")):
        return templates.TemplateResponse(
            "ErrorPages/illegal.html",{"request": request,"message":"key失效"}
        )
    if not valid_battle_identifier(gameSeq) or not targetRoleId.isascii() or not targetRoleId.isdigit():
        raise HTTPException(status_code=400, detail="invalid battle identifier")
    if (check_battle_local_exist(gameSeq,targetRoleId)):
        web_path=f"/battle-data/{gameSeq}?roleid={targetRoleId}"
    else:
        if gameSeq.startswith('-'):
            raise HTTPException(status_code=404, detail="battle detail not found")
        try:
            res=wzry_get_official(reqtype="btldetail",gameseq=gameSeq,gameSvrId=gameSvr,relaySvrId=relaySvr,roleid=int(targetRoleId),pvptype=battleType)
        except Exception as e:
            return templates.TemplateResponse(
                "ErrorPages/expired.html",{"request": request,"message":f"对局已过期或id无效 {str(e)}"}
            )
        file_name=secrets.token_hex(8)+".json"
        save_path=os.path.join(file_path_root,"temp_files", file_name)
        web_path=os.path.join("file_transfer","temp_files",file_name)
        writerl(save_path,res)
    return templates.TemplateResponse(
        "CommonPages/BattleDetail.html",
        {
            "request": request,
            "filename": web_path,
            "key": final_key,
            "gameSeq":gameSeq,
            "gameSvr":gameSvr,
            "relaySvr":relaySvr,
            "targetRoleId":targetRoleId,
            "battleType":battleType,
        }
    )
@app.get("/like-battle", response_class=HTMLResponse)
async def like_btldetail(request:Request,gameSeq: str,key:str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(key=final_key,reqtype="like_btldetail")):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": f"key失效",
                "error_code": "LIKE_FAILED"
            }
        )
    happen_time=int(time.time())
    is_liked = bool(
        r_liked_set.sismember(BATTLE_LIKED_IDS_KEY, gameSeq)
    )
    if is_liked:
        r_liked_set.srem(BATTLE_LIKED_IDS_KEY, gameSeq)
        success_data={
            "success": True,
            "message": "取消收藏成功",
            "data": {
                "battle_id": gameSeq,
                "timestamp": happen_time
            }
        }
    else:
        r_liked_set.sadd(BATTLE_LIKED_IDS_KEY, gameSeq)
        success_data={
            "success": True,
            "message": "收藏成功",
            "data": {
                "battle_id": gameSeq,
                "timestamp": happen_time
            }
        }
    return JSONResponse(success_data)
@app.get("/share-battle", response_class=HTMLResponse)
async def share_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,key:str = Query(None), AdminKey: str = Cookie(None),Special: bool = False):
    final_key = key or AdminKey
    if (not check_key_valid(key=final_key,reqtype="share_btldetail")):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": f"key失效",
                "error_code": "LIKE_FAILED"
            }
        )
    params={
        "gameSvrId":gameSvr,
        "gameseq":gameSeq,
        "roleid":targetRoleId,
        "relaySvrId":relaySvr,
        "pvptype":battleType
    }
    try:
        json_params = json.dumps(params)
        result = r_share_queue.lpush(BATTLE_SHARE_QUEUE_KEY, json_params)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "数据库操作失败",
                "error_code": "DB_OPERATION_ERROR"
            }
        )
    
    happen_time=int(time.time())
    success_data={
        "success": True,
        "message": "分享成功",
        "data": {
            "battle_id": gameSeq,
            "timestamp": happen_time
        }
    }
    return JSONResponse(success_data)
@app.get("/analyze-battle", response_class=HTMLResponse)
async def analyze_btldetail(request:Request,gameSvr: str,gameSeq: str,targetRoleId: str, relaySvr: str,battleType:str,Special: bool,key: str = Query(None), AdminKey: str = Cookie(None)):
    final_key = key or AdminKey
    if (not check_key_valid(key=final_key,reqtype="analyze_btldetail")):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": f"key失效",
                "error_code": "LIKE_FAILED"
            }
        )
    game_params={
        "gameSvrId":gameSvr,
        "gameseq":gameSeq,
        "roleid":targetRoleId,
        "relaySvrId":relaySvr,
        "pvptype":battleType,
        "Special":Special
    }
    params={
        "game_params":game_params,
        "Special":Special
    }
    try:
        json_params = json.dumps(params)
        result = r_analyze_queue.lpush(BATTLE_ANALYZE_QUEUE_KEY, json_params)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "数据库操作失败",
                "error_code": "DB_OPERATION_ERROR"
            }
        )
    
    happen_time=int(time.time())
    success_data={
        "success": True,
        "message": "分析底蕴中",
        "data": {
            "battle_id": gameSeq,
            "timestamp": happen_time
        }
    }
    return JSONResponse(success_data)


@app.get("/admin", response_class=JSONResponse)
async def admin_verify(request: Request):
    raise HTTPException(status_code=403)

@app.get("/admin/verify", response_class=JSONResponse)
async def admin_verify(request: Request, pattern: str):
    def parse_pattern(raw: str) -> list[int]:
        try:
            return [int(item) for item in raw.split(',') if item.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pattern 参数不合法") from exc

    if parse_pattern(pattern) != VALID_PATTERN:
        return JSONResponse({"state": "failed","message": "认证失败","key":""})

    else:
        return {"state": "success","message":"认证成功","key": SECRET_KEY}
        
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    from chat_trace import _render
    return _render(templates, "AdminPages/AdminLogin.html", {"request": request})

@app.post("/admin/login")
async def admin_login(request: Request, password: str = Body(..., embed=True)):
    if password == SECRET_KEY:
        response = JSONResponse({"status": "success", "message": "登录成功"})
        # 设置 cookie，有效期 7000 天
        response.set_cookie(key="AdminKey", value=password, max_age=604800000, httponly=True)
        return response
    else:
        return JSONResponse({"status": "error", "message": "密码错误"}, status_code=401)

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    from chat_trace import _render
    return _render(templates,
        "AdminPages/DashBoard.html",
        {
            "request": request,
            "AdminKey": AdminKey
        }
    )

@app.get("/admin/funcs/request-analytics", response_class=HTMLResponse)
async def admin_request_analytics_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    return templates.TemplateResponse(
        "AdminPages/RequestAnalytics.html",
        {
            "request": request,
            "AdminKey": AdminKey,
        }
    )

@app.get("/admin/funcs/health-check", response_class=HTMLResponse)
async def admin_health_check_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    return templates.TemplateResponse(
        "AdminPages/HealthCheck.html",
        {"request": request, "AdminKey": AdminKey},
    )

@app.post("/admin/funcs/health-check/run")
async def admin_health_check_run(AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return JSONResponse({"status": "error", "message": "认证失败"}, status_code=401)
    if manual_health_check_lock.locked():
        return JSONResponse(
            {"status": "error", "message": "已有一项深度诊断正在运行"},
            status_code=409,
        )
    async with manual_health_check_lock:
        services = await asyncio.to_thread(collect_health_services)
        platform_status = service_overall_status(services)
        chat_report = await asyncio.to_thread(run_chat_runtime_diagnostic, RUNTIME.nbot_root)
    status = "failed" if chat_report.get("status") != "ok" or platform_status == "down" else platform_status
    return JSONResponse({
        "status": status,
        "platform_status": platform_status,
        "services": manual_health_service_summary(services),
        "chat": chat_report,
    })

@app.get("/admin/funcs/request-analytics/data")
async def admin_request_analytics_data(
    limit: int = Query(200, ge=1, le=500),
    AdminKey: str = Cookie(None),
):
    if AdminKey != SECRET_KEY:
        return JSONResponse({"status": "error", "message": "认证失败"}, status_code=401)
    try:
        return JSONResponse(analytics_payload(r_com, SECRET_KEY, limit=limit))
    except Exception as exc:
        logging.exception("REQUEST_ANALYTICS_READ_FAILED error=%r", exc)
        return JSONResponse(
            {"status": "error", "message": "访问统计读取失败"},
            status_code=500,
        )

@app.get("/admin/funcs/chat-traces", response_class=HTMLResponse)
async def admin_chat_traces_page(
    request: Request, page: int = Query(1, ge=1), q: str = Query("", max_length=200),
    status: str = Query("", pattern="^(?:ok|error|cancelled)?$"),
    group_id: str = Query("", pattern="^[0-9]{0,20}$"), AdminKey: str = Cookie(None),
):
    from admin_chat_traces import list_chat_traces
    from chat_trace import TRACE_HEADERS, _render
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login", headers=TRACE_HEADERS)
    try:
        listing = await asyncio.to_thread(list_chat_traces, r_com,
            max_records=confs.get("DynamicVariables", {}).get("ChatTraceMaxRecords", 1000),
            page=page, query=q.strip(), status=status, group_id=group_id)
    except Exception:
        return _render(templates, "ErrorPages/illegal.html",
            {"request": request, "message": "运行记录暂时无法读取，请稍后重试"},
            status_code=503, headers=TRACE_HEADERS)
    filters = {"q": q, "status": status, "group_id": group_id}
    return _render(templates, "AdminPages/ChatTraces.html", {
        "request": request, **listing, **filters,
        "previous_url": "/admin/funcs/chat-traces?" + urlencode({**filters, "page": listing["page"] - 1}),
        "next_url": "/admin/funcs/chat-traces?" + urlencode({**filters, "page": listing["page"] + 1}),
    }, headers=TRACE_HEADERS)


@app.get("/admin/funcs/chat-traces/{key}", response_class=HTMLResponse)
async def admin_chat_trace_detail(request: Request, key: str, AdminKey: str = Cookie(None)):
    from chat_trace import TRACE_HEADERS, chat_trace_response
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login", headers=TRACE_HEADERS)
    return await chat_trace_response(request, key, load_artifact=get_web_artifact,
                                     templates=templates, admin_authorized=True)


@app.get("/admin/funcs/direct-navigate", response_class=HTMLResponse)
async def jump_admin_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    reload_variables()
    return templates.TemplateResponse(
        "AdminPages/DirectNavigate.html",
        {
            "request": request,
            "AdminKey": AdminKey,
            "useridlist": {**userlist, **extra_useridlist},
            "roleidlist": {**roleidlist, **extra_roleidlist}
        }
    )

@app.get("/admin/funcs/user-edit", response_class=HTMLResponse)
async def admin_user_edit_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    return templates.TemplateResponse(
        "AdminPages/UserEdit.html",
        {
            "request": request,
            "AdminKey": AdminKey
        }
    )

@app.get("/admin/funcs/chat-viewer", response_class=HTMLResponse)
async def admin_chat_viewer_page(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return RedirectResponse(url="/admin/login")
    reload_variables()
    return templates.TemplateResponse(
        "AdminPages/ChatViewer.html",
        {
            "request": request,
            "AdminKey": AdminKey,
            "qid_map": qid # realname -> qid
        }
    )

@app.get("/admin/funcs/chat-viewer/fetch")
async def fetch_chat_records(target_qid: str, mode: str = "active", AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return {"status": "error", "message": "认证失败"}
    
    prefix = MEMORY_PREFIX
    try:
        if mode == "forced":
            # 获取长效记忆 (forced_mem)
            if target_qid == "global":
                # 全局模式下扫描所有人的记忆
                all_keys = r_chat.keys(f"{prefix}forced_mem:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    raw_records = r_chat.lrange(k, 0, -1) 
                    for idx, r in enumerate(raw_records):
                        item = json.loads(r.decode('utf-8'))
                        records.append({
                            "time": item.get("time", ""),
                            "nick": qid_part,
                            "Q": "强制记忆录入",
                            "A": item.get("mem", ""),
                            "qid": qid_part,
                            "idx": idx
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}forced_mem:{target_qid}"
                raw_records = r_chat.lrange(key, 0, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    item = json.loads(r.decode('utf-8'))
                    records.append({
                        "time": item.get("time", ""),
                        "Q": "主动强制内容",
                        "A": item.get("mem", ""),
                        "qid": target_qid,
                        "idx": idx
                    })
                records.reverse()
        elif mode == "passive":
            # 获取被动聊天记录 (passive_chat)
            if target_qid == "global":
                all_keys = r_chat.keys(f"{prefix}passive_chat:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    last_record = r_chat.lrange(k, -1, -1)
                    if last_record:
                        item = json.loads(last_record[0].decode('utf-8'))
                        records.append({
                            "time": item.get("time", ""),
                            "nick": qid_part,
                            "Q": item.get("text", ""),
                            "A": "(被动记录片段)",
                            "qid": qid_part
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}passive_chat:{target_qid}"
                raw_records = r_chat.lrange(key, -100, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    item = json.loads(r.decode('utf-8'))
                    records.append({
                        "time": item.get("time", ""),
                        "Q": item.get("text", ""),
                        "A": "(记录于群聊)",
                        "qid": target_qid,
                        "idx": idx
                    })
                records.reverse()
        elif mode == "summary":
            # 获取历史总结记忆 (summary_mem)
            if target_qid == "global":
                all_keys = r_chat.keys(f"{prefix}summary_mem:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    raw_records = r_chat.lrange(k, 0, -1)
                    for idx, r in enumerate(raw_records):
                        item = json.loads(r.decode('utf-8'))
                        records.append({
                            "time": item.get("time", ""),
                            "nick": qid_part,
                            "Q": f"用户总结 ({qid_part})",
                            "A": item.get("summary", ""),
                            "qid": qid_part,
                            "idx": idx
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}summary_mem:{target_qid}"
                raw_records = r_chat.lrange(key, 0, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    item = json.loads(r.decode('utf-8'))
                    records.append({
                        "time": item.get("time", ""),
                        "Q": "今日状态提炼",
                        "A": item.get("summary", ""),
                        "qid": target_qid,
                        "idx": idx
                    })
                records.reverse()
        else: # active_chat
            if target_qid == "global":
                all_keys = r_chat.keys(f"{prefix}active_chat:*")
                records = []
                for k in all_keys:
                    key_str = k.decode('utf-8')
                    qid_part = key_str.split(":")[-1]
                    raw_records = r_chat.lrange(k, -5, -1)
                    for idx, r in enumerate(raw_records):
                        item = json.loads(r.decode('utf-8'))
                        records.append({
                            **item,
                            "nick": qid_part,
                            "qid": qid_part,
                            "idx": idx
                        })
                records.sort(key=lambda x: x['time'], reverse=True)
            else:
                key = f"{prefix}active_chat:{target_qid}"
                raw_records = r_chat.lrange(key, -50, -1)
                records = []
                for idx, r in enumerate(raw_records):
                    records.append({**json.loads(r.decode('utf-8')), "idx": idx, "qid": target_qid})
                records.reverse()
        
        return {"status": "success", "records": records}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/admin/funcs/chat-viewer/memory-op")
async def memory_operation(op: str = Body(...), qid: str = Body(...), mode: str = Body("forced"), content: str = Body(None), idx: int = Body(None), AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return {"status": "error", "message": "认证失败"}
    
    mapping = {"forced": "forced_mem", "active": "active_chat", "passive": "passive_chat", "summary": "summary_mem"}
    if mode not in mapping: return {"status": "error", "message": "未知模式"}
    
    key = f"{MEMORY_PREFIX}{mapping[mode]}:{qid}"
    try:
        if op == "add":
            item = {"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            if mode == "active": item.update({"Q": content, "A": "(手动录入)"})
            elif mode == "passive": item["text"] = content
            elif mode == "forced": item["mem"] = content
            elif mode == "summary": item["summary"] = content
            r_chat.rpush(key, json.dumps(item, ensure_ascii=False))
            r_chat.ltrim(key, -100, -1)
        
        elif op == "delete":
            target_val = r_chat.lindex(key, idx)
            if target_val: r_chat.lrem(key, 1, target_val)
        
        elif op == "update":
            old_val_raw = r_chat.lindex(key, idx)
            if old_val_raw:
                item = json.loads(old_val_raw.decode('utf-8'))
                if mode == "active": item["Q"] = content
                elif mode == "passive": item["text"] = content
                elif mode == "forced": item["mem"] = content
                elif mode == "summary": item["summary"] = content
                
                # 更新时间并打上修改标记
                item["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (已修改)"
                r_chat.lset(key, idx, json.dumps(item, ensure_ascii=False))

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/admin/funcs/user-edit/fetch-user-info")
async def fetch_user_info(request: Request, AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return JSONResponse({"status": "error", "message": "AdminKey失效"}, status_code=401)
    reload_variables()
    return {
        "userlist": userlist,
        "roleidlist": roleidlist,
        "qid": qid,
        "namenick": namenick,
        "nameref": nameref,
        "extra_useridlist": extra_useridlist,
        "extra_roleidlist": extra_roleidlist,
        "extra_namenick": extra_namenick,
    }

@app.post("/admin/funcs/user-edit/submit-user-info")
async def submit_user_info(request: Request, changes: list = Body(...), AdminKey: str = Cookie(None)):
    if AdminKey != SECRET_KEY:
        return JSONResponse({"status": "error", "message": "AdminKey失效"}, status_code=401)
    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            full_config = yaml.safe_load(f) or {}
        full_data = full_config.setdefault("StaticVariables", {})
        
        for change in changes:
            op = change.get('op')
            ctype = change.get('type')
            ckey = change.get('key')
            cdata = change.get('data')

            if ctype == 'main':
                target_fields = ['userlist', 'roleidlist', 'qid', 'namenick', 'nameref']
            else:
                target_fields = ['extra_useridlist', 'extra_roleidlist', 'extra_namenick']

            if op in ['add', 'edit']:
                for f_name in target_fields:
                    if f_name not in full_data: full_data[f_name] = {}
                    val = cdata.get(f_name)
                    # 处理数值类型
                    if f_name in ['userlist', 'roleidlist', 'qid', 'extra_useridlist', 'extra_roleidlist'] and val:
                        try: val = int(val)
                        except: pass
                    full_data[f_name][ckey] = val
            elif op == 'delete':
                for f_name in target_fields:
                    if f_name in full_data and ckey in full_data[f_name]:
                        del full_data[f_name][ckey]

        temporary_path = config_file_path + ".tmp"
        with open(temporary_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(full_config, f, allow_unicode=True, sort_keys=False)
        os.replace(temporary_path, config_file_path)
        
        # 同步更新到内存中的全局变量
        reload_variables()
                
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Account login operations remain behind the existing administrator cookie.
from account_sessions import bridge as account_login_bridge, HEADERS as ACCOUNT_HEADERS


def _account_csrf():
    import hashlib
    import hmac
    return hmac.new(str(SECRET_KEY).encode(), b"account-sessions-v1", hashlib.sha256).hexdigest()


@app.get("/admin/funcs/account-sessions", response_class=HTMLResponse)
async def account_sessions_page(request: Request, AdminKey: str = Cookie(None)):
    if not SECRET_KEY or AdminKey != SECRET_KEY:
        return RedirectResponse("/admin/login", status_code=303, headers=ACCOUNT_HEADERS)
    from chat_trace import _render
    return _render(templates, "AdminPages/AccountSessions.html",
                   {"request": request, "csrf": _account_csrf()}, headers=ACCOUNT_HEADERS)


@app.get("/admin/funcs/account-sessions/state")
async def account_sessions_state(AdminKey: str = Cookie(None)):
    if not SECRET_KEY or AdminKey != SECRET_KEY:
        return JSONResponse({"ok": False, "error": "认证失败"}, status_code=401, headers=ACCOUNT_HEADERS)
    result = await account_login_bridge.call({"action": "list"})
    return JSONResponse(result, headers=ACCOUNT_HEADERS)


@app.post("/admin/funcs/account-sessions/action")
async def account_sessions_action(request: Request, AdminKey: str = Cookie(None)):
    if not SECRET_KEY or AdminKey != SECRET_KEY:
        return JSONResponse({"ok": False, "error": "认证失败"}, status_code=401, headers=ACCOUNT_HEADERS)
    supplied = request.headers.get("x-account-csrf", "")
    if request.headers.get("sec-fetch-site") == "cross-site" or not secrets.compare_digest(supplied, _account_csrf()):
        return JSONResponse({"ok": False, "error": "请求校验失败，请刷新页面"}, status_code=403, headers=ACCOUNT_HEADERS)
    try:
        raw = await request.body()
        if len(raw) > 1024:
            raise ValueError()
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) - {"provider", "action", "challenge_id", "role_choice"}:
            raise ValueError()
        if payload.get("provider") not in {"camp", "official", "napcat"} or payload.get("action") not in {"check", "start", "poll", "select_role"}:
            raise ValueError()
        if payload["action"] == "select_role":
            choice = payload.get("role_choice")
            if payload["provider"] != "camp" or type(choice) is not int or not 0 <= choice < 100:
                raise ValueError()
        elif "role_choice" in payload:
            raise ValueError()
        if payload["action"] in {"poll", "select_role"}:
            import re
            if not re.fullmatch(r"[a-f0-9]{32}", str(payload.get("challenge_id", ""))):
                raise ValueError()
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "无效请求"}, status_code=400, headers=ACCOUNT_HEADERS)
    result = await account_login_bridge.call(payload)
    return JSONResponse(result, status_code=429 if result.get("retry_after") else 200, headers=ACCOUNT_HEADERS)


@app.on_event("shutdown")
async def close_account_login_worker():
    await account_login_bridge.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.environ.get("HOK_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("HOK_WEB_PORT", "8000")),
    )

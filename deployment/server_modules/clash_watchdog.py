#!/usr/bin/env python3
"""Maintain a local Clash fallback group without replacing host configuration.

Private settings and subscription URLs belong to the host module, never Git.
The engine handles node checks; this process checks the actual proxy and refreshes
subscriptions with validation, a cooldown, and rollback on failed activation.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from urllib.parse import quote, urlsplit

import requests
import yaml


HEALTH_URL = "https://www.gstatic.com/generate_204"
MAX_SUBSCRIPTION_BYTES = 5 * 1024 * 1024


def read_subscription_url(path: Path) -> str:
    for line in path.read_text().splitlines():
        parts = shlex.split(line, comments=True)
        if parts and parts[0] == "export":
            parts = parts[1:]
        if len(parts) == 1 and parts[0].startswith("CLASH_URL="):
            value = parts[0].partition("=")[2]
            if urlsplit(value).scheme == "https" and urlsplit(value).hostname:
                return value
    raise ValueError("missing HTTPS subscription")


def fetch_subscription(session, url: str, proxy: str | None = None) -> dict:
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    with session.get(url, proxies=proxies, headers={"User-Agent": "Clash/1.13.0"},
                     timeout=(5, 20), stream=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_SUBSCRIPTION_BYTES:
                raise ValueError("subscription too large")
            chunks.append(chunk)
        result = yaml.safe_load(b"".join(chunks))
    if not isinstance(result, dict) or not result.get("proxies"):
        raise ValueError("subscription has no nodes")
    return result


def merge_subscription(current: dict, remote: dict, settings: dict) -> dict:
    """Replace node definitions and known memberships, preserving host policy."""
    nodes = remote.get("proxies")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("subscription has no nodes")
    names = [node.get("name") for node in nodes if isinstance(node, dict)]
    if len(names) != len(nodes) or any(not isinstance(n, str) or not n for n in names):
        raise ValueError("invalid node names")
    if len(set(names)) != len(names):
        raise ValueError("duplicate node names")
    result = copy.deepcopy(current)
    result["proxies"] = copy.deepcopy(nodes)
    groups = result.setdefault("proxy-groups", [])
    by_name = {g["name"]: g for g in groups}
    selector, fallback = settings["selector"], settings["fallback"]
    if selector not in by_name or by_name[selector].get("type") != "select":
        raise ValueError("local selector missing")
    remote_groups = {g["name"]: g for g in remote.get("proxy-groups", [])}
    for name, group in by_name.items():
        if name != fallback and name in remote_groups:
            group["proxies"] = list(remote_groups[name].get("proxies", []))
        if group.get("type") in {"url-test", "fallback"}:
            group.update(url=HEALTH_URL, interval=300, lazy=False)
    preferred = []
    for region in settings.get("preferred_regions", ["新加坡", "日本", "西雅图"]):
        preferred.extend(n for n in names if region in n and n not in preferred)
    # Keep other subscription nodes as a final recovery path when regions change.
    preferred.extend(n for n in names if n not in preferred)
    auto = {"name": fallback, "type": "fallback", "proxies": preferred,
            "url": HEALTH_URL, "interval": 300, "lazy": False}
    if fallback in by_name:
        by_name[fallback].update(auto)
    else:
        groups.append(auto)
    members = by_name[selector].get("proxies", [])
    by_name[selector]["proxies"] = [fallback] + [n for n in members if n != fallback]
    result.setdefault("profile", {})["store-selected"] = True
    valid = set(names) | {g["name"] for g in groups} | {"DIRECT", "REJECT"}
    for group in groups:
        if any(n not in valid for n in group.get("proxies", [])):
            raise ValueError("subscription would break a local group")
    return result


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd, name = tempfile.mkstemp(prefix=".watchdog-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            os.fchmod(file.fileno(), mode)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Controller:
    def __init__(self, config):
        port = str(config["external-controller"]).rsplit(":", 1)[-1]
        if not port.isdigit():
            raise ValueError("invalid controller port")
        self.base = "http://127.0.0.1:" + port
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers["Authorization"] = "Bearer " + str(config.get("secret", ""))

    def request(self, method, path, **kwargs):
        response = self.session.request(method, self.base + path, timeout=(3, 15), **kwargs)
        response.raise_for_status()
        return response

    def reload(self, path):
        self.request("PUT", "/configs?force=true", json={"path": str(path)})

    def select(self, selector, node):
        self.request("PUT", "/proxies/" + quote(selector, safe=""), json={"name": node})


def install_candidate(path: Path, candidate: dict, settings: dict, controller) -> bool:
    previous = path.read_bytes()
    if yaml.safe_load(previous) == candidate:
        return False
    fd, name = tempfile.mkstemp(prefix=".candidate-", suffix=".yaml", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            yaml.safe_dump(candidate, file, allow_unicode=True, sort_keys=False)
        subprocess.run([settings["binary"], "-t", "-d", str(path.parent), "-f", name],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        backup = backup_dir / ("config-watchdog-" + str(time.time_ns()) + ".yaml")
        atomic_write(backup, previous)
        atomic_write(path, Path(name).read_bytes(), path.stat().st_mode & 0o777)
        try:
            controller.reload(path)
            controller.select(settings["selector"], settings["fallback"])
        except Exception:
            atomic_write(path, previous)
            controller.reload(path)
            raise
        # Retain a bounded set of this watchdog's own recovery copies only.
        for old in sorted(backup_dir.glob("config-watchdog-*.yaml"))[:-10]:
            old.unlink()
        return True
    finally:
        Path(name).unlink(missing_ok=True)


def connectivity(session, proxy: str, probes: list[dict]) -> bool:
    # Multiple independent sites avoid treating one site's outage as route loss.
    for probe in probes:
        try:
            with session.get(probe["url"], proxies={"http": proxy, "https": proxy},
                             timeout=(5, 10), stream=True, allow_redirects=False) as response:
                if response.status_code in probe.get("statuses", [200, 204]):
                    return True
        except requests.RequestException:
            pass
    return False


def refresh_due(state: dict, now: float, healthy: bool) -> bool:
    cooldown = now - state.get("last_attempt", 0) >= 3600
    return cooldown and (not healthy or now - state.get("last_refresh", 0) >= 86400)


def check(settings: dict, state: dict, save_state, *, force_refresh=False) -> dict:
    path = Path(settings["config"])
    config = yaml.safe_load(path.read_text())
    controller = Controller(config)
    session = requests.Session()
    session.trust_env = False
    proxy = settings.get("proxy", "http://127.0.0.1:7890")
    probes = settings.get("probes", [{"url": HEALTH_URL, "statuses": [204]},
                                     {"url": "https://www.cloudflare.com/cdn-cgi/trace", "statuses": [200]}])
    healthy = connectivity(session, proxy, probes)
    if not healthy:
        # Reassert the fallback group if an old manual selection is unavailable.
        controller.select(settings["selector"], settings["fallback"])
        healthy = connectivity(session, proxy, probes)
    now = time.time()
    result = {"healthy": healthy, "refreshed": False, "changed": False}
    if force_refresh or refresh_due(state, now, healthy):
        state["last_attempt"] = now
        save_state(state)  # A killed/failed fetch still obeys the cooldown.
        try:
            url = read_subscription_url(Path(settings["subscription_env"]))
            try:
                remote = fetch_subscription(session, url)
            except (requests.RequestException, ValueError, yaml.YAMLError):
                remote = fetch_subscription(session, url, proxy)
            candidate = merge_subscription(config, remote, settings)
            result["changed"] = install_candidate(path, candidate, settings, controller)
            state["last_refresh"] = time.time()
            result["refreshed"] = True
        except Exception as exc:
            # requests errors and engine output can contain subscription credentials.
            result["refresh_error_type"] = type(exc).__name__
        result["healthy"] = connectivity(session, proxy, probes)
    state["last_check"] = time.time()
    state["healthy"] = result["healthy"]
    save_state(state)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true", help="refresh now, bypassing the scheduled cooldown")
    args = parser.parse_args()
    settings = json.loads(args.settings.read_text())
    state_path = Path(settings["state"])
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        save = lambda value: atomic_write(state_path, json.dumps(value).encode())
        try:
            result = check(settings, state, save, force_refresh=args.refresh)
        except Exception as exc:
            result = {"healthy": False, "error_type": type(exc).__name__}
        print(json.dumps(result))
        return 0 if result["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

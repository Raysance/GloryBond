#!/usr/bin/env python3
"""Confirm both application services are ready without calling a model."""

import argparse
import json
import subprocess
import time
from urllib.request import ProxyHandler, build_opener


def unit_property(unit, name):
    return subprocess.check_output(["systemctl", "show", unit, "-p", name, "--value"], text=True).strip()


def verify(timeout=180):
    invocation = unit_property("hok-nbot.service", "InvocationID")
    if not invocation:
        raise RuntimeError("Bot has no running invocation")
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        if unit_property("hok-nbot.service", "InvocationID") != invocation:
            raise RuntimeError("Bot restarted before startup completed")
        logs = subprocess.check_output(["journalctl", "_SYSTEMD_INVOCATION_ID=" + invocation,
                                        "--no-pager", "-o", "cat"], text=True)
        ready = "Application startup complete." in logs
        if ready and all(unit_property(unit, "ActiveState") == "active"
                         for unit in ("hok-nbot.service", "hok-web.service")):
            try:
                with opener.open("http://127.0.0.1:8000/health", timeout=3) as response:
                    if json.load(response).get("status") == "ok":
                        print("Bot startup and Web health confirmed")
                        return
            except (OSError, ValueError):
                pass
        time.sleep(2)
    raise RuntimeError("Bot/Web readiness was not confirmed within the deployment budget")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=180)
    verify(parser.parse_args().timeout)

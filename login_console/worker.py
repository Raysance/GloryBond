"""One private JSON-line RPC process, launched on demand by the Web admin bridge."""
import argparse
import contextlib
import json
import sys

from .manager import Manager, Limited
from .providers import NotConfigured


def main():
    parser = argparse.ArgumentParser()
    for name in ("root", "env-file", "config-file", "data-dir"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    manager = Manager(args.root, args.env_file, args.config_file, args.data_dir)
    try:
        for line in sys.stdin:
            try:
                if len(line) > 8192:
                    raise ValueError("Invalid request")
                request = json.loads(line)
                with contextlib.redirect_stdout(sys.stderr):
                    result = manager.dispatch(request)
                reply = {"ok": True, "result": result}
            except Limited as exc:
                reply = {"ok": False, "error": "请求冷却中，请稍后重试", "retry_after": exc.seconds}
            except NotConfigured:
                reply = {"ok": False, "error": "缺少登录配置，请检查服务配置"}
            except Exception:
                reply = {"ok": False, "error": "请求未完成或结果未确认，请检查登录状态后再操作"}
            print(json.dumps(reply, ensure_ascii=False), flush=True)
    finally:
        manager.close()


if __name__ == "__main__":
    main()

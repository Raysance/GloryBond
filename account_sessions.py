"""Async bridge to the fixed private NBot login worker; no NoneBot imports."""
import asyncio
import json
import os
from pathlib import Path

from runtime_config import RUNTIME, load_shared_config

HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow",
           "X-Content-Type-Options": "nosniff"}


class LoginBridge:
    def __init__(self, runtime=RUNTIME):
        self.runtime = runtime
        self.lock = asyncio.Lock()
        self.process = None

    async def close(self):
        process, self.process = self.process, None
        if process and process.returncode is None:
            # EOF lets the worker close clients and release challenge leases.
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    async def call(self, payload):
        if self.lock.locked():
            return {"ok": False, "error": "另一项登录操作正在处理，请稍后重试", "retry_after": 5}
        async with self.lock:
            try:
                if not self.process or self.process.returncode is not None:
                    runtime = self.runtime
                    executable = Path(load_shared_config(runtime).get("AccountSessions", {}).get("worker_python", ".venv/bin/python"))
                    if not executable.is_absolute():
                        executable = runtime.nbot_root / executable
                    self.process = await asyncio.create_subprocess_exec(
                        str(executable), "-m", "login_console.worker", "--root", str(runtime.nbot_root),
                        "--env-file", str(runtime.env_file), "--config-file", str(runtime.config_file),
                        "--data-dir", str(runtime.data_dir), cwd=str(runtime.nbot_root),
                        # Do not inherit ambient credentials or HTTP proxy routing.
                        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONUNBUFFERED": "1",
                             "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8"},
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL, limit=2*1024*1024)
                self.process.stdin.write((json.dumps(payload) + "\n").encode())
                await self.process.stdin.drain()
                reply = await asyncio.wait_for(self.process.stdout.readline(), 100)
                result = json.loads(reply)
                if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                    raise ValueError("Invalid worker response")
                return result
            except asyncio.CancelledError:
                await self.close()
                raise
            except Exception:
                await self.close()
                return {"ok": False, "error": "登录服务暂时不可用，请稍后重试；二维码可能需要重新生成"}


bridge = LoginBridge()

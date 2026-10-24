"""Private login lifecycle, shared leases, pacing and sanitized status cache."""
import base64
import json
from pathlib import Path
import secrets
import time
import uuid

import redis

from . import providers, store
from .rate import RESERVE, COOLDOWN, AUTH_PREFIX as PREFIX, PLAYER_RATE_PREFIX

NAMES = {"camp": "王者营地", "official": "王者官方客户端", "napcat": "NapCat QQ"}
RELEASE = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0"


class Limited(RuntimeError):
    def __init__(self, seconds=5):
        self.seconds = max(1, int(seconds))


class Manager:
    def __init__(self, root, env_file, config_file, data_dir):
        self.root, self.env_file, self.config_file = Path(root), Path(env_file), Path(config_file)
        self.directory = store.private_directory(Path(data_dir) / "account_sessions")
        self.active = {}
        config = self.config()
        rc = config["Redis"]
        if int(rc["REDIS_DB"]) != 0:
            raise ValueError("Account sessions require DB0")
        self.redis = redis.Redis(host=rc["REDIS_HOST"], port=rc["REDIS_PORT"], db=0,
                                 socket_connect_timeout=3, socket_timeout=3)

    def config(self):
        return store.read_config(self.config_file)

    def reserve(self, name, operation, seconds):
        if not self.redis.set(PREFIX + name + ":" + operation, "1", nx=True, ex=seconds):
            raise Limited(self.redis.ttl(PREFIX + name + ":" + operation))

    def official_gate(self):
        rates = self.config()["PlayerClient"]["rate_limit"]
        base = PLAYER_RATE_PREFIX
        ok, wait, reason = self.redis.eval(RESERVE, 3, base + ":cooldown", base + ":login:next", base + ":login:window",
             max(60000, int(float(rates["login_interval_seconds"])*1000)), int(rates["login_per_hour"]),
             int(rates["login_per_hour"]), uuid.uuid4().hex)
        if not ok:
            raise Limited((wait + 999)//1000)

    def cooldown(self, name):
        # Never retry a failed auth exchange automatically, across processes too.
        if name == "official":
            seconds = self.config()["PlayerClient"]["rate_limit"]["login_failure_cooldown_seconds"]
            self.redis.eval(COOLDOWN, 1, PLAYER_RATE_PREFIX + ":cooldown", int(seconds * 1000))
        else:
            self.redis.set(PREFIX + name + ":start", "1", ex=60)

    def provider(self, name, env, directory):
        kind = {"camp": providers.Camp, "official": providers.Official, "napcat": providers.NapCat}[name]
        args = (self.config(), env, directory)
        return kind(*args, self.official_gate) if name == "official" else kind(*args)

    def cached(self, name):
        value = self.redis.get(PREFIX + name + ":status")
        if not value:
            return {"authenticated": None, "message": "尚未检查，请手动检查", "checked_at": None}
        result = json.loads(value)
        if time.time() - result["checked_at"] > 300:
            result["authenticated"] = None
            result["message"] = "上次检查已超过 5 分钟，请重新检查"
        return result

    def record(self, name, result):
        result = {"authenticated": result.get("authenticated"), "message": result["message"], "checked_at": time.time()}
        self.redis.set(PREFIX + name + ":status", json.dumps(result), ex=86400)
        return result

    def lease(self, name, token, ttl):
        if not self.redis.set(PREFIX + name + ":lease", token, nx=True, ex=ttl):
            raise Limited(self.redis.ttl(PREFIX + name + ":lease"))

    def release(self, name, token):
        self.redis.eval(RELEASE, 1, PREFIX + name + ":lease", token)

    def discard(self, name):
        active = self.active.pop(name, None)
        if active:
            try:
                active["provider"].close()
            finally:
                store.remove_directory(active["directory"])
                self.release(name, active["id"])

    def cleanup(self):
        for name, challenge in list(self.active.items()):
            if time.time() >= challenge["expires_at"]:
                self.discard(name)

    def check(self, name):
        if name in self.active:
            raise Limited(5)
        self.reserve(name, "check", 30)
        token = secrets.token_hex(16)
        self.lease(name, token, 120)
        directory = store.private_directory(self.directory / token)
        client = None
        try:
            client = self.provider(name, store.secrets(self.env_file), directory)
            result = client.check()
        except providers.NotConfigured:
            result = providers.status(None, "缺少登录配置，请检查服务配置")
        except providers.IdentityMismatch:
            result = providers.status(None, "账号与配置不一致，请使用配置中的账号")
        except Limited:
            raise
        except Exception:
            if name == "official":
                self.cooldown(name)
            result = providers.status()
        finally:
            if client:
                client.close()
            store.remove_directory(directory)
            self.release(name, token)
        return self.record(name, result)

    def start(self, name):
        if name in self.active:
            return self.public(self.active[name])
        if self.cached(name)["authenticated"] is True:
            return {"state": "authenticated", "message": "最近检查为有效，无需重新登录"}
        self.reserve(name, "start", 30)
        token = secrets.token_hex(16)
        self.lease(name, token, 300)
        directory = store.private_directory(self.directory / token)
        client = None
        try:
            env = store.secrets(self.env_file)
            client = self.provider(name, env, directory)
            png = client.start(directory)
            if not isinstance(png, bytes) or not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 1048576:
                raise ValueError("Invalid QR image")
            key = "HOK_CAMP_SESSION_JSON" if name == "camp" else "HOK_PLAYER_CLIENT_SESSION_JSON"
            expected = {key: env.get(key)}
            if name == "camp":
                expected.update({k: env.get(k) for k in ("HOK_WZRY_TOKEN", "HOK_WZRY_ENCODERES")})
            challenge = {"id": token, "provider": client, "directory": directory, "expected": expected,
                         "expires_at": time.time()+240, "qr": "data:image/png;base64,"+base64.b64encode(png).decode()}
            self.active[name] = challenge
            return self.public(challenge)
        except Exception:
            if client:
                client.close()
            store.remove_directory(directory)
            self.release(name, token)
            self.cooldown(name)
            raise

    @staticmethod
    def public(challenge):
        return {"state": "waiting_scan", "challenge_id": challenge["id"], "expires_at": challenge["expires_at"],
                "qr": challenge["qr"], "message": "请使用对应的 QQ 账号扫码并确认"}

    def poll(self, name, token):
        challenge = self.active.get(name)
        if not challenge or not secrets.compare_digest(challenge["id"], token):
            return {"state": "expired", "message": "二维码已过期或服务已重启，请重新生成"}
        self.reserve(name, "poll", 5)
        if self.redis.get(PREFIX + name + ":lease") != token.encode():
            self.discard(name)
            return {"state": "expired", "message": "登录会话已失效，请重新生成二维码"}
        try:
            state, updates = challenge["provider"].poll()
            if state == "authenticated":
                if time.time() >= challenge["expires_at"] or self.redis.get(PREFIX + name + ":lease") != token.encode():
                    raise ValueError("Login lease expired")
                if updates:
                    store.save_secrets(self.env_file, updates, self.directory, expected=challenge["expected"])
                self.record(name, providers.status(True, "登录成功，登录态已更新"))
            message = {"authenticated": "登录成功，登录态已更新", "waiting_scan": "等待扫码",
                       "waiting_confirmation": "已扫码，请在 QQ 确认", "expired": "二维码已过期，请重新生成"}.get(state, "登录失败，请稍后重新生成二维码")
            if state not in ("waiting_scan", "waiting_confirmation"):
                self.discard(name)
            return {"state": state, "message": message}
        except Limited:
            # Final QR authorization must never be exchanged twice after completion.
            self.discard(name)
            raise
        except Exception:
            self.cooldown(name)
            self.discard(name)
            raise

    def dispatch(self, request):
        self.cleanup()
        name, action = request.get("provider"), request.get("action")
        if action == "list":
            return {"accounts": [{"provider": n, "name": label, **self.cached(n)} for n, label in NAMES.items()]}
        if name not in NAMES:
            raise ValueError("Invalid provider")
        if action == "check":
            return self.check(name)
        if action == "start":
            return self.start(name)
        if action == "poll":
            return self.poll(name, str(request.get("challenge_id", "")))
        raise ValueError("Invalid operation")

    def close(self):
        for name in list(self.active):
            self.discard(name)
        self.redis.close()

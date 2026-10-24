"""The only login-worker filesystem boundary; canonical secrets remain in .env."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from dotenv import dotenv_values

MANAGED_KEYS = frozenset({"HOK_CAMP_SESSION_JSON", "HOK_WZRY_TOKEN", "HOK_WZRY_ENCODERES",
                          "HOK_PLAYER_CLIENT_SESSION_JSON", "HOK_NAPCAT_WEBUI_TOKEN"})


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def atomic_write(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".login-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False))


def secrets(env_file):
    return dotenv_values(env_file, interpolate=False)


def save_secrets(env_file, updates, lock_dir, expected=None):
    """Merge under flock; validate dotenv round-trip before atomic replacement."""
    if not updates or not set(updates) <= MANAGED_KEYS:
        raise ValueError("Unsupported credential update")
    lock_path = private_directory(lock_dir) / "credentials.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = Path(env_file)
        original = path.read_text(encoding="utf-8")
        if expected is not None:
            current = secrets(path)
            if any(current.get(k) != v for k, v in expected.items()):
                raise ValueError("Credentials changed during login; start a new challenge")
        text = original
        for key, value in updates.items():
            if not isinstance(value, str) or "\0" in value or "\n" in value or "\r" in value:
                raise ValueError("Invalid credential")
            line = key + "='" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
            pattern = re.compile(r"^(?:export\s+)?" + re.escape(key) + r"=.*$", re.M)
            if pattern.search(text):
                text = pattern.sub(lambda _: line, text)
            else:
                text = text.rstrip("\n") + "\n" + line + "\n"
        from io import StringIO
        parsed = dotenv_values(stream=StringIO(text), interpolate=False)
        if any(parsed.get(k) != v for k, v in updates.items()):
            raise ValueError("Credential serialization failed")
        atomic_write(path, text)


def camp_overrides(state):
    """Only protocol/account fields; never export login_response or QQ credentials."""
    profile = state.get("profile", {})
    role = state.get("role", {})
    result = {"token": state["token"], "encoderes": state["encode_res"],
              "userid": str(state["userId"]), "openid": state["openId"]}
    headers = {"cclientversionname": profile["version_name"], "cclientversioncode": str(profile["version_code"]),
               "csystemversioncode": str(profile["sdk"]), "csystemversionname": profile["os_version"],
               "cpuhardware": profile["hardware"], "cchannelid": profile.get("channel_id", "00000"),
               "tinkerid": "2057978310_64_0"}
    headers.update({k.lower(): str(v) for k, v in role.items()})
    result["client_headers"] = headers
    if role.get("gameOpenId"):
        result["gameopenid"] = role["gameOpenId"]
    if role.get("gameRoleId"):
        result["gameroleid"] = str(role["gameRoleId"])
    return result


def apply_credentials(config, env):
    """Hot reload only managed Camp fields, retaining legacy settings until first scan."""
    target = config.setdefault("wzry", {})
    for name, key in (("HOK_WZRY_TOKEN", "token"), ("HOK_WZRY_ENCODERES", "encoderes")):
        if env.get(name):
            target[key] = env[name]
    if env.get("HOK_CAMP_SESSION_JSON"):
        target.update(camp_overrides(json.loads(env["HOK_CAMP_SESSION_JSON"])))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_bytes(path):
    return Path(path).read_bytes()


def read_config(path):
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def remove_directory(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)

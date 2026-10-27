"""The only login-worker filesystem boundary; canonical secrets remain in .env."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from dotenv import dotenv_values

MANAGED_KEYS = frozenset({"HOK_CAMP_SESSION_JSON", "HOK_WZRY_TOKEN", "HOK_WZRY_ENCODERES",
                          "HOK_PLAYER_CLIENT_SESSION_JSON", "HOK_NAPCAT_WEBUI_TOKEN",
                          "HOK_PLAYER_CLIENT_ACCOUNT_JSON", "HOK_NAPCAT_ACCOUNT_JSON", "NAPCAT_QUICK_ACCOUNT", "HOK_NAPCAT_ONEBOT_JSON"})


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


def save_secrets(env_file, updates, lock_dir, expected=None, config_file=None):
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
        # The complete session envelope is authoritative even if a process exits
        # between these replacements. Both readers project its account fields.
        projected = prepare_config(config_file, parsed) if config_file else None
        atomic_write(path, text)
        if projected is not None:
            try:
                atomic_write(config_file, projected)
            except Exception:
                atomic_write(path, original)
                raise


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
    # Empty/zero is an intentional new-account value and must erase stale roles.
    result["gameopenid"] = role.get("gameOpenId", "")
    result["gameroleid"] = str(role.get("gameRoleId", 0))
    result["roleid"] = result["gameroleid"]
    for key, default in (("gameAreaId", 0), ("gameServerId", 0), ("gameUserSex", 0), ("kohDimGender", 1)):
        result[key.lower()] = int(role.get(key, default))
    result["tinkerid"] = headers["tinkerid"]
    result["x-log-uid"] = state.get("log_id", "")
    return result


def apply_credentials(config, env):
    """Hot reload only managed Camp fields, retaining legacy settings until first scan."""
    target = config.setdefault("wzry", {})
    for name, key in (("HOK_WZRY_TOKEN", "token"), ("HOK_WZRY_ENCODERES", "encoderes")):
        if env.get(name):
            target[key] = env[name]
    if env.get("HOK_CAMP_SESSION_JSON"):
        target.update(camp_overrides(json.loads(env["HOK_CAMP_SESSION_JSON"])))
    if env.get("HOK_NAPCAT_ACCOUNT_JSON"):
        account = json.loads(env["HOK_NAPCAT_ACCOUNT_JSON"])
        uin = str(account["uin"])
        if not re.fullmatch(r"[1-9][0-9]{4,19}", uin):
            raise ValueError("Invalid saved QQ identity")
        config.setdefault("QQBot", {})["bot_qid"] = uin
    if env.get("HOK_PLAYER_CLIENT_ACCOUNT_JSON"):
        routing = json.loads(env["HOK_PLAYER_CLIENT_ACCOUNT_JSON"])
        config.setdefault("PlayerClient", {}).update({"server_id": int(routing["server_id"]),
                                                      "tree_index": int(routing["tree_index"])})


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


def prepare_config(path, env):
    """Patch verified identity fields only, preserving other settings and comments."""
    import yaml
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    apply_credentials(config, env)
    patches = {}
    if env.get("HOK_CAMP_SESSION_JSON"):
        fields = ("userid", "openid", "gameopenid", "gameroleid", "roleid", "tinkerid", "x-log-uid", "gameareaid", "gameserverid", "gameusersex", "kohdimgender")
        patches["wzry"] = {k: config["wzry"][k] for k in fields}
    if env.get("HOK_NAPCAT_ACCOUNT_JSON"):
        patches["QQBot"] = {"bot_qid": config["QQBot"]["bot_qid"]}
    if env.get("HOK_PLAYER_CLIENT_ACCOUNT_JSON"):
        patches["PlayerClient"] = {k: config["PlayerClient"][k] for k in ("server_id", "tree_index")}
    for section, values in patches.items():
        pattern = re.compile(r"^"+re.escape(section)+r":[^\n]*\n(?:(?:[ \t].*|[ \t]*)\n)*", re.M)
        found = pattern.search(text)
        if not found:
            raise ValueError("Missing managed config section")
        block = found.group()
        for key, value in values.items():
            field = re.compile(r"^  "+re.escape(key)+r":.*$", re.M)
            line = "  "+key+": "+json.dumps(value, ensure_ascii=False)
            block = field.sub(lambda _: line, block) if field.search(block) else block.rstrip("\n")+"\n"+line+"\n"
        text = text[:found.start()]+block+text[found.end():]
    checked = yaml.safe_load(text)
    if any(checked[section].get(k) != v for section, fields in patches.items() for k, v in fields.items()):
        raise ValueError("Account config serialization failed")
    return text


def reconcile_config(env_file, config_file, lock_dir):
    """Repair an interrupted projection from the canonical complete session envelope."""
    lock_path = private_directory(lock_dir) / "credentials.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        projected = prepare_config(config_file, secrets(env_file))
        if Path(config_file).read_text(encoding="utf-8") != projected:
            atomic_write(config_file, projected)


def read_napcat_onebot(directory, uin):
    """Read only the configured Bot's native NapCat transport, never enumerate accounts."""
    if not re.fullmatch(r"[1-9][0-9]{4,19}", uin):
        raise ValueError("Invalid configured QQ")
    directory = Path(directory).resolve()
    path = directory / ("onebot11_"+uin+".json")
    if not path.is_file():
        path = directory / "onebot11.json"  # NapCat's documented native default.
    if not path.is_file():
        return None
    value = read_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("network"), dict):
        raise ValueError("Invalid native OneBot transport config")
    return value

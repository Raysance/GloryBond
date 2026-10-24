"""Fixed service protocols. No NoneBot imports, public files, or credential logging."""
import hashlib
from io import BytesIO
import json
from urllib.parse import urlsplit
import time
import re

import requests

from hok_camp_client import CampClient
from hok_camp_client.qq import QQLogin


class DirectCampClient(CampClient):
    """Keep QQ routing direct before begin(); upstream has no transport hook."""
    def start_login(self, qr_path):
        if time.monotonic() - self._last_qr_start < 30:
            raise RuntimeError("QR generation is cooling down")
        self._last_qr_start = time.monotonic()
        http = requests.Session()
        http.trust_env = False
        self._qr = QQLogin(session=http, timeout=self.timeout)
        p = self.profile
        return self._qr.begin(qr_path, os_version=p["os_version"], model=p["model"], sdk=p["sdk"])

from . import store


class IdentityMismatch(RuntimeError):
    pass


class NotConfigured(RuntimeError):
    pass


def status(authenticated=None, message="暂时无法确认，请稍后检查"):
    return {"authenticated": authenticated, "message": message}


class Camp:
    def __init__(self, config, env, directory):
        from hok_camp_client.crypto import decode_encode_res
        self.path = directory / "camp.json"
        self.expected = str(config["wzry"]["userid"])
        state = json.loads(env["HOK_CAMP_SESSION_JSON"]) if env.get("HOK_CAMP_SESSION_JSON") else {}
        if not state and env.get("HOK_WZRY_ENCODERES") and env.get("HOK_WZRY_TOKEN"):
            state = {"userId": self.expected, "openId": config["wzry"]["openid"],
                     "token": env["HOK_WZRY_TOKEN"], "encode_res": env["HOK_WZRY_ENCODERES"],
                     "userKey": decode_encode_res(env["HOK_WZRY_ENCODERES"])["userKey"]}
        store.write_json(self.path, state)
        self.client = DirectCampClient(state_file=self.path, timeout=15)
        self.client.http.trust_env = False
        self.role = state.get("role") or dict(gameOpenId=config["wzry"]["gameopenid"],
            gameRoleId=int(config["wzry"]["gameroleid"]),
            gameAreaId=int(config["wzry"].get("gameareaid", 1)),
            gameServerId=int(config["wzry"].get("gameserverid", 1545)),
            gameUserSex=int(config["wzry"].get("gameusersex", 1)), kohDimGender=2)

    def check(self):
        result = self.client.login_status()
        value = result["authenticated"]
        return status(value, {True: "营地登录有效", False: "营地登录已失效，请扫码", None: "营地状态暂时无法确认"}[value])

    def start(self, directory):
        self.qr_path = directory / "camp-qr.png"
        self.client.start_login(self.qr_path)
        return store.read_bytes(self.qr_path)

    def poll(self):
        result = self.client.poll_login()
        state = result["state"]
        if state == "authenticated":
            saved = store.read_json(self.path)
            if str(saved.get("userId")) != self.expected:
                raise IdentityMismatch()
            self.client.set_role(game_open_id=self.role["gameOpenId"], game_role_id=self.role["gameRoleId"],
                                 game_area_id=self.role["gameAreaId"], game_server_id=self.role["gameServerId"],
                                 game_user_sex=self.role["gameUserSex"], dim_gender=self.role["kohDimGender"])
            checked = self.check()
            if checked["authenticated"] is not True:
                raise RuntimeError("Login could not be verified")
            saved = store.read_json(self.path)
            return "authenticated", {"HOK_CAMP_SESSION_JSON": json.dumps(saved, ensure_ascii=False),
                 "HOK_WZRY_TOKEN": saved["token"], "HOK_WZRY_ENCODERES": saved["encode_res"]}
        return state, None

    def close(self):
        self.client.http.close()
        qr = self.client._qr
        if qr is not None:
            qr.http.close()


class Official:
    def __init__(self, config, env, directory, gate):
        from hok_research import HokClient, MsdkSession
        settings = config["PlayerClient"]
        self.settings, self.gate = settings, gate
        paths = {}
        for name in ("resources", "session", "installation"):
            raw = env.get("HOK_PLAYER_CLIENT_" + name.upper() + "_JSON")
            if not raw:
                raise NotConfigured()
            paths[name] = directory / (name + ".json")
            store.write_json(paths[name], json.loads(raw))
        self.client = HokClient.from_resources(paths["resources"], installation_path=paths["installation"], timeout=15)
        self.session = MsdkSession.load(paths["session"])
        self.session_path = paths["session"]

    def verify(self):
        self.gate()
        self.client.servers(platform_id=int(self.settings["platform_id"]))
        self.client.login(server_id=self.settings.get("server_id"), tree_index=int(self.settings.get("tree_index", 0)))

    def check(self):
        expiry = self.session.raw.get("token_expire_time")
        if type(expiry) in (int, float) and 0 < expiry <= time.time():
            return status(False, "官方客户端会话已超过服务端有效期，请扫码")
        self.client.use_msdk_session(self.session)
        self.verify()
        return status(True, "官方客户端登录有效（游戏服务器认证通过）")

    def start(self, directory):
        return self.client.start_qq_login().png

    def poll(self):
        result = self.client.poll_qq_login()
        if result.code in (66, 67):
            return ("waiting_scan" if result.code == 66 else "waiting_confirmation"), None
        if result.code == 65:
            return "expired", None
        if result.code != 0:
            return "error", None
        self.client.complete_qq_login(result)
        if self.client.msdk_session.openid != self.session.openid:
            raise IdentityMismatch()
        self.verify()
        self.client.msdk_session.save(self.session_path)
        raw = store.read_json(self.session_path)
        return "authenticated", {"HOK_PLAYER_CLIENT_SESSION_JSON": json.dumps(raw, ensure_ascii=False)}

    def close(self):
        self.client.close()


class PinnedLoopbackAdapter(requests.adapters.HTTPAdapter):
    """Authenticate the configured local self-signed server by its exact certificate."""
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        super().__init__(max_retries=0)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["assert_fingerprint"] = self.fingerprint
        super().init_poolmanager(*args, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host, options = super().build_connection_pool_key_attributes(request, False, cert)
        options["assert_fingerprint"] = self.fingerprint
        return host, options

    def cert_verify(self, conn, url, verify, cert):
        # urllib3 still verifies assert_fingerprint before sending HTTP credentials.
        # CA/hostname validation is replaced only for this pinned loopback pool.
        conn.cert_reqs = "CERT_NONE"
        conn.ca_certs = None
        conn.ca_cert_dir = None


class NapCat:
    def __init__(self, config, env, directory):
        base = config.get("AccountSessions", {}).get("napcat", {}).get("base_url", "http://127.0.0.1:6099")
        parsed = urlsplit(base)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
            raise NotConfigured()
        self.base, self.token = base.rstrip("/"), env.get("HOK_NAPCAT_WEBUI_TOKEN", "")
        if not self.token:
            raise NotConfigured()
        self.expected = str(config["QQBot"]["bot_qid"])
        self.http = requests.Session()
        self.http.trust_env = False
        if parsed.scheme == "https":
            fingerprint = config.get("AccountSessions", {}).get("napcat", {}).get("tls_fingerprint_sha256", "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
                self.http.close()
                raise NotConfigured()
            self.http.mount(self.base + "/", PinnedLoopbackAdapter(fingerprint))
        self.credential = None

    def call(self, route, body=None):
        response = self.http.post(self.base + "/api/" + route, json=body or {},
            headers={"Authorization": "Bearer " + self.credential} if self.credential else {},
            timeout=10, allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError("NapCat unavailable")
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError("NapCat request rejected")
        return data["data"]

    def authorize(self):
        digest = hashlib.sha256((self.token + ".napcat").encode()).hexdigest()
        self.credential = self.call("auth/login", {"hash": digest})["Credential"]

    def check(self):
        if self.credential is None:
            self.authorize()
        result = self.call("QQLogin/CheckLoginStatus")
        if result.get("isLogin") is False:
            return status(False, "QQ 未登录，请扫码")
        if result.get("isLogin") is not True:
            return status()
        info = self.call("QQLogin/GetQQLoginInfo")
        if str(info.get("uin")) != self.expected:
            raise IdentityMismatch()
        return status(True, "NapCat QQ 登录有效")

    def start(self, directory):
        if self.check()["authenticated"] is not False:
            raise RuntimeError("QQ is already online or unknown")
        value = self.call("QQLogin/GetQQLoginQrcode")["qrcode"]
        if not isinstance(value, str) or not 1 <= len(value) <= 4096:
            raise RuntimeError("Invalid QR payload")
        import qrcode
        output = BytesIO()
        qrcode.make(value).save(output, format="PNG")
        return output.getvalue()

    def poll(self):
        checked = self.check()
        return ("authenticated" if checked["authenticated"] is True else "waiting_scan"), None

    def close(self):
        self.http.close()

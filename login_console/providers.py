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


class NotConfigured(RuntimeError):
    pass


def status(authenticated=None, message="暂时无法确认，请稍后检查"):
    return {"authenticated": authenticated, "message": message}


class Camp:
    def __init__(self, config, env, directory):
        from hok_camp_client.crypto import decode_encode_res
        self.path = directory / "camp.json"
        self.previous_user = str(config["wzry"]["userid"])
        self.pending_roles = None
        state = json.loads(env["HOK_CAMP_SESSION_JSON"]) if env.get("HOK_CAMP_SESSION_JSON") else {}
        if not state and env.get("HOK_WZRY_ENCODERES") and env.get("HOK_WZRY_TOKEN"):
            state = {"userId": self.previous_user, "openId": config["wzry"]["openid"],
                     "token": env["HOK_WZRY_TOKEN"], "encode_res": env["HOK_WZRY_ENCODERES"],
                     "userKey": decode_encode_res(env["HOK_WZRY_ENCODERES"])["userKey"]}
        store.write_json(self.path, state)
        self.client = DirectCampClient(state_file=self.path, timeout=15)
        self.client.http.trust_env = False

    def check(self):
        result = self.client.login_status()
        value = result["authenticated"]
        return status(value, {True: "营地登录有效", False: "营地登录已失效，请扫码", None: "营地状态暂时无法确认"}[value])

    def start(self, directory):
        # Start a clean account state: CampClient merges login responses into its state.
        # An old role must never survive a new QQ authorization.
        self.client.http.close()
        store.write_json(self.path, {})
        self.client = DirectCampClient(state_file=self.path, timeout=15)
        self.client.http.trust_env = False
        self.qr_path = directory / "camp-qr.png"
        self.client.start_login(self.qr_path)
        return store.read_bytes(self.qr_path)

    @staticmethod
    def normalize_roles(payload):
        data = payload.get("data", payload)
        if isinstance(data, dict):
            data = data.get("roles", data.get("list", data.get("roleList")))
        if not isinstance(data, list) or len(data) > 100:
            raise RuntimeError("Unrecognized Camp roles response")
        roles = []
        for row in data:
            if not isinstance(row, dict):
                raise RuntimeError("Invalid Camp role")
            role_id = int(row["roleId"])
            open_id = row["openid"]
            if role_id <= 0 or not isinstance(open_id, str) or not open_id:
                raise RuntimeError("Incomplete Camp role")
            role = dict(gameOpenId=open_id, gameRoleId=role_id, gameAreaId=int(row["areaId"]),
                        gameServerId=int(row["serverId"]), gameUserSex=int(row.get("sex", 0)),
                        kohDimGender=int(row.get("kohDimGender", 1)))
            label = str(row.get("roleName") or row.get("name") or "王者角色")[:60]
            label += " · 区服 " + str(role["gameServerId"])
            roles.append({"role": role, "main": row.get("isMainRole") in (True, 1, "1"), "label": label})
        return roles

    @property
    def role_choices(self):
        return [{"choice": i, "label": row["label"]} for i, row in enumerate(self.pending_roles or [])]

    def _complete(self, role):
        self.client.set_role(game_open_id=role["gameOpenId"], game_role_id=role["gameRoleId"],
                             game_area_id=role["gameAreaId"], game_server_id=role["gameServerId"],
                             game_user_sex=role["gameUserSex"], dim_gender=role["kohDimGender"])
        if self.check()["authenticated"] is not True:
            raise RuntimeError("Login could not be verified")
        saved = store.read_json(self.path)
        return "authenticated", {"HOK_CAMP_SESSION_JSON": json.dumps(saved, ensure_ascii=False),
             "HOK_WZRY_TOKEN": saved["token"], "HOK_WZRY_ENCODERES": saved["encode_res"]}

    def select_role(self, choice):
        if self.pending_roles is None or not 0 <= choice < len(self.pending_roles):
            raise ValueError("Invalid role selection")
        return self._complete(self.pending_roles[choice]["role"])

    def poll(self):
        if self.pending_roles is not None:
            return "select_role", None
        result = self.client.poll_login()
        state = result["state"]
        if state == "authenticated":
            # Explicit admin reauthorization authorizes this single authenticated role lookup.
            payload, _ = self.client._post("/game/roles", {"gameId": 20001})
            roles = self.normalize_roles(payload)
            mains = [r for r in roles if r["main"]]
            if len(mains) == 1 or len(roles) == 1:
                return self._complete((mains or roles)[0]["role"])
            if not roles:
                return self._complete(dict(gameOpenId="", gameRoleId=0, gameAreaId=0,
                                           gameServerId=0, gameUserSex=0, kohDimGender=1))
            self.pending_roles = roles
            return "select_role", None
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

    def verify(self, *, new_account=False):
        self.gate()
        directory = self.client.servers(platform_id=int(self.settings["platform_id"]))
        if new_account:
            selected = directory.preferred_server()
            self.routing = {"server_id": int(selected["node"]["id"]), "tree_index": int(selected["tree_index"])}
            self.client.login(**self.routing)
        else:
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
        self.verify(new_account=True)
        self.client.msdk_session.save(self.session_path)
        raw = store.read_json(self.session_path)
        return "authenticated", {"HOK_PLAYER_CLIENT_SESSION_JSON": json.dumps(raw, ensure_ascii=False),
                                 "HOK_PLAYER_CLIENT_ACCOUNT_JSON": json.dumps(self.routing)}

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
        self.previous_qq = str(config["QQBot"]["bot_qid"])
        self.onebot_config = json.loads(env["HOK_NAPCAT_ONEBOT_JSON"]) if env.get("HOK_NAPCAT_ONEBOT_JSON") else None
        native_directory = config.get("AccountSessions", {}).get("napcat", {}).get("config_dir")
        if native_directory:
            native = store.read_napcat_onebot(native_directory, self.previous_qq)
            if native is not None:
                self.onebot_config = native
        self.base, self.token = base.rstrip("/"), env.get("HOK_NAPCAT_WEBUI_TOKEN", "")
        if not self.token:
            raise NotConfigured()
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
        uin = str(info.get("uin", ""))
        if not re.fullmatch(r"[1-9][0-9]{4,19}", uin):
            raise RuntimeError("Invalid QQ login identity")
        self.account = {"uin": uin}
        return status(True, "NapCat QQ 登录有效")

    def start(self, directory):
        current = self.check()["authenticated"]
        if current is True:
            return None  # Explicit admin action synchronizes the already logged-in account.
        if current is not False:
            raise RuntimeError("QQ login status is unknown")
        value = self.call("QQLogin/GetQQLoginQrcode")["qrcode"]
        if not isinstance(value, str) or not 1 <= len(value) <= 4096:
            raise RuntimeError("Invalid QR payload")
        import qrcode
        output = BytesIO()
        qrcode.make(value).save(output, format="PNG")
        return output.getvalue()

    def poll(self):
        checked = self.check()
        if checked["authenticated"] is True:
            if self.account["uin"] != self.previous_qq:
                if not isinstance(self.onebot_config, dict) or not self.onebot_config.get("network"):
                    raise NotConfigured()
                # Preserve the Bot's existing transport when NapCat creates per-QQ config.
                self.call("OB11Config/SetConfig", {"config": json.dumps(self.onebot_config)})
            self.call("QQLogin/SetQuickLoginQQ", {"uin": self.account["uin"]})
            updates = {"HOK_NAPCAT_ACCOUNT_JSON": json.dumps(self.account), "NAPCAT_QUICK_ACCOUNT": self.account["uin"]}
            if self.onebot_config is not None:
                updates["HOK_NAPCAT_ONEBOT_JSON"] = json.dumps(self.onebot_config, ensure_ascii=False)
            return "authenticated", updates
        return "waiting_scan", None

    def close(self):
        self.http.close()

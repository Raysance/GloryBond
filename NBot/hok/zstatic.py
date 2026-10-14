
from .zutil import *
from dotenv import load_dotenv
from urllib.parse import urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.util import timezone


# Redis key schema shared by NBot and Web. All HOK data lives in DB0.
REDIS_KEY_WEB_ARTIFACT_PREFIX = "hok:web:artifact:"
REDIS_KEY_BATTLE_LIKED_IDS = "hok:battle:liked_ids"
REDIS_KEY_BATTLE_SHARE_QUEUE = "hok:queue:battle:share"
REDIS_KEY_BATTLE_ANALYZE_QUEUE = "hok:queue:battle:analyze"
REDIS_KEY_MESSAGE_OUTBOUND_QUEUE = "hok:queue:message:outbound"
REDIS_KEY_HERO_TODAY_PREFIX = "hok:hero:today:"
REDIS_KEY_HERO_HISTORY_PREFIX = "hok:hero:history:"
REDIS_KEY_BATTLE_EVALUATOR_RECORDS = "hok:evaluator:battle:records"
REDIS_KEY_DIY_CODES = "hok:diy:codes"
REDIS_KEY_DIY_SUMMARIES = "hok:diy:summaries"
REDIS_KEY_CHAT_FACTS_PREFIX = "hok:memory:facts:"
REDIS_KEY_EMOJI_PREFIX = "hok:emoji:"


def _runtime_path(env_name, default_path):
    """Return one normalized runtime path from the environment or its default."""
    return os.path.abspath(os.path.expanduser(os.environ.get(env_name) or default_path))


def _load_runtime_environment():
    """Load an optional dotenv file without coupling startup to /QQBot."""
    explicit_path = os.environ.get("HOK_ENV_FILE")
    if explicit_path:
        candidates = [explicit_path]
    else:
        candidates = [
            os.path.join(os.path.dirname(os.getcwd()), ".env"),
            os.path.join(os.getcwd(), ".env"),
        ]
    loaded_paths = []
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            load_dotenv(dotenv_path=candidate, override=False)
            loaded_paths.append(os.path.abspath(candidate))
    return os.pathsep.join(loaded_paths)


def _build_chat_api_config(config, environment):
    """Resolve chat provider settings while allowing an explicit empty proxy."""
    values = {}
    for key, env_name in {
        "base_url": "HOK_CHAT_BASE_URL",
        "api_key": "HOK_CHAT_API_KEY",
        "model": "HOK_CHAT_MODEL",
        "proxy_url": "HOK_CHAT_PROXY_URL",
    }.items():
        raw_value = environment[env_name] if env_name in environment else config.get("ChatAPI", {}).get(key)
        values[key] = str(raw_value or "").strip()
    key_name = config.get("ChatAPI", {}).get("api_key_env")
    if key_name:
        if "HOK_CHAT_API_KEY" not in environment:
            values["api_key"] = str(environment.get(key_name) or "").strip()
        if not values["api_key"]:
            raise ValueError(f"ChatAPI model key is not configured: {key_name}")
    elif not values["api_key"] and urlparse(values["base_url"]).hostname == "api.deepseek.com":
        values["api_key"] = str(config.get("QQBot", {}).get("deepseek_key") or "").strip()
    return values


def _apply_secret_environment(config, environment):
    """Inject credentials from the single .env file into runtime config."""
    secret_paths = {
        "HOK_DEEPSEEK_API_KEY": ("QQBot", "deepseek_key"),
        "HOK_ARK_API_KEY": ("QQBot", "ark_key"),
        "HOK_ARK_IMAGE_API_KEY": ("QQBot", "ark_image_key"),
        "HOK_APIMART_API_KEY": ("QQBot", "apimart_key"),
        "HOK_STEAM_API_KEY": ("Steam", "api_key"),
        "HOK_WEB_SECRET_KEY": ("WebService", "secret_key"),
        "HOK_WEB_VALID_PATTERN": ("WebService", "valid_pattern"),
        "HOK_WZRY_TOKEN": ("wzry", "token"),
        "HOK_WZRY_ENCODERES": ("wzry", "encoderes"),
    }
    for env_name, (section, key) in secret_paths.items():
        if env_name in environment:
            config.setdefault(section, {})[key] = str(environment[env_name]).strip()
    return config


env_path = _load_runtime_environment()
project_root = _runtime_path("BOT_PATH", os.getcwd())
data_root = _runtime_path("HOK_DATA_DIR", os.path.join(project_root, "data"))
temp_path = _runtime_path(
    "HOK_FILE_TRANSFER_DIR",
    os.path.join(project_root, "file_transfer"),
)
log_root = _runtime_path("HOK_LOG_DIR", os.path.join(project_root, "log"))
config_path = _runtime_path(
    "HOK_CONFIG_FILE",
    os.path.join(project_root, "config.yaml"),
)

# .env stores credentials; config.yaml stores every non-secret setting.
with open(config_path, 'r', encoding='utf-8') as file:
    confs = yaml.load(file, Loader=yaml.FullLoader) or {}
_apply_secret_environment(confs, os.environ)
globals().update(confs.get("Redis", {}))
chat_api_config = _build_chat_api_config(confs, os.environ)
aliyun_search_config = {
    key: str(os.environ.get(env_name) or confs.get("AliyunSearch", {}).get(key) or default).strip()
    for key, env_name, default in (
        ("endpoint", "HOK_ALIYUN_SEARCH_ENDPOINT", ""),
        ("api_key", "HOK_ALIYUN_SEARCH_API_KEY", ""),
        ("workspace", "HOK_ALIYUN_SEARCH_WORKSPACE", "default"),
        ("service_id", "HOK_ALIYUN_SEARCH_SERVICE_ID", "ops-web-search-001"),
        ("content_type", "HOK_ALIYUN_SEARCH_CONTENT_TYPE", "snippet"),
        ("way", "HOK_ALIYUN_SEARCH_WAY", "pro"),
    )
}
aliyun_search_config["query_rewrite"] = str(
    os.environ.get("HOK_ALIYUN_SEARCH_QUERY_REWRITE")
    if "HOK_ALIYUN_SEARCH_QUERY_REWRITE" in os.environ
    else confs.get("AliyunSearch", {}).get("query_rewrite", True)
).strip().casefold() not in {"0", "false", "no", "off"}
clash_proxy_url = str(
    os.environ.get("HOK_CLASH_PROXY_URL")
    or confs.get("Proxy", {}).get("clash_url")
    or ""
).strip()
chat_readonly_dsn = str(
    os.environ.get("HOK_CHAT_READONLY_DSN")
    or confs.get("AgentSQL", {}).get("dsn")
    or ""
).strip()
agent_plot_config = confs.get("AgentPlots", {})
qq_profile_config = confs.get("QQProfiles", {})
postgres_dsn = str(
    os.environ.get("HOK_DATABASE_DSN")
    or confs.get("PostgreSQL", {}).get("dsn")
    or ""
)
postgres_archive_json = bool(confs.get("PostgreSQL", {}).get("archive_json", False))

# Static and dynamic variables share the same non-secret config file.
varia = dict(confs.get("StaticVariables", {}))
for heroid,heroname in varia["HeroList"].items():
    varia["HeroNames"].append(heroname)
for heroid,heroname in varia["HeroName_replacements"].items():
    varia["HeroNames"].append(heroname)
globals().update(varia)
dynamic_variables = dict(confs.get("DynamicVariables", {}))

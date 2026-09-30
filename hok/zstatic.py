
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
REDIS_KEY_ACTIVE_CHAT_PREFIX = "hok:memory:active_chat:"
REDIS_KEY_CHAT_ROLE_PREFIX = "hok:chat:role:"


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
    if not explicit_path:
        private_path = os.path.join(os.environ.get("BOT_PATH") or os.getcwd(), ".env.local")
        if os.path.isfile(private_path):
            load_dotenv(dotenv_path=private_path, override=False)
            loaded_paths.append(os.path.abspath(private_path))
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
    if not values["api_key"] and urlparse(values["base_url"]).hostname == "api.deepseek.com":
        values["api_key"] = str(config.get("QQBot", {}).get("deepseek_key") or "").strip()
    return values


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
variables_static_path = _runtime_path(
    "HOK_STATIC_VARIABLES_FILE",
    os.path.join(project_root, "variables_static.json"),
)
variables_dynamic_path = _runtime_path(
    "HOK_DYNAMIC_VARIABLES_FILE",
    os.path.join(project_root, "variables_dynamic.json"),
)

# 引入Redis配置
redis_path = _runtime_path(
    "REDIS_CONF",
    os.path.join(project_root, "redis.json"),
)
with open(redis_path, 'r', encoding='utf-8') as file:
    varia = json.load(file)
globals().update(varia)
# 引入程序配置
confs={}
with open(config_path, 'r', encoding='utf-8') as file:
    confs = yaml.load(file, Loader=yaml.FullLoader)
chat_api_config = _build_chat_api_config(confs, os.environ)
openrouter_search_config = {
    key: str(os.environ.get(env_name) or confs.get("OpenRouterSearch", {}).get(key) or default).strip()
    for key, env_name, default in (
        ("base_url", "HOK_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"),
        ("api_key", "HOK_OPENROUTER_API_KEY", ""),
        ("model", "HOK_OPENROUTER_SEARCH_MODEL", "openrouter/auto"),
        ("engine", "HOK_OPENROUTER_SEARCH_ENGINE", "auto"),
    )
}
clash_proxy_url = str(
    os.environ.get("HOK_CLASH_PROXY_URL")
    or confs.get("Proxy", {}).get("clash_url")
    or ""
).strip()
chat_readonly_dsn = str(
    os.environ.get("HOK_CHAT_READONLY_DSN")
    or confs.get("ChatSQL", {}).get("dsn")
    or ""
).strip()
chat_sql_config = confs.get("ChatSQL", {})
chat_plot_config = confs.get("ChatPlot", {})
postgres_dsn = str(
    os.environ.get("HOK_DATABASE_DSN")
    or confs.get("PostgreSQL", {}).get("dsn")
    or "REDACTED_CREDENTIAL"
)
postgres_archive_json = bool(confs.get("PostgreSQL", {}).get("archive_json", False))

# 引入程序静态变量
with open(variables_static_path, 'r', encoding='utf-8') as file:
    varia = json.load(file)
for heroid,heroname in varia["HeroList"].items():
    varia["HeroNames"].append(heroname)
for heroid,heroname in varia["HeroName_replacements"].items():
    varia["HeroNames"].append(heroname)
globals().update(varia)

# OpenRouter 搜索密钥默认跟随静态变量文件，部署环境变量仍拥有最高优先级。
openrouter_search_config["api_key"] = str(
    os.environ.get("HOK_OPENROUTER_API_KEY")
    or globals().get("openrouter_api_key")
    or confs.get("OpenRouterSearch", {}).get("api_key")
    or ""
).strip()

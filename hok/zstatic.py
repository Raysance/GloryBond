
from .zutil import *
from dotenv import load_dotenv

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


env_path = "/QQBot/.env"
load_dotenv(dotenv_path=env_path)

# 引入Redis配置
redis_path=str(os.environ.get('REDIS_CONF'))
with open(redis_path, 'r', encoding='utf-8') as file:
    varia = json.load(file)
globals().update(varia)
project_root=str(os.environ.get('BOT_PATH'))
temp_path=os.path.join(project_root,"file_transfer")
# 引入程序配置
confs={}
with open('config.yaml', 'r') as file:
    confs = yaml.load(file, Loader=yaml.FullLoader)
postgres_dsn = str(
    os.environ.get("HOK_DATABASE_DSN")
    or confs.get("PostgreSQL", {}).get("dsn")
    or "REDACTED_CREDENTIAL"
)
postgres_archive_json = bool(confs.get("PostgreSQL", {}).get("archive_json", False))

# 引入程序静态变量
with open('variables_static.json', 'r', encoding='utf-8') as file:
    varia = json.load(file)
for heroid,heroname in varia["HeroList"].items():
    varia["HeroNames"].append(heroname)
for heroid,heroname in varia["HeroName_replacements"].items():
    varia["HeroNames"].append(heroname)
globals().update(varia)


from .zutil import *
from .zstatic import *
import redis

# 引入程序动态变量
with open('variables_dynamic.json', 'r', encoding='utf-8') as file:
    varia = json.load(file)
globals().update(varia)
redis_deamon = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
redis_deamon_liked_btl = redis_deamon
redis_deamon_share_btl = redis_deamon
redis_deamon_analyze_btl = redis_deamon
MessageQueue = redis_deamon
TodayHeroPool = redis_deamon
BtlAnalyzeEvaluatorPool = redis_deamon
redis_deamon_diy_code = redis_deamon
redis_deamon_chat_memory = redis_deamon

BattlePowerInProgressLock = threading.Lock()
BattlePowerInProgress = {}


from .zutil import *
from .zstatic import *
import redis

# Dynamic defaults are loaded from the sole non-secret config file.
globals().update(dynamic_variables)
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

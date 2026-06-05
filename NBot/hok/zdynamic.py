
from .zutil import *
from .zstatic import *
import redis

# 引入程序动态变量
with open('variables_dynamic.json', 'r', encoding='utf-8') as file:
    varia = json.load(file)
globals().update(varia)
redis_deamon = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
redis_deamon_liked_btl = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_LIKED_SET)
redis_deamon_share_btl = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_SHARE_QUEUE)
redis_deamon_analyze_btl = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_ANALYZE_QUEUE)
MessageQueue=redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_MESSAGE_QUEUE)
TodayHeroPool=redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_TODAY_HERO_POOL)
BtlAnalyzeEvaluatorPool=redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_BTL_ANALYZE_EVALUATOR_POOL)
redis_deamon_diy_code = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_DIY_CODE)
redis_deamon_chat_memory = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_CHAT_MEMORY)
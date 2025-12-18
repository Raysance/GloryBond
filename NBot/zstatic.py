
from .zutil import *

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.util import timezone

# 引入Redis配置
nginx_path=str(os.environ.get('NGINX_HTML')) # 依赖环境变量
redis_path=str(os.environ.get('REDIS_CONF'))
with open(redis_path, 'r', encoding='utf-8') as file:
    varia = json.load(file)
globals().update(varia)
# 引入程序配置
confs={}
with open('config.yaml', 'r') as file:
    confs = yaml.load(file, Loader=yaml.FullLoader)

# 引入程序静态变量
with open('variables_static.json', 'r', encoding='utf-8') as file:
    varia = json.load(file)
for heroid,heroname in varia["HeroList"].items():
    varia["HeroNames"].append(heroname)
for heroid,heroname in varia["HeroName_replacements"].items():
    varia["HeroNames"].append(heroname)
globals().update(varia)
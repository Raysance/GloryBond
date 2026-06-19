
from .zutil import *
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.util import timezone


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

# 引入程序静态变量
with open('variables_static.json', 'r', encoding='utf-8') as file:
    varia = json.load(file)
for heroid,heroname in varia["HeroList"].items():
    varia["HeroNames"].append(heroname)
for heroid,heroname in varia["HeroName_replacements"].items():
    varia["HeroNames"].append(heroname)
globals().update(varia)


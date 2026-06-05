from .config import Config
from nonebot.plugin import PluginMetadata
from nonebot import get_plugin_config

import redis

from .zutil import * # 引入通用库
from .zstatic import * # 引入静态变量
from . import zdynamic as dmc # 引入动态变量

from .zapi import * # API处理（王者荣耀、deepseek）
from .zevent import * # QQBot事件（接收、发送、戳一戳、定时）
from .zfile import * # 文件IO
from .zfunc import * # 辅助函数
from .zscheduler import * # 定时事件
from .ztime import * # 时间获取

# NONEBOT配置 
__plugin_meta__ = PluginMetadata(
    name="Qbot",
    description="QQ Bot for Honor of Kings: Track Stats & Interactive Engagement.",
    usage="Application",
    config=Config,
)
config = get_plugin_config(Config)

# logging配置
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("QBOT.log")]
)

# 加载昨日数据
load_yesterday(1)
init_fetch_news()
init_fetch_heroranklist()
init_fetch_hero_tier()
if __name__=="__main__":
    pass
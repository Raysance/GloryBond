from glorybond.apps.qq.config import Config
from nonebot.plugin import PluginMetadata
from nonebot import get_plugin_config

import redis

from glorybond.common import * # 引入通用库
from glorybond.config.settings import * # 引入静态变量
from glorybond import runtime as dmc # 引入动态变量

from glorybond.integrations.api import * # API处理（王者荣耀、deepseek）
from glorybond.apps.qq.events import * # QQBot事件（接收、发送、戳一戳、定时）
from glorybond.storage.files import * # 文件IO
from glorybond.features.facade import * # 辅助函数
from glorybond.apps.qq.scheduler import * # 定时事件
from glorybond.time import * # 时间获取

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

# Business cache initialization runs in isolated startup hooks in zscheduler.
if __name__=="__main__":
    pass

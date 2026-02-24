
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc
import datetime
from datetime import timedelta
from dateutil import parser


def time_r(): # time_real
    time_real=datetime.datetime.now()
    return time_real
def date_r():
    date_real = datetime.datetime.now().strftime("%Y-%m-%d")
    return date_real
def time_r_delta(delta=0):
    time_real=time_r()
    time_back=time_real-timedelta(days=delta)
    return time_back
#别用默认参数列表
def time_sul(time_real=None): # time_stay_up_late 将凌晨对局算在前一天，以3:30为界，时间向前挪动(将3:30视作0:00)
    if (time_real==None):time_real=datetime.datetime.now()
    time_fake=time_real-datetime.timedelta(hours=bound_hour, minutes=bound_minute)
    return time_fake
def date_roleback(time_real=None): # time_stay_up_late 将凌晨对局算在前一天，以3:30为界，时间向前挪动(将3:30视作0:00)
    if (time_real==None):time_real=datetime.datetime.now()
    time_fake=time_real-datetime.timedelta(days=1)
    return time_fake
def date_sul(time_real=None): # time_stay_up_late 将凌晨对局算在前一天，以3:30为界，时间向前挪动(将3:30视作0:00)
    if (time_real==None):time_fake=time_sul()
    date_fake = time_fake.strftime("%Y-%m-%d")
    return date_fake
def stamp_to_time(timestamp):
    return datetime.datetime.fromtimestamp(timestamp)
def str_to_time(time_str):
    time_datetime = parser.parse(time_str)
    return time_datetime
def time_to_str(time_datetime, format_str="%Y-%m-%d %H:%M:%S"):
    return time_datetime.strftime(format_str)
def time_delta(time_in,delta):
    return time_in+timedelta(days=delta)
def wait():
    delay_second=random.uniform(3,5)
    time.sleep(delay_second)
def short_wait():
    delay_second=random.uniform(0.5,1)
    time.sleep(delay_second)
def calc_gap(t1,t2):
    return abs((t1-t2).total_seconds())
def add_second(src,det):
    return src+timedelta(seconds=det)
def get_timebased_rand(n,rand_gap):
    """
    基于当前时间获取[0, n]内的随机整数，间隔一段时间变一次
    """
    time_now = time_r()
    time_seed = int(time_now.timestamp()) // (60*rand_gap)
    random.seed(time_seed)
    return random.randint(0, n-1) # 保证左闭右开

def parse_fuzzy_time(fuzzy_str):
    """
    解析模糊时间描述，返回(start_time, end_time)
    """
    now = time_r()
    target_date_start = now.date()
    target_date_end = now.date()
    
    # 解析日期
    if "大前天" in fuzzy_str:
        target_date_start = target_date_end = (now - timedelta(days=3)).date()
    elif "前天" in fuzzy_str:
        target_date_start = target_date_end = (now - timedelta(days=2)).date()
    elif "昨天" in fuzzy_str or "昨日" in fuzzy_str:
        target_date_start = target_date_end = (now - timedelta(days=1)).date()
    elif "今天" in fuzzy_str or "今日" in fuzzy_str:
        target_date_start = target_date_end = now.date()
    elif "三天前" in fuzzy_str:
        target_date_start = target_date_end = (now - timedelta(days=3)).date()
    elif "几天前" in fuzzy_str:
        target_date_start = (now - timedelta(days=7)).date()
        target_date_end = now.date()
    elif "上周" in fuzzy_str:
        target_date_start = (now - timedelta(days=now.weekday() + 7)).date()
        target_date_end = (target_date_start + timedelta(days=6)).date()
    elif "本周" in fuzzy_str or "这周" in fuzzy_str:
        target_date_start = (now - timedelta(days=now.weekday())).date()
        target_date_end = now.date()
    elif "这个月" in fuzzy_str:
        target_date_start = now.replace(day=1).date()
        target_date_end = now.date()
    else:
        # 尝试匹配 "N天前"
        day_match = re.search(r'(\d+)天前', fuzzy_str)
        if day_match:
            days = int(day_match.group(1))
            target_date_start = target_date_end = (now - timedelta(days=days)).date()
    
    start_time = datetime.datetime.combine(target_date_start, datetime.time(0, 0))
    end_time = datetime.datetime.combine(target_date_end, datetime.time(23, 59, 59))
    
    # 解析时段
    if "凌晨" in fuzzy_str or "深夜" in fuzzy_str or "半夜" in fuzzy_str:
        start_time = start_time.replace(hour=0, minute=0)
        end_time = end_time.replace(hour=6, minute=0)
    elif "清晨" in fuzzy_str:
        start_time = start_time.replace(hour=5, minute=0)
        end_time = end_time.replace(hour=8, minute=0)
    elif "上午" in fuzzy_str or "早晨" in fuzzy_str or "早上" in fuzzy_str:
        start_time = start_time.replace(hour=6, minute=0)
        end_time = end_time.replace(hour=12, minute=0)
    elif "中午" in fuzzy_str:
        start_time = start_time.replace(hour=11, minute=0)
        end_time = end_time.replace(hour=14, minute=0)
    elif "午后" in fuzzy_str or "下午" in fuzzy_str:
        start_time = start_time.replace(hour=12, minute=0)
        end_time = end_time.replace(hour=18, minute=0)
    elif "傍晚" in fuzzy_str:
        start_time = start_time.replace(hour=17, minute=0)
        end_time = end_time.replace(hour=20, minute=0)
    elif "晚上" in fuzzy_str:
        start_time = start_time.replace(hour=18, minute=0)
        end_time = end_time.replace(hour=23, minute=59)
        
    return start_time, end_time

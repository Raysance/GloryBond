
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

def date_start_epoch_ms(time_real=None):
    """
    获取 time_real 所在日期的 00:00:00 的 epoch 毫秒时间戳（以本机时区为准）。
    """
    if time_real is None:
        time_real = time_r()
    day_start = time_real.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day_start.timestamp() * 1000)


def epoch_ms_to_date(timestamp_ms):
    """Convert an epoch-millisecond value to the local YYYY-MM-DD date."""
    return datetime.datetime.fromtimestamp(int(timestamp_ms) / 1000).strftime("%Y-%m-%d")


def epoch_to_text(timestamp, format_str="%Y-%m-%d %H:%M:%S"):
    """Format an epoch-second value in the deployment host timezone."""
    if timestamp in (None, ""):
        return None
    return datetime.datetime.fromtimestamp(int(timestamp)).strftime(format_str)


def _chinese_day_count(text):
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text == "十":
        return 10
    if "十" in text:
        tens_text, ones_text = text.split("十", 1)
        tens = digits.get(tens_text, 1) if tens_text else 1
        ones = digits.get(ones_text, 0) if ones_text else 0
        return tens * 10 + ones
    return digits.get(text)


def parse_representative_battle_date(query_text, now=None):
    """Extract one natural-language date for representative-battle queries."""
    reference_time = time_sul(now)
    text = str(query_text or "").strip()

    full_date_match = re.search(
        r"(?<!\d)(\d{4})(?:年|[-/.])(\d{1,2})(?:月|[-/.])(\d{1,2})(?:日|号)?",
        text,
    )
    if full_date_match:
        year, month, day = (int(value) for value in full_date_match.groups())
        try:
            return datetime.date(year, month, day).strftime("%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"无效日期：{full_date_match.group(0)}") from error

    month_day_match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})(?:日|号)?", text)
    if month_day_match:
        month, day = (int(value) for value in month_day_match.groups())
        try:
            return datetime.date(reference_time.year, month, day).strftime("%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"无效日期：{month_day_match.group(0)}") from error

    numeric_days_match = re.search(r"(?<!\d)(\d+)天前", text)
    if numeric_days_match:
        days = int(numeric_days_match.group(1))
        return (reference_time - timedelta(days=days)).strftime("%Y-%m-%d")

    chinese_days_match = re.search(r"([一二两三四五六七八九十]+)天前", text)
    if chinese_days_match:
        days = _chinese_day_count(chinese_days_match.group(1))
        if days is not None:
            return (reference_time - timedelta(days=days)).strftime("%Y-%m-%d")

    relative_days = (
        (("大前天",), 3),
        (("前天",), 2),
        (("昨天", "昨日"), 1),
        (("今天", "今日"), 0),
    )
    for keywords, days in relative_days:
        if any(keyword in text for keyword in keywords):
            return (reference_time - timedelta(days=days)).strftime("%Y-%m-%d")

    return reference_time.strftime("%Y-%m-%d")


def parse_representative_battle_date_range(query_text, now=None):
    """Extract an inclusive date range from a representative-battle debug query."""
    text = str(query_text or "").strip()
    full_date_pattern = re.compile(
        r"(?<!\d)(\d{4})(?:年|[-/.])(\d{1,2})(?:月|[-/.])(\d{1,2})(?:日|号)?"
    )
    full_date_matches = list(full_date_pattern.finditer(text))

    def validated_date(match):
        year, month, day = (int(value) for value in match.groups())
        try:
            return datetime.date(year, month, day).strftime("%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"无效日期：{match.group(0)}") from error

    if len(full_date_matches) >= 2:
        start_date = validated_date(full_date_matches[0])
        end_date = validated_date(full_date_matches[1])
    else:
        range_parts = re.split(r"\s*(?:到|至|~|～)\s*", text, maxsplit=1)
        if len(range_parts) == 2:
            start_date = parse_representative_battle_date(range_parts[0], now=now)
            end_date = parse_representative_battle_date(range_parts[1], now=now)
        else:
            target_date = parse_representative_battle_date(text, now=now)
            start_date = target_date
            end_date = target_date

    if start_date > end_date:
        raise ValueError(f"开始日期不能晚于结束日期：{start_date} > {end_date}")
    return start_date, end_date


def inclusive_date_strings(start_date, end_date):
    """Return every YYYY-MM-DD date in an inclusive range."""
    current_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    final_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    dates = []
    while current_date <= final_date:
        dates.append(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)
    return dates


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

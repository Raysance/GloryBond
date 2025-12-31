# HOK_QQBot API Manual

## 1. 核心模块

### 1.1 zapi.py (外部接口)

*   **`ai_api(user_query, temperature)`**
    *   **描述**: 调用 DeepSeek Chat 模型生成文本。
    *   **参数**: `user_query` (str, 提示词), `temperature` (float, 0.0-2.0)。
    *   **返回**: 生成的文本 (str)。

*   **`wzry_get_official(reqtype, userid=-1, roleid=0, ...)`**
    *   **描述**: 获取王者荣耀官方数据。
    *   **参数**: `reqtype` (str, 请求类型: "btldetail", "btlist", "profile", "season", "heropower", "allhero", "herostatistics", "heroranklist")。
    *   **返回**: JSON 数据 (dict)。

### 1.2 zfunc.py (功能函数)

#### 数据处理与分析
*   **`wzry_data(realname, savepath=None)`**
    *   **描述**: 获取指定用户的王者荣耀战绩和详情。
    *   **参数**: `realname` (str, 用户名), `savepath` (str, 可选保存路径)。
*   **`fetch_history(userid=None, start_date=None, end_date=None, filter_official=True)`**
    *   **描述**: 获取历史战绩数据。
*   **`ai_parser(user_query, msg_type, network=False)`**
    *   **描述**: 处理 AI 对话请求。

#### 业务流程处理 (Process Functions)
*   **`rnk_process(rcv_msg, caller=None, show_zero=True, show_analyze=False, debug=False)`**: 处理排行榜查询。
*   **`single_process(rcv_msg)`**: 处理单人今日战绩查询。
*   **`view_process(rcv_msg, time_gap=analyze_time_gap)`**: 处理战绩总览查询。
*   **`btldetail_process(gameSvrId, relaySvrId, gameseq, pvptype, roleid, ...)`**: 处理单局战绩详情。
*   **`heropower_process(realname)`**: 处理英雄战力查询。
*   **`recentgame_process(realname)`**: 处理最近比赛查询。
*   **`todayhero_process(realname, ignore_limit=False, ai_comment=True)`**: 处理今日英雄池分析。
*   **`allhero_process(realname)`**: 处理所有英雄数据查询。
*   **`gradeanalyze_process(realname)`**: 处理评分分析。
*   **`watchbattle_process(realname)`**: 处理观战请求。
*   **`coplayer_process(...)`**: 处理组队分析。

#### 统计分析
*   **`single_player_single_hero_process(username, heroid, heroname, this_season=True)`**: 单人单英雄分析。
*   **`single_player_mult_hero_process(username, days=30, top_n=3, min_games=2)`**: 单人多英雄分析。
*   **`mult_player_mult_hero_process(days=30, top_n=5, min_games=5)`**: 多人多英雄分析。
*   **`mult_player_single_hero_process(hero_id, hero_name, days=30, min_games=3, top_n=5)`**: 多人单英雄分析。

#### 工具函数
*   **`_to_pinyin(s)`**: 字符串转拼音。
*   **`create_website(contents, sitetype)`**: 生成网页内容。
*   **`online_process()`**: 获取在线状态。
*   **`file_exist(path)`**: 检查文件是否存在。

### 1.3 ztime.py (时间处理)

*   **`time_r()`**: 获取当前时间 (datetime 对象)。
*   **`date_r()`**: 获取当前日期 (字符串 "YYYY-MM-DD")。
*   **`time_sul(time_real=None)`**: 获取“熬夜时间”（将凌晨 3:30 前的时间算作前一天）。
*   **`date_sul(time_real=None)`**: 获取“熬夜日期” (字符串)。
*   **`stamp_to_time(timestamp)`**: 时间戳转 datetime。
*   **`str_to_time(time_str)`**: 字符串转 datetime。
*   **`time_to_str(time_datetime, format_str="%Y-%m-%d %H:%M:%S")`**: datetime 转字符串。
*   **`time_delta(time_in, delta)`**: 时间加减天数。
*   **`calc_gap(t1, t2)`**: 计算两个时间点的时间差（秒）。
*   **`wait()` / `short_wait()`**: 随机睡眠一段时间。
*   **`get_timebased_rand(n, rand_gap)`**: 基于时间的随机数生成。

### 1.4 utils.message_sender.py (消息发送)

*   **`add_msg(target, content, type='group')`**
    *   **描述**: 添加消息到发送队列。
    *   **参数**: `target` (int/str, 群号或QQ号), `content` (str/Message), `type` ("group"/"private")。

## 2. 变量系统

### 2.1 静态变量 (variables_static.json)
*可以直接通过 `from .zstatic import *` 使用*

#### 配置与 URL
*   **`wzry_url`**: 王者荣耀个人主页 URL。
*   **`deepseek_url`**: DeepSeek API URL。
*   **`ark_app_url` / `ark_model_url`**: 火山引擎 API URL。

#### 提示词模板 (Prompts)
*   **`single_pmpt1` / `single_pmpt2`**: 单人战绩评价提示词。
*   **`chat_pmpt`**: 聊天回复提示词。
*   **`ark_chat_pmpt`**: 豆包模型聊天提示词。
*   **`rnk_pmpt`**: 排行榜描述提示词。
*   **`poke_pmpt`**: 戳一戳回复提示词。
*   **`festival_pmpt`**: 节日祝福提示词。
*   **`fetch_news_pmpt`**: 获取新闻提示词。
*   **`urge_game_pmpt`**: 催促游戏提示词。
*   **`raise_question_pmpt`**: 游戏情境提问提示词。
*   **`skill_advantage_pmpt`**: 英雄推荐提示词。
*   **`diy_code_pmpt`**: 代码生成助手提示词。

#### 关键词与列表
*   **`HeroList`**: 英雄 ID 到名称的映射字典 (如 "105": "廉颇")。
*   **`HeroNames`**: 所有英雄名称列表。
*   **`rnk_keywords`**: 排行榜关键词 (["排行", "排名"])。
*   **`single_keywords`**: 战绩关键词 (["战况", "战绩"])。
*   **`atall_keywords`**: @全体成员关键词。

### 2.2 动态变量 (variables_dynamic.json)
*通过 `from . import zdynamic as dmc` 使用*

#### 缓存与状态
*   **`dmc.infolast`**: 用户上次查询的信息缓存 (dict)。
*   **`dmc.ai_memory`**: AI 对话历史记录 (list)。
*   **`dmc.today_news`**: 今日新闻缓存。
*   **`dmc.herorank`**: 英雄排行榜缓存。
*   **`dmc.rank_query_late`**: 排行榜查询延迟标记。

#### 战绩查询状态
*   **`dmc.LastBtlParams`**: 上次战绩查询参数。
*   **`dmc.LastBtlRoleId`**: 上次查询的角色 ID。
*   **`dmc.LastBtlMsgTime`**: 上次战绩消息时间。

#### 系统状态
*   **`dmc.use_mem`**: 是否使用 AI 记忆 (bool)。
*   **`dmc.amnesia`**: 是否遗忘模式 (bool)。
*   **`dmc.streamurl`**: 直播流 URL。

## 3. 数据库 (Redis)
*通过 `from . import zdynamic as dmc` 使用*

*   **`dmc.redis_deamon`**: 默认 Redis 连接。
*   **`dmc.redis_deamon_liked_btl`**: 点赞战绩集合。
*   **`dmc.redis_deamon_share_btl`**: 分享战绩队列。
*   **`dmc.redis_deamon_analyze_btl`**: 分析战绩队列。
*   **`dmc.MessageQueue`**: 消息队列。
*   **`dmc.TodayHeroPool`**: 今日英雄池。
*   **`dmc.redis_deamon_diy_code`**: DIY 代码存储 (DB 9)。

## 4. 示例代码

```python
from .zapi import ai_api
from .zfunc import wzry_data, time_sul
from .utils.message_sender import add_msg
from . import zdynamic as dmc
from .zstatic import HeroList

# 获取当前“熬夜时间”
current_date = time_sul().strftime("%Y-%m-%d")

# 获取英雄名称
hero_name = HeroList.get("105", "未知英雄")

# 调用 AI
response = ai_api(f"今天是{current_date}，介绍一下{hero_name}", 0.7)

# 发送消息
add_msg(123456789, response, "group")
```

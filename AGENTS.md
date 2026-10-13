# HOK_QQBot NBot — 子项目补充规范

本文件只记录 `NBot/` 子项目的目录职责、配置来源、调用边界和运行约定。通用代码规范、仓库边界、README 定位与 `.gitignore` 分层规则见根目录 `AGENTS.md`。

## 1. 目录与文件职责（`hok/`）

以下规则适用于 `hok/` 下所有代码。

- `hok/__init__.py`：NoneBot 插件入口；注册插件元信息并集中加载配置、静态变量、动态变量、API、事件、文件、业务函数、定时任务与时间工具。
- `hok/config.py`：Pydantic 配置模型定义；除非明确需要，否则不要新增依赖或复杂逻辑。
- `hok/zdynamic.py`：**动态变量**导入与初始化必须放在这里；其他模块通过 `from . import zdynamic as dmc` 读取动态配置初始值；运行时需要跨部署持久化的状态必须通过 Redis 业务接口保存。 新 QQ agent 的进程内服务引用 `qq_agent_service` 在此初始化，持久任务仍写 DB0。
- `hok/zevent.py`：NoneBot matcher 声明、注册及最薄处理器入口；只做初步解析、分发与调用接口，不实现具体业务算法。通用路由谓词放在 `event_rules.py`，群消息最初捕获放在 `event_ingress.py`，可独立测试的处理器解析与业务分发放在 `event_handlers/`；普通用户的“代表局”自然语言查询在此路由且必须以 `#` 或 `＃` 开头，正式回复不得附带调试信息；`##rep3` 仅供管理员按日期区间调试每日三类指数冠军；`#巅峰排名` / `#巅峰排行` 仅调用 `zfunc.py` 的本地结构化历史排名流程；`#梯度` / `＃梯度` 仅调用 `zfunc.py` 的梯度长图流程；消息中同时出现“战力”和“查询”时调用 `zfunc.py` 的指定地区荣耀战力查询流程，英雄名和地区名顺序不限；B 站 UP 视频订阅命令的剥离与业务分发由 `event_handlers/bili_video.py` 完成。
- `hok/event_rules.py`：不依赖 NoneBot 类型的消息路由谓词、用户权限和命令判定；不得注册 matcher 或发送消息。
- 本次消息直接包含 `at` 到机器人 `self_id` 且没有 `#` / `＃` 前缀时，`zevent._direct_chat` 在业务关键词路由前调用同一 AI 处理器；检查适配器保留的 `original_message`，不能用引用、昵称或 `to_me` 推断直接提及。前缀命令继续按原路由处理；管理员命令也必须来自本次前缀文本。直接提及沿用相同的 QQ 白名单、禁用检查、休眠与维修规则，不因「在线」「战力查询」等词落入旧业务命令。
- `hok/event_ingress.py`：群消息进入业务路由前只保存一次原始归档，绑定用户、群号、消息及引用 ID；保存失败只记录错误，不阻断路由。没有被动聊天缓存或摘要写入。
- `hok/event_handlers/`：不注册 matcher、不导入 NoneBot 适配器的处理器解析与业务分发；当前包含英雄查询与视觉产物、玩家战报/排行、实时对局预言、历史战绩查询、管理员历史导出、代表局查询/调试、底蕴与时长查询、AI 聊天输入、表情生成、戳一戳决策及 B 站订阅命令处理器，返回文本、消息序列或结构化结果给 `zevent.py`，消息发送和 `MessageSegment` 拼装仍留在入口/出口层。历史导出命令解析、逐用户调用和失败汇总由 `event_handlers/history_export.py` 完成；代表局普通查询、单日调试信息和区间调试结果由 `event_handlers/representative.py` 归一化；玩家在线状态、群体排行、单人战报及最近单局、战绩视图与上次详情由 `event_handlers/player_reports.py` 分发；英雄战力、今日英雄参数、评分图与观战截图由 `event_handlers/hero_visuals.py` 分发；实时对局查询、五分钟缓存与预言计算参数由 `event_handlers/spoiler.py` 管理；底蕴/时长的个人与排行分流由 `event_handlers/activity.py` 完成；聊天文本替换、记忆开关、用户和群消息元数据（不再解析 `&`）由 `event_handlers/chat.py` 归一化；表情模板、提示词及图片参数由 `event_handlers/emoji.py` 解析并调用生成工具；戳一戳的观战截图、底蕴触发、冷却及随机回复由 `event_handlers/poke.py` 决策；历史查询的单局图片组合仍由 `zevent.py` 完成，多局网页产物由 `zfunc.py` 编排。
- QQ 入口绑定真实发送者 QQ、当前群、消息 ID 与输出目的地，不采用网页默认 example_user_10 身份。群请求只能读取当前群；仅可信入口确认发送者等于 `QQBot.super_qid` 的管理员私聊具有跨群范围。普通私聊无群聊权限。模型不得修改身份、授权或任务目的地；群检索按 `(group_id, message_id)` 排除当前群消息，私聊消息 ID 不用于排除群聊。SQL 使用共享目录动态生成并整批只读校验；不改业务数据库 schema、不回退业务写账号。
- `hok/zfile.py`：文件/IO 读写统一入口；所有 IO（读写文件、落盘缓存、路径拼接、动态变量重载等）必须通过此模块提供的接口完成；荣耀战力地区树统一从 `data/honor/districts.json` 读取；历史日期枚举与每日数据读取通过此模块转发到 PostgreSQL，数据库异常时才读取应急 JSON；网页历史 JSON 的路径构造与写入也统一由此模块负责；梯度英雄头像属于长期资产，按英雄 ID 与头像 URL 指纹保存在 `resources/wzry_images/hero_avatars/`，`file_transfer/` 只保存每次查询重新生成的梯度长图；HOK Exception 运行时错误记录统一追加到 `log/error.log`；生成 Python 和绘图执行由外部共享沙箱负责，此模块只处理最终产物 PNG 校验、落盘、合图及公开路径。 `store_agent_artifact()` 校验独立 worker 返回的图片字节并保存为 trace 兼容 PNG；图片 IO 不放入内核。
- `hok/zdb.py`：PostgreSQL 业务数据访问入口，维护结构化游戏历史、群聊归档和导入清单。群聊以 `(group_id, message_id)` 幂等保存，`group_chat_messages` 私有表与 payload 不向模型披露。模型只读 SQL 由外部 worker 使用独立 `hok_chat_reader` 与 `shared/agent` 目录执行；业务写账号不用于模型查询。`load_group_chat_messages` 的可选 `user_id` 为入口绑定的参数，用于表情包最近发言，不接受模型生成 SQL。
- `hok/zfunc.py`：业务门面、跨领域编排与 Redis 业务访问入口。`agent_runtime_start/stop`、`agent_chat`、`agent_task_tick`、`agent_clear_memory` 和 `agent_register_tool` 接入共享外部 agent；消息与产物分别通过 message_sender 和 zfile 发送/落盘。群聊历史写入 zdb，失败才保存 DB0 应急 list；读取时 SQL 重复项为准，Redis 原数据在迁移验证前不得删除。`ChatHistoryMaxMessages` 仅限制应急 list。`recent_emoji_messages` 读取当前群当前发言者的归档及应急消息，`emoji_message_state` 保存 `hok:emoji:*` 下的短期表情决策/去重缓存；不再保存额外被动聊天或摘要。游戏 API 优先级、其他业务 Redis 状态及跨领域编排继续由此门面管理。
- `hok/business/`：按领域拆分的不含 Redis、NoneBot、直接 HTTP 和直接文件读写的业务实现；当前包含用户辅助、AI 文案组装、每日战报、代表局、结构化历史读取、历史自然语言查询、荣耀战力地区解析、英雄资料、英雄统计、今日英雄推荐、玩家战绩采集、单人战报、战绩分析视图与单局详情、观战协议转换、共玩/底蕴分析、单局历史与统计分析、游戏时长统计、对局指标、玩家在线状态、玩家视觉产物、群体排行、战绩可见性状态计算、网页产物标识与路由规则、B 站订阅流程及 KPL 推送流程。问候、QQ 身份映射、表情选择、URL 参数和巅峰分段解析由 `business/user_helpers.py` 实现，表情配置读取仍通过 `zfile.py`，AI 选择仍通过 `zapi.py`；游戏业务文案的提示词组装与标准/联网适配器选择由 `business/ai_prompts.py` 实现，实际请求只调用 `zapi.py`；每日战报的排行正文与代表局文字、图片、AI 文案顺序由 `business/daily_notification.py` 组装；结构化历史的 PostgreSQL 优先读取与 JSON 应急聚合由 `business/history_data.py` 实现，目录枚举和文件读取仍通过 `zfile.py`；需要调用其他业务能力时通过运行时导入 `zfunc.py` 的公开接口，避免形成模块导入环。`representative_battle_query_impl()` 必须隔离正式文字、图片路径、图片下方 AI 文案与调试载荷；`representative_battle_range_debug_impl()` 只组装每日三类指数冠军的纯文本区间调试结果。英雄战力列表与常用英雄摘要由 `business/hero_profiles.py` 实现；英雄名安全解析、拼音转换及天元之弈梯度 API、头像缓存和长图编排由 `business/hero_tier.py` 实现；英雄统计实现只负责结构化统计与文字组装；今日英雄的候选选择、推荐依据和文案组装由 `business/today_hero.py` 实现，Redis 当日缓存与历史列表只通过 `zfunc.py` 的窄接口读写，皮肤和技能资产只通过 `zfile.py` 访问；战绩分析视图与单局详情的文本、网页载荷和图片生成编排由 `business/battle_detail.py` 实现；观战接口到共玩分析结构的严格转换及对局预言编排由 `business/battle_watch.py` 实现；单局详情读取时的目标玩家视角重建及历史胜率、英雄、受益度、交集统计由 `business/battle_history.py` 实现；共玩/底蕴数值计算、阵营汇总、图片载荷与历史记录对象由 `business/battle_power.py` 实现，评估记录的 Redis 写入仍通过 `zfunc.py`，文件路径与读写仍通过 `zfile.py`；王者与 Steam 最近时长汇总、群体排行和局部错误聚合由 `business/game_activity.py` 实现，Steam 请求只调用 `zapi.py`，图表路径只由 `zfile.py` 提供；英雄阵容对位的精确/分路回退统计与可选 AI 短评由 `business/battle_matchup.py` 实现；正式对局判定、评分均值与团队贡献系数统一由 `business/battle_metrics.py` 实现；玩家战绩列表与资料拉取、当日结构化转换、技能缓存补齐、单局详情补拉及指定用户回填由 `business/player_data.py` 实现，API 通过 `zfunc.py` 的优先级门面调用，路径与写入通过 `zfile.py`；单人当天与历史战报的日期解析、数据选择和文本组装由 `business/player_report.py` 实现；评分趋势图与观战截图流程由 `business/player_visuals.py` 实现，输出路径只由 `zfile.py` 提供；群体排行的并发采集、榜单展示、遍历错误格式化及本地巅峰排名由 `business/rankings.py` 实现；王者与 Steam 在线状态的并发遍历、分组展示和局部失败聚合由 `business/online_status.py` 实现；战绩可见性的关联 QQ 解析与禁用名单状态迁移由 `business/battle_visibility.py` 实现，Redis 读写、日志和禁言任务编排仍保留在 `zfunc.py`；网页产物的 hash、路由映射和元数据组装由 `business/web_artifacts.py` 实现，Redis 发布仍通过 `zfunc.py`，文件路径与写入仍通过 `zfile.py`；B 站订阅解析、身份更新、最新视频与轮询推送流程由 `business/bili_video.py` 实现，订阅存储、去重集合、分布式锁和消息出口仍通过 `zfunc.py`；KPL 比赛筛选、图片提示词和推送流程由 `business/kpl.py` 实现，推送锁与已推送集合仍通过 `zfunc.py`，图片落盘通过 `zfile.py`，消息拼装与发送通过 `utils/message_sender.py`。
- `hok/zscheduler.py`：所有定时/间隔任务的声明、注册与定义（不要在别处私自创建 scheduler 任务）；旧版凌晨 03:30 的 `daily_user_summary` 已停用，禁止重新注册会清理原始聊天记录的摘要任务；每日 23:30 的 `notify_msg()` 统一发送当日王者战报，并按“代表局文字 → 图片 → AI 文案”的顺序发送代表性对局；网页底蕴分享保留阵容 AI 短评参数，当前以 `False` 禁用；B 站 UP 新视频轮询任务只在此注册，实际检查与推送编排调用 `zfunc.py`。 QQ agent 启停 hook 与任务 tick 只在此注册；外部任务服务只领取/执行已持久化任务，不另建轮询循环。
- `hok/zstatic.py`：**静态变量**导入必须放在这里（从文件与系统环境变量导入）；其他模块通过 `from .zstatic import *` 获取静态变量。
- `hok/ztime.py`：时间工具与日期处理统一入口；任何时间计算、格式化、时间窗口判断都应调用这里的接口；代表局查询中的自然语言日期及区间统一由 `parse_representative_battle_date()`、`parse_representative_battle_date_range()` 解析，群聊历史检索时间边界统一由 `parse_chat_time_bound()` 解析。
- `hok/zutil.py`：基础工具集；统一导入常用库与通用小工具（不要在各处散落重复 import 与重复工具实现）。
- `hok/utils/message_sender.py`：发送消息统一入口；任何对外消息发送必须调用此模块的函数接口（禁止绕开直接调用底层适配器发送）。
- `hok/zapi.py`：外部 API 的兼容门面，从 api_adapters 导出业务函数。业务文案只使用单轮文本/图片接口；不提供第二套 agent 的工具或 Responses 编排入口。QQ 与网页模型协议由 `agent_console/provider.py` 适配，多轮编排由独立内核负责。
- `hok/api_adapters/`：按外部服务封装协议、签名、响应解析与重试；不读取 Redis。业务 AI 文案使用已配置 ChatAPI 单轮文本接口，图片与原有 Ark 文案接口继续保留。agent 的 DeepSeek 工具链与原生图片在外部 provider 处理，统一关闭工具链 thinking。阿里云 OpenSearch 与官方游戏请求显式禁用环境代理直连，Steam/APIMart 经配置的 Clash 代理，缺少代理时不回退直连。
- `hok/zkpl.py`：KPL 数据统一入口；仅 `get_match_list_json()` 与 `get_match_detail_json()` 负责获取赛程和完整比赛数据，其他 KPL 转换与兼容接口必须调用二者。
- `hok/zdiy.py`：自定义/临时扩展的业务能力聚合处；当能力稳定后应迁移到职责更明确的模块（`zfunc.py` / `tools/` / `zapi.py` 等），避免长期堆叠。

HOK_QQBot 与 Web 的全部 Redis 数据统一存放在 `REDIS_DB`（DB0），以 `hok:` 为根命名空间；独立 Planit 应用继续使用 DB9。`zdynamic.py` 只创建一个 DB0 Redis 客户端，历史兼容别名必须指向同一客户端，不得再连接 DB1–DB7 或 DB10。Key 使用冒号分层命名并由 `zstatic.py` 暴露共享常量，例如 `hok:web:artifact:<token>`、`hok:battle:liked_ids`、`hok:queue:*`、`hok:hero:*`、`hok:evaluator:*`、`hok:chat:*` 与 `hok:memory:*`。跨 DB 收敛统一通过 `scripts/consolidate_redis_to_db0.py` 执行，正式执行前必须生成可恢复的 DUMP 备份。

### 1.0 Chat 回复、引用与运行记录

- `event_handlers/chat.py` 解析本次显式引用与原生图片 URL，支持原生消息段及 CQ 字符串；引用优先取 `event.reply`，缺失时由注入的 OneBot `get_msg` 补读一次，不递归拉取。引用中的开头 `#` / `＃` 和机器人 @ 去除，其余内容仅作为资料，不参与命令路由或 `nomem` 解析。引用作用域/消息 ID 校验失败时不提供原文或媒体。QQ 外部适配器验证引用图片和直接图片后提供原生内容块；视频等未读取媒体保留明确占位符。两类图片合并去重后共用单次图片数量/体积预算。
- `zevent.f_chat()` await `zfunc.agent_chat()`；所有分段输出、最终答案和后台通知由注入的 QQOutput 发往 `utils/message_sender.add_chat_result_msg(destination=...)`，入口不再重复发送最终结果。后台目的地与身份在创建任务时绑定。
- QQ 回复保留详细事实底稿和角色群聊版，默认发送群聊版，明确请求详细/完整内容时发送详细版。两版都通过 `normalize_qq_text()` 与 `format_chat_reply()` 清理 Markdown 和内部玩家/身份标识；图表标签与正文使用配置昵称。直接对话历史仅保存实际发送的一个版本。阶段性 `emit_message` 独立入队。
- QQOutput 将内核模型/工具事件、真实 payload、两个回复版本和用量投影为现有 `chat_trace` v1；失败保留已完成 observation。原始事件与图片引用另外持久保存到 `log/qq_agent/<会话>/runs/<run_id>.jsonl` 和 `dialogue.jsonl`，不记录 HTTP headers，凭据脱敏。输入原图默认保存在非公开 `data/agent_inputs/`；日志和原图不进 Git 或部署包。
- `zfunc.chat_prepare_reply()` 合并图表并发布运行记录；合图失败保留原图，发布失败保留正常回答。`zfile.combine_chat_plot_images()` 默认两列合图。`chat_publish_trace()` 使用共享 `WebArtifacts.make_hash()` 生成 16 位随机 hex，写 DB0 `hok:web:artifact:<token>`，TTL 默认 7 天；网页 `/chat-trace?key=...` 接受新 16 位 key，已有 48 位链接保留至自然过期。输出 PNG 为 `chat_plot_<32位hex>.png`，遵守现有产物清理周期。
- QQAgent 预算与输入/输出规则统一来自 `config.yaml#QQAgent`；默认 10 轮、16 次工具、300 秒、4 张输入图片。工具执行仍要求每个调用产生 observation，渐进披露与授权由共享注册表控制。

### 1.1 Tools（`hok/tools/`）

`hok/tools/` 目录用于放置可复用、可抽象的“工具”模块：

1. **可封装的函数视为工具**：例如编码/解码、图表生成、数据格式转换、外部 API 适配器等，应当在 `tools/` 下单独建文件。
2. **工具模块要求**：
   - 导入即执行的副作用必须最小化（禁止 import 时自动发请求/写文件/注册任务）。
   - 对外只暴露明确的函数/类接口，不要把业务编排写进工具模块。
   - 工具所需的配置与常量从 `zstatic.py`/`zdynamic.py` 获取，不要在工具里散落路径与 key。

命名建议：

- 工具文件以动词或名词短语命名，避免 `tmp.py`、`test2.py` 这类不可维护命名。
- 若工具围绕某一类产物生成（如战报图、统计图），建议使用 `gen_*.py` 前缀并保持输入输出一致。

当前工具文件职责索引：

- `hok/tools/chat_text.py`：使用 `markdown-it-py` 将模型 Markdown 解析为 QQ 纯文本，去除标题、强调、引用、代码围栏和链接语法，表格转为字段值行，保留代码和数学中的字面符号；`format_chat_reply()` 接收配置昵称及身份映射，只处理最终纯文本中的内部玩家键与身份字段，普通词语、统计数值和公开链接保持原样。
- `hok/tools/endecoder.py`：王者营地接口加解密与请求参数生成工具。
- `hok/tools/emoji_renderer.py`：emoji 文本拆分与图片文字渲染辅助。
- `hok/tools/gen_battle_res.py`：单局战绩详情长图生成器。
- `hok/tools/gen_battle_shot.py`：RTMP 监听与对局截图工具。
- `hok/tools/gen_coplayer_analyses.py`：共玩关系、头像、胜率、评价等图表生成器。
- `hok/tools/gen_emoji_image.py`：表情包生成链路与模板；仅通过 `tools/emoji_context.py` 读取当前群的本人发言及表情决策缓存，不加载旧聊天记忆/摘要，Redis 与归档访问经 zfunc。
- `hok/tools/gen_gametime_table.py`：游戏时长表格聚合与渲染辅助。
- `hok/tools/gen_grade_chart.py`：评分/星数趋势图生成工具。
- `hok/tools/gen_hero_tier.py`：天元之弈英雄梯度数据按网页版梯度分层、临界区和英雄头像布局生成可视化长图。
- `hok/tools/kpl_match_collector.py`：历史 KPL 采集兼容入口，仅转发到 `zkpl.py`。
- `hok/tools/gen_kpl_match_card.py`：KPL 总比分、总体评分及全部小局数据长图生成器。
- `hok/tools/representative_battle.py`：基于战绩 JSON 的代表性对局候选过滤、优秀/糟糕/极端三类指数计算与确定性排序工具。
- `hok/tools/PowerAnalyzeEvaluator.py`：战力分析结果一致性评估脚本。

### 1.2 Debug Tools（`hok/debug_tools/`）

`hok/debug_tools/` 仅用于**调试工具脚本**与实验性验证；上线逻辑不得长期停留在此目录。调试工具必须以文件夹为单位组织，每个调试目标对应 `debug_tools/` 下的一个独立文件夹，文件夹内再放置该调试工具的具体脚本、测试数据、样例输入输出等内容。调试脚本应模块化、最精简地调用项目中已有函数，不得复制业务实现或绕开项目既有接口。

调试工具的 CLI 规范与现有工具说明维护在 `hok/debug_tools/AGENTS.md`。总索引只记录 `hok/debug_tools/` 作为调试工具目录，不在根规范中逐项记录脚本或函数功能。

### 1.3 Local Debugger（`local_debugger/`）

`local_debugger/` 是根目录共享本地调试器运行时，用于供 `hok/debug_tools/` 下的调试脚本复用本地导入环境。它只负责准备项目根目录导入路径、必要环境变量、缺失的 import-time 依赖占位，以及绕过 `hok/__init__.py` 的模块导入入口；不得承载线上业务逻辑、不得发起外部请求、不得替代 `hok/` 内已有业务接口。

本地调试依赖固定保存在被 Git 忽略的 `local_debugger/.venv/`。Codex Desktop 与本地开发会话运行调试脚本时必须优先复用 `local_debugger/.venv/bin/python`；环境不存在时运行 `python3 local_debugger/setup_env.py` 创建，或通过 `python3 local_debugger/run.py <脚本> [参数...]` 自动创建并执行。只有 `pyproject.toml` 依赖发生变化或虚拟环境损坏时才重新同步，不得因切换 session 重复创建临时环境或重复安装依赖。

### 1.4 PostgreSQL 数据目录与迁移脚本

- `database/chat_readonly.sql`：幂等创建 `hok_chat_reader`、十张游戏表的显式列授权及群聊安全视图的显式列授权，不包含密码、不修改业务数据；必须先应用最新 `database/schema.sql` 创建视图，配置与使用见 `database/CHAT_AGENT.md`。
- `database/schema.sql`：结构化历史库的 schema、表、外键与查询索引。
- `scripts/import_json_to_postgres.py`：幂等回填入口；只读扫描原始 JSON，并通过文件大小与纳秒 mtime 清单跳过未变化文件。
- `scripts/migrate_group_chat_history_to_postgres.py`：将 DB0 `hok:chat:group:*` 幂等迁移到私有群聊表；默认只预览，`--apply` 必须先生成 0600 DUMP 备份，逐消息验证 SQL 结果并保留 Redis 原数据。

### 1.5 部署运行方式

- 部署服务器上的 NoneBot 进程由 `hok-nbot.service` 统一管理，禁止在发布流程中再使用 `nohup` 或按端口手工结束进程。
- `deployment/` 是跨 Linux 主机部署包：`systemd/` 保存可渲染单元，`nginx/` 保存反向代理模板，`scripts/` 提供安装、检查与 bundle 构建，`bin/` 保存服务启动包装器；不得再生成独立 env/example/JSON 配置模板；调整该结构时必须同步维护 `deployment/README.md`。
- Aliyun 整机部署以 `/srv/modules/{hok,personal-site,clash}` 为三个应用模块；每个模块维护 `module.json`、`apps/`、`config/`、状态/日志、`systemd/`、`nginx/` 和 `ops/`。HOK 的物理代码路径为 `hok/apps/{NBot,Web}`；BotDemo、Lagrange 与旧 NapCat installer 已在完整导出和 Git bundle 备份后移除，HOK 不再依赖 `/QQBot` 下的兼容入口。
- 三个统一入口为 `hok.target`、`personal-site.target` 与 `clash.target`，子服务用 `PartOf=` 归属模块，原服务名称保留供 CI 单独重启。Nginx、Redis、PostgreSQL、证书和 Actions runner 是共享基础设施，不随模块停止；个人网站 target 停止 OAuth/API 后，静态页面仍由共享 Nginx 提供。
- `deployment/server_modules/` 保存服务器迁移、带回滚日志的目录整理、模块管理及私有导出工具；HOK 导出只抓取 HOK PostgreSQL 库和 Redis DB0 的 `hok:*`，不得混入 PlanIt DB9。导出包含密钥和 QQ 会话，必须使用私有权限与 SSH 传输。
- `/opt/hok-qqbot/{nbot,web}`、`/etc/hok-qqbot`、`/var/lib/hok-qqbot` 与 `/var/log/hok-qqbot` 是独立的全新 HOK 安装模板布局，不是现有 Aliyun 模块的实际路径；新主机恢复细节见 `deployment/server_modules/README.md`。
- GitHub Actions 在 `/srv/modules/hok/apps/NBot` 完成代码同步后通过 `systemctl restart hok-nbot.service` 发布，并以 `systemctl is-active` 验证启动结果。
- 新版 `deploy_runner.sh` 默认调用项目内 `.venv/bin/nb`，允许主机级 `HOK_NB_BIN` 覆盖；代理、CLI 路径和服务目录由 systemd 单元与项目两个配置文件注入，不得再增加 `nbot-host.env` 等分散配置。既有运行日志通过 `log` 链接进入 `hok/logs/nbot`，新装模板进程输出进入 journald，HOK Exception 仍写入配置的错误日志目录。

## 2. 配置与变量的来源（必须遵守）

### 2.1 配置文件

- `.env`：唯一的密钥文件，仅保存 API key、token、密码、数据库 DSN 等凭据，另保留 NoneBot 启动必需的 `ENVIRONMENT` 和 `DRIVER`。本仓库为私有仓库，该文件允许提交 Git，但日志、诊断和分享页仍必须脱敏。不得再新增 `.env.local`、`*.env.example` 或其他密钥文件。
- `config.yaml`：唯一的非密钥配置文件，统一保存服务端点、模型、代理、超时、查询限制、Redis、NapCat、稳定变量与动态初始值。原 `variables_static.json` 并入 `StaticVariables`，原 `variables_dynamic.json` 并入 `DynamicVariables`。不得再新增 `config.yaml.example`、`redis.json` 或其他应用配置文件。
- `AliyunSearch` 在 `config.yaml` 中保存 endpoint、workspace、service ID、内容类型、搜索策略与 query rewrite；API key 仅放在 `.env` 的 `HOK_ALIYUN_SEARCH_API_KEY`。

原则：
1. **任何可能变化的值**不得硬编码在业务逻辑里，必须进入上述文件或对应的静态/动态变量模块。
2. `zstatic.py` 负责加载静态配置；`zdynamic.py` 负责加载动态配置初始值，不作为运行时持久化写入入口。
3. 部署环境只可通过 `HOK_ENV_FILE` 覆盖密钥文件路径，通过 `HOK_CONFIG_FILE` 覆盖非密钥配置路径；未设置时读取 `BOT_PATH` 下的 `.env` 与 `config.yaml`。

### 2.2 Linux 环境变量（在 `hok/zstatic.py` 导入）

部署环境下预计存在以下环境变量（缺失时的处理策略以现有代码为准，禁止凭空新增“变量不存在”的冗余判断链）：

- `BOT_PATH`：Bot 部署目录。
- `HOK_ENV_FILE`：可选的密钥 dotenv 路径；未指定时加载项目 `.env`。
- `HOK_CHAT_BASE_URL`、`HOK_CHAT_API_KEY`、`HOK_CHAT_MODEL`、`HOK_CHAT_PROXY_URL`：覆盖 `config.yaml` 的 `ChatAPI` 对应字段，由 `zstatic.py` 统一导入为 `chat_api_config`；显式空 `HOK_CHAT_PROXY_URL` 必须覆盖文件中的代理并表示直连，客户端仍禁止继承环境代理。
- `HOK_ALIYUN_SEARCH_API_KEY`、`HOK_ALIYUN_SEARCH_ENDPOINT`、`HOK_ALIYUN_SEARCH_WORKSPACE`、`HOK_ALIYUN_SEARCH_SERVICE_ID`、`HOK_ALIYUN_SEARCH_CONTENT_TYPE`、`HOK_ALIYUN_SEARCH_WAY`、`HOK_ALIYUN_SEARCH_QUERY_REWRITE`：可选覆盖 `.env` 私有载荷或 `AliyunSearch` 公共默认值，由 `zstatic.py` 统一导入为 `aliyun_search_config`；请求始终直连且禁用环境代理。
- `HOK_CHAT_READONLY_DSN`：专用 `hok_chat_reader` 连接串，必须通过私有环境文件注入；`AgentSQL` 管理查询限制，`AgentPlots` 管理共享字体与 QQ 合图布局。
- `HOK_CLASH_PROXY_URL`：覆盖 `config.yaml` 的 `Proxy.clash_url`，由 `zstatic.py` 导入为 `clash_proxy_url`；Steam 与 APIMart 当前默认使用 `http://127.0.0.1:7890`，也支持 `socks5h://127.0.0.1:7891`。
- `HOK_CONFIG_FILE`：可选的非密钥配置路径；未指定时加载项目 `config.yaml`。
- `HOK_DATA_DIR`：应急 JSON、地区树和每日数据的持久目录；默认 `BOT_PATH/data`。
- `HOK_FILE_TRANSFER_DIR`：NBot 与 Web 共享的公开产物目录；默认 `BOT_PATH/file_transfer`。
- `HOK_LOG_DIR`：NBot 文件日志目录；默认 `BOT_PATH/log`。

项目根目录统一使用全局变量 `BOT_PATH` 的绝对路径，通过 `hok/zstatic.py` 的 `project_root` 暴露给其他模块；数据、Web 静态产物与日志分别通过 `data_root`、`temp_path`、`log_root` 暴露，不再从 `NGINX_HTML` 或进程当前目录推断部署状态。

## 3. 代码结构与改动边界

1. **入口与路由**：`zevent.py` 仅做“接收 → 解析 → 选择接口 → 调用”，不承载业务细节。
2. **流程编排**：业务流程（多步调用、拼装文本/图片/数据）写在 `zfunc.py`，并保持接口可被 `zevent.py` 直接调用。
3. **状态与缓存**：
   - 动态配置初始值：统一放在 `zdynamic.py`（通过 `dmc.xxx` 访问）。
   - 运行时需要跨部署持久化的业务状态：统一放 Redis，并通过 `zfunc.py` 暴露业务接口访问。
   - 静态映射/常量：统一放在 `zstatic.py`。
   - 历史查询数据：PostgreSQL 为主查询源和主写入目标；完成全量 payload 校验与数据库备份后，可清理 `data/history/`、`data/herotier/` 与 `data/herorank/` 下已迁移 JSON。数据库写入失败时，`zfile.py` 才写入同路径应急 JSON，供恢复与补录。
4. **IO 与时间**：IO 一律走 `zfile.py`；时间一律走 `ztime.py`。
5. **发送消息**：所有对外消息发送必须走 `utils/message_sender.py`，用于统一出口与后续可观测性。
6. **运行日志**：服务标准输出统一进入 systemd journal，HOK Exception 错误日志统一写入 `HOK_LOG_DIR/error.log`；运行时日志目录不纳入 Git。
7. **架构规范同步**：每次升级项目、调整目录职责、改变调用链或修改项目架构时，必须同步更新本 `AGENTS.md`，确保后续 AI 与开发者读取到的架构规则始终与当前项目一致。

### 3.1 Git 发布规则

通用规则：

1. Git commit message 必须使用英文，不得使用中文提交信息。
2. 一个完整的逻辑变更应形成一个语义清晰的最终提交；禁止 `A backup`、`Update config`等无法说明变更目的的泛化提交信息。
3. 发布前必须先同步并确认 `origin/main` 的最新状态；禁止通过多层 merge commit 解决本可避免的历史分叉。

#### 3.1.1 Codex Desktop / 本地开发

1. 代码变更一律直接在 `main` 完成，禁止新建、切换或推送功能分支，禁止创建 Pull Request。
2. 开始改动和推送前先执行等价于 `git pull --ff-only origin main` 的快进同步；如本地与远程已分叉，必须停止发布并先查明原因，不得自动创建 merge commit。
3. 当用户要求“推送远程”或类似发布动作时，必须直接提交并推送 `origin/main`。
4. 每轮对话产生的代码或文档变更必须独立提交一个 commit，不积攒到后续轮次；只提交本轮授权范围内的变更，不混入用户或其他任务的未提交修改。未要求推送时只提交本地。

#### 3.1.2 Codex Cloud

Codex Cloud 无须遵守本节的任何 Git 规范；本文件不规定 Codex Cloud 的 Git 操作方式。

### 3.2 库导入边界（严格）

1. **NoneBot 与机器人适配器**：与 NoneBot、机器人事件、消息段、适配器、bot 实例操作相关的库，只能在 `zevent.py`、`utils/message_sender.py` 等顶层消息入口/出口脚本中导入和使用；业务层不得直接导入。
2. **Redis 交互**：与 Redis 连接、读写、缓存交互相关的库，只能在 `zfunc.py` 中导入和使用；其他模块需要 Redis 数据时必须通过 `zfunc.py` 暴露的业务接口获取。
3. **AI 与 HTTP API**：与 OpenAI、AI API、`requests` 等外部 HTTP/API 请求相关的库，只能在 `hok/api_adapters/` 中导入和使用；`zapi.py` 只做兼容导出，业务流程只调用 `zapi.py` 的公开接口。协议适配器不得访问 Redis、文件系统或消息发送接口；API 错误日志如需落盘，仅通过 `zfile.py` 的明确接口完成。
4. **时间处理**：`time`、`datetime`、时区、日期解析与时间窗口判断相关库，只能在 `ztime.py` 中导入和使用；其他模块必须调用 `ztime.py` 的时间工具接口。
5. **IO 与路径处理**：文件读写、目录创建、路径拼接、缓存文件操作等 IO 相关库，只能在 `zfile.py` 中导入和使用；其他模块必须通过 `zfile.py` 接口完成 IO。
6. **PostgreSQL 交互**：`psycopg`、SQL 执行和数据库连接只能在 `zdb.py` 中使用；`zfile.py` 负责为现有文件接口提供数据库优先与 JSON 回退，业务层调用 `zdb.py` 或 `zfile.py` 的明确接口。
7. **例外处理**：如用户明确提出突破上述导入边界，必须质疑用户，如果确认无误，先调整模块职责并同步更新本 `AGENTS.md`，不得在业务代码中临时绕开。

## 4. NBot 异常提示出口

1. 需要向用户反馈的异常必须通过 `utils/message_sender.py` 或既有消息发送接口输出。
2. 异常提示应包含发生位置、关键参数、`repr(e)`/`str(e)`，便于在群聊或日志中检索。
3. 仅面向本地调试的脚本可只输出到调试终端，但不得混入线上业务路径。

## 5. NBot 代码习惯

1. 优先复用项目内现有命名、结构与导入方式，例如 `from .zstatic import *`、`from . import zdynamic as dmc`。
2. 用户可见文本（群消息、提示语）必须可检索、可定位，避免“只有一个笼统的失败”。
3. 单人单英雄查询默认复用 `single_player_single_hero_process()` 的本赛季统计分支，起始日期使用 `this_season_start_date`；消息路由不得因未包含“本赛季”关键词而覆盖此默认值。

## 6. NBot 变更自检清单

1. 新增代码是否放在了职责正确的 `hok/` 模块中？
2. 是否所有 IO、时间、消息发送都走了指定模块？
3. 是否遵守了 NoneBot、Redis、OpenAI/requests、time、IO 相关库的导入边界？
4. 是否需要同步更新本文件或更深层目录的 `AGENTS.md`？

## 7. 独立 Agent 内核与本地可视化适配层

- `vendor/react-agent-runtime/` 是私有仓库的 Git submodule，固定到父仓库记录的 commit；`agent_runtime` 仅为指向其 `src/agent_runtime` 的源码兼容软链接，不复制实现。独立安装使用 `pip install ./vendor/react-agent-runtime`。内核是独立、可安装的 Python 包；只依赖注入的模型、状态、输出、时钟与能力接口，不导入 `hok`、NoneBot 或应用配置，不自行连接数据库、Redis、SSH 或 HTTP，不实现 UI。
- `agent_runtime/core/` 管理有预算的 ReAct 循环、通用上下文和授权；`tools/` 仅管理注册、参数校验与执行协议；`runtime/` 仅管理结构化事件。内核不得包含具体工具名称、类别、实现、SQL 方言/schema、参考目录或群聊身份字段，也不得识别具体工具结果中的 SQL 行结构。每个工具调用必须有对应 observation。运行记录与模型可见的截断 observation 分别保存。
- 工具的初始披露、动态描述、结果投影均由外部注册信息注入；通用 `Principal.attributes` 只承载可信适配器提供的扩展属性，其业务含义由适配层解释。`ToolContext.resources` 只管理本次执行的通用资源引用，具体数据集结构由工具维护。独立包只依赖 Pydantic，不依赖 SQL 解析器或业务服务。
- `RunRequest.metadata` 是调用方提供的通用事件元数据，内核仅透传和快照，不解释任务、渠道或业务字段。适配层用它区分后台输出，避免后台通知占用前台输入/停止状态。
- `RunRequest.context_messages` 为仅本轮可见的 user 角色补充资料，支持文字及原生内容块，不允许 system/assistant/tool 或工具调用字段；在工具循环和运行记录中保留，直接对话保存不含这些资料。QQ 引用通过此接口输入，不能放在 system prompt，也不能改变身份和权限；内核不识别引用、QQ 或来源字段。
- `agent_console/` 是外部本地适配器，允许在此封装 FastAPI、SSH、HTTP、时间及 IO；这是独立包接入层，不适用上文针对 `hok/` 的具体模块导入边界。UI 仅消费内核事件；`qq_agent/` 同为外部适配器，复用同一 `AgentRuntime`、工具和角色服务，不导入 Web server。QQ 的网络、进程、时间及 IO 封装也不适用 `hok/` 内部导入边界。
- `examples/independent_agent.py` 演示通用调用方如何提供模型、内存状态、输出和标准时钟，不导入 HOK 或连接外部服务；示例适配器的标准库使用同样不适用 `hok/` 的导入边界。
- `agent_console/remote_worker.py` 支持两种相同的 RPC 传输：网页用 SSH 临时执行，QQ 在部署服务器上使用 ProcessBridge 启动本地子进程。均不修改业务数据库 schema。SSH 模式读取服务运行进程环境；QQ worker 继承当前进程环境并读取现有 `.env` / `config.yaml`，从服务器实际源码提取 API 适配函数。凭据只保留在适配器内存，不写新密钥文件、不返回浏览器。
- `agent_console/tools/` 定义应用的具体工具、PostgreSQL AST 校验和参考数据查询；应用提示词由 `agent_console/capabilities.py` 组装，持久任务到通用请求的转换由 `agent_console/tasks.py` 完成。聊天和游戏查询使用服务器独立 `hok_chat_reader` PostgreSQL 账号；长期记忆及本地会话运行状态使用 Redis DB0。普通群与跨群范围在可信 `Principal.attributes.chat` 中传入并由适配器绑定，模型不得提供或改变。所有后台任务和运行记录使用 `hok:agent_runtime:console:*`。QQ 对话会话使用 `qq_g_<群>_<QQ>` / `qq_p_<QQ>`，与网页隔离；QQ 与网页任务分别使用 `tasks:qq` / `tasks` due 索引，避免相互领取或阻塞。本地默认玩家由 `LocalAgent.player_key` 指定为 example_user_10，入口从权威参考数据唯一解析其 QQ；长期事实记忆使用该用户已有的 `hok:memory:facts:<QQ>`，跨会话共享。旧匿名 `local-ui:<session>` 记忆保留，不自动认领、迁移或删除。
- `agent_console/roleplay.py` 编排角色和通用用户偏好；`identity.py` 单独维护本地 HOK 身份映射与权限策略，角色管理器不识别 QQ、游戏玩家键或群范围。`roleplay_models.py` 定义纯数据校验，`roleplay_store.py` 仅供外部 SSH worker 执行 DB0 持久化，`tools/roleplay.py` 注册按需披露的角色工具。角色定义在 `shared/agent/roles/*.json`，与内核及 SQL 独立。用户自建角色、当前选择和回复偏好按可信用户 ID 的摘要隔离，使用 `hok:agent_runtime:console:roleplay:<用户摘要>:*`，不覆盖 QQ 旧角色记录；新 QQ 与网页在同一个真实 QQ 下共享新角色选择和偏好。角色来源来自真实联网搜索，模型生成档案时保留请求、响应和来源事件，生成失败不保存；角色与偏好不能改变工具授权或查询范围。选择由本次最终回复整理器和后续对话读取，后台 agent 任务在执行时重新读取其已绑定用户的当前角色、偏好及近期/相关长期事实，固定消息任务保持原文。旧任务保留原授权与身份，不自动增加角色权限。网页与 QQ 入口和工具共用相同角色服务。
- 本地聊天的前置工具由适配层设置为历史检索、能力发现，模型不得在未发现任务/记忆等类别时把未披露误报为能力缺失。本人偏好的归属已经由入口绑定，不需要额外 QQ 或玩家身份。业务调用与 Redis 状态/通知使用两条独立 SSH 连接，避免长 SQL、图片或沙箱阻塞发送。
- `chat_history` 类别提供按需的 `read_recent_chat_history`：当前消息指代不明、依据不足或相关性检索未还原当前话题时读取近期窗口，不作为每轮必调工具。`AgentHistory` 配置默认 15 分钟/20 条、上限 60 分钟/50 条及每条 600 字摘录；共享纯校验在 `tools/memory.py`，worker 启动将有效限制返回给工具 schema 和发现目录，避免前后端限额不一致。worker 只查询 `hok.chat_history_messages`，在 SQL 中按 Unix 秒时间窗口、群号、当前消息排除和 LIMIT 过滤后取最新消息并按时间顺序返回，覆盖群内所有发言者，标记截断和窗口边界，不加载全量归档或用命中数统计总体。普通群绑定可信当前群且不能改群；仅跨群授权私聊/本地调试可指定一个目标群，禁止自动混入多个群，私聊消息 ID 不用于排除群内同 ID 消息。近期发言作为不可信 tool observation，不写长期事实记忆；QQ 与网页共用工具，内核不解释时间窗口或群身份。
- 应用任务有 `agent` 和 `message` 两种：前者调用同一 ReAct 内核，后者直接通过通用事件/输出端口发送固定文字且不请求模型。周期最短 1 秒，未指定首次延迟的周期任务等待一个周期；后续时间按原计划递推，错过的时间点跳过，禁止集中补发。调度不等待前台模型空闲。任务的类型、计数、租约与取消规则均留在适配层。
- `shared/agent/{chat_sql,hok_sql}/` 保存不含密钥的模型语义目录及可信视图定义，可独立修改；目录是模型披露与 AST 校验的共同来源。服务器缺少语义视图时，适配层将仓库语义视图定义编译为只读 CTE；模型仍不允许查询采集层表，不执行 DDL。
- `shared/agent/reference_data/manifest.json` 声明参考数据源及名称、别名、ID 命名空间与关系；`agent_console/tools/reference_data.py` 是不含 IO 的目录构建/检索器，HOK 字段名只放共享清单。外部适配器读取最新服务器静态配置，常用映射按清单投影进上下文，完整映射经 `references` 工具披露；不得用 SQL 结果后补昵称、群聊推断或长期记忆代替权威参考数据。多对一、同名与同人账号关联保留全部匹配，参考关系不授予身份权限。
- 一般生成 Python 仅在远程 Linux bubblewrap 沙箱运行，关闭网络、清空凭据环境、限制资源并验证 PNG。隔离依赖缺失时拒绝执行，禁止回退到宿主 `exec`。
- `shared/agent/plots/catalog.json` 独立定义绘图主题、配色、图型说明与数据规范；`agent_console/tools/plotting.py` 定义参数并生成调用代码，`agent_console/plot_renderer.py` 是不含 IO、配置或业务身份的可信绘图库，由 SSH worker 注入 bubblewrap 内执行。条形、折线、散点、热力图与环形图共用主题、标题层次、标注和数据口径脚注。`render_plot` 与一般 Python 绘图均使用目录默认主题，角色与 ReAct 内核不得包含绘图样式。热力图必须保留轴标签，长表明确数值列，重复格拒绝隐式聚合，缺失值默认留空；补零、聚合只能由调用参数明确指定。趋势图保留真实观测点、不插值平滑；查询截断必须在图中说明。主题和可信绘图代码修改后重启本地适配器。
- 本地界面只监听 `127.0.0.1`，提供思考字段、工具调用/结果、产物及完整事件轨迹；无真实 `reasoning_content` 时不得伪造思考过程。独立配置统一放在根 `config.yaml` 的 `LocalAgent`，不新增应用配置或密钥文件。
- `agent_console/static/usage.js` 是外部 UI 的纯用量统计器：只按持久的 `model.response` / `roleplay.model.response` / `reply.model.response` 汇总接口 usage，按事件 ID 去重；流式片段、工具 payload 和缓存/思考子集不得重复加总。按请求、本轮和会话展示输入、输出、总量及可用缓存/思考字段，未知值与零明确区分，中断或失败请求保留未返回状态。会话恢复重放相同事件；思考与工具步骤默认折叠，完整事件轨迹保留。
- `ImageInput` / `RunRequest.images` 是内核的通用图片输入协议，源为 URL、data URL 或外部模型适配器解析的引用，内核不做图片 IO、不包含供应商与文件策略。用户文字与图片作为原生内容块进入每轮 ReAct 请求；`StatePort.save_dialogue.question` 接受字符串或内容块列表并原样恢复，纯文本调用兼容。图片、图片中的指令不得改变身份或工具授权。
- `agent_console/image_inputs.py` 负责本地图片校验、原始像素存储、上下文预算和事件引用投影。输入图片及元数据存于忽略目录 `file_transfer/agent_inputs/`；网页选择、粘贴、拖入均走认证 `/api/images`，`/api/chat` 只接受已上传图片 ID。格式依实际像素检测，拒绝损坏文件、超大图片、无效 ID 和重复附件。原图保持不变；GIF、动态 WebP/APNG 等动画在外部适配器按帧序抽样成带帧号的 PNG 拼图，默认最多 4 帧、源动画最多 240 帧且限制累计解码像素，配置在 `LocalAgent.images` / `QQAgent.images`。原图与实际模型输入拼图各自保存，拼图元数据记录原图 ID、总帧数和抽样帧索引；静态图直接转换为原始 data URL，动画转换为拼图 data URL。Redis/SSE/事件快照使用 `attachment://<id>`，实际 request payload 必须引用真正发送的像素文件，不能把拼图冒充原 GIF；provider 在线程中做投影，不阻塞任务发送。默认 4 张、单张 4 MiB、每次 8 MiB；模型图片预算 16 MiB 以实际发送字节计算，优先近期图片，被省略的历史图片必须有明确提示和记录。QQ 入口支持带真实 URL 的 image/mface/marketface/face，缺少 URL 的表情明确标记未读取像素，不猜测素材地址。
- 图片模型名称分别在根 `config.yaml#LocalAgent.vision_model` / `QQAgent.vision_model` 设置，当前按用户要求使用 `deepseek-v4-flash`，由官方兼容路由承接；模型 key 与 endpoint 继续从服务器读取，不新增凭据。带当前或历史图片时在 `agent_console/provider.py` 选择该模型，角色、工具与同一 ReAct 内核继续工作；纯文本请求沿用服务器模型。图片输入的 token 已包含在 API 输入用量中，不重复统计。
- 内核的可选 `FinalizerPort` 接收 `FinalizationContext` 中的请求、任务草稿和模型上下文副本，返回通用 `FinalAnswer`。内核不识别角色、QQ、版本名称或排版；只发布默认 text、透传 variants/metadata，并保存 history_text（缺省为 text）。原模型响应及草稿保持完整。处理器失败保留草稿并警告，取消与总体预算仍生效；同步阶段性输出不受最终整理器影响。
- `agent_console/replies.py` 是外部双版本展示器：ReAct 答案作为唯一事实底稿，detailed 原样保留；JSON 模型仅生成 chat，不带工具、不重新分析或计算。表达输入只有当前问题、底稿、最新角色表达卡和用户表达偏好，不再次注入原始工具结果、目录、检索发言、旧对话、长期记忆与角色生平；有 voice 的角色只投影其表达卡，旧档案兼容提取 personality / speech_style。数字沿用底稿的对象、标签、单位与分母，不拆开重组。默认最多两次、总阶段 60 秒，检查结构、长度、纯文本和新增数值/链接；字面量检查不代表语义验证，不增加事实复核模型。超出输入预算不截断事实；失败保留底稿并显式 degraded。预算统一在 config.yaml 的 LocalAgent.reply。
- `output.message.data.text` 和本地 run 结果 text 默认使用群聊版，variants 另存详细版与群聊版，网页分别展示并允许复制群聊纯文本；QQ 出口按当次需求选择版本。reply.model.* 完整记录请求、输入字段长度、响应、原始JSON、修复与失败，并与 ReAct/角色生成统一统计 token。当前本地 history_variant=detailed 只保存一份底稿供后续追问，避免重复答案膨胀上下文；QQ 适配器可选择 chat，只保存实际发送内容。两个版本均保留在事件中；固定文字定时任务保持原文且不新增模型请求。
- 角色包可选 voice 数据只在 shared/agent/roles/*.json 和外部角色服务维护，含 tone、habits、avoid、原创问答语气样例；旧记录默认兼容，联网角色也生成并校验这些字段。表达样例不能被当作当前问题的事实或复制答案，角色描述、事实、工具权限继续解耦。最终整理时重新读取当前用户角色与偏好，变更对接下来的最终回复和后台 agent 任务生效。
- `agent_console/local_logs.py` 是外部本地调试日志出口，不进入独立内核；默认由 LocalAgent.local_logging 启用，写入忽略目录 log/agent_console/<session_id>/dialogue.jsonl 和 runs/<run_id>.jsonl，包含收到的请求、模型上下文/payload、真实思考与流式片段、工具参数/observation、各条输出、token 与失败/取消状态。凭据沿用 bridge.redact 脱敏，图片沿用已投影的附件引用；不裁剪字段或套用远程 TTL。文件按事件 ID 去重，页面加载旧会话时补存仍可读取的历史事件，不能伪造旧流式片段。IO 在线程中执行，写入失败保留正常消息发送并通过日志、事件字段和 /api/status 暴露；请求在上下文准备阶段失败也要保留原问题及异常栈。

- 独立内核变更必须先在私有仓库提交并推送，再更新父仓库 submodule 指针。首次克隆执行 `git submodule update --init --recursive`。部署固定检出 gitlink commit，不使用 `--remote` 跟随分支；现有部署用 `deployment/scripts/sync_agent_runtime.sh` 将旧复制目录备份后安装软链接，保留其他业务数据。
- DeepSeekModel 实现可选 `StructuredModelPort.complete_request(ModelRequest)`，正确传递内核选择的命名 tool_choice；所有含工具或继续工具链的请求统一关闭 thinking，不在强制轮和自动轮间切换思考协议。独立内核不识别 DeepSeek 或工具名称。

- `agent_console/tools/memory.py` 维护当前使用的纯事实校验、BM25 与多 query RRF；worker 由外部适配器传入源码，不从 Hok 旧记忆模块提取。存储和可信身份继续由 worker/适配器处理，不进入内核。
- 旧聊天兼容入口、注册器、schema、角色包、绘图 worker、诊断、JSON/主动/被动/摘要缓存和过时开关均已删除。不要恢复第二套聊天实现。历史数据库/Redis 数据未由代码清理删除；`forget_me` 只按可信入口清除本人长期事实及当前 QQ 会话上下文，不删除归档、日志、角色偏好或其他会话。

- 部署恢复使用 `deployment/scripts/restore_application.sh`，先按旧 HEAD 与目标版本的删除列表移除源文件，再 reset/restore；禁止仅 reset 导致已退休模块遗留为可导入的未跟踪文件。历史目录继续排除，复制内核备份由 sync_agent_runtime.sh 负责。

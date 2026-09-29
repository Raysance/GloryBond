# HOK_QQBot NBot — 子项目补充规范

本文件只记录 `NBot/` 子项目的目录职责、配置来源、调用边界和运行约定。通用代码规范、仓库边界、README 定位与 `.gitignore` 分层规则见根目录 `AGENTS.md`。

## 1. 目录与文件职责（`hok/`）

以下规则适用于 `hok/` 下所有代码。

- `hok/__init__.py`：NoneBot 插件入口；注册插件元信息并集中加载配置、静态变量、动态变量、API、事件、文件、业务函数、定时任务与时间工具。
- `hok/config.py`：Pydantic 配置模型定义；除非明确需要，否则不要新增依赖或复杂逻辑。
- `hok/zdynamic.py`：**动态变量**导入与初始化必须放在这里；其他模块通过 `from . import zdynamic as dmc` 读取动态配置初始值；运行时需要跨部署持久化的状态必须通过 Redis 业务接口保存。
- `hok/zevent.py`：NoneBot matcher 声明、注册及最薄处理器入口；只做初步解析、分发与调用接口，不实现具体业务算法。通用路由谓词放在 `event_rules.py`，群消息最初捕获放在 `event_ingress.py`，可独立测试的处理器解析与业务分发放在 `event_handlers/`；普通用户的“代表局”自然语言查询在此路由且必须以 `#` 或 `＃` 开头，正式回复不得附带调试信息；`##rep3` 仅供管理员按日期区间调试每日三类指数冠军；`#巅峰排名` / `#巅峰排行` 仅调用 `zfunc.py` 的本地结构化历史排名流程；`#梯度` / `＃梯度` 仅调用 `zfunc.py` 的梯度长图流程；消息中同时出现“战力”和“查询”时调用 `zfunc.py` 的指定地区荣耀战力查询流程，英雄名和地区名顺序不限；B 站 UP 视频订阅命令的剥离与业务分发由 `event_handlers/bili_video.py` 完成。
- `hok/event_rules.py`：不依赖 NoneBot 类型的消息路由谓词、用户权限和命令判定；不得注册 matcher 或发送消息。
- `hok/event_ingress.py`：群消息进入业务路由前的历史保存与被动聊天捕获；提取 `group_id`、`user_id`、`message_id`、引用消息 ID 与纯文本后调用 `zfunc.py`，保存失败只记录错误且不得阻断正常路由。
- `hok/event_handlers/`：不注册 matcher、不导入 NoneBot 适配器的处理器解析与业务分发；当前包含英雄查询与视觉产物、玩家战报/排行、实时对局预言、历史战绩查询、管理员历史导出、代表局查询/调试、底蕴与时长查询、AI 聊天输入、表情生成、戳一戳决策及 B 站订阅命令处理器，返回文本、消息序列或结构化结果给 `zevent.py`，消息发送和 `MessageSegment` 拼装仍留在入口/出口层。历史导出命令解析、逐用户调用和失败汇总由 `event_handlers/history_export.py` 完成；代表局普通查询、单日调试信息和区间调试结果由 `event_handlers/representative.py` 归一化；玩家在线状态、群体排行、单人战报及最近单局、战绩视图与上次详情由 `event_handlers/player_reports.py` 分发；英雄战力、今日英雄参数、评分图与观战截图由 `event_handlers/hero_visuals.py` 分发；实时对局查询、五分钟缓存与预言计算参数由 `event_handlers/spoiler.py` 管理；底蕴/时长的个人与排行分流由 `event_handlers/activity.py` 完成；聊天文本替换、联网与记忆开关、用户和群消息元数据由 `event_handlers/chat.py` 归一化；表情模板、提示词及图片参数由 `event_handlers/emoji.py` 解析并调用生成工具；戳一戳的观战截图、底蕴触发、冷却及随机回复由 `event_handlers/poke.py` 决策；历史查询的单局图片组合仍由 `zevent.py` 完成，多局网页产物由 `zfunc.py` 编排。
- `hok/zchat.py`：AI chat 的结构化消息组装、多轮 tool-call 循环、细粒度工具白名单与参数校验入口；玩家战报、单英雄统计、英雄汇总等意图必须使用各自独立的结构化 tool schema，由程序解析玩家/英雄并调用确定的 `zfunc.py` 业务接口，禁止把多个意图重新合并为自然语言总入口；任何 tool call 无论成功或失败都必须生成对应的 tool result；群聊历史检索由模型先基于原 query 生成多组互补查询，再调用本地检索接口，命中后可按 `message_id` 展开上下文。
- `hok/zfile.py`：文件/IO 读写统一入口；所有 IO（读写文件、落盘缓存、路径拼接、动态变量重载与旧聊天缓存删除等）必须通过此模块提供的接口完成；荣耀战力地区树统一从 `data/honor/districts.json` 读取；历史日期枚举与每日数据读取通过此模块转发到 PostgreSQL，数据库异常时才读取应急 JSON；网页历史 JSON 的路径构造与写入也统一由此模块负责；梯度英雄头像属于长期资产，按英雄 ID 与头像 URL 指纹保存在 `resources/wzry_images/hero_avatars/`，`file_transfer/` 只保存每次查询重新生成的梯度长图；HOK Exception 运行时错误记录统一追加到 `log/error.log`。
- `hok/zdb.py`：PostgreSQL 数据访问唯一入口；负责结构化历史、对局详情、个人快照、战力分析、英雄梯度、英雄排行及导入清单的读写。历史业务以 PostgreSQL 为主数据源；仅当数据库写入失败时，`zfile.py` 才生成应急 JSON。
- `hok/zfunc.py`：业务能力的稳定兼容门面、跨领域编排与 Redis 访问入口；规模较大的独立业务实现逐步下沉到 `hok/business/`，但 `zevent.py`、`zchat.py` 和其他调用方仍只通过 `zfunc.py` 的公开接口访问。群聊历史 Redis 读写仍保留在此，具体分词、BM25 与结果融合算法委托 `zmemory.py`；新版群聊历史按群永久保留全部文本消息，`ChatHistoryMaxMessages` 为 `0` 时禁止裁剪，仅在显式配置正整数时作为安全上限；`peak_rank_process()` 只读取本赛季本地结构化历史；荣耀战力查询只调用一次指定地区 `ranklist`；B 站订阅、战绩隐身及其他 Redis 业务状态的原子读写仍由此模块维护。
- `hok/business/`：按领域拆分的不含 Redis、NoneBot、直接 HTTP 和直接文件读写的业务实现；当前包含用户辅助、AI 文案组装、每日战报、代表局、结构化历史读取、历史自然语言查询、荣耀战力地区解析、英雄资料、英雄统计、今日英雄推荐、玩家战绩采集、单人战报、战绩分析视图与单局详情、观战协议转换、共玩/底蕴分析、单局历史与统计分析、游戏时长统计、对局指标、玩家在线状态、玩家视觉产物、群体排行、战绩可见性状态计算、网页产物标识与路由规则、B 站订阅流程及 KPL 推送流程。问候、QQ 身份映射、表情选择、URL 参数和巅峰分段解析由 `business/user_helpers.py` 实现，表情配置读取仍通过 `zfile.py`，AI 选择仍通过 `zapi.py`；旧式 AI 消息类型的提示词组装与标准/联网适配器选择由 `business/ai_prompts.py` 实现，实际请求只调用 `zapi.py`；每日战报的排行正文与代表局文字、图片、AI 文案顺序由 `business/daily_notification.py` 组装；结构化历史的 PostgreSQL 优先读取与 JSON 应急聚合由 `business/history_data.py` 实现，目录枚举和文件读取仍通过 `zfile.py`；需要调用其他业务能力时通过运行时导入 `zfunc.py` 的公开接口，避免形成模块导入环。`representative_battle_query_impl()` 必须隔离正式文字、图片路径、图片下方 AI 文案与调试载荷；`representative_battle_range_debug_impl()` 只组装每日三类指数冠军的纯文本区间调试结果。英雄战力列表与常用英雄摘要由 `business/hero_profiles.py` 实现；英雄名安全解析、拼音转换及天元之弈梯度 API、头像缓存和长图编排由 `business/hero_tier.py` 实现；英雄统计实现只负责结构化统计与文字组装；今日英雄的候选选择、推荐依据和文案组装由 `business/today_hero.py` 实现，Redis 当日缓存与历史列表只通过 `zfunc.py` 的窄接口读写，皮肤和技能资产只通过 `zfile.py` 访问；战绩分析视图与单局详情的文本、网页载荷和图片生成编排由 `business/battle_detail.py` 实现；观战接口到共玩分析结构的严格转换及对局预言编排由 `business/battle_watch.py` 实现；单局详情读取时的目标玩家视角重建及历史胜率、英雄、受益度、交集统计由 `business/battle_history.py` 实现；共玩/底蕴数值计算、阵营汇总、图片载荷与历史记录对象由 `business/battle_power.py` 实现，评估记录的 Redis 写入仍通过 `zfunc.py`，文件路径与读写仍通过 `zfile.py`；王者与 Steam 最近时长汇总、群体排行和局部错误聚合由 `business/game_activity.py` 实现，Steam 请求只调用 `zapi.py`，图表路径只由 `zfile.py` 提供；英雄阵容对位的精确/分路回退统计与可选 AI 短评由 `business/battle_matchup.py` 实现；正式对局判定、评分均值与团队贡献系数统一由 `business/battle_metrics.py` 实现；玩家战绩列表与资料拉取、当日结构化转换、技能缓存补齐、单局详情补拉及指定用户回填由 `business/player_data.py` 实现，API 通过 `zfunc.py` 的优先级门面调用，路径与写入通过 `zfile.py`；单人当天与历史战报的日期解析、数据选择和文本组装由 `business/player_report.py` 实现；评分趋势图与观战截图流程由 `business/player_visuals.py` 实现，输出路径只由 `zfile.py` 提供；群体排行的并发采集、榜单展示、遍历错误格式化及本地巅峰排名由 `business/rankings.py` 实现；王者与 Steam 在线状态的并发遍历、分组展示和局部失败聚合由 `business/online_status.py` 实现；战绩可见性的关联 QQ 解析与禁用名单状态迁移由 `business/battle_visibility.py` 实现，Redis 读写、日志和禁言任务编排仍保留在 `zfunc.py`；网页产物的 hash、路由映射和元数据组装由 `business/web_artifacts.py` 实现，Redis 发布仍通过 `zfunc.py`，文件路径与写入仍通过 `zfile.py`；B 站订阅解析、身份更新、最新视频与轮询推送流程由 `business/bili_video.py` 实现，订阅存储、去重集合、分布式锁和消息出口仍通过 `zfunc.py`；KPL 比赛筛选、图片提示词和推送流程由 `business/kpl.py` 实现，推送锁与已推送集合仍通过 `zfunc.py`，图片落盘通过 `zfile.py`，消息拼装与发送通过 `utils/message_sender.py`。
- `hok/zmemory.py`：所有 AI 对话记忆、摘要、长期记忆、表情记忆相关的读写与策略接口，并提供群聊历史的 jieba 分词、BM25、多 query 融合和上下文展开算法；chat 动态上下文仍只允许自动加载当前用户经 `f_chat()` 捕获的直接人机对话，不得自动混入历史 summary、强制记忆、群聊被动发言、其他用户上下文或回复引用内容；群聊历史只能由 `zchat.py` 在模型明确调用检索工具时按需注入为 tool result。
- `hok/chat_roles/`：chat 角色扮演的可插拔角色包；每个角色模块的 `ChatRole` 只维护该角色自身的信息与表达特征，角色无关的通用约束集中维护并在角色信息之后单独追加；角色通过包级注册表接入，当前默认角色由 `variables_static.json` 的 `chat_role` 指定。
- `hok/zscheduler.py`：所有定时/间隔任务的声明、注册与定义（不要在别处私自创建 scheduler 任务）；旧版凌晨 03:30 的 `daily_user_summary` 已停用，禁止重新注册会清理原始聊天记录的摘要任务；每日 23:30 的 `notify_msg()` 统一发送当日王者战报，并按“代表局文字 → 图片 → AI 文案”的顺序发送代表性对局；网页底蕴分享保留阵容 AI 短评参数，当前以 `False` 禁用；B 站 UP 新视频轮询任务只在此注册，实际检查与推送编排调用 `zfunc.py`。
- `hok/zstatic.py`：**静态变量**导入必须放在这里（从文件与系统环境变量导入）；其他模块通过 `from .zstatic import *` 获取静态变量。
- `hok/ztime.py`：时间工具与日期处理统一入口；任何时间计算、格式化、时间窗口判断都应调用这里的接口；代表局查询中的自然语言日期及区间统一由 `parse_representative_battle_date()`、`parse_representative_battle_date_range()` 解析，群聊历史检索时间边界统一由 `parse_chat_time_bound()` 解析。
- `hok/zutil.py`：基础工具集；统一导入常用库与通用小工具（不要在各处散落重复 import 与重复工具实现）。
- `hok/utils/message_sender.py`：发送消息统一入口；任何对外消息发送必须调用此模块的函数接口（禁止绕开直接调用底层适配器发送）。
- `hok/zapi.py`：外部 API 的稳定兼容门面，只负责从 `hok/api_adapters/` 导出业务层可调用的公开接口；不得在门面中新增协议细节或业务编排。AI chat 的单轮协议适配通过该门面对外提供，普通聊天的 Chat Completions 与联网聊天的 Responses 均归一化为 `content`、`tool_calls`、`output_items`；多轮编排留在 `zchat.py`。
- `hok/api_adapters/`：按外部服务拆分请求封装、签名、响应解析、超时与协议级重试；当前包含王者官方 API、AI/图片、天元之弈、Steam 与 B 站适配器。普通聊天及 `ai_api()` / `ai_function()` 使用 SJTU Chat Completions endpoint，默认模型为 `deepseek-chat`，可配置 `deepseek-reasoner`、`qwen` 或 `qwen3.8-27b`；SJTU 客户端必须显式绑定 `ChatAPI.proxy_url` / `HOK_CHAT_PROXY_URL` 指定的 `sjtu-vpn` SOCKS5 代理并禁用环境代理继承，缺少代理配置时不得直连。Steam 与 APIMart 请求必须通过 `api_adapters/proxy.py` 显式绑定 `Proxy.clash_url` / `HOK_CLASH_PROXY_URL` 指定的 Clash 代理，并禁用环境代理继承；缺少配置时不得直连。适配器负责工具 schema 与 tool result 的协议转换，并完整保留 assistant 的 `tool_calls`、`reasoning_content` 供后续轮次回传；`&` 联网聊天仍使用火山方舟标准 Responses endpoint 与内置 `web_search`，不得回退到应用 Bot 的 Chat Completions endpoint；荣耀战力指定地区 `ranklist` 只在王者适配器组装和发送；B 站 UP 视频的 WBI 签名、用户/视频搜索、用户卡片请求和响应归一化只在 B 站适配器实现。适配器不得读取 Redis 或承担业务队列优先级调度，相关逻辑留在 `zfunc.py`。
- `hok/zkpl.py`：KPL 数据统一入口；仅 `get_match_list_json()` 与 `get_match_detail_json()` 负责获取赛程和完整比赛数据，其他 KPL 转换与兼容接口必须调用二者。
- `hok/zdiy.py`：自定义/临时扩展的业务能力聚合处；当能力稳定后应迁移到职责更明确的模块（`zfunc.py` / `tools/` / `zapi.py` 等），避免长期堆叠。

HOK_QQBot 与 Web 的全部 Redis 数据统一存放在 `REDIS_DB`（DB0），以 `hok:` 为根命名空间；独立 Planit 应用继续使用 DB9。`zdynamic.py` 只创建一个 DB0 Redis 客户端，历史兼容别名必须指向同一客户端，不得再连接 DB1–DB7 或 DB10。Key 使用冒号分层命名并由 `zstatic.py` 暴露共享常量，例如 `hok:web:artifact:<token>`、`hok:battle:liked_ids`、`hok:queue:*`、`hok:hero:*`、`hok:evaluator:*`、`hok:chat:*` 与 `hok:memory:*`。跨 DB 收敛统一通过 `scripts/consolidate_redis_to_db0.py` 执行，正式执行前必须生成可恢复的 DUMP 备份。

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

- `hok/tools/endecoder.py`：王者营地接口加解密与请求参数生成工具。
- `hok/tools/emoji_renderer.py`：emoji 文本拆分与图片文字渲染辅助。
- `hok/tools/gen_battle_res.py`：单局战绩详情长图生成器。
- `hok/tools/gen_battle_shot.py`：RTMP 监听与对局截图工具。
- `hok/tools/gen_coplayer_analyses.py`：共玩关系、头像、胜率、评价等图表生成器。
- `hok/tools/gen_emoji_image.py`：表情包生成链路与风格模板维护工具。
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

- `database/schema.sql`：结构化历史库的 schema、表、外键与查询索引。
- `scripts/import_json_to_postgres.py`：幂等回填入口；只读扫描原始 JSON，并通过文件大小与纳秒 mtime 清单跳过未变化文件。

### 1.5 部署运行方式

- 部署服务器上的 NoneBot 进程由 `hok-nbot.service` 统一管理，禁止在发布流程中再使用 `nohup` 或按端口手工结束进程。
- GitHub Actions 在完成代码同步后通过 `systemctl restart hok-nbot.service` 发布，并以 `systemctl is-active` 验证启动结果。
- `hok-nbot.service` 从 `/QQBot/NBot` 启动 `deploy_runner.sh`，依赖 Redis、PostgreSQL 与网络就绪，运行日志仍写入 `log/run.log`。

## 2. 配置与变量的来源（必须遵守）

### 2.1 配置文件（``）

- `config.yaml`：王者荣耀/Steam/AI 的 API-Key、AI 模型、QQ群号、王者荣耀 request 参数、服务器 IP/域名等配置。`ChatAPI` 配置 SJTU 普通聊天的 `base_url`、`model`、`proxy_url` 与可选 `api_key`；`Proxy.clash_url` 配置 Steam 与 APIMart 专用 Clash 出口；新密钥优先通过私有环境变量 `HOK_CHAT_API_KEY` 注入，禁止新增到 Git 跟踪文件。
- `config.yaml` 的 `PostgreSQL.dsn`：PostgreSQL 本地连接串；部署环境可由 `HOK_DATABASE_DSN` 覆盖。`PostgreSQL.archive_json` 为 `false` 时历史数据数据库单写，写库失败才应急落 JSON。
- `variables_static.json`：用户 QQ 号、王者荣耀 roleid/userid、用户昵称、SteamID、常见俚语缩写、赛季起止时间、英雄 ID 映射、部分功能 prompt 等稳定数据。
- `variables_dynamic.json`：动态变量初始值，例如是否记忆、机器人是否开放、英雄梯度、今日新闻、上一次查询战绩时间、今日导出失败用户名单、B 站 UP 视频轮询开关等；运行时需要跨部署持久化的业务状态必须放 Redis，不得依赖 Git 工作区文件保存订阅、用户状态或去重状态。

原则：
1. **任何可能变化的值**不得硬编码在业务逻辑里，必须进入上述文件或对应的静态/动态变量模块。
2. `zstatic.py` 负责加载静态配置；`zdynamic.py` 负责加载动态配置初始值，不作为运行时持久化写入入口。

### 2.2 Linux 环境变量（在 `hok/zstatic.py` 导入）

部署环境下预计存在以下环境变量（缺失时的处理策略以现有代码为准，禁止凭空新增“变量不存在”的冗余判断链）：

- `REDIS_CONF`：Redis 配置文件路径。
- `BOT_PATH`：Bot 部署目录。
- `HOK_ENV_FILE`：可选 dotenv 路径；systemd 部署优先用 `EnvironmentFile` 直接注入，不要求存在 dotenv。未指定时，本地调试另加载 `BOT_PATH/.env.local`（Git 忽略），用于保存私有 API 密钥。
- `HOK_CHAT_BASE_URL`、`HOK_CHAT_API_KEY`、`HOK_CHAT_MODEL`、`HOK_CHAT_PROXY_URL`：覆盖 `config.yaml` 的 `ChatAPI` 对应字段，由 `zstatic.py` 统一导入为 `chat_api_config`；当前专用代理为 `socks5h://10.203.0.2:1080`。
- `HOK_CLASH_PROXY_URL`：覆盖 `config.yaml` 的 `Proxy.clash_url`，由 `zstatic.py` 导入为 `clash_proxy_url`；Steam 与 APIMart 当前默认使用 `http://127.0.0.1:7890`，也支持 `socks5h://127.0.0.1:7891`。
- `HOK_CONFIG_FILE`、`HOK_STATIC_VARIABLES_FILE`、`HOK_DYNAMIC_VARIABLES_FILE`：外置配置文件路径。
- `HOK_DATA_DIR`：应急 JSON、地区树和每日数据的持久目录；默认 `BOT_PATH/data`。
- `HOK_FILE_TRANSFER_DIR`：NBot 与 Web 共享的公开产物目录；默认 `BOT_PATH/file_transfer`。
- `HOK_LOG_DIR`：NBot 文件日志目录；默认 `BOT_PATH/log`。

项目根目录统一使用全局变量 `BOT_PATH` 的绝对路径，通过 `hok/zstatic.py` 的 `project_root` 暴露给其他模块；Web 静态产物目录统一使用 `BOT_PATH/file_transfer/`，通过 `temp_path` 暴露，不再从 `NGINX_HTML` 读取。

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
6. **运行日志**：部署运行日志统一写入 `log/run.log`，HOK Exception 错误日志统一写入 `log/error.log`；`log/` 为运行时目录，不纳入 Git。
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

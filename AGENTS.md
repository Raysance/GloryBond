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
- `hok/event_handlers/`：不注册 matcher、不导入 NoneBot 适配器的处理器解析与业务分发；当前包含英雄查询与视觉产物、玩家战报/排行、实时对局预言、历史战绩查询、管理员历史导出、代表局查询/调试、底蕴与时长查询、AI 聊天输入、表情生成、戳一戳决策及 B 站订阅命令处理器，返回文本、消息序列或结构化结果给 `zevent.py`，消息发送和 `MessageSegment` 拼装仍留在入口/出口层。历史导出命令解析、逐用户调用和失败汇总由 `event_handlers/history_export.py` 完成；代表局普通查询、单日调试信息和区间调试结果由 `event_handlers/representative.py` 归一化；玩家在线状态、群体排行、单人战报及最近单局、战绩视图与上次详情由 `event_handlers/player_reports.py` 分发；英雄战力、今日英雄参数、评分图与观战截图由 `event_handlers/hero_visuals.py` 分发；实时对局查询、五分钟缓存与预言计算参数由 `event_handlers/spoiler.py` 管理；底蕴/时长的个人与排行分流由 `event_handlers/activity.py` 完成；聊天文本替换、记忆开关、用户和群消息元数据（不再解析 `&`）由 `event_handlers/chat.py` 归一化；表情模板、提示词及图片参数由 `event_handlers/emoji.py` 解析并调用生成工具；戳一戳的观战截图、底蕴触发、冷却及随机回复由 `event_handlers/poke.py` 决策；历史查询的单局图片组合仍由 `zevent.py` 完成，多局网页产物由 `zfunc.py` 编排。
- `hok/zchat.py`：AI chat 的结构化消息组装与多轮 tool-call 循环；每轮可返回多个工具，每个调用无论成功或失败都必须产生对应 observation。每次具有可信群范围的 chat 都必须在回答前强制模型直接调用 `search_chat_history`；系统只为这项必需能力预披露 `chat_history` 类别并指定首轮 tool choice，其他 `game_data`、`plots`、`internet`、`memory`、`roleplay` 类别仍通过 `discover_tools` 渐进披露。当前问题明确写出能力类别、数据库/SQL、可视化等工具意图时，完成强制历史检索后必须以 tool choice 强制调用一次 `discover_tools`，程序合并显式类别，防止模型把“尚未披露”误报成“不具备能力”；发现完成后继续按类别强制最小可执行链，数据库依次为 schema、SQL 检查和一次性 check_id 执行，已有查询数据的绘图依次为模板读取和渲染。模型准备以工具/权限/查询入口不可用为由结束、但仍有未披露类别时，也必须追加一次受限的发现重试并执行所选类别的最小链。模型必须从原问题提取人物、对象、事件、动作、别称或同义表达，生成 2–6 个简短、去重且不重复原问题的互补 query；程序附加原问题后执行多 query BM25 与 RRF 融合。普通群聊检索入口绑定群内全部用户的全部已保存发言并按 `(group_id, message_id)` 排除当前消息；管理员私聊传 `all_groups=true` 检索所有已保存群；普通私聊因没有可信群范围只检索本人直接对话。`hok/chat_tools.py` 维护工具 schema、参数校验、当前用户/群身份绑定、本轮 SQL 数据集、一次性 SQL 检查票据与图片产物；未披露工具不得执行。历史玩家、英雄、战局、跨玩家、底蕴及比较统一由模型根据 `hok/chat_sql_schema.py` 的真实表列、关联、字段能力、JSON 字段及去重口径生成 SELECT/CTE，先调用 `check_game_database_query` 提交查询意图、假设和 SQL，整批通过后才可用一次性 `check_id` 调用 `query_game_database`；执行工具不接受 SQL，问题特定查询范式不得硬编码进 schema 或工具。当前玩家英雄战力与指定地区荣耀战力保持独立工具。SQL 批量查询各自返回 observation，截断只能裁剪行预览，必须保留各查询状态与 dataset_id。联网由模型调用 `web_search`，通过 OpenRouter `openrouter:web_search` server tool 和 Clash 代理完成，不再使用 `&`。记忆由模型按语义调用 recall/remember/forget 工具，禁用记忆时只是不提供长期事实记忆工具；当前用户的直接对话仍在所有 chat 请求中检索、注入并保存。`manage_roleplay` 负责联网生成、查看、清除当前用户专属角色背景，持久化后在后续对话中自动注入。群聊工具还支持按发言者/时间筛选、读取最近发言以及展开命中上下文或回复链；两类工具优先传 `players`，由 `business/user_helpers.resolve_chat_qq_ids()` 精确解析别名为 QQ，`qq_ids` 及旧 `user_ids` 仅表示 QQ，检测到已知游戏 ID 必须返回纠正提示。普通群聊工具只检索入口绑定的当前群，普通私聊不提供群聊工具；仅发送者 QQ 与 `QQBot.super_qid` 一致的管理员私聊开放跨群检索，身份来自消息入口而非模型参数。管理员私聊首次强制 search 使用 `all_groups=true`；后续定向 search/recent/context/reply-thread 必须传已有历史记录的 `group_id`，并按 `(group_id, message_id)` 展开，私聊消息 ID 不用于排除群内同 ID 消息。提示词必须由本次已披露工具列表生成，准确区分管理员私聊、群聊和普通私聊，禁止引导调用未注册工具或将范围限制描述为服务故障。
- `hok/zfile.py`：文件/IO 读写统一入口；所有 IO（读写文件、落盘缓存、路径拼接、动态变量重载与旧聊天缓存删除等）必须通过此模块提供的接口完成；荣耀战力地区树统一从 `data/honor/districts.json` 读取；历史日期枚举与每日数据读取通过此模块转发到 PostgreSQL，数据库异常时才读取应急 JSON；网页历史 JSON 的路径构造与写入也统一由此模块负责；梯度英雄头像属于长期资产，按英雄 ID 与头像 URL 指纹保存在 `resources/wzry_images/hero_avatars/`，`file_transfer/` 只保存每次查询重新生成的梯度长图；HOK Exception 运行时错误记录统一追加到 `log/error.log`；chat 绘图子进程、隔离挂载、超时、PNG 校验与落盘由此负责。
- `hok/zdb.py`：PostgreSQL 数据访问唯一入口；负责结构化历史、对局详情、个人快照、战力分析、英雄梯度、英雄排行、私有群聊归档及导入清单的读写。群聊以 `(group_id, message_id)` 幂等写入 `hok.group_chat_messages`，按可信群号读取；该表不得加入模型 schema 或 `hok_chat_reader` 授权。模型只读 SQL 也只在此执行：独立 `hok_chat_reader` 账号、只读事务、表列授权、超时、行列及结果体积上限；SQL AST 校验委托 `tools/chat_sql.py`，禁止回退使用业务写账号。历史业务以 PostgreSQL 为主数据源；仅当数据库写入失败时，`zfile.py` 才生成应急 JSON。
- `hok/zfunc.py`：业务能力的稳定兼容门面、跨领域编排与 Redis 访问入口；规模较大的独立业务实现逐步下沉到 `hok/business/`，但 `zevent.py`、`zchat.py` 和其他调用方仍只通过 `zfunc.py` 的公开接口访问。chat SQL、实时战力、绘图和 OpenRouter 搜索经窄接口分发，语义记忆通过 `hok:memory:facts:<当前QQ>` 的 Redis hash 保存并由此读写，新增/更新使用 WATCH 保证容量限制；用户自定义角色背景通过 `hok:chat:role:<当前QQ>` 保存。群聊历史由此门面转发到 `zdb.py` 作为 PostgreSQL 主存储，写库失败才追加 DB0 `hok:chat:group:<群号>` 应急 list；读取阶段按 `(group_id, message_id)` 合并尚未迁移的 Redis 记录，SQL 重复项为准，Redis 原数据在迁移验证前不得删除。`ChatHistoryMaxMessages` 只限制应急 Redis list，不裁剪 SQL 历史。`list_chat_history_groups()` 只枚举已有记录的群号与消息数，读取消息时由入口绑定可信来源群号；`search_group_chat_history()` 与仅限已验证管理员私聊工具调用的 `search_all_group_chat_history()` 加载可信范围内全部用户发言，具体分词、BM25 与多 query RRF 融合算法委托 `zmemory.py`；`peak_rank_process()` 只读取本赛季本地结构化历史；荣耀战力查询只调用一次指定地区 `ranklist`；B 站订阅、战绩隐身及其他 Redis 业务状态的原子读写仍由此模块维护。
- `hok/business/`：按领域拆分的不含 Redis、NoneBot、直接 HTTP 和直接文件读写的业务实现；当前包含用户辅助、AI 文案组装、每日战报、代表局、结构化历史读取、历史自然语言查询、荣耀战力地区解析、英雄资料、英雄统计、今日英雄推荐、玩家战绩采集、单人战报、战绩分析视图与单局详情、观战协议转换、共玩/底蕴分析、单局历史与统计分析、游戏时长统计、对局指标、玩家在线状态、玩家视觉产物、群体排行、战绩可见性状态计算、网页产物标识与路由规则、B 站订阅流程及 KPL 推送流程。问候、QQ 身份映射、表情选择、URL 参数和巅峰分段解析由 `business/user_helpers.py` 实现，表情配置读取仍通过 `zfile.py`，AI 选择仍通过 `zapi.py`；旧式 AI 消息类型的提示词组装与标准/联网适配器选择由 `business/ai_prompts.py` 实现，实际请求只调用 `zapi.py`；每日战报的排行正文与代表局文字、图片、AI 文案顺序由 `business/daily_notification.py` 组装；结构化历史的 PostgreSQL 优先读取与 JSON 应急聚合由 `business/history_data.py` 实现，目录枚举和文件读取仍通过 `zfile.py`；需要调用其他业务能力时通过运行时导入 `zfunc.py` 的公开接口，避免形成模块导入环。`representative_battle_query_impl()` 必须隔离正式文字、图片路径、图片下方 AI 文案与调试载荷；`representative_battle_range_debug_impl()` 只组装每日三类指数冠军的纯文本区间调试结果。英雄战力列表与常用英雄摘要由 `business/hero_profiles.py` 实现；英雄名安全解析、拼音转换及天元之弈梯度 API、头像缓存和长图编排由 `business/hero_tier.py` 实现；英雄统计实现只负责结构化统计与文字组装；今日英雄的候选选择、推荐依据和文案组装由 `business/today_hero.py` 实现，Redis 当日缓存与历史列表只通过 `zfunc.py` 的窄接口读写，皮肤和技能资产只通过 `zfile.py` 访问；战绩分析视图与单局详情的文本、网页载荷和图片生成编排由 `business/battle_detail.py` 实现；观战接口到共玩分析结构的严格转换及对局预言编排由 `business/battle_watch.py` 实现；单局详情读取时的目标玩家视角重建及历史胜率、英雄、受益度、交集统计由 `business/battle_history.py` 实现；共玩/底蕴数值计算、阵营汇总、图片载荷与历史记录对象由 `business/battle_power.py` 实现，评估记录的 Redis 写入仍通过 `zfunc.py`，文件路径与读写仍通过 `zfile.py`；王者与 Steam 最近时长汇总、群体排行和局部错误聚合由 `business/game_activity.py` 实现，Steam 请求只调用 `zapi.py`，图表路径只由 `zfile.py` 提供；英雄阵容对位的精确/分路回退统计与可选 AI 短评由 `business/battle_matchup.py` 实现；正式对局判定、评分均值与团队贡献系数统一由 `business/battle_metrics.py` 实现；玩家战绩列表与资料拉取、当日结构化转换、技能缓存补齐、单局详情补拉及指定用户回填由 `business/player_data.py` 实现，API 通过 `zfunc.py` 的优先级门面调用，路径与写入通过 `zfile.py`；单人当天与历史战报的日期解析、数据选择和文本组装由 `business/player_report.py` 实现；评分趋势图与观战截图流程由 `business/player_visuals.py` 实现，输出路径只由 `zfile.py` 提供；群体排行的并发采集、榜单展示、遍历错误格式化及本地巅峰排名由 `business/rankings.py` 实现；王者与 Steam 在线状态的并发遍历、分组展示和局部失败聚合由 `business/online_status.py` 实现；战绩可见性的关联 QQ 解析与禁用名单状态迁移由 `business/battle_visibility.py` 实现，Redis 读写、日志和禁言任务编排仍保留在 `zfunc.py`；网页产物的 hash、路由映射和元数据组装由 `business/web_artifacts.py` 实现，Redis 发布仍通过 `zfunc.py`，文件路径与写入仍通过 `zfile.py`；B 站订阅解析、身份更新、最新视频与轮询推送流程由 `business/bili_video.py` 实现，订阅存储、去重集合、分布式锁和消息出口仍通过 `zfunc.py`；KPL 比赛筛选、图片提示词和推送流程由 `business/kpl.py` 实现，推送锁与已推送集合仍通过 `zfunc.py`，图片落盘通过 `zfile.py`，消息拼装与发送通过 `utils/message_sender.py`。
- `hok/zmemory.py`：所有 AI 对话记忆、摘要、长期记忆、表情记忆相关的读写与策略接口，并提供群聊历史的 jieba 分词、BM25、多 query RRF 融合和上下文展开算法；语义事实的校验/检索是纯函数，Redis 操作由 `zfunc.py` 完成；旧强制记忆只允许显式 recall 读取，不再注册“记住”关键词 matcher。每次 chat 都读取当前用户保留的直接问答，按“最近 `ChatActiveDialogueContext` 轮 + 最多 `ChatActiveDialogueRelevant` 轮 BM25 相关旧对话”筛选，再以原生 `user` / `assistant` 角色按时间顺序注入；具有可信群范围时，由 `zchat.py` 强制模型先生成互补 query 并调用群聊检索工具，结果作为不可信 tool observation 进入上下文。默认保留最近 10 轮直接问答（`ChatActiveDialogueRetention`），`nomem` 只禁用长期事实工具，不再禁用直接对话或强制群聊检索。不得自动混入历史 summary、强制记忆或历史回复引用内容；群聊命中和用户本次明确引用的消息都作为本次不可信资料，不写入长期记忆。主动问答的 Redis 读写通过 `zfunc.chat_active_dialogue_load/save()`，沿用 `hok:memory:active_chat:<QQ>` 和 `time/Q/A` 数据格式；追加与裁剪在同一 Redis 事务执行，时间通过 `ztime.py`，兼容旧数据。
- `hok/chat_roles/`：chat 角色扮演的可插拔角色包；每个内置角色模块的 `ChatRole` 只维护该角色自身的信息与表达特征，角色无关的通用约束集中维护并在角色信息之后单独追加；角色通过包级注册表接入，当前默认角色由 `variables_static.json` 的 `chat_role` 指定。`custom.py` 只负责用户自定义角色记录的纯校验与提示词渲染，联网和 Redis 分别通过 `zapi.py` 与 `zfunc.py` 完成；用户自定义角色存在时覆盖默认角色。
- `hok/zscheduler.py`：所有定时/间隔任务的声明、注册与定义（不要在别处私自创建 scheduler 任务）；旧版凌晨 03:30 的 `daily_user_summary` 已停用，禁止重新注册会清理原始聊天记录的摘要任务；每日 23:30 的 `notify_msg()` 统一发送当日王者战报，并按“代表局文字 → 图片 → AI 文案”的顺序发送代表性对局；网页底蕴分享保留阵容 AI 短评参数，当前以 `False` 禁用；B 站 UP 新视频轮询任务只在此注册，实际检查与推送编排调用 `zfunc.py`。
- `hok/zstatic.py`：**静态变量**导入必须放在这里（从文件与系统环境变量导入）；其他模块通过 `from .zstatic import *` 获取静态变量。
- `hok/ztime.py`：时间工具与日期处理统一入口；任何时间计算、格式化、时间窗口判断都应调用这里的接口；代表局查询中的自然语言日期及区间统一由 `parse_representative_battle_date()`、`parse_representative_battle_date_range()` 解析，群聊历史检索时间边界统一由 `parse_chat_time_bound()` 解析。
- `hok/zutil.py`：基础工具集；统一导入常用库与通用小工具（不要在各处散落重复 import 与重复工具实现）。
- `hok/utils/message_sender.py`：发送消息统一入口；任何对外消息发送必须调用此模块的函数接口（禁止绕开直接调用底层适配器发送）。
- `hok/zapi.py`：外部 API 的稳定兼容门面，只负责从 `hok/api_adapters/` 导出业务层可调用的公开接口；不得在门面中新增协议细节或业务编排。AI chat 的单轮协议适配通过该门面对外提供，普通聊天的 Chat Completions 与兼容 Responses 均归一化为 `content`、`tool_calls`、`output_items`；多轮编排留在 `zchat.py`。
- `hok/api_adapters/`：按外部服务拆分请求封装、签名、响应解析、超时与协议级重试；当前包含王者官方 API、AI/图片、天元之弈、Steam 与 B 站适配器。普通聊天及 `ai_api()` / `ai_function()` 当前临时使用 DeepSeek 官方 Chat Completions endpoint `https://api.deepseek.com` 与 `deepseek-flash`，显式 `trust_env=False` 直连且不使用代理；由于 harness 以命名工具开始链路且 DeepSeek 思考模式要求续传 `reasoning_content`，所有携带 tools 的轮次必须统一设置 `thinking.disabled`，不得在同一工具链中从非思考强制轮切回思考自动轮，最终无工具请求可使用官方默认模式。Steam、APIMart 与 OpenRouter 搜索必须通过 `api_adapters/proxy.py` 显式绑定 `Proxy.clash_url` / `HOK_CLASH_PROXY_URL` 指定的 Clash 代理，并禁用环境代理继承；缺少配置时不得直连。适配器负责工具 schema 与 tool result 的协议转换，并完整保留 assistant 的 `tool_calls`、`reasoning_content` 供后续轮次回传；`web_search` 工具通过 OpenRouter Chat Completions 的 `openrouter:web_search` server tool 执行，密钥默认读取 `variables_static.json` 的 `openrouter_api_key`，可由 `HOK_OPENROUTER_API_KEY` 覆盖，归一化真实引用并在不可用时返回错误 observation；普通聊天不得回退到应用 Bot 的 Chat Completions endpoint；荣耀战力指定地区 `ranklist` 只在王者适配器组装和发送；B 站 UP 视频的 WBI 签名、用户/视频搜索、用户卡片请求和响应归一化只在 B 站适配器实现。适配器不得读取 Redis 或承担业务队列优先级调度，相关逻辑留在 `zfunc.py`。
- `hok/zkpl.py`：KPL 数据统一入口；仅 `get_match_list_json()` 与 `get_match_detail_json()` 负责获取赛程和完整比赛数据，其他 KPL 转换与兼容接口必须调用二者。
- `hok/zdiy.py`：自定义/临时扩展的业务能力聚合处；当能力稳定后应迁移到职责更明确的模块（`zfunc.py` / `tools/` / `zapi.py` 等），避免长期堆叠。

HOK_QQBot 与 Web 的全部 Redis 数据统一存放在 `REDIS_DB`（DB0），以 `hok:` 为根命名空间；独立 Planit 应用继续使用 DB9。`zdynamic.py` 只创建一个 DB0 Redis 客户端，历史兼容别名必须指向同一客户端，不得再连接 DB1–DB7 或 DB10。Key 使用冒号分层命名并由 `zstatic.py` 暴露共享常量，例如 `hok:web:artifact:<token>`、`hok:battle:liked_ids`、`hok:queue:*`、`hok:hero:*`、`hok:evaluator:*`、`hok:chat:*` 与 `hok:memory:*`。跨 DB 收敛统一通过 `scripts/consolidate_redis_to_db0.py` 执行，正式执行前必须生成可恢复的 DUMP 备份。

### 1.0 Chat 回复、引用与运行记录

- `event_handlers/chat.py` 解析本次显式引用的消息；优先使用 `event.reply`，缺失时由 `zevent.f_chat()` 通过 OneBot `get_msg` 补读，只读取本次引用，不递归拉取历史引用。图片/视频仅注入未识别内容的占位符，不伪造视觉识别。
- `zchat.py` 返回最终回答、图片产物和结构化运行记录；简短确认结合上轮提议继续，必要参数缺失时只澄清缺项，不把肯定回应默认视为告别。最终回答统一调用 `tools/chat_text.normalize_qq_text()` 转为 QQ 纯文本，再由 `format_chat_reply()` 按 `namenick` 替换内部玩家键、纠正附带别名并清理身份/记录 ID；兜底摘录的发言者也只显示昵称或群成员。模型身份表必须提供明确的 `namenick`，别名仅用于解析，最终正文和图表标签使用配置昵称；配置昵称本身为缩写时不得擅自扩写。默认简短回答，只保留结论和必要数据，用户明确要求完整名单或详细分析时再展开。记忆保存和页面 answer 使用同一份最终文本；原始 API payload 继续完整保留，不经过回复格式化。记录上下文加载的轮数、消息数和最新时间。记录每次模型请求、每个工具调用与对应 observation、失败/跳过状态和耗时。失败通过 `ChatRunError` 保留已经完成的轨迹。每轮在调用适配器前保存 `context_injection`，完整快照模型本轮可见的 system messages、非 system 上下文、工具定义与 tool choice；同时保存实际发送与收到的完整 JSON `request_payload` / `response_payload`（包括业务模型返回字段及后续续传字段），不采集 HTTP headers；保留 finish_reason、usage、正文长度、错误阶段、异常原因链和栈位置。空正文最多追加一次禁用工具的补试（`ChatEmptyResponseRetries` 默认 1，限制 0–1），仍失败时返回已获取资料的兜底回复且不写入对话记忆；记忆保存失败保留正常答案并记录警告。
- `business/chat_trace.py` 负责纯数据脱敏、异常链和统计；分享页完整展示模型请求/响应 payload 及所有工具的实际参数与 observation，包括系统消息、直接对话、用户本次引用、工具定义、记忆、群聊原文及 API 返回字段。payload 不限字符、数组、字段数量或嵌套预览层级；只脱敏凭据并排除 HTTP headers，不按工具类别隐藏。发布不再使用旧 2 MiB 限制。工具发给模型的 observation 仍受上下文预算约束，分享记录保留工具原始结果与实际发送的 payload，两者各自如实展示。
- `zfunc.chat_prepare_reply()` 编排图表合并与记录发布；`zfile.combine_chat_plot_images()` 用 Pillow 将多张 harness PNG 等比合为一张，默认两列，`ChatPlot.collage_width` / `collage_columns` 可调整宽度/列数。合图失败保留原图，记录发布失败保留答案并提示链接不可用。
- `zfunc.chat_publish_trace()` 将脱敏记录写入 DB0 `hok:web:artifact:<48位随机hex>`，由 Web `/chat-trace?key=...` 展示。`ChatTraceExpireSeconds` 默认 604800 秒，网页原图路径只允许当前产物目录的 `chat_plot_<uuid>.png`；图片仍遵守已有清理周期。
- `utils/message_sender.add_chat_result_msg()` 将纯文本、图表和末尾运行记录链接组成一个 QQ 消息，只入队一次。默认上限为 10 轮工具循环，加至多一次收束回答请求和一次空正文补试（最多 12 次模型请求）、16 次实际工具调用和 4 张源图；多个源图默认先合并再发送。

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

- `hok/tools/chat_sql.py`：模型 SQL 的纯 AST 解析、命名参数替换、只读语法与函数白名单校验；不得连接数据库。
- `hok/tools/chat_plot.py`：五种图表模板、JSON 数据和受限 Python 校验，经 `zfile.py` 调用绘图 worker。
- `hok/plot_runtime/worker.py`：独立绘图运行时，逐节点解释 Python AST，不执行任意代码；只允许 numpy/pandas/matplotlib/seaborn 的明确操作。该边界例外允许 stdin/stdout、进程资源限制和沙箱内临时字体缓存；不得导入应用配置或处理正式文件路径。Linux 必须使用 bubblewrap 隔离文件系统与网络，缺失时拒绝执行。
- `hok/tools/chat_text.py`：使用 `markdown-it-py` 将模型 Markdown 解析为 QQ 纯文本，去除标题、强调、引用、代码围栏和链接语法，表格转为字段值行，保留代码和数学中的字面符号；`format_chat_reply()` 接收配置昵称及身份映射，只处理最终纯文本中的内部玩家键与身份字段，普通词语、统计数值和公开链接保持原样。
- `hok/tools/chat_runtime_diagnostic.py`：管理员手动触发的只读 chat 运行诊断；验证 DeepSeek 直连配置、普通文本请求以及“强制工具调用 → observation → 自动续传”协议，输出仅含脱敏摘要。该工具不得接入应用启动、systemd 重启或 GitHub Actions 自动部署检查，避免增加发布耗时和模型调用费用。
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

- `database/chat_readonly.sql`：幂等创建 `hok_chat_reader` 与十张游戏表的显式列授权，不包含密码、不修改游戏数据；配置与使用见 `database/CHAT_AGENT.md`。
- `database/schema.sql`：结构化历史库的 schema、表、外键与查询索引。
- `scripts/import_json_to_postgres.py`：幂等回填入口；只读扫描原始 JSON，并通过文件大小与纳秒 mtime 清单跳过未变化文件。
- `scripts/migrate_group_chat_history_to_postgres.py`：将 DB0 `hok:chat:group:*` 幂等迁移到私有群聊表；默认只预览，`--apply` 必须先生成 0600 DUMP 备份，逐消息验证 SQL 结果并保留 Redis 原数据。

### 1.5 部署运行方式

- 部署服务器上的 NoneBot 进程由 `hok-nbot.service` 统一管理，禁止在发布流程中再使用 `nohup` 或按端口手工结束进程。
- `deployment/` 是跨 Linux 主机部署包：`config/` 保存无密钥模板，`systemd/` 保存可渲染单元，`nginx/` 保存反向代理模板，`scripts/` 提供安装、检查与 bundle 构建，`bin/` 保存服务启动包装器；调整该结构时必须同步维护 `deployment/README.md`。
- Aliyun 整机部署以 `/srv/modules/{hok,personal-site,clash}` 为三个应用模块；每个模块维护 `module.json`、`apps/`、`config/`、状态/日志、`systemd/`、`nginx/` 和 `ops/`。HOK 的物理代码路径为 `hok/apps/{NBot,Web}`；BotDemo、Lagrange 与旧 NapCat installer 已在完整导出和 Git bundle 备份后移除，HOK 不再依赖 `/QQBot` 下的兼容入口。
- 三个统一入口为 `hok.target`、`personal-site.target` 与 `clash.target`，子服务用 `PartOf=` 归属模块，原服务名称保留供 CI 单独重启。Nginx、Redis、PostgreSQL、证书和 Actions runner 是共享基础设施，不随模块停止；个人网站 target 停止 OAuth/API 后，静态页面仍由共享 Nginx 提供。
- `deployment/server_modules/` 保存服务器迁移、带回滚日志的目录整理、模块管理及私有导出工具；HOK 导出只抓取 HOK PostgreSQL 库和 Redis DB0 的 `hok:*`，不得混入 PlanIt DB9。导出包含密钥和 QQ 会话，必须使用私有权限与 SSH 传输。
- `/opt/hok-qqbot/{nbot,web}`、`/etc/hok-qqbot`、`/var/lib/hok-qqbot` 与 `/var/log/hok-qqbot` 是独立的全新 HOK 安装模板布局，不是现有 Aliyun 模块的实际路径；新主机恢复细节见 `deployment/server_modules/README.md`。
- GitHub Actions 在 `/srv/modules/hok/apps/NBot` 完成代码同步后通过 `systemctl restart hok-nbot.service` 发布，并以 `systemctl is-active` 验证启动结果。
- 新版 `deploy_runner.sh` 默认调用项目内 `.venv/bin/nb`，允许 `HOK_NB_BIN` 覆盖；代理、CLI 路径和服务目录通过配置注入，不得新增硬编码。Aliyun 现有 CLI 在主机 Conda 中，路径和代理已集中于 `hok/config/nbot-host.env`，应用虚拟环境继续复用；既有运行日志通过 `log` 链接进入 `hok/logs/nbot`，新装模板进程输出进入 journald，HOK Exception 仍写入配置的错误日志目录。

## 2. 配置与变量的来源（必须遵守）

### 2.1 配置文件（``）

- `config.yaml`：王者荣耀/Steam/AI 的 API-Key、AI 模型、QQ群号、王者荣耀 request 参数、服务器 IP/域名等配置。`ChatAPI` 当前配置 DeepSeek 官方普通聊天的 `base_url`、`model`、空 `proxy_url` 与可选 `api_key`；官方 endpoint 缺少独立 key 时可临时复用既有 `QQBot.deepseek_key`，新部署仍优先通过私有环境变量 `HOK_CHAT_API_KEY` 注入。`Proxy.clash_url` 只配置 Steam、APIMart 与 OpenRouter 搜索的 Clash 出口。
- `config.yaml` 的 `OpenRouterSearch`：配置 chat 联网搜索的 `base_url`、`model` 与 `engine`；API key 默认读取 `variables_static.json` 的 `openrouter_api_key`，可由 `HOK_OPENROUTER_API_KEY` 覆盖，网络出口复用 `Proxy.clash_url`。
- `config.yaml` 的 `PostgreSQL.dsn`：PostgreSQL 本地连接串；部署环境可由 `HOK_DATABASE_DSN` 覆盖。`PostgreSQL.archive_json` 为 `false` 时历史数据数据库单写，写库失败才应急落 JSON。
- `variables_static.json`：OpenRouter API key、用户 QQ 号、王者荣耀 roleid/userid、用户昵称、SteamID、常见俚语缩写、赛季起止时间、英雄 ID 映射、部分功能 prompt 等稳定数据。
- `variables_dynamic.json`：动态变量初始值，例如是否记忆、机器人是否开放、英雄梯度、今日新闻、上一次查询战绩时间、今日导出失败用户名单、B 站 UP 视频轮询开关等；运行时需要跨部署持久化的业务状态必须放 Redis，不得依赖 Git 工作区文件保存订阅、用户状态或去重状态。

原则：
1. **任何可能变化的值**不得硬编码在业务逻辑里，必须进入上述文件或对应的静态/动态变量模块。
2. `zstatic.py` 负责加载静态配置；`zdynamic.py` 负责加载动态配置初始值，不作为运行时持久化写入入口。
3. 部署环境可通过 `HOK_CONFIG_FILE`、`HOK_STATIC_VARIABLES_FILE`、`HOK_DYNAMIC_VARIABLES_FILE` 指向 `/etc` 下的外置配置；未设置时才读取 `BOT_PATH` 下同名文件。

### 2.2 Linux 环境变量（在 `hok/zstatic.py` 导入）

部署环境下预计存在以下环境变量（缺失时的处理策略以现有代码为准，禁止凭空新增“变量不存在”的冗余判断链）：

- `REDIS_CONF`：Redis 配置文件路径。
- `BOT_PATH`：Bot 部署目录。
- `HOK_ENV_FILE`：可选 dotenv 路径；systemd 部署优先用 `EnvironmentFile` 直接注入，不要求存在 dotenv。未指定时，本地调试另加载 `BOT_PATH/.env.local`（Git 忽略），用于保存私有 API 密钥。
- `HOK_CHAT_BASE_URL`、`HOK_CHAT_API_KEY`、`HOK_CHAT_MODEL`、`HOK_CHAT_PROXY_URL`：覆盖 `config.yaml` 的 `ChatAPI` 对应字段，由 `zstatic.py` 统一导入为 `chat_api_config`；显式空 `HOK_CHAT_PROXY_URL` 必须覆盖文件中的代理并表示直连，客户端仍禁止继承环境代理。
- `HOK_OPENROUTER_API_KEY`、`HOK_OPENROUTER_BASE_URL`、`HOK_OPENROUTER_SEARCH_MODEL`、`HOK_OPENROUTER_SEARCH_ENGINE`：覆盖静态变量中的 OpenRouter key 或 `OpenRouterSearch` 对应字段，由 `zstatic.py` 统一导入为 `openrouter_search_config`；实际请求统一走 `HOK_CLASH_PROXY_URL` 指定的 Clash 出口。
- `HOK_CHAT_READONLY_DSN`：专用 `hok_chat_reader` 连接串，必须通过私有环境文件注入；`ChatSQL` 管理查询限制，`ChatPlot` 管理绘图上限及字体。
- `HOK_CLASH_PROXY_URL`：覆盖 `config.yaml` 的 `Proxy.clash_url`，由 `zstatic.py` 导入为 `clash_proxy_url`；Steam 与 APIMart 当前默认使用 `http://127.0.0.1:7890`，也支持 `socks5h://127.0.0.1:7891`。
- `HOK_CONFIG_FILE`、`HOK_STATIC_VARIABLES_FILE`、`HOK_DYNAMIC_VARIABLES_FILE`：外置配置文件路径。
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

# HOK_QQBot NBot — 子项目补充规范

本文件只记录 `NBot/` 子项目的目录职责、配置来源、调用边界和运行约定。通用代码规范、仓库边界、README 定位与 `.gitignore` 分层规则见根目录 `AGENTS.md`。

## 1. 目录与文件职责（`hok/`）

以下规则适用于 `hok/` 下所有代码。

- `hok/__init__.py`：NoneBot 插件入口；注册插件元信息并集中加载配置、静态变量、动态变量、API、事件、文件、业务函数、定时任务与时间工具。
- `hok/config.py`：Pydantic 配置模型定义；除非明确需要，否则不要新增依赖或复杂逻辑。
- `hok/zdynamic.py`：**动态变量**导入与初始化必须放在这里；其他模块通过 `from . import zdynamic as dmc` 读取动态配置初始值；运行时需要跨部署持久化的状态必须通过 Redis 业务接口保存。 新 QQ agent 的进程内服务引用 `qq_agent_service` 在此初始化，持久任务仍写 DB0。
- `hok/zevent.py`：NoneBot matcher 声明、注册及最薄处理器入口；只做初步解析、分发与调用接口，不实现具体业务算法。通用路由谓词放在 `event_rules.py`，群消息最初捕获放在 `event_ingress.py`，可独立测试的处理器解析与业务分发放在 `event_handlers/`；普通用户的“代表局”自然语言查询在此路由且必须以 `#` 或 `＃` 开头，正式回复不得附带调试信息；`##rep3` 仅供管理员按日期区间调试每日三类指数冠军；`#巅峰排名` / `#巅峰排行` 仅调用 `zfunc.py` 的本地结构化历史排名流程；`#梯度` / `＃梯度` 仅调用 `zfunc.py` 的梯度长图流程；消息中同时出现“战力”和“查询”时调用 `zfunc.py` 的指定地区荣耀战力查询流程，英雄名和地区名顺序不限；B 站 UP 视频订阅命令的剥离与业务分发由 `event_handlers/bili_video.py` 完成。
- `hok/event_rules.py`：不依赖 NoneBot 类型的消息路由谓词、用户权限和命令判定；不得注册 matcher 或发送消息。
- 管理员 `##health` / `##连通性检查`（兼容全角井号）是完整匹配的独立 handler，不进入 AI 工具链。`event_handlers/service_health.py` 调用 `zfunc.service_health_check()`，由 `business/service_health.py` 维护外部服务清单与报告；HTTP 最小探测只经 `zapi.service_health_http`，QQ 状态经只读 `utils/qq_profiles.py`，PostgreSQL 经 `zdb.service_health_ping`，DB0 PING 在 `zfunc.py`，systemd 仅经 `zfile.service_health_systemd` 读取显式配置的 Bot 依赖 unit，不枚举本机其他 service、timer 或 socket，不检查个人网站、OAuth、SSH、Actions runner 等无关服务。检查使用当前解析后的模型端点与实际代理路由；模型只读列举、Steam/B站最小 GET、数据库 SELECT 1、OneBot get_status、worker health 及健康端点，不生成内容、不搜索、不发送测试消息、不重启服务。HEAD 只能报告可达，不能当作鉴权或业务正常；HTTP 401/403、限流、缺配置、未安装 unit、非 systemd 主机及总预算未完成均明确区分。配置集中 `config.yaml#ServiceHealth`；进程锁在 `zdynamic.py`，单项并发/超时、总预算及取消清理隔离；报告仅经统一消息出口 `add_forward_msg(event=...)` 向原群或原私聊发送一份聊天记录转发，固定两个节点，第一条列异常及待确认项（含仅可达、跳过、未完成），第二条仅列正常项；空组保留说明。不回显凭据、URL、响应正文或传输异常原文，不自动注册监控任务。
- 本次消息直接包含 `at` 到机器人 `self_id` 且没有 `#` / `＃` 前缀时，`zevent._direct_chat` 在业务关键词路由前调用同一 AI 处理器；检查适配器保留的 `original_message`，不能用引用、昵称或 `to_me` 推断直接提及。前缀命令继续按原路由处理；管理员命令也必须来自本次前缀文本。直接提及沿用相同的 QQ 白名单、禁用检查、休眠与维修规则，不因「在线」「战力查询」等词落入旧业务命令。
- `hok/event_ingress.py`：群消息进入业务路由前只保存一次原始归档，绑定用户、群号、消息及引用 ID；保存失败只记录错误，不阻断路由。没有被动聊天缓存或摘要写入。
- `hok/event_handlers/`：不注册 matcher、不导入 NoneBot 适配器的处理器解析与业务分发；当前包含英雄查询与视觉产物、玩家战报/排行、实时对局预言、历史战绩查询、管理员历史导出、代表局查询/调试、底蕴与时长查询、AI 聊天输入、表情生成、戳一戳决策及 B 站订阅命令处理器，返回文本、消息序列或结构化结果给 `zevent.py`，消息发送和 `MessageSegment` 拼装仍留在入口/出口层。历史导出命令解析、逐用户调用和失败汇总由 `event_handlers/history_export.py` 完成；代表局普通查询、单日调试信息和区间调试结果由 `event_handlers/representative.py` 归一化；玩家在线状态、群体排行、单人战报及最近单局、战绩视图与上次详情由 `event_handlers/player_reports.py` 分发；英雄战力、今日英雄参数、评分图与观战截图由 `event_handlers/hero_visuals.py` 分发；实时对局查询、五分钟缓存与预言计算参数由 `event_handlers/spoiler.py` 管理；底蕴/时长的个人与排行分流由 `event_handlers/activity.py` 完成；聊天文本替换、记忆开关、用户和群消息元数据（不再解析 `&`）由 `event_handlers/chat.py` 归一化；表情模板、提示词及图片参数由 `event_handlers/emoji.py` 解析并调用生成工具；戳一戳的观战截图、底蕴触发、冷却及随机回复由 `event_handlers/poke.py` 决策；历史查询的单局图片组合仍由 `zevent.py` 完成，多局网页产物由 `zfunc.py` 编排。
- QQ 入口绑定真实发送者 QQ、当前群、消息 ID 与输出目的地，不采用网页默认 example_user_10 身份。群请求只能读取当前群；仅可信入口确认发送者等于 `QQBot.super_qid` 的管理员私聊具有跨群范围。普通私聊无群聊权限。模型不得修改身份、授权或任务目的地；群检索按 `(group_id, message_id)` 排除当前群消息，私聊消息 ID 不用于排除群聊。SQL 使用共享目录动态生成并整批只读校验；不改业务数据库 schema、不回退业务写账号。
- `hok/zfile.py`：文件/IO 读写统一入口；所有 IO（读写文件、落盘缓存、路径拼接、动态变量重载等）必须通过此模块提供的接口完成；荣耀战力地区树统一从 `data/honor/districts.json` 读取；历史日期枚举与每日数据读取通过此模块转发到 PostgreSQL，数据库异常时才读取应急 JSON；网页历史 JSON 的路径构造与写入也统一由此模块负责；梯度英雄头像属于长期资产，按英雄 ID 与头像 URL 指纹保存在 `resources/wzry_images/hero_avatars/`，`file_transfer/` 只保存每次查询重新生成的梯度长图；HOK Exception 运行时错误记录统一追加到 `log/error.log`；生成 Python 和绘图执行由外部共享沙箱负责，此模块只处理最终产物 PNG 校验、落盘、合图及公开路径。 `store_agent_artifact()` 校验独立 worker 返回的图片字节并保存为 trace 兼容 PNG；图片 IO 不放入内核。
- `hok/zdb.py`：PostgreSQL 业务数据访问入口，维护结构化游戏历史、群聊归档和导入清单。群聊以 `(group_id, message_id)` 幂等保存，`group_chat_messages` 私有表与 payload 不向模型披露。模型只读 SQL 由外部 worker 使用独立 `hok_chat_reader` 与 `shared/agent` 目录执行；业务写账号不用于模型查询。`load_group_chat_messages` 的可选 `user_id` 为入口绑定的参数，用于表情包最近发言，不接受模型生成 SQL。
- `hok/zfunc.py`：业务门面、跨领域编排与 Redis 业务访问入口。`agent_runtime_start/stop`、`agent_chat`、`agent_task_tick`、`agent_clear_memory` 和 `agent_register_tool` 接入共享外部 agent；消息与产物分别通过 message_sender 和 zfile 发送/落盘。群聊历史写入 zdb，失败才保存 DB0 应急 list；读取时 SQL 重复项为准，Redis 原数据在迁移验证前不得删除。`ChatHistoryMaxMessages` 仅限制应急 list。`recent_emoji_messages` 读取当前群当前发言者的归档及应急消息，`emoji_message_state` 保存 `hok:emoji:*` 下的短期表情决策/去重缓存；不再保存额外被动聊天或摘要。游戏 API 优先级、其他业务 Redis 状态及跨领域编排继续由此门面管理。
- QQ AI 的现有业务函数由 `qq_agent/business_functions.py` 显式绑定到 `zfunc.py`，`agent_console/function_calls.py` 提供通用目录、分页搜索、单函数参数披露、严格校验与执行。`hok_business` 只有 `search_hok_functions` / `describe_hok_function` / `call_hok_function` 三个隐藏工具，初始上下文不注入完整目录或所有 schema；前台和定时 agent 共用，固定 message 任务不调用函数。本轮须先 describe，逐次检查真实 principal 的 scope；参数不接受身份、群范围或目的地，模型不能指定模块、路径或任意函数。本人今日英雄从可信 identity 绑定且不能绕过次数限制。`agent_register_function()` 供可信启动代码以参数模型、处理器、scope 和 effect 扩展同一目录，不扫描/导入模型指定代码；新 scope 仍需入口授权。当前仅 QQ 注入此目录，本地 Web 不自动导入 NoneBot 或连接业务写账号。
- 业务函数执行用 ContextVar 阻止经 zfunc 重入 AI/工具注册/调度入口；同轮相同函数和归一化参数成功复用、失败/取消不重放，并限制每轮调用数和结果大小。全目录保留一个执行槽以保护旧渲染器共享路径；同步线程超时或取消后仍占槽到真实结束，不宣称已停止。后台任务统一拒绝 create_task，重复执行仅使用原任务周期/次数，不允许派生任务循环。限制集中 `config.yaml#QQAgent.business_functions`。业务函数返回显式 FunctionOutput，图片路径只在可信适配层流转，经 `zfile.store_business_agent_image()` 校验产物目录及像素、复制为标准 chat_plot PNG，再由 QQOutput 的 run_id 隔离临时产物进入现有事件、合图、运行记录及统一发送出口；路径不作为模型参数或 observation。禁止登记 AI/调度/健康检查/全局推送入口，新增函数须审核间接调用与副作用。
- `hok/business/`：按领域拆分的不含 Redis、NoneBot、直接 HTTP 和直接文件读写的业务实现；当前包含用户辅助、AI 文案组装、每日战报、代表局、结构化历史读取、历史自然语言查询、荣耀战力地区解析、英雄资料、英雄统计、今日英雄推荐、玩家战绩采集、单人战报、战绩分析视图与单局详情、观战协议转换、共玩/底蕴分析、单局历史与统计分析、游戏时长统计、对局指标、玩家在线状态、玩家视觉产物、群体排行、战绩可见性状态计算、网页产物标识与路由规则、B 站订阅流程及 KPL 推送流程。问候、QQ 身份映射、表情选择、URL 参数和巅峰分段解析由 `business/user_helpers.py` 实现，表情配置读取仍通过 `zfile.py`，AI 选择仍通过 `zapi.py`；游戏业务文案的提示词组装与标准/联网适配器选择由 `business/ai_prompts.py` 实现，实际请求只调用 `zapi.py`；每日战报的排行正文与代表局文字、图片、AI 文案顺序由 `business/daily_notification.py` 组装；结构化历史的 PostgreSQL 优先读取与 JSON 应急聚合由 `business/history_data.py` 实现，目录枚举和文件读取仍通过 `zfile.py`；需要调用其他业务能力时通过运行时导入 `zfunc.py` 的公开接口，避免形成模块导入环。`representative_battle_query_impl()` 必须隔离正式文字、图片路径、图片下方 AI 文案与调试载荷；`representative_battle_range_debug_impl()` 只组装每日三类指数冠军的纯文本区间调试结果。英雄战力列表与常用英雄摘要由 `business/hero_profiles.py` 实现；英雄名安全解析、拼音转换及天元之弈梯度 API、头像缓存和长图编排由 `business/hero_tier.py` 实现；英雄统计实现只负责结构化统计与文字组装；今日英雄的候选选择、推荐依据和文案组装由 `business/today_hero.py` 实现，Redis 当日缓存与历史列表只通过 `zfunc.py` 的窄接口读写，皮肤和技能资产只通过 `zfile.py` 访问；战绩分析视图与单局详情的文本、网页载荷和图片生成编排由 `business/battle_detail.py` 实现；观战接口到共玩分析结构的严格转换及对局预言编排由 `business/battle_watch.py` 实现；单局详情读取时的目标玩家视角重建及历史胜率、英雄、受益度、交集统计由 `business/battle_history.py` 实现；共玩/底蕴数值计算、阵营汇总、图片载荷与历史记录对象由 `business/battle_power.py` 实现，评估记录的 Redis 写入仍通过 `zfunc.py`，文件路径与读写仍通过 `zfile.py`；王者与 Steam 最近时长汇总、群体排行和局部错误聚合由 `business/game_activity.py` 实现，Steam 请求只调用 `zapi.py`，图表路径只由 `zfile.py` 提供；英雄阵容对位的精确/分路回退统计与可选 AI 短评由 `business/battle_matchup.py` 实现；正式对局判定、评分均值与团队贡献系数统一由 `business/battle_metrics.py` 实现；玩家战绩列表与资料拉取、当日结构化转换、技能缓存补齐、单局详情补拉及指定用户回填由 `business/player_data.py` 实现，API 通过 `zfunc.py` 的优先级门面调用，路径与写入通过 `zfile.py`；单人当天与历史战报的日期解析、数据选择和文本组装由 `business/player_report.py` 实现；评分趋势图与观战截图流程由 `business/player_visuals.py` 实现，输出路径只由 `zfile.py` 提供；群体排行的并发采集、榜单展示、遍历错误格式化及本地巅峰排名由 `business/rankings.py` 实现；王者与 Steam 在线状态的并发遍历、分组展示和局部失败聚合由 `business/online_status.py` 实现；战绩可见性的关联 QQ 解析与禁用名单状态迁移由 `business/battle_visibility.py` 实现，Redis 读写、日志和禁言任务编排仍保留在 `zfunc.py`；网页产物的 hash、路由映射和元数据组装由 `business/web_artifacts.py` 实现，Redis 发布仍通过 `zfunc.py`，文件路径与写入仍通过 `zfile.py`；B 站订阅解析、身份更新、最新视频与轮询推送流程由 `business/bili_video.py` 实现，订阅存储、去重集合、分布式锁和消息出口仍通过 `zfunc.py`；KPL 比赛筛选、图片提示词和推送流程由 `business/kpl.py` 实现，推送锁与已推送集合仍通过 `zfunc.py`，图片落盘通过 `zfile.py`，消息拼装与发送通过 `utils/message_sender.py`。
- `hok/zscheduler.py`：所有定时/间隔任务的声明、注册与定义（不要在别处私自创建 scheduler 任务）；旧版凌晨 03:30 的 `daily_user_summary` 已停用，禁止重新注册会清理原始聊天记录的摘要任务；每日 23:30 的 `notify_msg()` 统一发送当日王者战报，并按“代表局文字 → 图片 → AI 文案”的顺序发送代表性对局；网页底蕴分享保留阵容 AI 短评参数，当前以 `False` 禁用；B 站 UP 新视频轮询任务只在此注册，实际检查与推送编排调用 `zfunc.py`。 QQ agent 启停 hook 与任务 tick 只在此注册；外部任务服务只领取/执行已持久化任务，不另建轮询循环。
- `hok/zstatic.py`：**静态变量**导入必须放在这里（从文件与系统环境变量导入）；其他模块通过 `from .zstatic import *` 获取静态变量。
- `hok/ztime.py`：时间工具与日期处理统一入口；任何时间计算、格式化、时间窗口判断都应调用这里的接口；代表局查询中的自然语言日期及区间统一由 `parse_representative_battle_date()`、`parse_representative_battle_date_range()` 解析，群聊历史检索时间边界统一由 `parse_chat_time_bound()` 解析。
- `hok/zutil.py`：基础工具集；统一导入常用库与通用小工具（不要在各处散落重复 import 与重复工具实现）。
- `hok/utils/message_sender.py`：发送消息统一入口；任何对外消息发送必须调用此模块的函数接口（禁止绕开直接调用底层适配器发送）。
- `hok/utils/qq_profiles.py`：QQ 资料与账号适配器边界，通过真实 bot 校验群成员列表并读取指定成员的新资料，不发送消息。`business/qq_profiles.py` 只对白名单字段、身份一致性和未知值做归一化；头像 HTTP 下载经 `zapi.qq_avatar_bytes()` 转发给 `api_adapters/qq_profiles.py`，不在业务层请求网络。配置来自 `QQProfiles`，由 `zstatic.qq_profile_config` 暴露。
- `hok/zapi.py`：外部 API 的兼容门面，从 api_adapters 导出业务函数。业务文案只使用单轮文本/图片接口；不提供第二套 agent 的工具或 Responses 编排入口。QQ 与网页模型协议由 `agent_console/provider.py` 适配，多轮编排由独立内核负责。
- `hok/api_adapters/`：按外部服务封装协议、签名、响应解析与重试；不读取 Redis。业务 AI 文案使用已配置 ChatAPI 单轮文本接口，图片与原有 Ark 文案接口继续保留。agent 的 DeepSeek 工具链与原生图片在外部 provider 处理，统一关闭工具链 thinking。阿里云 OpenSearch 与官方游戏请求显式禁用环境代理直连，Steam/APIMart 经配置的 Clash 代理，缺少代理时不回退直连。
- `hok/zkpl.py`：KPL 数据统一入口；仅 `get_match_list_json()` 与 `get_match_detail_json()` 负责获取赛程和完整比赛数据，其他 KPL 转换与兼容接口必须调用二者。
- `hok/zdiy.py`：自定义/临时扩展的业务能力聚合处；当能力稳定后应迁移到职责更明确的模块（`zfunc.py` / `tools/` / `zapi.py` 等），避免长期堆叠。

HOK_QQBot 与 Web 的全部 Redis 数据统一存放在 `REDIS_DB`（DB0），以 `hok:` 为根命名空间；独立 Planit 应用继续使用 DB9。`zdynamic.py` 只创建一个 DB0 Redis 客户端，历史兼容别名必须指向同一客户端，不得再连接 DB1–DB7 或 DB10。Key 使用冒号分层命名并由 `zstatic.py` 暴露共享常量，例如 `hok:web:artifact:<token>`、`hok:battle:liked_ids`、`hok:queue:*`、`hok:hero:*`、`hok:evaluator:*`、`hok:chat:*` 与 `hok:memory:*`。跨 DB 收敛统一通过 `scripts/consolidate_redis_to_db0.py` 执行，正式执行前必须生成可恢复的 DUMP 备份。

### 1.0 Chat 回复、引用与运行记录

- `event_handlers/chat.py` 解析本次显式引用与原生图片 URL，支持原生消息段及 CQ 字符串；引用优先取 `event.reply`，缺失时由注入的 OneBot `get_msg` 补读一次，不递归拉取引用链。通过外层引用作用域/消息 ID 校验后，合并转发只展开一层，优先读取 `forward.data.content`，否则经 `zevent.py` 注入的 `get_forward_msg(id=...)` 读取；兼容 OneBot `message/node.data.content` 与 NapCat `messages/sender/message`，同轮同 ID 只读一次。保留节点顺序和资料署名，署名不作为可信身份；子节点中的引用 ID、嵌套转发（包括内嵌内容）不继续读取，视频等媒体保留未读取提示。`QQAgent.forward_messages` 统一限制转发数、节点总数、总文字与总读取超时（默认3份/100条/12000字/10秒）；失败、无效或截断明确标记，取消向上传递。引用中的开头 `#` / `＃` 和机器人 @ 去除，其余内容仅作为资料，不参与命令路由或 `nomem` 解析。引用作用域/消息 ID 校验失败时不提供原文或媒体。QQ 外部适配器验证引用图片和直接图片后提供原生内容块，三者合并去重后共用单次图片数量/体积预算；合并转发超出图片数量时保留文字和额度内图片，并明确标记省略，不能因此阻断文字回答。
- `zevent.f_chat()` await `zfunc.agent_chat()`；所有分段输出、最终答案和后台通知由注入的 QQOutput 发往 `utils/message_sender.add_chat_result_msg(destination=...)`，入口不再重复发送最终结果。后台目的地与身份在创建任务时绑定。
- AI 定时任务的 `list_tasks` / `cancel_task` 在 QQ 群内对同群成员具有相同权限，范围以可信 principal、`qq_g_<群>_<创建者>` 会话和保存的群目的地共同校验；其他群、私聊与 Web 会话隔离，管理员私聊默认群不扩大任务权限。列表显式投影 creator 的真实 QQ 与名称和调度字段，不披露完整 principal、权限、租约或个人记忆；不修改原任务创建者、授权和目的地。引用定时消息时使用 `list_tasks(message_id=...)` 按当前群与真实 QQ 发送回执精确查询，再调用 `cancel_task`；没有关联不能按文案或 @ 对象猜测。QQOutput 仅从 origin=background 的可信事件 metadata 透传 task_id，经 `add_chat_result_msg(task_id=...)` 和统一队列保存；消费取得真实 message_id 后通过 `zfunc.agent_record_task_message()` 写 DB0 `hok:agent_runtime:console:task_message:<群>:<消息ID>`，TTL 来自 `QQAgent.task_message_link_ttl_seconds`（默认30天）。未取得回执不建立关联，关联保存失败不重发。旧消息与过期关联明确无法确认；固定消息、agent 最终/分批消息均沿用这条链路，不在独立内核增加QQ逻辑。
- 群聊 AI 入口默认在可信 `Principal.attributes.delivery.mention_user_id` 绑定真实发送者。`qq_agent/mentions.py` 的 `set_reply_mention`（chat_delivery 类别）允许同一 ReAct 模型按本次消息语义选择当前群其他成员、`user_id=all` 原生 @全体成员或明确不 @；提醒全群须选择 all，不能沿用默认 @创建者，仅说在群里发不等于 @全体。all 只限当前可信群，不按普通 QQ 查询资料，实际效果受 QQ 权限及额度限制；入口保留本次原生 @全体作为输入资料；非空个人目标必须通过注入的 QQ 实时资料读取器确认群成员身份，不能按昵称猜 QQ。覆盖按 run_id 隔离，仅影响之后的分段、最终消息及新建任务的原生 @，run.end 释放。`QQCapabilities.create_task` 只将验证后的选择复制到新任务 delivery，创建者、授权、会话与发送群不变，旧任务不被改写。当前消息中的其他原生 @ 由 chat 入口保留 QQ 资料，引用中的 @ 不代表本次要求。统一消息出口只采用可信 destination，模型正文、packet 字段、引用作者或后续发言人不能伪造提及。私聊、Web 及无绑定用户的旧目的地不猜测 @；非法目标拒绝入队，正文 CQ 字符串仍转义为 text。@ 不进入模型回复文本、两个回复版本或个人直接对话历史，内核不解释 QQ 提及。
- QQ 回复保留详细事实底稿和角色群聊版，默认发送群聊版，明确请求完整依据或长期偏好要求详细时可发送详细版。版本选择复用表达模型的结构化 `default_variant`，由 `QQAgent.reply.select_delivery_variant` 启用，只允许 chat/detailed；禁止根据“详细”“每个”“前几名”等正文关键词猜测。两版都通过 `normalize_qq_text()` 与 `format_chat_reply()` 清理 Markdown 和内部玩家/身份标识；图表标签与正文使用配置昵称。直接对话历史仅保存实际发送的一个版本。阶段性 `emit_message` 独立入队。
- AI 动作通过已披露的工具调用执行，不新增联网、记忆、定时等自然语言关键词分派。`#清除记忆` / `＃清除记忆` 是完整匹配的显式入口命令，关于该功能的提问、否定或引用不得因含有这四个字触发清除。原生消息解析、前缀业务命令、授权、common_expr 名称展开及显式 nomem 隐私选项继续在入口处理，不由模型越权修改。
- QQOutput 将内核模型/工具事件、真实 payload、两个回复版本和用量投影为现有 `chat_trace` v1；失败保留已完成 observation。原始事件与图片引用另外持久保存到 `log/qq_agent/<会话>/runs/<run_id>.jsonl` 和 `dialogue.jsonl`，不记录 HTTP headers，凭据脱敏。输入原图默认保存在非公开 `data/agent_inputs/`；日志和原图不进 Git 或部署包。
- `zfunc.chat_prepare_reply()` 合并图表并发布运行记录；合图失败保留原图，发布失败保留正常回答。`zfile.combine_chat_plot_images()` 默认两列合图。`chat_publish_trace()` 使用共享 `WebArtifacts.make_hash()` 生成16位随机hex，将 visibility=admin 的完整脱敏载荷写 DB0 `hok:web:artifact:<token>`，并在同一事务 LPUSH `hok:chat:traces` 摘要索引；TTL 默认7天，索引由 DynamicVariables.ChatTraceMaxRecords 限制（默认1000条）。Web AdminPage 的 /admin/funcs/chat-traces 统一分页检索，详情及公开 /chat-trace 对新载荷均验证管理员，旧公开链接保留至自然过期。QQAgent.show_trace_link 默认 false，QQ 不附运行记录提示、记录网址或链接失败提示，普通来源网址保持原样。QQOutput 对正常、失败、取消和固定后台提醒都发布记录，后两者不额外发送最终消息；私有 JSONL 照常保存，不迁移旧日志。输出 PNG 为 `chat_plot_<32位hex>.png`，遵守现有产物清理周期。
- QQAgent 预算与输入/输出规则统一来自 `config.yaml#QQAgent`；默认 10 轮、16 次工具、1200 秒、4 张输入图片。QQ/Web 与后台任务的默认整轮预算由外部 `agent_console/timeouts.py` 提供，渠道 budget 配置可覆盖；生图轮询600秒、RPC800秒、工具810秒，其他工具和RPC保持既有超时。生图等待中由 application 工具每120秒 emit 一次 progress，完成、失败或取消后清理提示等待器，不重新提交；远端RPC仍按既有取消规则消费响应，不宣称服务端任务已停止。后台领取租约覆盖整轮预算并额外预留300秒，避免长生图被其他worker重复领取。工具执行仍要求每个调用产生 observation，渐进披露与授权由共享注册表控制。

- 分批回答由外部 application_prompt 与 emit_message 描述引导：信息较多、多子问题、步骤和对比可按完整语义块交付，保持当前角色/偏好，不按字数机械切割、不逐句刷屏、不重复全文。QQOutput 与 Web EventBroker 在输出接受后通过 DeliveryHistory 按 run_id 收集 partial；最终整理只处理未发送的最后一段，保存直接对话时按顺序合并已发送分批正文与当前最终 history_text。progress/notification 不入此回答历史，并发隔离，run.end 清理；内核与双版本展示协议不变，失败/取消的已发送内容继续保留在运行日志。

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
- `hok/tools/gen_battle_res.py`：单局战绩详情长图生成器；娱乐分享兼容空评分/未知统计，按实际技能行增加卡片高度。图片、字体和 JSON IO 经 zfile，公开图标请求经 zapi，长期缓存保存于 resources/wzry_images/battle_assets/。网页分享消费者显式关闭正式模式过滤，正式战报查询的默认过滤保持不变。
- `hok/tools/gen_battle_shot.py`：RTMP 监听与对局截图工具。
- `hok/tools/gen_coplayer_analyses.py`：共玩关系、头像、胜率、评价等图表生成器。
- `hok/tools/gen_emoji_image.py`：表情包生成链路与模板；仅通过 `tools/emoji_context.py` 读取当前群的本人发言及表情决策缓存，不加载旧聊天记忆/摘要，Redis 与归档访问经 zfunc。
- `hok/tools/gen_gametime_table.py`：游戏时长表格聚合与渲染辅助。
- `hok/tools/gen_grade_chart.py`：评分/星数趋势图生成工具。
- `hok/tools/gen_hero_tier.py`：天元之弈英雄梯度数据按网页版梯度分层、临界区和英雄头像布局生成可视化长图。
- `hok/tools/gen_player_client.py`：使用 resources/player_client/ 下的三张用户截图作界面模板，只替换统计、英雄插画、筛选及缺失项；卡片严格对齐原截图的五组坐标，使用官方 mobileskin 立绘独立居中裁切；图中仅保留界面字段和—占位，数据缺项说明只在图外文字发送；显示名称、不显示英雄 ID，胜率数字按 `PlayerClient.win_rate_bands` 着色；字体、头像解码与图片落盘经 `zfile.py`，不请求网络或展开 raw 协议数据。
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

### AI 日报补充

- `api_adapters/aihot.py` 只读请求 AIHOT `/api/v1/dailies/latest`，不需要密钥，不接入聊天工具链；禁用环境代理和重定向，限制超时与响应字节，校验版本、日期、时间窗口、分类和来源。429/503 不进行即时重试。
- `business/ai_daily.py` 将单条合并转发整理为“今日看点 → 应用详情 → 前沿观察”。首条只归纳日常学习、创作与普通工作中可直接使用的应用资讯，法律、金融、研究、模型参数和深度工程内容留在后半部，不进入首页概要；没有应用动态时不拿专业内容填充。按编辑顺序统一编号，详情保留原始标题、摘要及原文链接，快讯共用编号并去重；不展示生成时间、统计窗口、信源名称、聚合站链接、单独来源说明或面向人群/遵循指令等元叙述。首条总览保持单节点，必要时只压缩要点，详情长节点拆分但不截断。
- “今日看点”使用自然小标题加一至两句日常解释，不堆砌功能和套餐清单；编辑 JSON 中 daily 条目必须同时提供 headline 与 takeaway。两部分标题分别附短说明“日常用得上的新工具、新功能。”及“模型、技术研究与行业动态。”，进入“前沿观察”前添加原生可见分界线；对应文字与线条统一读取 `AIDaily.overview_description` / `professional_description` / `section_divider`。
- 日报编辑提示词由 `business/ai_prompts.ai_daily_editorial_prompt()` 组装，资料独立放在 user 消息中；`ai_daily._request_editorial()` 只通过已有 `zapi.ai_api()` 单轮请求结构化分类、排序和应用要点。只接受原始条目 ID，完整覆盖且无重复/未知 ID；application + daily 才可进入首页，其他话题强制放后半部。模型不能替换详情、来源链接或发送目的地。编辑超时/结构异常时不入队，不回退为未分类概要。配置统一在 `config.yaml#AIDaily`，默认每天北京时间09:00向 `QQBot.group_qid` 推送。
- 定时任务仅在 `zscheduler.ai_daily_push` 注册，异步线程调用 `zfunc.ai_daily_check_and_push()`；不另起轮询，不替换原06:00游戏新闻任务。失败经统一出口通知管理员。
- `utils/message_sender.add_group_forward_msg()` 负责原生合并转发节点、机器人署名及纯文本转义；日报标题与节点展示署名默认统一为 `Next Signal`，分别读取 `AIDaily.title` / `sender_name`。标题随队列持久化，消费时映射为 `send_group_forward_msg` 的 `source` / `prompt`，不含标题的旧队列继续兼容。真实返回 `message_id` 后才标记发送成功，失败不终止转发消费，也不拆成多条群消息刷屏。
- `zfunc.enqueue_forward_message()` 在 DB0 原子完成入队及防重复预留；`hok:message:forward:delivery:ai_daily:<群>:<日期>` 保存 queued/sent/failed，默认7天。失败/未知结果不盲目重放；跨部署防重复，状态写入失败保留 queued，不冒充成功。手册与检索树同步维护在 `shared/agent/manual/`。

### X 订阅补充

- `event_handlers/x_subscription.py` 解析 X 账号订阅、取消、本人列表、最新内容及管理员检查命令；`event_rules.py` 独立判断 X 命令并从 B站通用订阅路由中排除，`zevent.py` 仅注册入口并通过统一消息出口回复。
- `business/x_subscription.py` 编排账号订阅、首次基线、增量推送、热门回复采样和英文翻译；外部查询通过 `zapi.py` 导出的 `api_adapters/x.py`，翻译只调用已有单轮 `ai_api()`。默认仅原创帖，等待回复积累；热门回复为网页可见公开会话有限采样内的点赞排序，必须标注采样范围和失败状态，英文原文与 AI 译文并列。
- X 使用网页会话 GraphQL，不调用开发者 `/2` API、不回退付费 API；`api_adapters/x.py` 自行处理限定的账号/时间线/详情 GET、解析、广告与置顶过滤及分页，Twikit 仅提供网页协议参数与 transaction 签名。操作 ID 从当前 X 主脚本发现，可由 `XSubscriptions.web_query_ids` 覆盖；feature 修正从 `web_features` 读取。网页客户端显式注入共享 `clash_proxy_url`、禁用环境代理与请求重定向；媒体仍通过既有 `clash_request`。网页登录 Cookie 仅来自既有 `.env` 的 `HOK_X_AUTH_TOKEN` 和 `HOK_X_CT0`，由 `zstatic.py` 注入运行时配置；始终将 Cookie 绑定 `.x.com`，不得传给媒体/静态资产，不调用库的登录、自动解锁、Cookie 文件读写或账号写接口。非密钥配置仅在 `config.yaml#XSubscriptions`；无会话时轮询跳过，主动命令说明配置要求。会话失效、限流、未知结构与不完整分页保留游标，错误不得披露 Cookie 或原始 HTTP 载荷。
- `tools/gen_x_post.py` 负责可分页的正文、媒体预览、回复及译文卡片；采用白色圆角卡片、浅薄荷底色与清晰字重层级，中文译文优先、英文原文小字并列。图片只保留作者/账号、时间、正文、配图和回复，采样数量以一行小字注明；不渲染“X关注动态”、重复的 AI 说明、逐条回复链接或原帖长链接，消息参照 B站推送的分块排版：首行“作者名 · 发帖时间（多久前）”，换行后优先显示中文译文预览（`message_preview_max_chars` 默认 280 字符，超出注明全文见图），再换行附图片，全部图片之后换行附原帖链接，各部分不额外添加空行，文字预览压缩空白行；图片中的原文与译文不按字符数截断，长内容分页；发帖时间取原帖 `created_at`，经 `ztime.parse_chat_time_bound()` / `epoch_to_text(timezone_name="Asia/Shanghai")` 按北京时间显示到秒，缺失时标注时间未知，不用当前时间代替；`ztime.time_ago_text()` 按消息生成时刻计算相对时间；翻译失败明确标注并回退原文，文字经 `MessageSegment.text` 转义。字体优先使用 `resources/fonts/noto-sans-sc/` 下附 OFL 许可的 Noto Sans SC，字重由可变字体设置；`zfile.x_card_font_path()` 按项目绝对根目录解析配置中的相对字体路径。路径、图片读写通过 `zfile.py`，输出为公开产物目录下 `x_post_<随机hex>_<页号>.png`。原帖媒体仅允许有体积预算的 HTTPS `pbs.twimg.com` 图片，不下载视频本体；仅删除与已读取配图完全对应的 t.co 占位链接，正常外链保留。
- `api_adapters/x_transaction.py` 适配当前网页登录态 `/home` 的 transaction 初始化和拆分 webpack chunk 映射，签名计算仍继承 Twikit；不使用已换成独立应用的未登录首页初始化，不修改第三方安装包或全局 monkey patch。
- X 正文和回复配图共用 `max_media_images` 与体积/像素预算，已读取的回复配图嵌入对应卡片；读取失败的回复保留原始媒体短链。英文翻译仍经单轮 `zapi.ai_api()` 并请求 `json_object` 输出，按原始帖子 ID 校验每条译文；超时和 thinking 仅由 `XSubscriptions.translation_timeout_seconds` / `translation_thinking` 控制，不更改其他业务调用的默认值。
- X 状态全部通过 `zfunc.py` 的窄接口写 DB0，共享 key 常量在 `zstatic.py`：`hok:x:subscriptions` 为按真实 QQ 和 X 用户 ID 隔离的 hash；`hok:x:cursors` 保存每账号增量游标；`hok:x:seen:*` 保存已入队帖子；`hok:lock:x:push` 使用持有者 token 校验、续租和释放。新增订阅不推进其他订阅者的待推游标；发送失败不标记已推或跳过游标。自动推送目的地沿用配置 QQ 群，同账号只推一次。
- X 轮询仅在 `zscheduler.py` 注册，正文、热门回复、翻译和媒体均不创建独立后台轮询；管理员 `##x check` 复用同一检查流程。用户手册与检索树同步维护在 `shared/agent/manual/`。

### 2.1 配置文件

- `.env`：唯一的密钥文件，仅保存 API key、token、密码、数据库 DSN 等凭据，另保留 NoneBot 启动必需的 `ENVIRONMENT` 和 `DRIVER`。用户已明确授权在本私有仓库中将真实凭据随相关代码或配置正常提交及推送；后续不得仅因含有密钥而默认排除 `.env`、拆分提交或再次要求确认。日志、诊断、聊天回复和分享页仍必须脱敏，不在说明文档中复制密钥值。不得再新增 `.env.local`、`*.env.example` 或其他密钥文件。
- `config.yaml`：唯一的非密钥配置文件，统一保存服务端点、模型、代理、超时、查询限制、Redis、NapCat、稳定变量与动态初始值。原 `variables_static.json` 并入 `StaticVariables`，原 `variables_dynamic.json` 并入 `DynamicVariables`。不得再新增 `config.yaml.example`、`redis.json` 或其他应用配置文件。
- AI Chat 的 QQ/Web 联网搜索统一经 worker 调用 `api_adapters/ai.py#deepseek_web_search()`，使用 DeepSeek 独立 `POST /v1/tools/search`，不调用模型内置搜索。`DeepSeekSearch` 在 `config.yaml` 保存 endpoint、api_key_env、need_content、超时及结果文字限制，默认复用 `.env` 的 `HOK_DEEPSEEK_API_KEY`；`zstatic._build_deepseek_search_config()` 与 worker 共用解析，独立于 ChatAPI/LocalAgent 的模型端点和密钥覆盖。query 最长128字符，工具保留最多10条，按 content/summary/snippet 选正文并保留标题、链接和源发布时间。`AliyunSearch` 配置、`aliyun_web_search()` 与兼容导出保留，但聊天链路不加载或调用，也不在失败时回退旧接口。
- `ChatAPI.api_key_env` 只保存密钥变量名，由 `zstatic._build_chat_api_config()` 从既有 `.env` / 进程环境解析；显式 `HOK_CHAT_API_KEY` 覆盖优先，指定变量缺失时拒绝使用其他供应商旧密钥。当前 ChatAPI 使用 DeepSeek 官方端点 `https://api.deepseek.com`、`HOK_DEEPSEEK_API_KEY` 和 `deepseek-flash`；LocalAgent.llm 使用 ZenMux、`LLM_API_KEY` 和 `deepseek/deepseek-v4.1-flash`；QQ 工具循环、回复整理、联网角色生成及业务单轮文案共用此远程 ChatAPI。远程 ChatAPI.proxy_url 与本地 llm.proxy_url 均为空表示直连；Steam、APIMart 与 X 继续使用独立的共享 Clash 配置；worker 将有效代理设置交给 provider，禁止继承环境代理，本地端点覆盖不继承远程 loopback 代理。既有服务启动文件不得保留旧端点、模型或密钥的 HOK_CHAT 覆盖，避免遮蔽项目配置；不新增密钥/配置文件。

原则：
1. **任何可能变化的值**不得硬编码在业务逻辑里，必须进入上述文件或对应的静态/动态变量模块。
2. `zstatic.py` 负责加载静态配置；`zdynamic.py` 负责加载动态配置初始值，不作为运行时持久化写入入口。
3. 部署环境只可通过 `HOK_ENV_FILE` 覆盖密钥文件路径，通过 `HOK_CONFIG_FILE` 覆盖非密钥配置路径；未设置时读取 `BOT_PATH` 下的 `.env` 与 `config.yaml`。

### 2.2 Linux 环境变量（在 `hok/zstatic.py` 导入）

部署环境下预计存在以下环境变量（缺失时的处理策略以现有代码为准，禁止凭空新增“变量不存在”的冗余判断链）：

- `BOT_PATH`：Bot 部署目录。
- `HOK_ENV_FILE`：可选的密钥 dotenv 路径；未指定时加载项目 `.env`。
- `ChatAPI.fallback` 配置百炼 `kimi-k3` 备用端点、模型、原生图片、协议和超时；密钥仅保存于现有 `.env` 的 `DASHSCOPE_API_KEY`。DeepSeek 首个有效输出等待上限为 15 秒；网络故障、鉴权失败、限流、5xx 或空/损坏响应在尚未交付流式内容时回退，取消、请求参数错误和已输出内容的失败不重发。QQ 对话、回复整理、角色生成和业务单轮文案共用回退配置；本地 Web 的独立 ZenMux 配置不继承 QQ 回退。Kimi K3 仅支持思考模式，使用百炼 `enable_thinking` / `preserve_thinking`，移除该模型不支持的 temperature 覆盖并保留原始 reasoning_content；命名强制工具调用转换为仅包含该已授权工具的 required，不修改内核授权与工具执行。备用密钥通过 worker private 平面传递并参与两条 bridge 的脱敏，不在 public、payload、日志或手册披露。
- `HOK_CHAT_BASE_URL`、`HOK_CHAT_API_KEY`、`HOK_CHAT_MODEL`、`HOK_CHAT_PROXY_URL`：覆盖 `config.yaml` 的 `ChatAPI` 对应字段，由 `zstatic.py` 统一导入为 `chat_api_config`；显式空 `HOK_CHAT_PROXY_URL` 必须覆盖文件中的代理并表示直连，客户端仍禁止继承环境代理。
- `HOK_ALIYUN_SEARCH_API_KEY`、`HOK_ALIYUN_SEARCH_ENDPOINT`、`HOK_ALIYUN_SEARCH_WORKSPACE`、`HOK_ALIYUN_SEARCH_SERVICE_ID`、`HOK_ALIYUN_SEARCH_CONTENT_TYPE`、`HOK_ALIYUN_SEARCH_WAY`、`HOK_ALIYUN_SEARCH_QUERY_REWRITE`：可选覆盖 `.env` 私有载荷或 `AliyunSearch` 公共默认值，由 `zstatic.py` 统一导入为 `aliyun_search_config`；请求始终直连且禁用环境代理。
- `HOK_CHAT_READONLY_DSN`：专用 `hok_chat_reader` 连接串，必须通过私有环境文件注入；`AgentSQL` 管理查询限制，`AgentPlots` 管理共享字体与 QQ 合图布局。
- `HOK_CLASH_PROXY_URL`：覆盖 `config.yaml` 的 `Proxy.clash_url`，由 `zstatic.py` 导入为 `clash_proxy_url`；Steam、APIMart 与 QQ/Web 消息网页抓取当前默认使用 `http://127.0.0.1:7890`，也支持 `socks5h://127.0.0.1:7891`。
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
5. 本私有仓库的 `.env` 与普通受版本控制的配置文件按同一流程处理；本轮需求涉及的凭据变更正常纳入相应提交及已授权的推送，不再做密钥与代码的默认隔离。此授权不扩大到其他任务的无关改动或其他仓库。

#### 3.1.2 Codex Cloud

Codex Cloud 无须遵守本节的任何 Git 规范；本文件不规定 Codex Cloud 的 Git 操作方式。

### 3.2 库导入边界（严格）

1. **NoneBot 与机器人适配器**：与 NoneBot、机器人事件、消息段、适配器、bot 实例操作相关的库，只能在 `zevent.py`、`utils/message_sender.py`、只读边界 `utils/qq_profiles.py` 等顶层适配器脚本中导入和使用；业务层不得直接导入。
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
3. 个人 `#玩家的英雄名` / `#玩家的英雄` 先发送原有英雄统计，再附加客户端详情或本赛季英雄统计图；原有单英雄默认本赛季、英雄汇总默认近30天及显式“本赛季”规则不变。`#玩家的数据` 查询客户端游戏统计，群u模板保留原群体查询。`single_player_single_hero_process()` 的本赛季起始日期继续使用 `this_season_start_date`。

## 6. NBot 变更自检清单

皮肤返场排行已经废弃，保留完整匹配命令 `#皮肤返场` / `#返场排行` / `#返场排名` / `#皮肤返场排行` / `#皮肤返场排名` / `#皮肤返场查询`（支持全角井号），沿用现有授权、休眠与维修规则。`event_handlers/skin_votes.py` 统一返回“功能已经废弃”，不再调用业务查询、外部 API 或图片生成。用法与检索树同步维护在 `shared/agent/manual/`。

1. 新增代码是否放在了职责正确的 `hok/` 模块中？
2. 是否所有 IO、时间、消息发送都走了指定模块？
3. 是否遵守了 NoneBot、Redis、OpenAI/requests、time、IO 相关库的导入边界？
4. 是否需要同步更新本文件或更深层目录的 `AGENTS.md`？

## 7. 独立 Agent 内核与本地可视化适配层

- `vendor/react-agent-runtime/` 是私有仓库的 Git submodule，固定到父仓库记录的 commit；`agent_runtime` 仅为指向其 `src/agent_runtime` 的源码兼容软链接，不复制实现。独立安装使用 `pip install ./vendor/react-agent-runtime`。内核是独立、可安装的 Python 包；只依赖注入的模型、状态、输出、时钟与能力接口，不导入 `hok`、NoneBot 或应用配置，不自行连接数据库、Redis、SSH 或 HTTP，不实现 UI。
- `agent_runtime/core/` 管理有预算的 ReAct 循环、通用上下文和授权；`tools/` 仅管理注册、参数校验与执行协议；`runtime/` 仅管理结构化事件。内核不得包含具体工具名称、类别、实现、SQL 方言/schema、参考目录或群聊身份字段，也不得识别具体工具结果中的 SQL 行结构。每个工具调用必须有对应 observation。运行记录与模型可见的截断 observation 分别保存。
- QQ/Web 使用外部 `agent_console/tools/diagnostics.py#DiagnosticToolRegistry` 包装所有工具处理器，包括后续注册的外部函数；通过既有 ToolResult.data.error_details 向内核提供失败阶段、原始异常类型、底层原因链、有限函数/文件名/行号和恢复建议，不修改内核或子模块协议。`agent_console/tool_errors.py` 是 bootstrap 携带的纯诊断/脱敏器；worker 的 RPC 失败保留类型与诊断，RemoteToolError 透传至工具 observation，旧 worker 的 error/type 兼容；SQL 整批仍先校验，逐查询失败保留 query_index、SQLSTATE、位置及数据库提示，其他成功结果和 dataset_id 不丢弃。Python 沙箱失败保留退出码与有限 stderr，KPL HTTP错误保留状态码，字段错误给出本次可用字段。诊断先脱敏再截断，不提供完整栈源码、局部变量、HTTP headers、请求体或连接串；只附最多4层原因、每层最多4个定位与1200字符消息、4000字符沙箱stderr。工具原超时在中间件执行，内核外层只多1秒清理保护，取消继续向上传递；读取故障可按预算有限修复，写操作超时或RPC响应丢失标为OUTCOME_UNKNOWN并阻止本轮重放，不自动重试工具。参数schema及授权仍由内核原流程校验。
- 工具的初始披露、动态描述、结果投影均由外部注册信息注入；通用 `Principal.attributes` 只承载可信适配器提供的扩展属性，其业务含义由适配层解释。`ToolContext.resources` 只管理本次执行的通用资源引用，具体数据集结构由工具维护。独立包只依赖 Pydantic，不依赖 SQL 解析器或业务服务。
- `RunRequest.metadata` 是调用方提供的通用事件元数据，内核仅透传和快照，不解释任务、渠道或业务字段。适配层用它区分后台输出，避免后台通知占用前台输入/停止状态。
- `RunRequest.context_messages` 为仅本轮可见的 user 角色补充资料，支持文字及原生内容块，不允许 system/assistant/tool 或工具调用字段；在工具循环和运行记录中保留，直接对话保存不含这些资料。QQ 引用通过此接口输入，不能放在 system prompt，也不能改变身份和权限；内核不识别引用、QQ 或来源字段。
- `agent_console/webpages.py` 是 QQ/Web 共用的外部网页输入提取器：从本次正文及已通过引用校验的文字识别 HTTP/HTTPS 链接，按规范化 URL 去重，只读一次并在宿主本地解析 HTML，保留标题、正文、列表和表格，移除标签、脚本、隐藏内容及导航等噪声。资料和读取/截断状态通过 user `context_messages` 加入本轮，原问题、原始群归档、直接对话历史和长期记忆不自动写入网页正文；完整内容进入运行记录，Web 准备阶段另记 `request.webpages`。不扫描检索历史、模型输出、网页子链接或图片地址，不执行浏览器脚本。限制来自 `QQAgent.webpages` / `LocalAgent.webpages`，默认3链接、12秒并行总等待、每页1MiB/5000字、总正文12000字。HTTP 只用标准公网端口，网页和 HTTPS DNS 请求显式使用共享 Clash 代理，QQ 由 zfunc 注入 zstatic.clash_proxy_url，Web 读取本机 Proxy.clash_url / HOK_CLASH_PROXY_URL；缺少代理或代理故障均不回退直连，禁用环境代理、凭据与 Cookie 继承；校验每次重定向的所有 DNS 地址并连接已验证 IP，HTTPS 用原域名校验 TLS/SNI，禁止本机/内网/保留地址。可配置 HTTPS 公网 IP 的 JSON DNS 端点绕开代理虚拟 DNS，本地当前启用、QQ 默认系统 DNS；解析返回仍需校验公网范围。抓取失败不阻断聊天，取消向上传递；登录/反爬/动态页面、非文字媒体和超限不能伪称已读。内核不增加网页、HTTP 或 HTML 依赖。
- `agent_console/` 是外部本地适配器，允许在此封装 FastAPI、SSH、HTTP、时间及 IO；这是独立包接入层，不适用上文针对 `hok/` 的具体模块导入边界。UI 仅消费内核事件；`qq_agent/` 同为外部适配器，复用同一 `AgentRuntime`、工具和角色服务，不导入 Web server。QQ 的网络、进程、时间及 IO 封装也不适用 `hok/` 内部导入边界。
- `examples/independent_agent.py` 演示通用调用方如何提供模型、内存状态、输出和标准时钟，不导入 HOK 或连接外部服务；示例适配器的标准库使用同样不适用 `hok/` 的导入边界。
- `zfunc.agent_read_group_member_profile()` 是 QQBot 的实时资料门面，通过注入的 `QQAgentService.member_profile_reader` 提供给 `qq_agent/member_profiles.py` 注册的 `read_group_member_profile`（references 类别）。普通群只能读取当前群的成员；配置管理员私聊省略群号使用入口默认群，也可明确指定目标群，普通私聊不披露。成员身份必须经 QQBot 验证，模型只能选择目标 QQ，不能提供原始 URL、原始资料或授权。头像失败、无效或超过共享输入预算时保留文字资料，缺失字段为 null；当前本地 Web 未注入此 QQBot 读取端口，不以历史数据库冒充实时资料。内核和独立包不导入 QQ 读取器。
- 机器人自身身份仅来自现有 `config.yaml#QQBot.bot_qid`，由 `zfunc.agent_runtime_start()` 注入 QQAgentService 并绑定到可信 `Principal.attributes.bot.user_id`，QQ 提示词同时明确机器人与提问者的身份。成员资料工具 `target=user` 默认查询提问者，也可提供其他成员 `user_id`；`target=bot` 查询绑定机器人，禁止参数覆盖其 QQ。机器人资料和头像沿用同一群授权、成员校验及图片预算；角色设定的外貌不代表实际 QQ 头像，不用玩家映射推断机器人身份。内核不解释该属性或选择语义。
- `agent_console/remote_worker.py` 支持两种相同的 RPC 传输：网页用 SSH 临时执行，QQ 在部署服务器上使用 ProcessBridge 启动本地子进程。均不修改业务数据库 schema。SSH 模式读取服务运行进程环境；QQ worker 继承当前进程环境并读取现有 `.env` / `config.yaml`，从服务器实际源码提取 API 适配函数。凭据只保留在适配器内存，不写新密钥文件、不返回浏览器。
- `agent_console/remote.py` 串行管理 RPC 与连接恢复：新请求发送前若 worker 已退出或流已关闭，在同一锁内重新启动并 bootstrap；已发送请求遇到 EOF、超时或坏响应时关闭旧流并明确报告结果未确认，禁止自动重放可能已经生效的操作。取消调用者仍等待原 RPC 消费响应，关闭后不自动重连。`/api/status` 必须实测业务与状态两条连接及其 Redis PING，不以缓存配置判定健康；连接故障通过 `BridgeUnavailable` 返回带中文说明的 HTTP 503，内核不参与 SSH 恢复。
- `agent_console/tools/` 定义应用的具体工具、PostgreSQL AST 校验和参考数据查询；应用提示词由 `agent_console/capabilities.py` 组装，持久任务到通用请求的转换由 `agent_console/tasks.py` 完成。聊天和游戏查询使用服务器独立 `hok_chat_reader` PostgreSQL 账号；长期记忆及本地会话运行状态使用 Redis DB0。普通群与跨群范围在可信 `Principal.attributes.chat` 中传入并由适配器绑定，模型不得提供或改变。所有后台任务和运行记录使用 `hok:agent_runtime:console:*`。QQ 对话会话使用 `qq_g_<群>_<QQ>` / `qq_p_<QQ>`，与网页隔离；QQ 与网页任务分别使用 `tasks:qq` / `tasks` due 索引，避免相互领取或阻塞。本地默认玩家由 `LocalAgent.player_key` 指定为 example_user_10，入口从权威参考数据唯一解析其 QQ；长期事实记忆使用该用户已有的 `hok:memory:facts:<QQ>`，跨会话共享。旧匿名 `local-ui:<session>` 记忆保留，不自动认领、迁移或删除。
- `bot_info` 的 `read_bot_manual` 在QQ/Web共用分层手册。`shared/agent/manual/catalog.json` 声明唯一root和父子节点、摘要/关键词、功能工具、独立Markdown正文/标题及只读代码位置；`handbook.md` 仅为人工导航，`chapters/` 按功能维护用户说明及计算口径/样本/默认值/限制，正文不讲内核架构。发现只提供6个一级目录；browse/search只返回当前节点的子节点卡片（无全文），分支路由只索引元信息，正文仅在所属功能范围内参与叶节点排名，不做全局全文搜索。read只读选中的叶节点，正文最多3000字符且next_offset分页，目录预算3000字符；默认每次3个节点、最多5个，树最大5层，预算在共享目录维护。`agent_console/tools/bot_manual.py` 在本轮ToolContext私有状态记录连续读取、正文完整性及手册版本；code必须针对已读完的同一叶节点并说明fallback_reason，跨节点、跳页、新会话和过期版本不能跳过说明读取代码。bootstrap只发送目录声明的共享Markdown文件和读取器；Python源码来自目标运行主机，AST定位声明函数/类（可用唯一赋值focus定位公式）、缓存按mtime/大小刷新，不导入执行，摘录仍受6000总字符/2000单片段/4个引用限制。每个节点暴露code_positions供兜底定位，叶节点省略code/tools时继承最近父节点，精确主题可覆盖，共用位置只维护一次；缺失/截断明确标记；图片像素、alt和链接属性不作检索证据。正文加载拒绝私有路径/链接并限制总字节，源码不接受模型路径或配置/密钥/日志读取；返回来源行号、版本、导航路径及当前渠道工具授权，内核不认识手册树。新增或改动功能同步维护正文、树元信息及代码位置，运行scripts/validate_agent_manual.py检查树、标题覆盖和符号；重启适配器加载更新。
- `agent_console/roleplay.py` 编排角色和通用用户偏好；`identity.py` 单独维护本地 HOK 身份映射与权限策略，角色管理器不识别 QQ、游戏玩家键或群范围。`roleplay_models.py` 定义纯数据校验，`roleplay_store.py` 仅供外部 SSH worker 执行 DB0 持久化，`tools/roleplay.py` 注册按需披露的角色工具。角色定义在 `shared/agent/roles/*.json`，与内核及 SQL 独立。用户自建角色、当前选择和回复偏好按可信用户 ID 的摘要隔离，使用 `hok:agent_runtime:console:roleplay:<用户摘要>:*`，不覆盖 QQ 旧角色记录；新 QQ 与网页在同一个真实 QQ 下共享新角色选择和偏好。角色来源来自真实联网搜索，模型生成档案时保留请求、响应和来源事件，生成失败不保存；角色与偏好不能改变工具授权或查询范围。选择由本次最终回复整理器和后续对话读取，后台 agent 任务在执行时重新读取其已绑定用户的当前角色、偏好及近期/相关长期事实，固定消息任务保持原文。旧任务保留原授权与身份，不自动增加角色权限。网页与 QQ 入口和工具共用相同角色服务。
- 本地聊天的前置工具由适配层设置为历史检索、能力发现，模型不得在未发现任务/记忆等类别时把未披露误报为能力缺失。本人偏好的归属已经由入口绑定，不需要额外 QQ 或玩家身份。业务调用与 Redis 状态/通知使用两条独立 SSH 连接，避免长 SQL、图片或沙箱阻塞发送。
- QQ 管理员私聊的默认查询群来自 `QQAgent.admin_private_default_group_id`，当前为 `2000000001`，存入可信 `Principal.attributes.chat.default_group_id`；不填充当前事件 `group_id`，不改变私聊会话、引用校验、消息 ID 排除或输出目的地。历史检索、聊天 SQL、近期发言与成员资料省略目标群时使用该默认值；管理员可通过工具 `group_id` 明确选择其他群，历史检索/SQL 还支持 `*` 查询全部归档。普通群始终优先绑定当前群且禁止覆盖，普通私聊没有群范围；本地 Web 与没有默认值的旧授权请求保持原范围。后台任务继承创建时的查询属性与私聊目的地。选择范围不能修改入口身份或跨群授权。
- `chat_history` 类别提供按需的 `read_recent_chat_history`：当前消息指代不明、依据不足或相关性检索未还原当前话题时读取最近发言，不作为每轮必调工具。`AgentHistory` 配置默认20条、上限50条及每条600字摘录，不限制时间跨度；共享纯校验在 `tools/memory.py`，worker 启动将有效限制返回给工具 schema 和发现目录，避免前后端限额不一致。worker 只查询 `hok.chat_history_messages`，在 SQL 中按群号、当前消息排除和 LIMIT 过滤后取最新消息并按时间顺序返回，覆盖群内所有发言者，保留时间并标记截断，不加载全量归档或用命中数统计总体。普通群绑定可信当前群且不能改群；仅跨群授权私聊/本地调试可指定一个目标群，禁止自动混入多个群，私聊消息 ID 不用于排除群内同 ID 消息。近期发言作为不可信 tool observation，不写长期事实记忆；QQ 与网页共用工具，内核不解释群身份。
- QQ 群入口额外通过 `qq_agent/context.py` 自动加载当前群有界公共背景，复用 AgentHistory 默认20条/每条600字，不限制时间跨度；合并所有成员近期归档与机器人已入队回复，按时间排序后保留最新20条。背景仅通过本轮 user context_messages 提供，不复制被动群发言、不跨群、不合并个人直接对话或记忆、不放宽本人任务列表/取消权限。`QQAgent.group_context_timeout_seconds` 默认10秒，读取失败标记缺失并保留可用来源。`QQOutput` 只在统一出口接受后调用 worker 的 qq_group_reply_save，将正文摘录、原请求者及实际 @ 目标写 DB0 `hok:agent_runtime:console:qq_group_replies:<群>`，保留 AgentHistory.max_limit 条，不设置时间过期，写入时用 PERSIST 清除旧版TTL；qq_group_replies 仅向可信当前群返回最新记录。私聊与未接受消息不写，旧日志/个人会话不迁移、不清理；共享背景不能用来执行他人历史指令或声明旧任务已成功，需结合发言时间避免把较早话题当成正在发生的事。
- 应用任务有 `agent` 和 `message` 两种：前者调用同一 ReAct 内核，后者直接通过通用事件/输出端口发送固定文字且不请求模型。首次时间支持带时区 ISO 8601 的 `run_at` 或 `delay_seconds` 二选一，均省略时保留旧默认；具体几点优先提交 run_at，外部 `agent_console/task_timing.py` 统一解析并拒绝过去或超过一年后的日期，不允许模型心算替代或自动改期。创建及列表由 worker 投影实际北京时间 `next_run_at_text`，确认须使用该值。周期最短 1 秒，未指定首次时间的周期任务等待一个周期；后续时间按原计划递推，错过的时间点跳过，禁止集中补发。调度不等待前台模型空闲。任务的类型、计数、租约与取消规则均留在适配层。
- `shared/agent/{chat_sql,hok_sql}/` 保存不含密钥的模型语义目录及可信视图定义，可独立修改；目录是模型披露与 AST 校验的共同来源。服务器缺少语义视图时，适配层将仓库语义视图定义编译为只读 CTE；模型仍不允许查询采集层表，不执行 DDL。
- `shared/agent/reference_data/manifest.json` 声明参考数据源及名称、别名、ID 命名空间与关系；`agent_console/tools/reference_data.py` 是不含 IO 的目录构建/检索器，HOK 字段名只放共享清单。外部适配器读取最新服务器静态配置，常用映射按清单投影进上下文，完整映射经 `references` 工具披露；不得用 SQL 结果后补昵称、群聊推断或长期记忆代替权威参考数据。多对一、同名与同人账号关联保留全部匹配，参考关系不授予身份权限。
- `kpl` 类别的 `query_kpl` 是 QQ/Web 共用的只读公开赛事工具，权限为 web.read。`shared/agent/kpl/catalog.json` 独立声明18类查询的路径、参数类型/枚举、必填项、数据路径和口径，`agent_console/tools/kpl.py` 负责按需披露、动态 schema 及本轮 dataset_id；`agent_console/kpl_client.py` 是外部 HTTP/协议适配器，经业务 worker 调用 kplll.online 的公开 JSON API，不执行网页脚本或站点 AI/反馈/预测写接口，不改旧 B站 KPL采集/推送、内核或业务数据库。网络/体积/观察量设置只在 config.yaml#AgentKPL；bootstrap 携带当前工具源码、目录和公开默认配置，服务器 AgentKPL 优先覆盖，故本地新工具可在远程旧版本上调试，不落新配置文件。每次只发固定来源 HTTPS GET，禁用环境代理、认证/Cookie继承和重定向，不接受模型 URL/SQL/身份。未知参数、无效ID/类型、错误结构、HTTP故障及超预算明确失败，不回退猜测数据。赛事、比赛、小局、战队、选手和英雄是本站独立命名空间，先按名称/年份查询目录取得ID，禁止混用腾讯英雄、营地或B站cid。名称/赛程日期先在完整本次响应上过滤，再分页；有时区日期按Asia/Shanghai、无时区字段保留源日期。仅选手分均榜用已验证的服务器分页，offset须为limit倍数，不能混合本地名称过滤；所有分页/嵌套裁剪标记范围及next_offset，末页也不是全量。fields缺失值为null、未知字段拒绝；图像地址从正文移除且不下载像素。返回来源/实际API地址、参数、抓取时间、样本与截断状态；第三方收录不是官方实时，抓取时间不是更新时间。结构化数据可供现有Python/绘图资源使用，不自动写记忆或注册推送任务。
- 一般生成 Python 仅在远程 Linux bubblewrap 沙箱运行，关闭网络、清空凭据环境、限制资源并验证 PNG。隔离依赖缺失时拒绝执行，禁止回退到宿主 `exec`。
- `shared/agent/plots/catalog.json` 独立定义绘图主题、配色、图型说明与数据规范；`agent_console/tools/plotting.py` 定义参数并生成调用代码，`agent_console/plot_renderer.py` 是不含 IO、配置或业务身份的可信绘图库，由 SSH worker 注入 bubblewrap 内执行。条形、折线、散点、热力图与环形图共用主题、标题层次、标注和数据口径脚注。`render_plot` 与一般 Python 绘图均使用目录默认主题，角色与 ReAct 内核不得包含绘图样式。热力图必须保留轴标签，长表明确数值列，重复格拒绝隐式聚合，缺失值默认留空；补零、聚合只能由调用参数明确指定。趋势图保留真实观测点、不插值平滑；查询截断必须在图中说明。主题和可信绘图代码修改后重启本地适配器。
- 本地界面只监听 `127.0.0.1`，提供思考字段、工具调用/结果、产物及完整事件轨迹；无真实 `reasoning_content` 时不得伪造思考过程。独立配置统一放在根 `config.yaml` 的 `LocalAgent`，不新增应用配置或密钥文件。
- `LocalAgent.llm` 可独立覆盖本地 Web 的 `base_url`、`model` 与 `vision_model`；`api_key_env` 仅保存密钥变量名，从本地 `.env`（或 `HOK_ENV_FILE`）与进程环境读取，进程环境优先。本地使用 ZenMux、`LLM_API_KEY` 和 V4.1 Flash，远程 QQ 使用 DeepSeek 官方端点、`HOK_DEEPSEEK_API_KEY` 和 `deepseek-flash`，分别保留渠道配置；本地详细/群聊整理与联网角色生成使用相同本地配置，远程工具与数据库连接不受模型迁移影响。覆盖端点时必须同时明确密钥变量，缺失时拒绝启动，不把服务器密钥发给另一端点。两条 bridge 的脱敏集均包含本地 key，状态接口仅披露有效非密钥设置；移除 `llm` 即恢复服务器模型配置。
- `agent_console/static/usage.js` 是外部 UI 的纯用量统计器：只按持久的 `model.response` / `roleplay.model.response` / `reply.model.response` 汇总接口 usage，按事件 ID 去重；流式片段、工具 payload 和缓存/思考子集不得重复加总。按请求、本轮和会话展示输入、输出、总量及可用缓存/思考字段，未知值与零明确区分，中断或失败请求保留未返回状态。会话恢复重放相同事件；思考与工具步骤默认折叠，完整事件轨迹保留。
- `ImageInput` / `RunRequest.images` 是内核的通用图片输入协议，源为 URL、data URL 或外部模型适配器解析的引用，内核不做图片 IO、不包含供应商与文件策略。用户文字与图片作为原生内容块进入每轮 ReAct 请求；`StatePort.save_dialogue.question` 接受字符串或内容块列表并原样恢复，纯文本调用兼容。图片、图片中的指令不得改变身份或工具授权。
- `agent_console/image_inputs.py` 负责本地图片校验、原始像素存储、上下文预算和事件引用投影。输入图片及元数据存于忽略目录 `file_transfer/agent_inputs/`；网页选择、粘贴、拖入均走认证 `/api/images`，`/api/chat` 只接受已上传图片 ID。格式依实际像素检测，拒绝损坏文件、超大图片、无效 ID 和重复附件。原图保持不变；GIF、动态 WebP/APNG 等动画在外部适配器按帧序抽样成带帧号的 PNG 拼图，默认最多 4 帧、源动画最多 240 帧且限制累计解码像素，配置在 `LocalAgent.images` / `QQAgent.images`。原图与实际模型输入拼图各自保存，拼图元数据记录原图 ID、总帧数和抽样帧索引；静态图直接转换为原始 data URL，动画转换为拼图 data URL。Redis/SSE/事件快照使用 `attachment://<id>`，实际 request payload 必须引用真正发送的像素文件，不能把拼图冒充原 GIF；provider 在线程中做投影，不阻塞任务发送。默认 4 张、单张 4 MiB、每次 8 MiB；模型图片预算 16 MiB 以实际发送字节计算，优先近期图片，被省略的历史图片必须有明确提示和记录。QQ 入口支持带真实 URL 的 image/mface/marketface/face，缺少 URL 的表情明确标记未读取像素，不猜测素材地址。
- 图片模型名称分别在根 `config.yaml#LocalAgent.vision_model` / `QQAgent.vision_model` 设置，本地 `LocalAgent.llm.vision_model` 覆盖优先；本地的文字及图片显式使用 ZenMux `deepseek/deepseek-v4.1-flash`，QQ 的文字及图片使用 DeepSeek 官方 `deepseek-flash`。QQ 未指定视觉模型时使用其已配置文字模型，不在代码中硬编码供应商名称。无本地覆盖时模型 key 与 endpoint 从服务器读取，有覆盖时遵守上文的本地密钥规则。带当前或历史图片时在 `agent_console/provider.py` 选择视觉模型，角色、工具与同一 ReAct 内核继续工作；纯文本使用对应渠道的文字模型。图片输入的 token 已包含在 API 输入用量中，不重复统计。
- 外部工具可在成功 observation 的 `data.model_images` 中返回原生 `image_url` 内容块，仅接受适配器拥有的 `attachment://` 引用。ImageStore 在完整 tool 回复批次之后补充原生 user 图片资料，保持工具调用顺序并标明来源调用；provider 在投影后选择视觉模型，实际 payload 与图片引用继续入日志。该协议不按工具名称分支，不把工具图片写入直接对话或长期事实。QQ 成员头像先由 QQBot 下载，再经 QQ 适配器校验、私有保存并计入原消息、引用和本轮工具共用的图片数量/体积预算；内核仍只处理通用 JSON observation。
- 内核的可选 `FinalizerPort` 接收 `FinalizationContext` 中的请求、任务草稿和模型上下文副本，返回通用 `FinalAnswer`。内核不识别角色、QQ、版本名称或排版；只发布默认 text、透传 variants/metadata，并保存 history_text（缺省为 text）。原模型响应及草稿保持完整。处理器失败保留草稿并警告，取消与总体预算仍生效；同步阶段性输出不受最终整理器影响。
- `agent_console/replies.py` 是外部双版本展示器：ReAct 答案作为唯一事实底稿，detailed 原样保留；JSON 模型生成 chat，QQ 可在同一请求内依据本次问题与用户偏好选择受枚举约束的 default_variant，不加关键词分类器或额外模型请求。Web 默认固定展示 chat 并提供两版查看。表达阶段不带工具、不重新分析或计算；输入只有当前问题、底稿、最新角色表达卡和用户表达偏好，不再次注入原始工具结果、目录、检索发言、旧对话、长期记忆与角色生平。有 voice 的角色仅投影表达卡，旧档案兼容提取 personality / speech_style。数字沿用底稿对象、标签、单位与分母，不拆开重组。默认最多两次、总阶段60秒，检查结构、枚举、长度、纯文本及新增数值/链接；字面量检查不代表语义验证，不加事实复核模型。超预算不截断事实；失败保留底稿并显式 degraded。预算与选择开关分别在 LocalAgent.reply / QQAgent.reply。
- `output.message.data.text` 和本地 run 结果 text 默认使用群聊版，variants 另存详细版与群聊版，网页分别展示并允许复制群聊纯文本；QQ 出口按当次需求选择版本。reply.model.* 完整记录请求、输入字段长度、响应、原始JSON、修复与失败，并与 ReAct/角色生成统一统计 token。当前本地 history_variant=detailed 只保存一份底稿供后续追问，避免重复答案膨胀上下文；QQ 适配器可选择 chat，只保存实际发送内容。两个版本均保留在事件中；固定文字定时任务保持原文且不新增模型请求。
- 角色包可选 voice 数据只在 shared/agent/roles/*.json 和外部角色服务维护，含 tone、habits、avoid、原创问答语气样例；旧记录默认兼容，联网角色也生成并校验这些字段。表达样例不能被当作当前问题的事实或复制答案，角色描述、事实、工具权限继续解耦。最终整理时重新读取当前用户角色与偏好，变更对接下来的最终回复和后台 agent 任务生效。
- `agent_console/local_logs.py` 是外部本地调试日志出口，不进入独立内核；默认由 LocalAgent.local_logging 启用，写入忽略目录 log/agent_console/<session_id>/dialogue.jsonl 和 runs/<run_id>.jsonl，包含收到的请求、模型上下文/payload、真实思考与流式片段、工具参数/observation、各条输出、token 与失败/取消状态。凭据沿用 bridge.redact 脱敏，图片沿用已投影的附件引用；不裁剪字段或套用远程 TTL。文件按事件 ID 去重，页面加载旧会话时补存仍可读取的历史事件，不能伪造旧流式片段。IO 在线程中执行，写入失败保留正常消息发送并通过日志、事件字段和 /api/status 暴露；请求在上下文准备阶段失败也要保留原问题及异常栈。

- 独立内核变更必须先在私有仓库提交并推送，再更新父仓库 submodule 指针。首次克隆执行 `git submodule update --init --recursive`。部署固定检出 gitlink commit，不使用 `--remote` 跟随分支；现有部署用 `deployment/scripts/sync_agent_runtime.sh` 将旧复制目录备份后安装软链接，保留其他业务数据。
- DeepSeekModel 实现可选 `StructuredModelPort.complete_request(ModelRequest)`，正确传递内核选择的命名 tool_choice；所有含工具或继续工具链的请求统一关闭 thinking，不在强制轮和自动轮间切换思考协议。独立内核不识别 DeepSeek 或工具名称。

- `agent_console/tools/memory.py` 维护纯事实校验、BM25、多 query RRF、`memory_policy_prompt()` 及替换 ID 校验；worker 由外部适配器传入源码，不从 Hok 旧记忆模块提取。记忆不只由“记住”触发：当前用户明确纠正认知、澄清稳定背景/约定或提供与旧记忆/先前推断冲突的稳定信息时，由同一 ReAct 模型语义判断，发现 memory、召回相关记录后保存/更新，不新增关键词判定器或额外意图分类模型。当前用户自己的最新说明优先于过时个人记忆；客观事实纠正先核验，未核实说法只保留用户归属，不能覆盖权威身份、配置或查询证据。只说“不对”而缺少新信息时澄清，短期状态、疑问、假设、玩笑、引用/网页/工具原话及无直接用户新说明的后台任务不自动存为本人事实；nomem 和 memory.use 权限继续有效。`remember_memory.memory_id` 原位更新并保留 created_at；`supersedes` 只接受同一用户已查到的同一事实冲突/重复旧 ID，在 worker 的 WATCH/MULTI 事务内校验全部目标、写新事实并删除其余旧记录，任一目标缺失、越权、只读或无效时整次不写，不能先删后存。相同正文新增或无变化更新幂等，返回 changed=false；新事实与未删除记忆共用原有100条上限。部分纠正保留旧记录中不受影响的内容，条件/时期不同且可同时成立的信息不强行合并。实际保存/替换状态保留在 tool observation 与运行日志，成功后才能确认，存储、权限、时间和身份不进入内核。
- 旧聊天兼容入口、注册器、schema、角色包、绘图 worker、诊断、JSON/主动/被动/摘要缓存和过时开关均已删除。不要恢复第二套聊天实现。历史数据库/Redis 数据未由代码清理删除；`forget_me` 只按可信入口清除本人长期事实及当前 QQ 会话上下文，不删除归档、日志、角色偏好或其他会话。

- 部署恢复使用 `deployment/scripts/restore_application.sh`，先按旧 HEAD 与目标版本的删除列表移除源文件，再 reset/restore；删除列表与 restore 均排除运行时 `.env`，保留现有凭据；禁止仅 reset 导致已退休模块遗留为可导入的未跟踪文件。历史目录继续排除，复制内核备份由 sync_agent_runtime.sh 负责。

- `qq_agent/avatar.py` 注册 `set_bot_avatar`，仅可信入口确认的 `QQBot.super_qid` 获得 `qq.avatar.write`（群/私聊均可），Web 与普通用户不授予。图片可取本次消息和已校验引用中的 attachment（直接图片在前，按1起始序号选择），或本轮 generate_image 返回的 image_resource_id；不接受模型 URL/路径/身份。生成工具在产物输出成功后通过 ctx.add_resource 注册 generated_image 资源，引用只在同一 ToolContext 有效。生成图片读取经 zfunc.agent_read_generated_image 调用 zfile.load_agent_artifact_image，按经过当前资源校验的 artifact_id 读取既有已校验PNG，不把文件IO放入内核；过期/缺失/非图片资源不写QQ。经 `zfunc.agent_set_bot_avatar` 调用 `utils/qq_profiles.set_bot_avatar`，向配置绑定机器人提交 base64 像素，兼容远程 NapCat。写操作通过共享诊断器处理，超时结果未知且禁止自动重放；内核不增加 QQ 专用逻辑。
- `qq_agent/private_messages.py` 在 chat_delivery 类别注册 send_group_member_private_message(user_id, text, group_id?)，只有 QQ 群入口及可信配置管理员私聊获得 qq.private.send，普通私聊/Web/旧任务不自动获得。群请求限定当前群，管理员私聊使用默认或明确选择的一个群；目标必须通过注入成员读取器及统一出口再次校验。只按本次用户明确要求或用户创建时授权的 agent 私发任务发送，历史/引用/网页不构成授权，不读取或发送他人私人记忆。zfunc.agent_send_group_member_private_message 经 utils/message_sender.send_group_member_private_message 直接 await QQ send_private_msg 的真实消息ID，携带已绑定群的临时会话上下文，CQ正文用原生 text 转义，不把入队视为发送成功；不能因失败改群发或自动加好友。正文沿用统一QQ格式化，同轮同群/目标/正文成功去重；超时、断连或无ID用 OUTCOME_UNKNOWN 禁止本轮重放，明确拒绝如实报告。它是独立发送动作，不改变真实身份、授权、个人记忆、正常回复或任务目的地；不伪造收件人对话，也不另写群公共回复记录。工具参数/结果保留在运行记录供 AdminPage 调试，QQAgent.private_messages 统一配置 enabled/max_chars/timeout_seconds（默认 true/4000/45）。独立内核不增加QQ或私发分派逻辑。

### 玩家客户端子模块

- `vendor/hok-player-client` 固定 gitlink 版本（0.6.19，共鸣字段及连接复用修复），`hok_research` 软链接暴露公开 Python 包；不得修改上游以实现机器人限速。
- `api_adapters/player_client.py` 只调用公开登录与只读查询接口，主页和 Android/iOS 双端昵称搜索在适配层逐项编排以确保每个请求经过限速；不扫码、不自动重登或重试、不查询默认登录角色。英雄页面通过 _hero_page() 逐项读取 profile、hero_titles、hero_extra_statistics、hero_road_brief，个人荣誉再按需读取单英雄详情，所有请求逐次经过既有 gate；不调用会隐式追加资产/收藏查询的完整 homepage 聚合。隐私拒绝保留其他来源，限速停止后续扩展请求；普通空历史称号显示0和暂无排名，未读到时保留未知。
- `event_handlers/player_client.py` 解析独立 `#客户端` / `＃客户端` 命令，英雄详情通过 `StaticVariables.HeroList` / `HeroName_replacements` 精确解析英雄名、别名或数字 ID，拒绝模糊、歧义与负数占位映射；省略玩家时仍绑定本人。英雄列表经 `zfunc.player_client_hero_report()` 调用 `business/player_client.py`，经上游 hero_page() 原生筛选/排序，按历史最高战力降序选取 `PlayerClient.display_hero_limit` 个（默认5个，上限5个），仅投影名称、场次、胜负、胜率和战力，不发送 raw 协议数据。`tools/gen_player_client.py` 生成统计图片，字体和独立 PNG 落盘均通过 `zfile.py`；常规/粗体使用从原 APK 提取的 Ex_GameFontYaHei.ttf / Ex_GameFont.ttf，分别由 PlayerClient.report_font_path / report_bold_font_path 配置，不依赖系统字体；空数据及绘图失败返回有界文字。`zevent.py` 经统一出口向原事件发送摘要和图片，其他客户端结果也直接发送文字；这三类自然语言查询不使用合并转发。遵守既有白名单、维修和休眠规则；不修改 AI 工具目录。
- `parse_client_request()` 承接完整匹配的 `#玩家的英雄名`、`#玩家的英雄` 和 `#玩家的数据`（兼容全角井号）。前两类由 `original_hero_reply()` 将原始事件交给既有 `hero_statistics_reply()`，`event_handlers/player_client.reply_stream()` 在本轮同时启动原有统计和客户端查询，`zevent.py` 仍先经统一出口入队原有回复，再发送客户端 `hero_honors(scope=all)` 个人荣誉图或 `heroes(scope=season)` 英雄卡片图补充；原有查询范围不因客户端范围改变，任一来源失败不丢弃另一来源结果；async generator 由 aclosing 绑定本轮请求作用域，取消时回收并发 task，底层同步线程仍占真实执行槽直至结束。显式 `#客户端` 不重复原有统计；`#玩家的数据` 通过 `game_statistics` 选择服务端范围/模式/分路，默认当前赛季、所有游戏、全部分路；支持当前赛年（兼容当前塞年）、全部比赛和五个分路，关键词可在数据之后或玩家名之后。旧英雄 matcher 保留原个人/群u兼容判定，已被客户端 matcher 处理的事件仍由 block 隔离，群u不进入补充链路。玩家按配置昵称、账号键和 `nameref` 唯一匹配，“我”只用真实发送者绑定；无客户端绑定也保留可用的原有统计，不回退登录账号。非前缀直接 @ 仍进入既有 AI 入口。头像只为选中英雄生成配置 CDN URL，经现有头像 API 下载并复用 ID/URL 指纹缓存；头像失败不丢弃统计图，胜率配色与阈值来自 `PlayerClient.win_rate_bands`；默认英雄插画只经 `zapi.player_client_artwork_api()` 获取，zfile 按 ID/URL 指纹保存在独立长期缓存，不宣称为实际穿戴皮肤。
- `zfunc.player_client_text_report()` 调用 `business/player_client.py#text_report()` 对所有客户端文字结果做按接口白名单字段投影，使用中文标题与名称、胜负/胜率、等级、巅峰积分、徽章/称号计数及有界明细，不向用户发送 JSON、raw、未识别字段、位图或内部身份。名称读取与皮肤资源表只经 `zfile.py`，时间格式化只经 `ztime.py`。战绩按明确目标 UID 与区服恢复本人视角并保留“本次返回、不代表全部历史”；缺数据不补0，未知段位/称号/能力子项不猜测；截图数据由 business/player_client_screens.py 白名单投影，场次/胜率/奖牌/MVP 使用新公开统计接口，三类图片消费0.6.16正式显示视图：游戏与英雄的综合分只取 display.composite_score，五维只取 display.radar.plot_ratios；游戏场次/胜率/奖牌等同样优先使用 display 的分路加权口径，不混用 raw 汇总行或旧 native_score。个人荣誉填充 in_use 赛年标签、原生顺序1/2/3/5/4的历史徽章获得次数及 rank_badge 历史称号名次；英雄卡片显示 fight_style 文案、历史称号名次和 branches.by_score 前两个分路段位，图标仍经模板裁取。确实缺失的来源才显示—，缺项说明只在图外。列表上限来自 `PlayerClient.display_item_limit`，搜索为确认目标保留精确游戏UID/区服编号，不混用QQ或浮点格式化。
- `PlayerClient` 在 `config.yaml` 保存查询参数、限速和显式玩家引用；登录资源、会话及安装标识 JSON 仅由现有 `.env` 的三个 `HOK_PLAYER_CLIENT_*_JSON` 注入，`zfile.player_client_state_paths()` 以私有权限投影至忽略目录 `data/player_client/`，不复用旧 account 连接。
- `zfunc.py` 统一维护 DB0 `hok:player_client:rate:*` 滑动窗口、跨部署最小间隔及冷却；缺 Redis 拒绝请求。查询连接与线程锁在 `zdynamic.py` 初始化，超时/取消不提前释放真实执行槽，不创建后台轮询。已有连接的20秒保活只在 `zscheduler.py` 注册，调用 zfunc 窄门面并与查询共用锁；无连接或查询占槽时跳过，不自动登录或重试。正常配额等待按20秒分段保活，查询排队上限来自 max_wait_seconds（65秒），服务端冷却仍立即拒绝。查询串行间隔为1–1.2秒（SDK为0.5秒）、每分钟30次、每小时120次，服务端风控冷却与登录限制不变；适配器对同一目标资料/游戏/英雄来源做60秒、最多16项的连接内缓存，复制结果并在关闭时清空，游戏统计直接使用 profile.game 以复用同一精确身份的资料缓存；不缓存失败、不共享身份、不缓存完整战绩原始对象。英雄卡片仅在插画缺失时取备用头像，单英雄插画和头像并行下载，图片版式/字体不变。接口缓存命中、节流等待、请求及图片资产/渲染耗时只写内部日志，不附用户回复。启动不自动联网，关闭经 `zscheduler.py` hook。
- `scripts/resolve_player_client.py` 从 `zdb.load_latest_player_client_names()` 的真实对局 epoch 与快照取得昵称，只保存唯一完整昵称匹配及服务端身份字段；同名、缺数据与拒绝不猜测、不混用营地 role_id 与新 UID。默认双端查询，13002 按新版语义保留为该端空结果，不误判风控；`--refresh` 重查已绑定账号时只更新同一 UID/区服/平台的服务端引用，不按新同名结果换绑。脚本使用相同限速，发生异常立即停止并保留已绑定结果及待确认候选；短分钟窗口在等待预算内延迟，超出等待预算的配额与风控冷却仍拒绝；人工明确跳过的账号由 `binding_skip_players` 保存，人工更新的完整昵称由 `nickname_overrides` 保存。

- 业务缓存初始化只在 `zscheduler._initialize_business_cache` 启动 hook 执行，各项错误隔离并仅记录组件/错误类型；`hok/__init__.py` 不在导入时请求外部数据。旧营地会话失效不能阻断整个插件与新客户端入口。

- 战绩查询、排行及定时/指定日期导出共用 `business/player_data.py` 的按日分页采集：现有 `api_adapters/wzry.py` 以 POST `/game/morebattlelist` 的 `lastTime` 请求单页，业务层使用响应游标持续翻页，直到越过目标游戏日（沿用 `ztime.time_sul()` 的 03:30 边界）、`hasMore=false` 或空页；不得以单页30条或页大小判断当天已完整。跨页对局去重并按时间排序，实时状态保留首页值；游标无效/不推进、翻页失败或中途不可见必须报错，不将部分数据作为完整战绩保存，指定用户导出失败不得删除既有日记录。已绑定同一玩家/营地账号/角色时，通过两个线程并行查询营地分页与客户端 matches() 普通/娱乐双流；business/player_client_history.py 用精确 UID/区服恢复本人视角，按 desk sequence 或唯一的英雄/KDA/时长/时间匹配去重，营地完整字段优先；客户端独有记录使用稳定负 int64 序号避免与营地缓存碰撞，每次查询都将原始 clientMatch 和精确 clientPlayer 引用归档到个人快照；网页副本只含列表展示字段，不携带完整原始对局协议，来源、缺失项和摘要保存在日历史；camp_battle_detail() 将可用玩家/阵营/英雄/KDA/经济/伤害/装备/技能数据投影为既有 head/battle/redTeam/blueTeam/redRoles/blueRoles 结构，详情与参与者仍经 zfile→PostgreSQL/应急 JSON 写入 battle_details/battle_participants。zfile 的 battle 归档分类接受负 int64 序号。客户端 UID/world 仅经已配置精确绑定映射营地 userId/roleId，未绑定玩家的营地身份为 null，禁止直接拿 UID 冒充；评分由 SDK score/score_display 写入 gradeGame/gradeDisplay（旧快照按已确认的 score_raw 转换，零分有效），控制等原值另存 native 字段，未知界面值保留 null。装备通过 zfile.player_client_battle_assets() 的离线官网目录补齐名称/图标；selectedSkills 四槽由 SDK 显式配置补齐名称、描述和来源英雄，不按 ID 数值猜英雄，装备类效果保持无来源英雄。日历史和查询网页的客户端 GameSeq 序列化为字符串，网页兼容旧 JSON 的超长整数。scripts/backfill_player_client_battle_details.py 仅经公开门面离线回填已有 personal_snapshots 及旧网页查询缓存，默认计数预览，--apply 幂等保存详情，不请求游戏 API，不改历史列表或 schema。保留旧客户端记录，不用配额/超时覆盖为无对局；双方失败不覆盖历史；来源失败写 sourceErrors 结构化元数据，采集范围只记录日志/结构化元数据，战绩回复不再附客户端补充列表或协议/缺项说明。未知评分在旧 JSON 字段保留带 GradeMissing 的0占位，但 SQL 评分/段位/未知KDA列写 NULL，评分均值和代表局排除该占位；不把客户端 desk ID 当营地 Params 补拉详情。在线/观战等只读取实时状态的请求继续取单页。`vendor/hok-camp-client` 仅供登录适配，战绩分页只参考其协议资料，禁止调用该模块获取战绩。

### 1.6 管理员账号登录适配

- `vendor/hok-camp-client` 为固定版本营地协议子模块，`hok_camp_client` 仅链接其发布包；不得向子模块提交会话。`login_console/` 是独立于 NoneBot 的账号登录适配层，由 Web 管理员入口按需启动固定 JSON-line worker，不导入 `hok`、不注册后台任务、不自动循环登录或重试。
- `login_console/providers.py` 固定接入营地、官方 QQ/MSDK 客户端与本机 NapCat WebUI。营地 QQ transport 仅在适配层覆写初始化以禁用环境代理；NapCat 只接受 loopback HTTP(S)，HTTPS 必须配置证书 SHA256 指纹并严格核验，不调用注销、重启或 `SetQuickLogin`（发起快捷认证）接口。管理员扫码允许更换账号；营地在全新会话中显式调用一次 `/game/roles`，选择唯一角色/唯一主角色，否则由管理员选择；无角色清空旧角色，未知结构拒绝保存。官方以新目录的首选区服验证后保存。NapCat 验证实际 uin 后仅调用 `SetQuickLoginQQ` 同步重启账号，并同步 `NAPCAT_QUICK_ACCOUNT`；更换 QQ 时通过 `OB11Config/SetConfig` 继承原 Bot 的 OneBot 网络配置，避免新账号缺少反向连接。仅从显式 `AccountSessions.napcat.config_dir` 中读取原已配置机器人账号的 native 文件（或 NapCat 原生默认文件），不枚举其他账号；私有副本随 `HOK_NAPCAT_ONEBOT_JSON` 保存在唯一 `.env`，不向前端返回。网络失败报告 unknown。
- `login_console/store.py` 是该独立进程的文件边界：私有临时材料仅在 `data/account_sessions/`（0700/0600），二维码不进入 `file_transfer/`；`.env` 凭据更新使用 flock、并发版本比较、dotenv 往返验证与原子替换。成功验证后更新 `HOK_CAMP_SESSION_JSON`、原有营地 token/encoderes 或 `HOK_PLAYER_CLIENT_SESSION_JSON`；`HOK_PLAYER_CLIENT_ACCOUNT_JSON` 保存已验证的区服路由，`HOK_NAPCAT_ACCOUNT_JSON` 保存已验证 QQ 身份；非敏感身份投影同步到唯一 `config.yaml` 的 `wzry`、`PlayerClient` 和 `QQBot.bot_qid`，保留白名单/管理员/玩家绑定。单一完整 `.env` 会话为提交点，配置写入失败回滚凭据，中断后由 worker 启动幂等协调。NapCat QQ 会话继续由 NapCat 自行持久化，`HOK_NAPCAT_WEBUI_TOKEN` 仅用于访问其本机管理接口。
- 配置仅来自 `config.yaml#AccountSessions` 与原有 `wzry`/`PlayerClient`/`QQBot`/`Redis`。`login_console/manager.py` 在 DB0 `hok:auth:*` 下维护状态缓存、跨进程租约和限速，二维码至少30秒、轮询至少5秒、状态检查至少30秒；官方认证共用 `hok:player_client:rate` 的登录额度及失败冷却。纯 Lua 脚本由 `login_console/rate.py` 与 `zfunc.py` 共用。无 Redis 时拒绝发起请求。
- `hok/zfile.refresh_login_credentials()` 是运行中热加载的 IO 入口，更新营地协议/凭据、官方会话/路由与已验证机器人 QQ，QQ agent 服务的未来 principal 也使用新 bot_id，已有任务创建者/授权/目的地不变。群消息归档前和统一发送队列取 bot 前刷新，不另建轮询任务。营地请求发送前读取新参数，官方客户端在 `zdynamic.py` 的既有查询锁内检测会话指纹，旧请求结束后关闭旧连接再构建新连接。Web 的旧营地查询同样在请求前从唯一 `.env` 更新。

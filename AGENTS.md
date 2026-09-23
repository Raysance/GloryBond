# HOK_QQBot NBot — 子项目补充规范

本文件只记录 `NBot/` 子项目的目录职责、配置来源、调用边界和运行约定。通用代码规范、仓库边界、README 定位与 `.gitignore` 分层规则见根目录 `AGENTS.md`。

## 1. 目录与文件职责（`hok/`）

以下规则适用于 `hok/` 下所有代码。

- `hok/__init__.py`：NoneBot 插件入口；注册插件元信息并集中加载配置、静态变量、动态变量、API、事件、文件、业务函数、定时任务与时间工具。
- `hok/config.py`：Pydantic 配置模型定义；除非明确需要，否则不要新增依赖或复杂逻辑。
- `hok/zdynamic.py`：**动态变量**导入与初始化必须放在这里；其他模块通过 `from . import zdynamic as dmc` 读取动态配置初始值；运行时需要跨部署持久化的状态必须通过 Redis 业务接口保存。
- `hok/zevent.py`：所有消息收发的**最初层**与路由层；只做初步解析、分发与调用接口，不在此实现具体业务算法/流程细节；群消息最初层提取 `group_id`、`user_id`、`message_id`、引用消息 ID 与纯文本后调用 `zfunc.py` 保存历史，保存失败只记录错误且不得阻断正常路由；普通用户的“代表局”自然语言查询在此路由且必须以 `#` 或 `＃` 开头，正式回复不得附带调试信息；`##rep3` 仅供管理员按日期区间调试每日三类指数冠军；`#巅峰排名` / `#巅峰排行` 仅调用 `zfunc.py` 的本地结构化历史排名流程；`#梯度` / `＃梯度` 仅调用 `zfunc.py` 的梯度长图流程；消息中同时出现“战力”和“查询”时调用 `zfunc.py` 的指定地区荣耀战力查询流程，英雄名和地区名顺序不限；B 站 UP 视频订阅命令只在此做命令剥离并调用 `zfunc.py`，用户命令支持 `#订阅xxx`、`#取消订阅`、`#最新视频`、`#我的订阅`，不要求包含“B站”关键词。
- `hok/zchat.py`：AI chat 的结构化消息组装、多轮 tool-call 循环、细粒度工具白名单与参数校验入口；玩家战报、单英雄统计、英雄汇总等意图必须使用各自独立的结构化 tool schema，由程序解析玩家/英雄并调用确定的 `zfunc.py` 业务接口，禁止把多个意图重新合并为自然语言总入口；任何 tool call 无论成功或失败都必须生成对应的 tool result；群聊历史检索由模型先基于原 query 生成多组互补查询，再调用本地检索接口，命中后可按 `message_id` 展开上下文。
- `hok/zfile.py`：文件/IO 读写统一入口；所有 IO（读写文件、落盘缓存、路径拼接等）必须通过此模块提供的接口完成；荣耀战力地区树统一从 `data/honor/districts.json` 读取；历史日期枚举与每日数据读取通过此模块转发到 PostgreSQL，数据库异常时才读取应急 JSON；梯度英雄头像属于长期资产，按英雄 ID 与头像 URL 指纹保存在 `resources/wzry_images/hero_avatars/`，`file_transfer/` 只保存每次查询重新生成的梯度长图；HOK Exception 运行时错误记录统一追加到 `log/error.log`。
- `hok/zdb.py`：PostgreSQL 数据访问唯一入口；负责结构化历史、对局详情、个人快照、战力分析、英雄梯度、英雄排行及导入清单的读写。历史业务以 PostgreSQL 为主数据源；仅当数据库写入失败时，`zfile.py` 才生成应急 JSON。
- `hok/zfunc.py`：业务函数的**具体执行流程**（面向 `zevent.py` 暴露接口）；业务流程编排、调用工具、组装输出在此完成；同时作为 AI chat 工具访问现有业务能力与 Redis 群聊历史的唯一业务接口，负责保存、读取、检索和展开群聊记录，具体分词、BM25 与结果融合算法委托 `zmemory.py`；新版群聊历史按群永久保留全部文本消息，`ChatHistoryMaxMessages` 为 `0` 时禁止裁剪，仅在显式配置正整数时作为安全上限；`peak_rank_process()` 只读取 `this_season_start_date` 当日及之后的本地结构化历史，为每位玩家选取最近的有效巅峰赛后分并生成排名，禁止调用实时战绩或外部 API；`honor_power_query_process()` 从整句中模糊识别中文或拼音英雄名，并按最具体地区优先从本地地区树解析任意地区 `adcode`，只调用一次指定地区 `ranklist`，输出榜单 0% / 25% / 50% / 100% 四个位置的实际名次与战力，不查询本人战力或名次；`representative_battle_query_impl()` 负责普通用户代表局查询并将正式文字、图片路径和图片下方 AI 文案与调试载荷隔离；`representative_battle_range_debug_impl()` 仅组装每日三类指数冠军的纯文本区间调试结果；B 站 UP 视频订阅状态、Redis 去重、Web 详情页链接和推送消息组装在此完成，订阅身份必须以 UP 的 `mid` 为准，昵称仅用于展示、模糊匹配和搜索关键词缓存；B 站订阅持久化以 Redis key `bili:video_subscriptions` 为准，所有用户均可订阅多个 UP；战绩隐身禁用名单以 Redis key `battle:invisible_disabled_qids` 为准；戳一戳底蕴的英雄对位指标优先查询完整阵容，无样本时按五路对位拆分并汇总；阵容 AI 短评能力保留在 `with_ai_analysis` 参数后，启用时与玩家底蕴数据并行获取并缓存，当前戳一戳与网页底蕴分享入口均传入 `False` 禁用。
- `hok/zmemory.py`：所有 AI 对话记忆、摘要、长期记忆、表情记忆相关的读写与策略接口，并提供群聊历史的 jieba 分词、BM25、多 query 融合和上下文展开算法；chat 动态上下文仍只允许自动加载当前用户经 `f_chat()` 捕获的直接人机对话，不得自动混入历史 summary、强制记忆、群聊被动发言、其他用户上下文或回复引用内容；群聊历史只能由 `zchat.py` 在模型明确调用检索工具时按需注入为 tool result。
- `hok/chat_roles/`：chat 角色扮演的可插拔角色包；每个角色模块的 `ChatRole` 只维护该角色自身的信息与表达特征，角色无关的通用约束集中维护并在角色信息之后单独追加；角色通过包级注册表接入，当前默认角色由 `variables_static.json` 的 `chat_role` 指定。
- `hok/zscheduler.py`：所有定时/间隔任务的声明、注册与定义（不要在别处私自创建 scheduler 任务）；旧版凌晨 03:30 的 `daily_user_summary` 已停用，禁止重新注册会清理原始聊天记录的摘要任务；每日 23:30 的 `notify_msg()` 统一发送当日王者战报，并按“代表局文字 → 图片 → AI 文案”的顺序发送代表性对局；网页底蕴分享保留阵容 AI 短评参数，当前以 `False` 禁用；B 站 UP 新视频轮询任务只在此注册，实际检查与推送编排调用 `zfunc.py`。
- `hok/zstatic.py`：**静态变量**导入必须放在这里（从文件与系统环境变量导入）；其他模块通过 `from .zstatic import *` 获取静态变量。
- `hok/ztime.py`：时间工具与日期处理统一入口；任何时间计算、格式化、时间窗口判断都应调用这里的接口；代表局查询中的自然语言日期及区间统一由 `parse_representative_battle_date()`、`parse_representative_battle_date_range()` 解析，群聊历史检索时间边界统一由 `parse_chat_time_bound()` 解析。
- `hok/zutil.py`：基础工具集；统一导入常用库与通用小工具（不要在各处散落重复 import 与重复工具实现）。
- `hok/utils/message_sender.py`：发送消息统一入口；任何对外消息发送必须调用此模块的函数接口（禁止绕开直接调用底层适配器发送）。
- `hok/zapi.py`：与外部服务/API 交互的适配层（请求封装、签名、响应解析）；AI chat 在此提供单轮 OpenAI-compatible Responses API 请求，并归一化 `output` 中的 `function_call`，多轮编排留在 `zchat.py`；普通聊天使用 DeepSeek Responses endpoint，`&` 联网聊天使用火山方舟标准 Responses endpoint 与内置 `web_search`，不得回退到应用 Bot 的 Chat Completions endpoint；其他业务编排仍应留在 `zfunc.py`；荣耀战力查询的指定地区 `ranklist` 请求只在此组装和发送；B 站 UP 视频追踪只在此处理 WBI 签名、用户/视频搜索、用户卡片请求和响应归一化，视频结果需保留 `aid` 与 `bvid`，其中 `aid` 用于事实校验后的 App schema 唤起。
- `hok/zkpl.py`：KPL 数据统一入口；仅 `get_match_list_json()` 与 `get_match_detail_json()` 负责获取赛程和完整比赛数据，其他 KPL 转换与兼容接口必须调用二者。
- `hok/zdiy.py`：自定义/临时扩展的业务能力聚合处；当能力稳定后应迁移到职责更明确的模块（`zfunc.py` / `tools/` / `zapi.py` 等），避免长期堆叠。

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

### 1.4 PostgreSQL 数据目录与迁移脚本

- `database/schema.sql`：结构化历史库的 schema、表、外键与查询索引。
- `scripts/import_json_to_postgres.py`：幂等回填入口；只读扫描原始 JSON，并通过文件大小与纳秒 mtime 清单跳过未变化文件。

### 1.5 部署运行方式

- 部署服务器上的 NoneBot 进程由 `hok-nbot.service` 统一管理，禁止在发布流程中再使用 `nohup` 或按端口手工结束进程。
- GitHub Actions 在完成代码同步后通过 `systemctl restart hok-nbot.service` 发布，并以 `systemctl is-active` 验证启动结果。
- `hok-nbot.service` 从 `/QQBot/NBot` 启动 `deploy_runner.sh`，依赖 Redis、PostgreSQL 与网络就绪，运行日志仍写入 `log/run.log`。

## 2. 配置与变量的来源（必须遵守）

### 2.1 配置文件（``）

- `config.yaml`：王者荣耀/Steam/AI 的 API-Key、AI Responses 模型、QQ群号、王者荣耀 request 参数、服务器 IP/域名等配置。
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
3. **AI 与 HTTP API**：与 OpenAI、AI API、`requests` 等外部 HTTP/API 请求相关的库，只能在 `zapi.py` 中导入和使用；业务流程只调用 `zapi.py` 的适配函数。
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

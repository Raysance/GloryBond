# HOK_QQBot NBot — 子项目补充规范

本文件只记录 `NBot/` 子项目的目录职责、配置来源、调用边界和运行约定。通用代码规范、仓库边界、README 定位与 `.gitignore` 分层规则见根目录 `AGENTS.md`。

## 1. 目录与文件职责（`hok/`）

以下规则适用于 `hok/` 下所有代码。

- `hok/__init__.py`：NoneBot 插件入口；注册插件元信息并集中加载配置、静态变量、动态变量、API、事件、文件、业务函数、定时任务与时间工具。
- `hok/config.py`：Pydantic 配置模型定义；除非明确需要，否则不要新增依赖或复杂逻辑。
- `hok/zdynamic.py`：**动态变量**导入与初始化必须放在这里；其他模块通过 `from . import zdynamic as dmc` 读写动态变量。
- `hok/zevent.py`：所有消息收发的**最初层**与路由层；只做初步解析、分发与调用接口，不在此实现具体业务算法/流程细节。
- `hok/zfile.py`：文件/IO 读写统一入口；所有 IO（读写文件、落盘缓存、路径拼接等）必须通过此模块提供的接口完成。
- `hok/zfunc.py`：业务函数的**具体执行流程**（面向 `zevent.py` 暴露接口）；业务流程编排、调用工具、组装输出在此完成。
- `hok/zmemory.py`：所有 AI 对话记忆、摘要、长期记忆、表情记忆相关的读写与策略接口。
- `hok/zscheduler.py`：所有定时/间隔任务的声明、注册与定义（不要在别处私自创建 scheduler 任务）。
- `hok/zstatic.py`：**静态变量**导入必须放在这里（从文件与系统环境变量导入）；其他模块通过 `from .zstatic import *` 获取静态变量。
- `hok/ztime.py`：时间工具与日期处理统一入口；任何时间计算、格式化、时间窗口判断都应调用这里的接口。
- `hok/zutil.py`：基础工具集；统一导入常用库与通用小工具（不要在各处散落重复 import 与重复工具实现）。
- `hok/utils/message_sender.py`：发送消息统一入口；任何对外消息发送必须调用此模块的函数接口（禁止绕开直接调用底层适配器发送）。
- `hok/zapi.py`：与外部服务/API 交互的适配层（请求封装、签名、响应解析）；业务编排仍应留在 `zfunc.py`。
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
- `hok/tools/kpl_match_collector.py`：B 站 KPL 赛事赛程与单场数据采集工具。
- `hok/tools/PowerAnalyzeEvaluator.py`：战力分析结果一致性评估脚本。

### 1.2 Debug Tools（`hok/debug_tools/`）

`hok/debug_tools/` 仅用于**调试工具脚本**与实验性验证；上线逻辑不得长期停留在此目录。调试工具必须以文件夹为单位组织，每个调试目标对应 `debug_tools/` 下的一个独立文件夹，文件夹内再放置该调试工具的具体脚本、测试数据、样例输入输出等内容。调试脚本应模块化、最精简地调用项目中已有函数，不得复制业务实现或绕开项目既有接口。

调试工具的 CLI 规范与现有工具说明维护在 `hok/debug_tools/AGENTS.md`。总索引只记录 `hok/debug_tools/` 作为调试工具目录，不在根规范中逐项记录脚本或函数功能。

### 1.3 Local Debugger（`local_debugger/`）

`local_debugger/` 是根目录共享本地调试器运行时，用于供 `hok/debug_tools/` 下的调试脚本复用本地导入环境。它只负责准备项目根目录导入路径、必要环境变量、缺失的 import-time 依赖占位，以及绕过 `hok/__init__.py` 的模块导入入口；不得承载线上业务逻辑、不得发起外部请求、不得替代 `hok/` 内已有业务接口。

## 2. 配置与变量的来源（必须遵守）

### 2.1 配置文件（``）

- `config.yaml`：王者荣耀/Steam/AI 的 API-Key、QQ群号、王者荣耀 request 参数、服务器 IP/域名等配置。
- `variables_static.json`：用户 QQ 号、王者荣耀 roleid/userid、用户昵称、SteamID、常见俚语缩写、赛季起止时间、英雄 ID 映射、部分功能 prompt 等稳定数据。
- `variables_dynamic.json`：动态变量初始值，例如是否记忆、机器人是否开放、英雄梯度、今日新闻、上一次查询战绩时间、今日导出失败用户名单等。

原则：
1. **任何可能变化的值**不得硬编码在业务逻辑里，必须进入上述文件或对应的静态/动态变量模块。
2. `zstatic.py` 负责加载静态配置；`zdynamic.py` 负责加载动态配置并提供可写入口。

### 2.2 Linux 环境变量（在 `hok/zstatic.py` 导入）

部署环境下预计存在以下环境变量（缺失时的处理策略以现有代码为准，禁止凭空新增“变量不存在”的冗余判断链）：

- `REDIS_CONF`：Redis 配置文件路径。
- `BOT_PATH`：Bot 部署目录。

项目根目录统一使用全局变量 `BOT_PATH` 的绝对路径，通过 `hok/zstatic.py` 的 `project_root` 暴露给其他模块；Web 静态产物目录统一使用 `BOT_PATH/file_transfer/`，通过 `temp_path` 暴露，不再从 `NGINX_HTML` 读取。

## 3. 代码结构与改动边界

1. **入口与路由**：`zevent.py` 仅做“接收 → 解析 → 选择接口 → 调用”，不承载业务细节。
2. **流程编排**：业务流程（多步调用、拼装文本/图片/数据）写在 `zfunc.py`，并保持接口可被 `zevent.py` 直接调用。
3. **状态与缓存**：
   - 运行时可变状态：统一放在 `zdynamic.py`（通过 `dmc.xxx` 访问）。
   - 静态映射/常量：统一放在 `zstatic.py`。
4. **IO 与时间**：IO 一律走 `zfile.py`；时间一律走 `ztime.py`。
5. **发送消息**：所有对外消息发送必须走 `utils/message_sender.py`，用于统一出口与后续可观测性。
6. **架构规范同步**：每次升级项目、调整目录职责、改变调用链或修改项目架构时，必须同步更新本 `AGENTS.md`，确保后续 AI 与开发者读取到的架构规则始终与当前项目一致。

### 3.1 库导入边界（严格）

1. **NoneBot 与机器人适配器**：与 NoneBot、机器人事件、消息段、适配器、bot 实例操作相关的库，只能在 `zevent.py`、`utils/message_sender.py` 等顶层消息入口/出口脚本中导入和使用；业务层不得直接导入。
2. **Redis 交互**：与 Redis 连接、读写、缓存交互相关的库，只能在 `zfunc.py` 中导入和使用；其他模块需要 Redis 数据时必须通过 `zfunc.py` 暴露的业务接口获取。
3. **AI 与 HTTP API**：与 OpenAI、AI API、`requests` 等外部 HTTP/API 请求相关的库，只能在 `zapi.py` 中导入和使用；业务流程只调用 `zapi.py` 的适配函数。
4. **时间处理**：`time`、`datetime`、时区、日期解析与时间窗口判断相关库，只能在 `ztime.py` 中导入和使用；其他模块必须调用 `ztime.py` 的时间工具接口。
5. **IO 与路径处理**：文件读写、目录创建、路径拼接、缓存文件操作等 IO 相关库，只能在 `zfile.py` 中导入和使用；其他模块必须通过 `zfile.py` 接口完成 IO。
6. **例外处理**：如用户明确提出突破上述导入边界，必须质疑用户，如果确认无误，先调整模块职责并同步更新本 `AGENTS.md`，不得在业务代码中临时绕开。

## 4. NBot 异常提示出口

1. 需要向用户反馈的异常必须通过 `utils/message_sender.py` 或既有消息发送接口输出。
2. 异常提示应包含发生位置、关键参数、`repr(e)`/`str(e)`，便于在群聊或日志中检索。
3. 仅面向本地调试的脚本可只输出到调试终端，但不得混入线上业务路径。

## 5. NBot 代码习惯

1. 优先复用项目内现有命名、结构与导入方式，例如 `from .zstatic import *`、`from . import zdynamic as dmc`。
2. 用户可见文本（群消息、提示语）必须可检索、可定位，避免“只有一个笼统的失败”。

## 6. NBot 变更自检清单

1. 新增代码是否放在了职责正确的 `hok/` 模块中？
2. 是否所有 IO、时间、消息发送都走了指定模块？
3. 是否遵守了 NoneBot、Redis、OpenAI/requests、time、IO 相关库的导入边界？
4. 是否需要同步更新本文件或更深层目录的 `AGENTS.md`？

# Local Agent Studio

可直接运行的本地聊天 UI，使用 Python 3.11 或更新版本。`agent_console` 仅作为 `agent_runtime` 的外部适配层，QQ 接入时复用同一内核与工具协议，替换输入和输出适配器。

## 启动

在仓库根目录执行：

```bash
local_debugger/.venv/bin/python -m agent_console
```

然后打开 http://127.0.0.1:8765/ 。首次缺少环境时，先执行 `python3 local_debugger/setup_env.py`。端口可用 `--port` 覆盖，其他非密钥设置在根 `config.yaml` 的 `LocalAgent`。

需要已配置并能免交互连接的 `ssh Aliyun`。启动时通过 SSH 读取运行中的服务器配置和 API 源码，不上传项目、不部署 HTTP 服务、不修改数据库 schema。模型在本地直连 DeepSeek；查询、记忆、搜索、图片及 Python 执行通过外部 SSH 适配器调用。

## 功能

- 真实 DeepSeek 流式正文和 `reasoning_content`，同一工具链保持思考模式并续传原始思考字段。
- 按需披露工具，动态聊天/王者 SQL、BM25/RRF 群聊检索、联网搜索、长期记忆、图表和图片生成。
- 当前适配器强制先检索历史、再发现所需能力，避免模型把未披露工具误报为不可用。记忆由入口绑定当前会话调用者，保存本人偏好无需提供 QQ 或玩家名。
- 统一参考数据能力：`references` 类别下的 `list_reference_catalogs` 和 `lookup_reference_data` 提供玩家多种 ID、昵称/别名、英雄名称、榜单参数、段位与表达映射；重复 QQ、同名和多账号关联保留全部关系。
- 一次输入可有多条阶段性回复、图片和最终回复。工具输入、结果、模型上下文和执行时间线可以展开。
- 回答旁显示本轮 token 总量，输入框下显示会话总量；点击可查看输入、输出、缓存命中、命中率及各次模型请求，角色生成也计入。多次请求的系统提示、上下文和工具结果分别计入输入；缓存是输入子集，思考是输出子集，不重复相加。用量来自模型接口，未知字段显示“—”，中断、失败或缺失用量标注为部分统计。历史会话按持久事件恢复，重连不会重复计数。
- 回答作为主要内容，思考与工具调用默认折叠到“执行过程”，右上角仍可查看完整轨迹。
- 会话及完整持久事件保存在服务器 Redis DB0；浏览器保存会话列表，刷新可恢复记录。
- 延迟/周期后台任务保存在服务器，使用同一内核执行。任务仅在本地适配器运行期间调度；停机后租约到期可重新领取。
- 查询或推理使用 `agent` 任务；固定文字定时发送使用 `message` 任务，直接走同一输出端口，无额外模型调用。支持最短 1 秒周期、限定执行次数和序号模板 `{run}` / `{max_runs}`。省略首次延迟时在一个周期后发送；后续按原计划计时，错过的时间点跳过。调度可与前台聊天同时执行。
- 支持注册额外同步/异步 Python 函数；无需改核心循环。
- 绘图默认使用极光主题，支持霓虹夜色和落日主题：渐变条形、趋势面积、多系列配色、气泡散点、带轴标签的热力图、环形组成图，以及数值标注和口径脚注。可直接要求“用霓虹夜色主题画图”。所有图在同一隔离 Python 环境生成，样式不进入 ReAct 内核。
- 角色库与用户偏好完全在外部适配层：网页右上角可以选角色、设置回复长度/称呼/表达偏好。默认用户是 example_user_10（配置昵称示例玩家65），默认角色为牧濑红莉栖；选择“通用助手”可关闭虚构角色风格。角色选择与偏好按用户跨会话保存。
- `roleplay` 类别提供 `list_roles`、`select_role`、`add_role_from_web`、`set_reply_preferences`。可直接说“联网添加《原神》的安柏并选用”或“以后回复简短、少用表情”。添加会实际联网检索并生成背景、性格和语言档案，保留网页来源及独立模型请求/响应轨迹；失败不保存。自建角色仅创建用户可见。切换从下一次对话生效，后台 agent 任务读取执行时的最新角色。

## 数据与隔离

服务器实际数据源是 PostgreSQL 和 Redis，并非 MySQL。SQL 使用运行服务的 `hok_chat_reader` 账号、只读事务和 AST 白名单；整批 SQL 校验通过后才连接数据库。群聊通过受作用域约束的安全视图读取。

共享目录在 `shared/agent/`，内容来自仓库的已验证语义目录。服务器尚未部署语义视图时，适配器将可信视图定义编译为 CTE。模型仍只看到语义视图名，不直接访问采集层。此兼容方式对大范围查询可能受服务器 5 秒查询上限限制。

`shared/agent/reference_data/manifest.json` 声明参考目录的源字段、ID 命名空间、用途和上下文投影。当前源为服务器 `config.yaml#StaticVariables`；也支持通过清单改为独立 `static_variable.json`。每次新请求、后台执行和参考工具调用均读取最新源，返回版本摘要。常用玩家昵称、别名与 QQ 映射进入上下文，完整营地/角色/Steam ID 通过工具查询。此目录与 SQL、记忆分别提供各自的数据，参考查询的 `dataset_id` 可在 Python 中与 SQL 数据集关联并绘图。

服务只监听本机 loopback；请求校验 Host、Origin、本地会话 cookie 和写请求头。SSH 密钥、模型 key、DSN 不进入浏览器或新文件。运行记录保留完整输入和工具资料，因此本界面作为受信任的本地管理员控制台使用。

外部适配器分别维护业务连接和状态连接：数据库/搜索/图片/沙箱走业务连接，对话、运行事件、记忆和任务走状态连接，避免慢业务调用阻塞定时通知。事件通过通用 `metadata` 标记后台来源；后台通知不覆盖正在输入或执行的前台聊天状态。

本地 UI 通过 `LocalAgent.player_key: example_user_10` 从服务器权威映射唯一解析 QQ，作为稳定的 `Principal.user_id`；“我”默认指示例玩家65，游戏查询使用 `player_key`。本人长期事实与 QQ 共用 `hok:memory:facts:<QQ>`，每次对话自动读取用于个性化；回复偏好和角色选择单独存储于 `hok:agent_runtime:console:roleplay:<用户摘要>:*`。旧匿名会话的 `local-ui:<session>` 事实保留，未自动归入 example_user_10。会话对话记录仍按会话隔离，状态、任务和产物使用 `hok:agent_runtime:console:*`。独立模块无 QQ 类型、角色、配置、数据库和界面依赖。

内置角色可独立修改 `shared/agent/roles/*.json`（修改后重启本地适配器）；默认角色设置在 `LocalAgent.default_role`。`agent_console/roleplay.py` 负责角色上下文组合，`identity.py` 单独负责本地 HOK 身份与权限策略，`roleplay_models.py` 负责数据校验，`roleplay_store.py` 负责隔离持久化，`tools/roleplay.py` 负责工具注册。最终送入内核的仍是通用 `RunRequest.system_prompt` 和 `ToolRegistry`，QQ 适配器接入时可复用角色服务并传入可信用户身份。

生成的 Python 在远程 bubblewrap 内执行，关闭网络、不挂载服务器应用与凭据，限制 CPU、内存、执行时间、输出文件及产物类型。依赖缺失时拒绝执行，不回退宿主解释器。

## 复用内核

安装独立包：`pip install ./agent_runtime`。独立包仅依赖 Pydantic。外部提供 `ModelPort`、`StatePort`、`OutputPort` 和 `ClockPort`，然后构造 `AgentRuntime`。任意业务函数通过 `ToolRegistry.register(...)` 注入，默认按权限向模型披露；需要渐进披露时声明 `initially_visible=False`，再由应用自己的发现工具选择披露。

本应用的工具定义在 `agent_console/tools/application.py`，由 `register_application_tools(..., service=..., catalogs=...)` 接入。SQL 方言/校验器、参考查询、数据集投影和持久任务转换也都在 `agent_console/`；数据库 schema 从共享目录的 `schema` 字段显式传入。应用提示词、工具名称和群聊规则不进入内核。`description_provider` 和 `result_projector` 是工具可选的动态描述/结果投影回调；内核只执行回调和通用预算约束，不识别返回值的业务结构。

QQ 接入时以可信事件构造 `Principal`，把群号及经过验证的跨群授权放入 `attributes.chat`，由外部适配器解释；群聊固定当前群，跨群只允许验证过的管理员私聊。`OutputPort` 将 `output.message` / `output.artifact` 转给项目统一消息出口。旧后台任务的群字段由外部任务转换器兼容读取。

当前版本可以恢复会话记录和后台任务；正在执行的模型请求在本地进程重启后不会自动重放，避免重复发送或生成收费图片。外部发送接口若无幂等能力，也不能保证严格只发送一次。

## 检查

绘图主题、默认主题和说明放在 `shared/agent/plots/catalog.json`，可独立修改并重启本地适配器。参数和字段校验在 `tools/plotting.py`，可信渲染库在 `plot_renderer.py`；一般 Python 也预置 `render_chart`、`apply_plot_style` 和 `plot_themes`。热力图长表传 `value` 数值列，缺失格默认留空，明确确认后才传 `fill_value=0`；重复格需先在 SQL 聚合或显式传 `aggregation`。结果截断自动显示提示，趋势线不生成额外观测点。

```bash
local_debugger/.venv/bin/python -m unittest tests.test_agent_runtime tests.test_agent_console tests.test_agent_tasks_memory tests.test_reference_data tests.test_agent_roleplay tests.test_agent_plotting
node --test tests/test_agent_usage.js
```

自动测试使用脚本模型，不调用付费服务。真实 SSH/SQL/Python/API 的检查在开发时手动完成，不接入启动或部署诊断。

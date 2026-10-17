# Local Agent Studio

可直接运行的本地聊天 UI，使用 Python 3.11 或更新版本。`agent_console` 仅作为 `agent_runtime` 的外部适配层，QQ 通过 `qq_agent/` 复用同一内核、工具与角色服务，以 QQ 输入和输出适配器接入。

## 启动

在仓库根目录执行：

```bash
local_debugger/.venv/bin/python -m agent_console
```

然后打开 http://127.0.0.1:8765/ 。首次缺少环境时，先执行 `python3 local_debugger/setup_env.py`。端口可用 `--port` 覆盖，其他非密钥设置在根 `config.yaml` 的 `LocalAgent`。

本地 Web 使用 `https://zenmux.ai/api/v1`，文字和图片均显式调用 `deepseek/deepseek-v4.1-flash`，`LocalAgent.llm.api_key_env` 引用现有 `.env` 的 `LLM_API_KEY`。远程 QQ 使用 DeepSeek 官方 `https://api.deepseek.com` 的 `deepseek-flash`，`ChatAPI.api_key_env` 引用同一 `.env` 的 `HOK_DEEPSEEK_API_KEY`。进程环境可覆盖文件值，`HOK_ENV_FILE` 可覆盖密钥文件路径。ReAct、回复整理、联网角色生成及远程业务单轮文案使用对应渠道的相同端点和模型，SSH 工具与远程 Redis/PostgreSQL 继续使用原连接。未提供配置的密钥时拒绝启动，不回退发送其他供应商旧密钥。删除 `LocalAgent.llm` 并重启即可继承服务器当前模型配置；切回其他供应商需同步修改端点、模型和密钥变量。

QQ 的 `ChatAPI.fallback` 支持 DeepSeek 故障时切至百炼 `kimi-k3`，凭据仅通过 worker private 设置传递，并参与日志脱敏。本地 `LocalAgent.llm` 独立覆盖时继续使用本地模型配置；移除覆盖后继承服务器的主备模型和超时设置。

首次克隆先运行 `git submodule update --init --recursive`。需要已配置并能免交互连接的 `ssh Aliyun`。启动时通过 SSH 读取运行中的服务器配置和 API 源码，不上传项目、不部署 HTTP 服务、不修改数据库 schema。模型在本地调用已配置的 ZenMux；查询、记忆、搜索、图片及 Python 执行通过外部 SSH 适配器调用。

当前本地 `LocalAgent.llm.proxy_url` 与远程 `ChatAPI.proxy_url` 均为空，模型直连。模型客户端只采用对应渠道的显式代理，禁用环境代理继承。本地端点覆盖不继承远程的 loopback 代理地址。

## 功能

- 真实 DeepSeek 流式正文及接口返回的 `reasoning_content`。所有工具链统一关闭 thinking；无工具独立请求可开启思考，界面不伪造思考过程。
- 网页支持选择、粘贴、拖入 PNG/JPEG/WebP/GIF，发送前可预览、移除；可以只发图片，也可同时发送文字。默认最多 4 张、单张 4 MiB、合计 8 MiB。带当前或历史图片时使用 `LocalAgent.llm.vision_model`，同一 ReAct 循环继续调用工具并支持图片追问；当前文字和视觉均为 `deepseek/deepseek-v4.1-flash`。模型支持视觉输入，见 [ZenMux 模型说明](https://zenmux.ai/deepseek/deepseek-v4.1-flash)。
- 按需披露工具，动态聊天/王者 SQL、BM25/RRF 群聊检索、联网搜索、长期记忆、图表和图片生成。联网搜索统一经远程 worker 请求 [DeepSeek Search API](https://api-docs.deepseek.com/zh-cn/guides/search/)，默认复用服务器 `HOK_DEEPSEEK_API_KEY`，不使用本地 ZenMux 密钥。配置集中在 `DeepSeekSearch`，查询最多128字符、最多10条结果；默认读取长摘要，空结果与 HTTP 失败明确区分。旧阿里云实现及配置保留，聊天不再调用或回退。
- 工具失败的 observation 附带 `data.error_details`：失败环节、异常类型、底层原因、有限定位与修复建议。SQL逐查询给出错误码/位置/提示，保留其他成功结果；Python沙箱给出退出码和有限stderr，网站错误保留HTTP状态。模型据此修正参数或改用其他来源。错误先脱敏后截断，不记录headers、局部变量或凭据；超时/断连写操作仍禁止自动重放。QQ、角色工具和后续注册的外部函数共用外部诊断注册表，内核协议不变。
- KPL职业赛事数据：发现 `kpl` 后调用 `query_kpl`，直接读取 [KPL小助手](https://kplll.online/) 的公开 JSON 数据。支持18类查询：赛事、日期赛程、系列赛/小局BP、战队与最近赛程、选手与逐局表现、英雄统计/红蓝方摘要、分组积分、年度积分、分均输出/经济/承伤榜、MVP次数与英雄组合胜率。先查赛事与对象目录取得本站ID，名称和日期可过滤，不能混用营地、腾讯或B站ID。返回来源、范围、样本、分页/截断及可供Python/绘图使用的dataset_id；过大详情可用fields选择字段。第三方已收录资料不保证官方实时，不把缺失数据当零，不下载网页图片或调用站点AI/反馈功能。
- 正文中的网页链接会在本地自动抓取一次并提取可读文字，再作为本轮资料交给 agent；QQ 的已验证引用文字使用同一提取器。保留标题、正文、列表、表格和来源，移除 HTML 标签、脚本、导航等噪声，不执行 JavaScript、不下载页面图片或递归抓取子链接。原消息与后续对话历史不拼入整篇网页，提取内容和状态保存在本轮轨迹及本地日志。默认最多3个去重链接、并行等待12秒、每页1 MiB/5000字、总正文12000字，截断/失败明确标记且不阻断聊天。设置在 `LocalAgent.webpages`（QQ 使用 `QQAgent.webpages`）；网页及 HTTPS DNS 请求显式经过当前主机 `Proxy.clash_url` / `HOK_CLASH_PROXY_URL` 指定的 Clash，代理缺失或不可用时明确失败，不回退直连，不继承环境代理。本地配置 HTTPS DNS 以兼容代理虚拟地址，所有解析结果和重定向都必须为公网地址，TLS 仍验证原域名。不读取内网链接、登录 Cookie、非文字文件；需要登录或动态加载的内容可能无法提取。
- 当前适配器强制先检索历史、再发现所需能力，避免模型把未披露工具误报为不可用。记忆由入口绑定当前会话调用者，保存本人偏好无需提供 QQ 或玩家名。
- 记忆也支持自然纠正：例如“不是辅助，我一直主玩中路”或“现在不喜欢安琪拉，主玩小乔了”，不必再说“记住”。ReAct 模型结合当前直接发言与旧记忆判断，先召回相关记录，再原位更新；有多条同一事实的冲突旧记录时，`remember_memory.supersedes` 与保存在一次事务中完成替换。未被纠正的事实和其他偏好保留，相同正文重复保存不新增记录。只说“不对”而没有新说明时先澄清，临时状态和引用中的他人发言不自动入记忆；用户自己的最新说明优先于旧个人记忆，外部客观事实的纠正须核验或保留用户说法的归属。成功后才确认，`nomem` 和当前用户权限仍有效；没有关键词触发补丁或额外分类模型。
- 当消息指代不清或相关性检索缺乏当前话题依据时，可按需发现 `chat_history` 并调用 `read_recent_chat_history`。默认读取最新的最多 20 条已归档发言，不限制时间跨度，数量上限 50 条，每条返回最多 600 字的带截断标记摘录。按时间顺序展示不同发言者及引用 ID，不用于总体统计或长期事实记忆。本地调试有跨群权限，调用时须指定一个目标群，避免混入无关群聊；QQ 普通群自动绑定当前群。配置统一来自服务器 `config.yaml#AgentHistory`，有效限制同步到模型工具 schema，修改后重启适配器。
- 统一参考数据能力：`references` 类别下的 `list_reference_catalogs` 和 `lookup_reference_data` 提供玩家多种 ID、昵称/别名、英雄名称、榜单参数、段位与表达映射；重复 QQ、同名和多账号关联保留全部关系。
- 机器人功能指南：`read_bot_manual` 按“类别→功能→具体主题→正文”逐层检索。发现只给顶层目录，`browse/search` 返回当前节点的子节点卡片，`read` 读取叶节点；每次正文最多3000字符，余下内容用next_offset继续。读完说明仍缺少事实时，`code` 对同一节点说明fallback_reason后读取白名单代码。程序拒绝跳过正文、跨节点或跳页兜底；代码和手册各有来源行号与版本，不执行源码或读取任意文件。正文拆在共享chapters目录，图片不作模型输入；QQ和Web复用同一协议。维护约定见 [手册维护说明](../shared/agent/manual/README.md)。
- 一次输入可有多条阶段性回复、图片和最终回复。工具输入、结果、模型上下文和执行时间线可以展开。
- 回答旁显示本轮 token 总量，输入框下显示会话总量；点击可查看输入、输出、缓存命中、命中率及各次模型请求，角色生成也计入。多次请求的系统提示、上下文和工具结果分别计入输入；缓存是输入子集，思考是输出子集，不重复相加。用量来自模型接口，未知字段显示“—”，中断、失败或缺失用量标注为部分统计。历史会话按持久事件恢复，重连不会重复计数。
- 回答作为主要内容，思考与工具调用默认折叠到“执行过程”，右上角仍可查看完整轨迹。
- 每轮最终回复同时提供“详细内容”和“群聊回复”。详细版保留结论、依据、必要数据和来源；群聊版使用自然短句、角色语气和必要限制，上限 280 字，简短偏好默认最多 100 字，并可一键复制。`output.message.data.text` 和 `run()` 返回值的 `text` 字段默认就是群聊版，两个版本在 `variants.detailed` / `variants.chat`；QQ 出口默认发送群聊版，用户明确要求详情时选择详细版。
- 会话及完整持久事件保存在服务器 Redis DB0；浏览器保存会话列表，刷新可恢复记录。本地同时保存对话和完整调试日志，见下文。
- 延迟/周期后台任务保存在服务器，使用同一内核执行。任务仅在本地适配器运行期间调度；停机后租约到期可重新领取。
- 查询或推理使用 `agent` 任务；固定文字定时发送使用 `message` 任务，直接走同一输出端口，无额外模型调用。支持最短 1 秒周期、限定执行次数和序号模板 `{run}` / `{max_runs}`。省略具体首次时间与延迟时在一个周期后发送；后续按原计划计时，错过的时间点跳过。调度可与前台聊天同时执行。
- 支持注册额外同步/异步 Python 函数；无需改核心循环。
- 绘图默认使用极光主题，支持霓虹夜色和落日主题：渐变条形、趋势面积、多系列配色、气泡散点、带轴标签的热力图、环形组成图，以及数值标注和口径脚注。可直接要求“用霓虹夜色主题画图”。所有图在同一隔离 Python 环境生成，样式不进入 ReAct 内核。
- 角色库与用户偏好完全在外部适配层：网页右上角可以选角色、设置回复长度/称呼/表达偏好。默认用户是 example_user_10（配置昵称示例玩家65），默认角色为牧濑红莉栖；选择“通用助手”可关闭虚构角色风格。角色选择与偏好按用户跨会话保存。
- `roleplay` 类别提供 `list_roles`、`select_role`、`add_role_from_web`、`set_reply_preferences`。可直接说“联网添加《原神》的安柏并选用”或“以后回复简短、少用表情”。添加会实际联网检索并生成背景、性格和语言档案，保留网页来源及独立模型请求/响应轨迹；失败不保存。自建角色仅创建用户可见。切换对接下来的最终回复生效，后台 agent 任务读取执行时的最新角色。

## 数据与隔离

服务器实际数据源是 PostgreSQL 和 Redis，并非 MySQL。SQL 使用运行服务的 `hok_chat_reader` 账号、只读事务和 AST 白名单；整批 SQL 校验通过后才连接数据库。群聊通过受作用域约束的安全视图读取。

共享目录在 `shared/agent/`，内容来自仓库的已验证语义目录。服务器尚未部署语义视图时，适配器将可信视图定义编译为 CTE。模型仍只看到语义视图名，不直接访问采集层。此兼容方式对大范围查询可能受服务器 5 秒查询上限限制。

`shared/agent/reference_data/manifest.json` 声明参考目录的源字段、ID 命名空间、用途和上下文投影。当前源为服务器 `config.yaml#StaticVariables`；也支持通过清单改为独立 `static_variable.json`。每次新请求、后台执行和参考工具调用均读取最新源，返回版本摘要。常用玩家昵称、别名与 QQ 映射进入上下文，完整营地/角色/Steam ID 通过工具查询。此目录与 SQL、记忆分别提供各自的数据，参考查询的 `dataset_id` 可在 Python 中与 SQL 数据集关联并绘图。

服务只监听本机 loopback；请求校验 Host、Origin、本地会话 cookie 和写请求头。SSH 密钥、模型 key、DSN 不进入浏览器或新文件。运行记录保留完整输入和工具资料，因此本界面作为受信任的本地管理员控制台使用。

原始输入图片与校验元数据存于被 Git 忽略的 `file_transfer/agent_inputs/`，不会覆盖生成图表或修改原图。Redis 会话、运行记录和 SSE 用 `attachment://<id>` 引用图片，刷新、重启后仍可预览与继续追问。静态图片发送原始像素的 data URL；动画按帧序抽样为最多 4 帧的 PNG 拼图并注明帧号，原 GIF/动态 WebP/APNG 仍保留。拼图单独保存，元数据记录来源和抽样索引；实际模型请求快照引用真正发送的 PNG，默认限制源动画 240 帧及累计解码像素，配置在 `LocalAgent.images`。包含图片的实际请求快照会显式标注 `image_payload_storage`，`GET /api/images/{id}` 可还原对应原图或模型拼图的确切字节；轨迹中不反复嵌入 base64。需要保留图片会话时应一起保留此本地目录，文件被删除时会明确报错。

上传按实际内容检测格式、完整解码并校验文件大小、尺寸和像素数，API 同样执行数量与总大小限制。限制统一在 `LocalAgent.images`。默认每次模型调用最多读取 16 MiB 图片，优先保留当前及较新的图片，较早且超预算的图片替换为明确的缺失提示，`vision_context.omitted_history_images` 记录数量；不会把未提供的像素当作已看过。图片 token 包含在模型返回的输入 token 中，不另外估算叠加。

外部适配器分别维护业务连接和状态连接：数据库/搜索/图片/沙箱走业务连接，对话、运行事件、记忆和任务走状态连接，避免慢业务调用阻塞定时通知。事件通过通用 `metadata` 标记后台来源；后台通知不覆盖正在输入或执行的前台聊天状态。

SSH 断开后，新请求在发送前会串行重建连接和 worker，重新加载启动资料；无需重启页面服务。若请求已经发送却未收到有效响应，适配器关闭该连接并报告结果未确认，不自动重放写入、任务或收费操作。下一次请求可恢复连接；是否重新执行应先查看运行记录。调用取消不会遗留响应污染后续请求。`/api/status` 实际检查两条连接及 Redis PING，连接故障返回中文 HTTP 503，不再把缓存配置当作服务健康。

本地 UI 通过 `LocalAgent.player_key: example_user_10` 从服务器权威映射唯一解析 QQ，作为稳定的 `Principal.user_id`；“我”默认指示例玩家65，游戏查询使用 `player_key`。本人长期事实与 QQ 共用 `hok:memory:facts:<QQ>`，每次对话自动读取用于个性化；回复偏好和角色选择单独存储于 `hok:agent_runtime:console:roleplay:<用户摘要>:*`。旧匿名会话的 `local-ui:<session>` 事实保留，未自动归入 example_user_10。会话对话记录仍按会话隔离，状态、任务和产物使用 `hok:agent_runtime:console:*`。独立模块无 QQ 类型、角色、配置、数据库和界面依赖。

内置角色可独立修改 `shared/agent/roles/*.json`（修改后重启本地适配器）；默认角色设置在 `LocalAgent.default_role`。角色包的可选 `voice` 包含 tone、habits、avoid 和原创表达样例 examples，旧角色记录仍兼容；联网新增角色也生成这些信息。`agent_console/roleplay.py` 负责角色上下文与用户事实快照，`identity.py` 单独负责本地 HOK 身份与权限策略，`roleplay_models.py` 负责数据校验，`roleplay_store.py` 负责隔离持久化，`tools/roleplay.py` 负责工具注册。最终送入内核的仍是通用 `RunRequest.system_prompt` 和 `ToolRegistry`，QQ 适配器接入时可复用角色服务并传入可信用户身份。

`agent_console/replies.py` 作为内核可选的 FinalizerPort 接入。ReAct 负责一次性理解资料并形成事实底稿，详细版原样展示；独立无工具 JSON 请求生成群聊短回复。Web 默认展示短回复并提供两版；QQ 可在同一请求中根据实际意图和用户偏好选择 chat/detailed，使用结构化 default_variant，不用正文关键词猜测，也不增加额外请求。输入仅有当前问题、底稿、最新角色表达卡和用户表达偏好，不重新注入工具目录、检索发言、旧答案、长期记忆或完整角色生平，也不再分析或计算。角色特色体现为态度、措辞与互动；数字保留原有对象、单位和分母。角色背景与记忆在主 ReAct 阶段使用；有 voice 的角色仅将 voice 传给表达阶段，旧档案兼容提取 personality / speech_style。

默认至多两次群聊表达请求，总阶段 60 秒；检查结构、非空内容、长度、纯文本以及新增数值、链接，数值检查仅是字面量约束，不能作为语义正确性证明。超出输入预算时保留完整底稿，不任意截断事实；失败标记 degraded 并记录警告。不存在额外事实复核模型。reply.model.* 保留实际输入字段长度、请求、响应与 token 用量；原 ReAct 答案及完整 API payload 不被覆盖。选择角色及修改偏好对接下来的群聊回复生效。

回复限制位于 `LocalAgent.reply`。本地 `history_variant: detailed` 只保存一份事实底稿，支持详情追问，避免两版重复进入后续上下文；QQ 适配器可以设置为 chat，只保存实际发给群的正文。两个展示版本仍完整保存在运行事件中。固定文字任务保持原文，不请求回复表达模型；后台 agent 任务复用同一表达器。联网角色生成失败或格式检查失败时不保存角色。

生成的 Python 在远程 bubblewrap 内执行，关闭网络、不挂载服务器应用与凭据，限制 CPU、内存、执行时间、输出文件及产物类型。依赖缺失时拒绝执行，不回退宿主解释器。

## 本地对话与调试日志

默认启用 `LocalAgent.local_logging`，目录为仓库根目录的 `log/agent_console/`：

```text
log/agent_console/<session_id>/
  dialogue.jsonl           # 用户输入、各条回复、产物引用、警告与运行状态
  runs/<run_id>.jsonl      # 该次请求与完整事件轨迹
```

每行一个 UTF-8 JSON 对象。运行日志包括接收请求、模型实际上下文与请求/响应 payload、真实思考及流式片段、工具参数和 observation、详细/群聊两版答案、token 用量、错误与取消状态；上下文生成失败时也记录原问题和错误栈。后台任务使用相同日志出口。输入图片继续引用 `file_transfer/agent_inputs/` 中的原始文件，产物保留其引用，不重复嵌入已外置的图片字节。

`agent_console/local_logs.py` 只属于外部适配器，通过事件出口写盘，不影响独立内核。日志按事件 ID 去重，重启后读取已有 ID；页面加载旧会话时会补存服务器仍保留的历史事件。流式片段从本功能启用后记录，旧服务器历史中没有保存的片段无法补回。凭据沿用 SSH 适配器的脱敏规则，日志文件默认权限为 0600；目录已被 Git 忽略，不随 commit 上传，也不按 Redis 的七天 TTL 清理。日志写入失败只记录警告并继续发送，可从 `/api/status` 的 `local_logging.last_error` 或事件 `local_log_error` 检查。配置修改后重启本地服务。

## 复用内核

安装独立包：`pip install ./vendor/react-agent-runtime`。独立包仅依赖 Pydantic。外部提供 `ModelPort`、`StatePort`、`OutputPort` 和 `ClockPort`，然后构造 `AgentRuntime`。任意业务函数通过 `ToolRegistry.register(...)` 注入，默认按权限向模型披露；需要渐进披露时声明 `initially_visible=False`，再由应用自己的发现工具选择披露。

任务首次时间可选 `run_at`（带时区的 ISO 8601 日期时间）或 `delay_seconds`（延迟秒数），互斥；具体几点优先提交 `run_at`。程序拒绝过去或超过一年后的具体时间，不自动改到次日。创建和列表返回北京时间 `next_run_at_text`，确认回复使用该实际时间。周期后续仍按原计划递推并跳过错过的时间点。

本应用的工具定义在 `agent_console/tools/application.py`，由 `register_application_tools(..., service=..., catalogs=...)` 接入。SQL 方言/校验器、参考查询、数据集投影和持久任务转换也都在 `agent_console/`；数据库 schema 从共享目录的 `schema` 字段显式传入。应用提示词、工具名称和群聊规则不进入内核。`description_provider` 和 `result_projector` 是工具可选的动态描述/结果投影回调；内核只执行回调和通用预算约束，不识别返回值的业务结构。

QQ 接入时以可信事件构造 `Principal`，把群号及经过验证的跨群授权放入 `attributes.chat`，由外部适配器解释；群聊固定当前群，跨群只允许验证过的管理员私聊。`OutputPort` 将 `output.message` / `output.artifact` 转给项目统一消息出口。旧后台任务的群字段由外部任务转换器兼容读取。

当前版本可以恢复会话记录和后台任务；正在执行的模型请求在本地进程重启后不会自动重放，避免重复发送或生成收费图片。外部发送接口若无幂等能力，也不能保证严格只发送一次。

## 检查

绘图主题、默认主题和说明放在 `shared/agent/plots/catalog.json`，可独立修改并重启本地适配器。参数和字段校验在 `tools/plotting.py`，可信渲染库在 `plot_renderer.py`；一般 Python 也预置 `render_chart`、`apply_plot_style` 和 `plot_themes`。热力图长表传 `value` 数值列，缺失格默认留空，明确确认后才传 `fill_value=0`；重复格需先在 SQL 聚合或显式传 `aggregation`。结果截断自动显示提示，趋势线不生成额外观测点。

```bash
local_debugger/.venv/bin/python -m unittest tests.test_agent_runtime tests.test_agent_console tests.test_agent_tasks_memory tests.test_reference_data tests.test_agent_roleplay tests.test_agent_plotting
local_debugger/.venv/bin/python -m unittest tests.test_agent_images
local_debugger/.venv/bin/python -m unittest tests.test_agent_finalization tests.test_agent_replies
local_debugger/.venv/bin/python -m unittest tests.test_agent_local_logs
local_debugger/.venv/bin/python -m unittest tests.test_agent_bridge
local_debugger/.venv/bin/python -m unittest tests.test_agent_local_model
node --test tests/test_agent_usage.js tests/test_agent_image_ui.js
```

自动测试使用脚本模型，不调用付费服务。真实 SSH/SQL/Python/API 的检查在开发时手动完成，不接入启动或部署诊断。

共享 SQL 限制由根 `config.yaml#AgentSQL` 管理，字体与 QQ 合图布局为 `AgentPlots`。事实校验和 BM25/RRF 在 `agent_console/tools/memory.py`，由适配器传入 worker，与旧 Hok 聊天代码没有依赖。

KPL网络、体积和返回预算为根 `AgentKPL`，默认15秒、2MiB、列表最多100条、嵌套列表最多50条、数据正文16000字符。协议目录在 `shared/agent/kpl/catalog.json`；HTTP客户端与工具schema在外部适配层，内核没有KPL依赖。启动时将当前目录与客户端代码提供给业务SSH worker，服务器配置优先覆盖本地公开默认值；首次部署前可在本地直接调试新工具。选手分均榜使用网站实际分页，其他已验证列表由适配器过滤后分页，不给不支持分页的接口强塞page/pageSize。时间带时区时按上海日期过滤，无时区时间仅使用源日期。重启适配器加载修改，自动测试可运行 `local_debugger/.venv/bin/python -m unittest tests.test_agent_kpl`。

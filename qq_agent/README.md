# QQ agent adapter

`qq_agent` 将 QQ 传输接入网页使用的同一个独立 ReAct 内核。内核以
`vendor/react-agent-runtime` Git submodule 固定版本接入，根目录 `agent_runtime`
只是源码导入软链接。首次克隆运行 `git submodule update --init --recursive`。

```text
OneBot event → event_handlers/chat → zfunc.agent_chat → QQAgentService
                                                   ↓
                                       shared AgentRuntime
                                      ↙          ↓          ↘
                              shared tools   role/reply    QQOutput
                                   ↓                       ↓
                         two ProcessBridge workers   message_sender
                      SQL / search / sandbox / Redis      ↓
                                                       QQ messages
```

`zevent` 不实现工具循环、不重复发送最终结果。正式入口为 `zfunc.agent_chat`，没有旧聊天兼容循环。
群中直接 @ 机器人即可聊天，无需 `#`；这类消息中的业务关键词交给 agent 处理。
带 `#` / `＃` 前缀的命令继续按原入口执行。@ 其他人、@ 全体或引用里的 @ 不会触发 AI。
直接 @ 仍遵守原有 QQ 白名单、禁用、休眠及维修限制。
QQ 输入使用真实发送者，网页身份由独立配置绑定。群聊只授权当前群；普通私聊
不提供群聊工具；已验证的 `QQBot.super_qid` 管理员私聊允许跨群。模型不能更改发送
会话，后台任务继承创建时的用户、会话、权限和目的地。

群聊 AI 回复默认原生 @ 本次提问者。`qq_agent/mentions.py` 注册 `chat_delivery`
类别的 `set_reply_mention`，由同一 ReAct 模型按本次意思选择其他当前群成员，或传
`user_id=all` 原生 @全体成员、`user_id=null` 明确不 @。要求提醒全群时先选择 all，
只说在群里发送不代表 @全体。个人目标通过实时资料读取器验证群成员身份，all 仅限当前群，
实际效果受 QQ 权限与额度限制。本次消息里的原生 @全体也保留为输入资料。选择按 run_id
覆盖后续分段与最终消息的 `delivery.mention_user_id`；多个请求交错完成互不影响。
`QQCapabilities.create_task` 将校验后的选择保存到新任务的 delivery，保持创建者、
权限、群和会话不变；设置后新建任务才继承，已有任务不被修改。run.end 释放覆盖。
本次原生 @ 的其他成员 QQ 由入口保留为文字资料，不把引用中的 @ 当作本次要求。
统一消息出口只采用验证后的 destination，模型正文或 packet 字段不能伪造提及。
私聊和本地 Web 不加 @，未绑定用户的旧目的地不猜测。
提及只属于 QQ 消息段，不写入模型正文、回复版本或直接对话历史。

`qq_agent/private_messages.py` 在 `chat_delivery` 类别注册
`send_group_member_private_message(user_id, text, group_id?)`，仅 QQ 入口授予
`qq.private.send`；群请求只限当前群成员，配置管理员私聊可使用默认群或显式选择一个群，
普通私聊及 Web 不授予。需要本次用户明确要求，或用户创建时明确授权的 agent 私发任务；
历史/引用/网页文本不能授权发送。真实调用者、个人记忆、正常回复及任务目的地不变，旧任务不新增权限。
定时私发使用 agent 任务，在 instruction 中保留目标与正文，并在到时调用同一个私发工具；
message 固定消息仍沿用原绑定会话，不新增私发目的地参数或第二套调度。
工具由同一 ReAct 模型发现并调用，无自然语言关键词分派。目标先经注入的成员资料读取器确认，
正文走统一昵称/QQ纯文本格式化；`zfunc.agent_send_group_member_private_message` 转发至
`utils/message_sender.send_group_member_private_message`，在该统一出口再次校验成员并调用
`send_private_msg`，携带当前群临时会话上下文，CQ正文只作为 text 段。为取得真实消息ID，
该工具在统一出口内直接 await QQ 响应，不将普通队列入队视为发送成功；不回退群发或加好友。
成功仅表示 QQ 返回 message_id，不表示已读。同轮相同群/目标/格式化正文成功后去重；
响应丢失、超时或缺少消息ID标记 OUTCOME_UNKNOWN，由既有诊断器禁止本轮重放。
QQ明确拒绝时报告失败，不自动重试。工具参数、结果与失败保留在 AdminPage 运行记录，
不伪造目标用户的私聊对话或将私发正文另写入群公共回复记录。
配置仅在 `QQAgent.private_messages`：enabled=true、max_chars=4000、timeout_seconds=45。

`qq_agent/context.py` 在群聊运行前自动加载有界公共背景，复用 `AgentHistory` 的
20条/每条600字配置，不限制时间跨度，合并当前群不同成员归档和机器人已入队回复，并按时间
排序后保留最新20条。读取总等待由 `QQAgent.group_context_timeout_seconds` 控制，
默认10秒；故障保留可用来源并标记缺失。背景仅作为本轮 user context，不改个人
`qq_g_<群>_<QQ>` 会话，不跨群共享，不写本人长期事实。任务查看和取消独立按当前群范围校验。
`QQOutput` 在消息出口接受后将正文和真实 @ 目标记录到 DB0
`hok:agent_runtime:console:qq_group_replies:<群>`，最多保留 `AgentHistory.max_limit`
条摘录，不设置时间过期，写入时清除旧版TTL；没有额外复制被动群发言，私聊不进入该记录。新版本从启用后开始记录
机器人回复；历史日志与个人会话不迁移、不删除。

管理员私聊未指定群时，历史检索、聊天 SQL、近期发言和成员资料默认使用
`QQAgent.admin_private_default_group_id`，当前配置为 `2000000001`。工具可显式指定
其他群；检索与 SQL 可用 `group_id: "*"` 查询全部已归档群，近期发言和成员资料
仍一次读取一个群。默认群是查询属性，私聊会话、显式引用校验和通知目的地保持私聊。
普通群固定当前群，普通私聊没有群聊读取权限；本地 Web 的默认范围保持原配置。

## 工具与数据

所有工具处理器（含后续注册的外部函数）经共用 `DiagnosticToolRegistry` 包装，失败
通过既有 ToolResult 的 `data.error_details` 传给内核：原异常类型、失败阶段、底层原因
与有限定位，SQL错误码/位置/提示、沙箱stderr及HTTP状态按实际故障附带。远程异常
信息经过RPC保留，局部成功结果不丢失；诊断脱敏且不提供headers或局部变量。
读取失败可在预算内修正或有限重试；写操作超时或响应丢失保留OUTCOME_UNKNOWN，
禁止本轮自动重放。取消、权限、参数schema仍遵循原内核规则。

`kpl` 类别提供 `query_kpl`，使用 kplll.online 的公开 JSON API 查询18类职业赛数据，
包括赛季/赛事、指定日期赛程、系列赛和单小局BP、队伍、选手逐局表现、英雄/红蓝方
统计、分组及年度积分、选手分均榜、MVP次数和英雄组合。当前群与私聊都可读取公开
资料，权限为web.read，不需要群成员身份。先按名称/年份查询本站ID，不能套用营地、
腾讯英雄或B站比赛ID；失败/缺失不猜测，第三方收录不保证官方实时。
协议与参数目录位于 `shared/agent/kpl/catalog.json`，预算在根 `AgentKPL`，客户端
位于外部 `agent_console/kpl_client.py`，QQ本地worker与Web SSH worker复用相同源码。
API只读GET且无凭据、环境代理与重定向，保留查询范围、来源、抓取时间、样本及
分页/嵌套截断；数据集可交给现有Python/绘图工具。固定业务KPL推送继续使用原接口，
本工具不注册新定时任务，内核和业务SQL不包含KPL网站schema。

本次正文和通过范围校验的引用文字含网页链接时，由共享外部提取器
`agent_console/webpages.py` 自动抓取并在运行主机本地解析，无额外模型提取请求。
保留标题、正文、列表、表格和来源，去掉 HTML 标签、脚本、导航及隐藏文字。
同一轮重复 URL（含不同锚点）只抓一次；不读取引用未获授权的文字、不递归追链接。
网页作为本轮不可信 `context_messages` 提供给 agent，不放 system prompt，不自动
写入直接对话历史或长期记忆，完整内容与读取状态保留在运行日志。
`QQAgent.webpages` 默认最多3链接、并行等待12秒、每页1 MiB/5000字、总正文12000字；
截断、超时、登录/反爬和无法解析均标记，失败不阻断正常回复。不执行页面脚本或
下载页面图片。每次连接与重定向校验公网地址并固定连接 IP，保留原域名 TLS 验证，
禁止本机/内网访问、环境代理、认证和 Cookie 继承。QQ 默认系统 DNS；本地 Web
按自身配置使用 HTTPS DNS，解析结果同样必须为公网。

工具实现和参数位于 `agent_console/tools`，数据库 schema、参考映射、绘图和角色
位于 `shared/agent`，内核不识别 QQ 或数据库。QQ worker 在服务器本地执行同一 RPC
协议，不经过 SSH；网页仍通过 SSH 调用。两个 worker 分别处理业务和状态，长查询
不会阻塞任务领取。SQL 继续使用独立 `hok_chat_reader`，动态 SQL 先整批校验再执行。
生成的 Python 只在 Linux bubblewrap 中运行，缺失隔离依赖时拒绝执行。

支持历史检索、游戏/聊天 SQL、联网搜索、参考映射、绘图、图片生成、隔离 Python、
长期记忆、角色联网新增/选择/偏好、分段消息与持久任务。群聊和管理员私聊先调用
`search_chat_history`，再 `discover_tools`；普通私聊只强制发现工具。未披露或未授权
工具不能执行。DeepSeek 工具链统一关闭 thinking，原生图片使用配置中的 vision_model。

当前 QQ 的文字、视觉、回复整理与联网角色生成使用 DeepSeek 官方
`https://api.deepseek.com` 的 `deepseek-flash`。远程 `ChatAPI.api_key_env`
引用现有 `.env` 中的 `HOK_DEEPSEEK_API_KEY`；业务单轮文案也使用该 ChatAPI。
显式 `HOK_CHAT_API_KEY` 仍可覆盖，但部署启动环境不得遗留旧供应商配置。
指定密钥缺失时拒绝启动，不回退其他供应商密钥。
远程 `ChatAPI.proxy_url` 为空，工具循环、回复整理、角色生成和业务文案均直连，
不继承环境代理。本地 Web 继续按自己的 llm 配置使用 ZenMux 与 `LLM_API_KEY`。

`ChatAPI.fallback` 使用百炼 `kimi-k3`，密钥来自现有 `.env` 的 `DASHSCOPE_API_KEY`。
DeepSeek 15 秒没有首个有效输出，或发生连接故障、鉴权失败、限流、服务故障时自动回退。
已交付流式内容后不重发，用户取消和参数错误不触发回退。文字、图片、工具调用、回复整理、
角色生成和业务文案均支持回退；实际模型名称保留在运行记录中。
Kimi K3 始终思考，按百炼协议保留 reasoning_content，并移除其不支持的 temperature 覆盖；仅对 DeepSeek 工具链关闭 thinking。
命名强制工具调用转换为仅含该已授权工具的 required，不扩大可调用范围。
凭据与登录会话保存在 Git 忽略的 `.env`，业务配置与身份映射保存在同样忽略的 `config.yaml`。
私有配置通过 SSH 单独同步，源码由 GloryBond 的 Actions 工作流发布；聊天、日志和运行记录中的凭据统一脱敏。
现有发布脚本会保留服务器已有 `.env`，部署与恢复行为见 [部署说明](../deployment/README.md#updating-and-rollback)。

询问机器人的功能、特性和命令用法时，可发现 `bot_info` 并调用 `read_bot_manual`。
它按共享目录树逐层定位功能，再read具体主题的叶节点正文，目录不夹带全文。
正文默认最多3000字符并按next_offset分页。需要代码兜底时必须已在本轮读完同一叶节点，
使用action=code并说明fallback_reason；跨节点、跳页或手册版本变化会拒绝读取。
代码只读取节点声明的函数/类或公式赋值，不导入执行；正文按功能分文件维护。

`references` 类别还提供 `read_group_member_profile`，一次读取一个群成员的 QQ 昵称、
群名片、角色、头衔、群等级、展示的地区/性别/年龄、入群和最后发言时间，以及可选
头像。默认 `target="user"` 且省略 `user_id` 查询提问者本人；`target="bot"` 查询机器人
自身。机器人身份由 `zfunc.agent_runtime_start` 从现有 `QQBot.bot_qid` 注入，存入可信
`Principal.attributes.bot.user_id`，同时提供给模型上下文；不能由工具参数覆盖。
“你的QQ头像”应读取机器人，“我的QQ头像”应读取提问者，角色外貌不能代替实际头像。
其他成员的名称需先通过参考映射确定 QQ。普通群只读取当前群，
管理员私聊省略 `group_id` 使用入口默认群，普通私聊没有该工具权限。未返回的字段为 null，不推断
现实身份、年龄或在线状态。群等级不是游戏段位。

读取链为 `zfunc.agent_read_group_member_profile → utils/qq_profiles → OneBot`，
头像 HTTP 通过 `zapi → api_adapters/qq_profiles` 获取，字段归一化在
`business/qq_profiles.py`。QQBot 将该读取器注入外部 `QQAgentService`，工具和内核
不直接操作 bot。先验证群成员身份再读取，头像失败时仍提供文字资料。

头像校验后保存在非公开输入目录，与本次直接图片、引用图片及其他头像共用数量和
体积预算。工具 observation 返回 `model_images` 的私有附件引用；外部 provider 将
像素作为原生图片加入下一轮模型调用，保持完整工具批次的顺序，头像及其中的文字
只作为资料。内核仍只处理 JSON observation，直接对话历史不保存这些工具图片。
配置位于 `config.yaml#QQProfiles`。本地 Web 当前未注入 QQBot 的实时资料读取器。

当前问题指代不清或相关性检索仍不足以判断时，agent 可发现 `chat_history` 类别并调用
`read_recent_chat_history`。默认读取当前群最新的最多 20 条已归档发言，不限制时间跨度，
按时间顺序返回所有发言者的文字摘录，排除当前群的本次消息；
每条最多 600 字，截断会标明，不读取历史图片像素，不把返回条数当作总体统计。
数量上限 50 条，可在 `config.yaml#AgentHistory` 调整。
管理员私聊省略群号使用入口默认群，无默认群的跨群调用需明确指定一个目标群，普通私聊不提供该工具；近期背景不足时继续澄清，
QQ入口已自动提供当前群最新20条公共背景，现有背景足够时不重复调用该工具；需要增加条数或补读时再调用，也不将这些发言写入本人长期事实记忆。

新 QQ 直接对话记录按 `qq_g_<群>_<QQ>` / `qq_p_<QQ>` 隔离，默认加载最近 12 条
原生 user/assistant 消息。只保存实际发送的答案版本，引用和工具 observation 不写入
直接对话。旧聊天记录、长期事实和旧角色数据保留。长期事实继续共用
`hok:memory:facts:<QQ>`；新角色选择与偏好按真实 QQ 共用网页的角色服务。

`QQBot.super_qid`绑定的真实QQ在群聊和私聊获授`roleplay.manage_others`。现有
`list_roles`、`select_role`和`add_role_from_web`接受可选`target_user_id`，省略仍为本人。
QQ适配层先验证超级管理员及可信目的地，群内通过实时资料读取器校验目标为当前群成员，
管理员私聊可以明确指定目标QQ。角色服务只将角色库读写指向目标，不替换调用者principal、
回复对象、原生@、记忆或任务目的地，不返回目标的个人回复偏好，也不开放代改偏好。
目标不存在所需角色时可联网添加到其独立角色库并选用，继续保留真实来源和生成事件。
跨用户变更产生`roleplay.user_changed`，管理员最终回复仍读取其本人角色；目标之后的
对话与agent任务读取新角色。自动消息规则剥离该授权，本地Web默认身份不自动获授。

记忆不要求明确说“记住”：用户直接纠正你的理解、说明稳定偏好变化或提供与旧认知
冲突的稳定背景时，由同一 ReAct 模型判断并先召回相关记忆，再更新/新增。旧个人
记忆不能反驳本人最新说明；客观事实纠正需核验，未核实说法只保留用户归属。
`remember_memory.memory_id` 原位更新，`supersedes` 可一起替换同一事实的其他冲突或
重复旧记录，全部目标须属于当前用户且可更新，校验与保存/删除在一次 Redis 事务
内完成；相同正文重复保存不新增。没有新说明的“不对”、临时状态、假设、玩笑及
引用/工具中的他人说法不自动写入。未受影响的背景保留，`nomem` 与原权限不变。
工具成功后才能确认纠正，结果和被替换的 ID 保留在运行轨迹；内核不包含记忆意图
分类或 QQ 事实规则。

任务存于 DB0 `hok:agent_runtime:console:*`。QQ 的 due 索引为 `tasks:qq`，网页为
`tasks`，分别领取。调度 hook 和 tick 只注册在 `hok/zscheduler.py`。固定文字任务
直接发送，不额外调用模型；agent 任务复用相同内核，并读取当前角色与偏好。
任务使用持久租约；入队后异常重启可能导致重复通知，不承诺 exactly-once。
群内所有成员可查看和取消发往本群的 AI 任务，列表显式返回创建者 QQ 与创建时保存的名称；
创建者与提醒的 @ 对象相互独立。其他群、私聊与网页任务不共享，私聊管理员的默认群也不扩大任务范围。
`list_tasks(message_id=...)` 支持用当前群引用的 QQ 消息 ID 精确查询任务，再调用 `cancel_task`。
QQOutput 只从后台事件 metadata 绑定 task_id，经统一消息队列透传；消费时取得真实 QQ message_id 后，
通过 `zfunc.agent_record_task_message` 将关联写 DB0 `hok:agent_runtime:console:task_message:<群>:<消息ID>`。
关联默认保留30天，可由 `QQAgent.task_message_link_ttl_seconds` 调整；保存失败只记录错误，不重发消息。
旧消息、过期或没有回执的消息明确返回无法确认，不按相似文字或 @ 对象猜测。列表仅投影调度字段与创建者，
不向同群其他成员披露执行权限、租约、会话标识或个人记忆，取消不改变任务创建者与发送目的地。

## 回复与日志

每轮最终回复固定发送两条，私聊和群聊一致：先将已有variants.detailed通过原生聊天记录转发发送，
再将已有variants.chat简略版直接发送。详细文字按段落分节点，图表作为图片节点放在同一份记录中。
详细转发的首节点放本次用户原话，以入口绑定的真实提问者QQ和名称署名；末节点放本轮chat-trace链接。
原话由prepare_chat_request在缩写替换、前缀/nomem处理前保留，经QQAgentService的metadata.reply_question
及QQOutput的_reply_question传递，作为展示资料，继续沿用凭据脱敏；被@成员和引用作者不改变提问者署名。
无文字输入标记本次消息无文字；后台任务缺少原话绑定时展示已有trace.question，署名提问内容。
简版保留原有图片及本次选定的原生@，不额外发送@短提示。两版直接读取既有生成结果，
QQ关闭select_delivery_variant，不再根据default_variant选一个版本，也不增加模型调用。
队列把简版reply_direct与详细转发一起保存，转发尝试结束后再入队简版；详细转发失败或结果未知时
仍独立发送简版，不重放详细版，取消继续向上传递。两条真实回执均沿用后台task_id关联，
分别按真实正文发布自动化发送事件，共用本轮来源与因果链。简版入队失败保留已发详细版并记录错误。
直接对话历史仅保存简版一次，两版完整保留在运行记录中。
QQAgent.reply_forward控制节点字数预算、署名、详细版标题及show_trace_link（默认true）。链接复用
chat_prepare_reply已发布的trace_url，不重新生成或重复留存轨迹；发布失败标记链接生成失败，正常回答继续发送。
表达整理降级时使用已有两版结果。
没有双版本的固定通知、旧输出和阶段性消息保持原发送方式。
共享reply_style约定用于底稿与群聊表达，直接写结论、数据范围、具体缺项和执行状态，
省去“只能”“不是……而是……”“不能表明”“没有详细的证据”“先说清楚”等防御性口吻。
群聊表达沿用原有修复预算检查措辞，原始引用、代码及必要事实条件照实保留。
联网、记忆和任务操作由 tool calling 决定；`#清除记忆` / `＃清除记忆` 只在完整命令
匹配时执行，问“清除记忆怎么用”会进入 AI 解释，不触发入口清除。
`emit_message` 可以先发送阶段性内容。原生上传图片来自配置允许的 QQ 媒体域名，
验证实际像素、大小和数量后存于非公开 `data/agent_inputs`。显式引用只读取一次，
优先使用适配器已取得的消息，缺失才通过 `get_msg` 补读；不会展开引用链。
引用文本与图片进入本轮 user 角色的补充上下文，不写入后续直接对话；其中的 #、@、
命令和记忆指令只作资料，不触发执行。引用的发言者、消息 ID 和可信范围会先校验，
删除或无法读取的消息明确标为不可用。直接图片和引用图片共用去重后的输入预算。
引用合并转发聊天记录时会展开一层，保留各条消息的顺序和署名；署名仅作转发资料，
不作为可信身份。优先使用消息自带的转发内容，缺失时通过 `get_forward_msg` 读取，
同轮相同转发 ID 只读一次；内部嵌套的转发和引用链不继续展开。
`QQAgent.forward_messages` 默认最多读取3份转发、合计100条节点、12000字，
总读取超时10秒；获取失败、格式无效、超时和截断均保留明确状态。
转发中的图片沿用现有校验，与本次直接图片共用输入预算；超出图片数量时保留文字，
仅附上额度内图片并标记其余未读取。转发内容只进入本轮资料上下文，不写入直接对话历史。
图表和生成图片由 `zfile.store_agent_artifact` 转为现有 Web 可展示的 PNG。

动态表情支持 NapCat 的 `image` GIF 地址以及带 URL 的 `mface` / `marketface` / `face`，
直接发送与引用均走同一图片输入流程。动画按顺序抽取最多 4 帧并生成带帧号的 PNG
拼图，送给配置中的 `deepseek/deepseek-v4.1-flash`；只分析实际提供的帧。原 GIF 保留，实际模型
拼图单独保存并关联原图与帧号，运行记录可以还原发送的确切像素。只有表情 ID 而
没有可读取图片地址时会标明未读取。抽样数量、动画帧数上限在 `QQAgent.images` 调整。

详细转发末条展示本轮chat-trace链接；`QQAgent.show_trace_link` 默认false，简版直接消息保持正文与图表，正常来源网址不受影响。
运行记录在 Web 管理控制台的“AI 运行记录”中统一查看，支持摘要/QQ/运行ID搜索、群号与状态筛选及分页，详情复用完整轨迹查看器。
正常、失败、取消和固定后台提醒都在结束时保存，取消/提醒不会额外发送一条消息。NBot 在同一 DB0 事务中写脱敏完整载荷与
`hok:chat:traces` 摘要索引；索引默认最多1000条（DynamicVariables.ChatTraceMaxRecords），载荷和索引TTL默认7天。
新载荷标记 `visibility=public`，公开 `/chat-trace` 持有效链接即可匿名查看；此前标记admin的已分享链接也可直接打开，沿用原有效期。
管理控制台的运行记录列表与详情入口继续验证管理员，公开分享入口不提供列表。
索引从新版本启用后开始记录，不扫描或搬迁旧日志。原始模型/工具事件、实际请求响应、两版答案
和 token 用量另外保存在 `log/qq_agent/<会话>/runs/<run_id>.jsonl`，对话输出为
`dialogue.jsonl`；凭据脱敏，输入图片使用附件引用。日志和原图不会进 Git 或部署包。
默认目录服从已有 `HOK_LOG_DIR` / `HOK_DATA_DIR`，自定义目录从 QQAgent 配置传入。

## 运行与扩展

现有 NoneBot 启动自动初始化服务，关闭时清理 worker 和运行任务。无额外 API key
文件。`config.yaml#QQAgent` 控制启用状态、角色、预算、图片与日志限制。第一次从旧
复制目录部署时，部署脚本备份旧目录并恢复软链接、初始化固定版本 submodule。

主 Python 进程可在服务启动后注册业务函数，外部函数不进入独立内核：

```python
from pydantic import BaseModel
from hok.zfunc import agent_register_tool

class InventoryArgs(BaseModel):
    sku: str

async def inventory(args, context):
    return {"sku": args.sku, "available": await inventory_service.lookup(args.sku)}

agent_register_tool(
    name="inventory",
    description="查询商品库存",
    args_model=InventoryArgs,
    handler=inventory,
    category="inventory",
    timeout=10,
    effect="read",
)
```

工具类别会自动进入发现描述。权限和可调用函数由应用注册，不允许模型传入任意
Python 模块或函数名。注册新的 scope 时，入口还必须显式授予该 scope。

### 按需调用现有业务函数

QQ 前台聊天及定时 `agent` 任务共用 `hok_business` 类别。模型先用
`search_hok_functions` 按用途或分类分页找函数，再用 `describe_hok_function`
读取选中函数的参数，最后 `call_hok_function(name, arguments)` 执行。始终只有这
三个通用工具，不为每个业务函数注入独立定义，也不在创建任务时保存完整定义。
后台执行仍由同一 ReAct 模型选择工具；这不是绕过模型的确定性函数调度任务。

`qq_agent/business_functions.py` 初始显式登记17个现有函数，覆盖在线状态、单日战报、
巅峰排名、英雄战力/常用英雄/统计/梯度、本人今日英雄、评分趋势、观战截图、底蕴、
游戏时长及代表局。只返回正式结果，旧接口的调试载荷、玩家内部参数和本地图片路径
不进入 observation。图片经 zfile 校验、快照为标准 PNG，沿用原运行记录和统一消息
出口。本人今日英雄绑定真实调用者，不允许指定他人或绕过每日限制。当前本地 Web
没有注入该业务目录，不会为此在 worker 中初始化 NoneBot 或使用业务写数据库账号。

扩展默认绑定可在 `build_hok_function_catalog()` 增加一个 `add()`，声明已有 zfunc
函数、参数、结果投影及必要的可信参数绑定。稳定扩展也可在服务启动后、现有启动
hook 中登记，不需要增加模型工具或修改内核。例如：

```python
from pydantic import Field
from agent_console.function_calls import FunctionArgs, FunctionOutput
from hok import zfunc

class PowerSummaryArgs(FunctionArgs):
    days: int = Field(default=7, ge=1, le=30, strict=True)

def power_summary(args, context):
    player = context.principal.attributes.get("identity", {}).get("player_key")
    if player not in zfunc.userlist:
        raise ValueError("当前用户没有唯一绑定玩家")
    return FunctionOutput(text=zfunc.recent_power_process(player, days=args.days))

zfunc.agent_register_function(
    name="my_power_summary", description="查询本人最近若干天的底蕴摘要",
    category="power", args_model=PowerSummaryArgs, handler=power_summary,
    scopes=("game.read",), effect="read",
)
```

登记来自可信应用代码，运行时登记重启后需由该启动 hook 重新执行。新增 scope
必须由入口显式授权；写操作声明 `effect="write"` 并审核用户授权与真实目的地，不能
把身份、权限或输出群号交给模型填写。禁止自动扫描全部 zfunc 函数、执行模型模块
路径或放开内部 Redis、全局推送、管理及 agent 入口。

循环保护包括本轮相同调用只执行一次、失败和取消不重放、拒绝业务调用重入 AI/
注册/调度、后台任务拒绝创建子任务。定时重复使用原任务的周期及次数。
`QQAgent.business_functions` 统一控制启用、每轮调用次数（默认8）、单次等待
（默认60秒）和文字结果大小（默认12000字）。旧渲染器共用文件名，因此全目录
同时只执行一个调用；忙时明确拒绝。同步函数超时或取消后线程可能仍在运行，
执行槽会保留到实际完成，不接受再次并发执行；写操作超时标为结果未知。

测试使用脚本模型和捕获发送器，不向实际 QQ 群发送测试消息：

```bash
local_debugger/.venv/bin/python -m unittest \
  tests.test_qq_agent tests.test_qq_agent_transport tests.test_qq_agent_facade
```

旧聊天实现与专属配置/诊断/测试已清理。共享算法在 `agent_console/tools/memory.py`，
QQ 和网页 worker 接收同一份源码。`AgentSQL` 配置只读查询限制，`AgentPlots` 配置
字体和合图。`forget_me` 通过新服务清除本人长期事实及当前 QQ 会话上下文；归档、
调试日志和其他会话不会被这个命令删除。表情包从当前群的本人归档读取发言，短期
去重缓存使用 `hok:emoji:*`，不再写被动聊天或读取历史摘要。

## 消息条件触发动作

`automation` 类别提供 `list_automation_actions`、`save_automation_rule`、
`list_automation_rules` 和 `delete_automation_rule`。同一ReAct模型解释“在…时提醒我”
及同义请求，先读取动作schema再保存完整规则；无额外关键词意图路由。
规则的身份、群/私聊范围由入口绑定，后台任务不能管理规则。同群成员均可查看、修改、
暂停和删除该群任意成员创建的规则；私聊管理本人规则，跨群和私聊各自隔离。
列表显示原创建者QQ及配置昵称，修改保留原创建者、提醒对象和执行权限；当前群成员身份
在管理入口实时确认，保存和删除同时校验规则版本，避免覆盖并发改动。
规则和执行记录保存在DB0 `hok:automation:*`，现有规则无需迁移，不新增数据库schema。
用户明确指定的固定回复以send_text原样保存，包括群内玩笑、轻度粗口与重复字符；
应用提示及保存工具说明共同约束模型，不因这些措辞自行拒绝、说教或按角色喜好替换文案。
每次触发发送一条指定文字，重复字符不表示连续发多条，仍受冷却、次数和防循环约束。

收到的消息由event_ingress观察，机器人普通消息、合并转发和工具私发从统一出口的
真实发送回执产生事件；自身回传忽略。普通群消息发送前可执行append_owner_mention，
在同一条消息上追加多个创建者的原生@。B站/X业务代码附加可信来源与作者稳定ID，
创建规则时从现有订阅目录确认UP或@username，并绑定mid或X账号数字ID；规则本身
不增加内容订阅。其他消息支持可见文字的
任一/全部关键词、发送者和来源条件，不自动解析视频或图片内容。

默认动作是notify_owner、send_text、send_media、run_agent和append_owner_mention。send_media
从list_automation_actions返回的input_media选择media_index，只绑定本次消息或已验证引用中的
原生QQ表情、图片和动图；模型不能提供素材URL、路径或已保存图片ID。QQ表情绑定原生ID，
图片经zfile复制到非公开data/automation_media并保留原始字节及动画，沿用QQAgent.images
的体积/像素/帧数预算。素材文件不进Git或部署源码包，迁移时随私有data另行备份。
QQAgent.automation.max_input_faces默认20；图片沿用当前图片预算，转发引用只展开一层。
列表不披露持久素材ID，修改已有媒体规则时空arguments沿用原素材，替换时须选择本轮素材。
原生消息拼装及真实发送回执仍走统一消息出口，固定媒体动作不额外调用模型或附加@。
复杂动作复用
现有内核，按创建者当前权限与保存权限的交集运行在规则独立会话，触发消息仅作本轮
资料；不授予任务/规则/记忆/角色管理、改头像、私发或提及覆盖，业务函数只披露read。
自定义动作由可信启动代码显式登记，无模块扫描或模型指定的函数路径，例如在现有
启动hook中、agent启动后登记：

```python
from agent_console.automation import TextArgs
from hok import zfunc
from hok.utils.message_sender import add_automation_message

async def custom_notice(args, job):
    # 使用统一出口，保留当前事件因果链；入队与执行状态原子保存。
    return add_automation_message(job, args.text, mention=True)

zfunc.agent_register_automation_action(
    "custom_notice", description="按规则向创建者发送自定义通知",
    args_model=TextArgs, handler=custom_notice,
    events=("message.received", "message.sent"), scopes=("automation.use",),
)
```

自定义动作的参数模型必须extra=forbid，处理器接收已校验参数和可信job，遵守现有IO、
Redis、时间和消息出口边界。新scope仍需入口显式授予。运行时登记重启后需重新执行。
发送前事件仅支持内置追加提及，查询和其他耗时动作在发送后执行。

规则消费只在zscheduler注册，设置集中config.yaml#QQAgent.automation。默认每人每
会话20条、每会话100条、冷却300秒、链深2、每个源事件最多10个动作、待执行最多500条。
版本、有效期、冷却、次数、幂等和根事件预算在Lua内原子检查；固定消息动作入队和
queued状态在同一事务完成。pending跨重启领取，过期running/queued标unknown且不重放，
真实迟到回执可改为sent。sent只代表QQ有回执，completed代表动作处理完成。存储故障
期间的事件不保证补发；已经开始的动作不会因删除规则而宣称被撤回。

`tests.test_automation`覆盖纯匹配、工具权限和agent隔离；可选测试依赖
`fakeredis[lua]`用于执行实际Lua的并发领取、持久化、消息出口和防循环契约测试。

## 更换机器人QQ头像

`set_bot_avatar` 仅配置管理员在QQ群或私聊中可用，发送或引用图片后明确要求更换即可。参数 `image_index` 从1开始，直接图片优先，随后为引用图片；可取本次已验证附件，或传本轮 `generate_image` 返回的 `image_resource_id`；二者互斥。生成后直接换头像无需重新发图，资源不能跨轮使用。生成图片经QQBot的zfile接口读取已保存PNG，不接受模型URL、路径或目标QQ。通过注入的QQBot账号写接口提交Base64，兼容分离部署的NapCat，不向独立内核加入QQ逻辑。超时结果未知，不自动重放；本地Web不注册此工具。

## 信息较多时分批回答

模型可用emit_message按主题、子问题、步骤或对比结果分批交付，不限于耗时任务的进度通知；保持当前角色与用户偏好，事实及其条件一起发送，短答不强制拆分。最终回复仅补充剩余内容。QQ与Web的DeliveryHistory只收集输出已接受的partial正文，按run_id隔离；直接对话历史保存各批正文及最终选中内容，进度/通知不混入回答历史，表达模型不额外读取分批内容或原始工具轨迹。原始分批事件仍在日志中，失败/取消由原有运行记录保留。

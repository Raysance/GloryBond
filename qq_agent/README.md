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
QQ 输入使用真实发送者，网页默认 example_user_10 的设置不影响 QQ。群聊只授权当前群；普通私聊
不提供群聊工具；已验证的 `QQBot.super_qid` 管理员私聊允许跨群。模型不能选择发送
对象，后台任务继承创建时的用户、会话、权限和目的地。

群聊 AI 回复的开头用原生 @ 提及本次发起对话的真实用户，覆盖阶段性消息、最终
答案以及新任务继承目的地后的通知；多个请求交错完成也不改为 @ 最近发言人。
目标由入口绑定到 `delivery.mention_user_id`，统一消息出口拼装，引用作者与模型
生成的文字或字段不能覆盖。私聊和本地 Web 不加 @，未绑定用户的旧目的地不猜测。
提及只属于 QQ 消息段，不写入模型正文、回复版本或直接对话历史。

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
Kimi K3 始终思考，按百炼协议保留 reasoning_content；仅对 DeepSeek 工具链关闭 thinking。
命名强制工具调用转换为仅含该已授权工具的 required，不扩大可调用范围。
发布脚本保留服务器现有 `.env`，不将备用密钥提交到代码仓库。

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
`read_recent_chat_history`。默认读取当前群最近 15 分钟的最多 20 条已归档发言，取
窗口内最新消息后按时间顺序返回所有发言者的文字摘录，排除当前群的本次消息；
每条最多 600 字，截断会标明，不读取历史图片像素，不把返回条数当作总体统计。
窗口与数量最多 60 分钟、50 条，均可在 `config.yaml#AgentHistory` 调整。
管理员私聊省略群号使用入口默认群，无默认群的跨群调用需明确指定一个目标群，普通私聊不提供该工具；近期背景不足时继续澄清，
不会每轮都自动加载窗口，也不将这些发言写入本人长期事实记忆。

新 QQ 直接对话记录按 `qq_g_<群>_<QQ>` / `qq_p_<QQ>` 隔离，默认加载最近 12 条
原生 user/assistant 消息。只保存实际发送的答案版本，引用和工具 observation 不写入
直接对话。旧聊天记录、长期事实和旧角色数据保留。长期事实继续共用
`hok:memory:facts:<QQ>`；新角色选择与偏好按真实 QQ 共用网页的角色服务。

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

## 回复与日志

每轮保留详细底稿和角色群聊版，QQ 默认发送群聊版，明确要求详细/完整时发送详细版。
版本由同一次表达模型请求理解当前要求和用户偏好，输出受枚举约束的 default_variant；
不再用“每个”“所有玩家”“前几名”等正文关键词切换版本，不增加一次模型调用。
联网、记忆和任务操作由 tool calling 决定；`#清除记忆` / `＃清除记忆` 只在完整命令
匹配时执行，问“清除记忆怎么用”会进入 AI 解释，不触发入口清除。
`emit_message` 可以先发送阶段性内容。原生上传图片来自配置允许的 QQ 媒体域名，
验证实际像素、大小和数量后存于非公开 `data/agent_inputs`。显式引用只读取一次，
优先使用适配器已取得的消息，缺失才通过 `get_msg` 补读；不会展开引用链。
引用文本与图片进入本轮 user 角色的补充上下文，不写入后续直接对话；其中的 #、@、
命令和记忆指令只作资料，不触发执行。引用的发言者、消息 ID 和可信范围会先校验，
删除或无法读取的消息明确标为不可用。直接图片和引用图片共用去重后的输入预算。
图表和生成图片由 `zfile.store_agent_artifact` 转为现有 Web 可展示的 PNG。

动态表情支持 NapCat 的 `image` GIF 地址以及带 URL 的 `mface` / `marketface` / `face`，
直接发送与引用均走同一图片输入流程。动画按顺序抽取最多 4 帧并生成带帧号的 PNG
拼图，送给配置中的 `deepseek/deepseek-v4.1-flash`；只分析实际提供的帧。原 GIF 保留，实际模型
拼图单独保存并关联原图与帧号，运行记录可以还原发送的确切像素。只有表情 ID 而
没有可读取图片地址时会标明未读取。抽样数量、动画帧数上限在 `QQAgent.images` 调整。

最终消息继续包含图表与运行记录链接。新链接使用与其他产物相同的 16 位随机 key，
默认保留 7 天；已有 48 位链接仍可读取至自然过期。原始模型/工具事件、实际请求响应、两版答案
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

## 更换机器人QQ头像

`set_bot_avatar` 仅配置管理员在QQ群或私聊中可用，发送或引用图片后明确要求更换即可。参数 `image_index` 从1开始，直接图片优先，随后为引用图片；可取本次已验证附件，或传本轮 `generate_image` 返回的 `image_resource_id`；二者互斥。生成后直接换头像无需重新发图，资源不能跨轮使用。生成图片经QQBot的zfile接口读取已保存PNG，不接受模型URL、路径或目标QQ。通过注入的QQBot账号写接口提交Base64，兼容分离部署的NapCat，不向独立内核加入QQ逻辑。超时结果未知，不自动重放；本地Web不注册此工具。

## 信息较多时分批回答

模型可用emit_message按主题、子问题、步骤或对比结果分批交付，不限于耗时任务的进度通知；保持当前角色与用户偏好，事实及其条件一起发送，短答不强制拆分。最终回复仅补充剩余内容。QQ与Web的DeliveryHistory只收集输出已接受的partial正文，按run_id隔离；直接对话历史保存各批正文及最终选中内容，进度/通知不混入回答历史，表达模型不额外读取分批内容或原始工具轨迹。原始分批事件仍在日志中，失败/取消由原有运行记录保留。

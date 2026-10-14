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

管理员私聊未指定群时，历史检索、聊天 SQL、近期发言和成员资料默认使用
`QQAgent.admin_private_default_group_id`，当前配置为 `2000000001`。工具可显式指定
其他群；检索与 SQL 可用 `group_id: "*"` 查询全部已归档群，近期发言和成员资料
仍一次读取一个群。默认群是查询属性，私聊会话、显式引用校验和通知目的地保持私聊。
普通群固定当前群，普通私聊没有群聊读取权限；本地 Web 的默认范围保持原配置。

## 工具与数据

工具实现和参数位于 `agent_console/tools`，数据库 schema、参考映射、绘图和角色
位于 `shared/agent`，内核不识别 QQ 或数据库。QQ worker 在服务器本地执行同一 RPC
协议，不经过 SSH；网页仍通过 SSH 调用。两个 worker 分别处理业务和状态，长查询
不会阻塞任务领取。SQL 继续使用独立 `hok_chat_reader`，动态 SQL 先整批校验再执行。
生成的 Python 只在 Linux bubblewrap 中运行，缺失隔离依赖时拒绝执行。

支持历史检索、游戏/聊天 SQL、联网搜索、参考映射、绘图、图片生成、隔离 Python、
长期记忆、角色联网新增/选择/偏好、分段消息与持久任务。群聊和管理员私聊先调用
`search_chat_history`，再 `discover_tools`；普通私聊只强制发现工具。未披露或未授权
工具不能执行。DeepSeek 工具链统一关闭 thinking，原生图片使用配置中的 vision_model。

询问机器人的功能、特性、命令或实现时，可发现 `bot_info` 并调用 `read_bot_manual`。
它按问题检索 `shared/agent/manual/handbook.md` 的少量相关章节；`section_id` 可精确
追问，`include_code=true` 可读取目录声明的关联函数摘录。结果含来源行号、版本和
截断/缺失状态，以及当前渠道相关工具的注册和授权信息。手册和实现有差异时需说明，
工具已注册不代表外部服务始终可用，传统 QQ 命令也不等于 agent 工具。
代码从目标服务器当前文件按 AST 定位，缓存随文件变化刷新，不导入执行源码。
不接受任意文件路径，不读取密钥、配置或日志；源码凭据脱敏。手册与代码映射位于
独立共享目录，修改后重启外部适配器；内核没有机器人说明或业务代码依赖。

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

任务存于 DB0 `hok:agent_runtime:console:*`。QQ 的 due 索引为 `tasks:qq`，网页为
`tasks`，分别领取。调度 hook 和 tick 只注册在 `hok/zscheduler.py`。固定文字任务
直接发送，不额外调用模型；agent 任务复用相同内核，并读取当前角色与偏好。
任务使用持久租约；入队后异常重启可能导致重复通知，不承诺 exactly-once。

## 回复与日志

每轮保留详细底稿和角色群聊版，QQ 默认发送群聊版，明确要求详细/完整时发送详细版。
`emit_message` 可以先发送阶段性内容。原生上传图片来自配置允许的 QQ 媒体域名，
验证实际像素、大小和数量后存于非公开 `data/agent_inputs`。显式引用只读取一次，
优先使用适配器已取得的消息，缺失才通过 `get_msg` 补读；不会展开引用链。
引用文本与图片进入本轮 user 角色的补充上下文，不写入后续直接对话；其中的 #、@、
命令和记忆指令只作资料，不触发执行。引用的发言者、消息 ID 和可信范围会先校验，
删除或无法读取的消息明确标为不可用。直接图片和引用图片共用去重后的输入预算。
图表和生成图片由 `zfile.store_agent_artifact` 转为现有 Web 可展示的 PNG。

动态表情支持 NapCat 的 `image` GIF 地址以及带 URL 的 `mface` / `marketface` / `face`，
直接发送与引用均走同一图片输入流程。动画按顺序抽取最多 4 帧并生成带帧号的 PNG
拼图，送给配置中的 `deepseek-v4-flash`；只分析实际提供的帧。原 GIF 保留，实际模型
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

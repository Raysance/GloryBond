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

`zevent` 不实现工具循环、不重复发送最终结果。`zchat.chat_process` 是异步兼容门面。
QQ 输入使用真实发送者，网页默认 example_user_10 的设置不影响 QQ。群聊只授权当前群；普通私聊
不提供群聊工具；已验证的 `QQBot.super_qid` 管理员私聊允许跨群。模型不能选择发送
对象，后台任务继承创建时的用户、会话、权限和目的地。

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
验证实际像素、大小和数量后存于非公开 `data/agent_inputs`；引用媒体仍为占位符。
图表和生成图片由 `zfile.store_agent_artifact` 转为现有 Web 可展示的 PNG。

最终消息继续包含图表与运行记录链接。原始模型/工具事件、实际请求响应、两版答案
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
  tests.test_qq_agent tests.test_qq_agent_transport tests.test_zchat
```

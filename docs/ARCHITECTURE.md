# 项目结构

应用源码统一放在 `src/glorybond/`。`src` 只是源码目录，`glorybond` 是 Python 包名；例如 `from glorybond.agent.chat_context import ChatModel`。Bot、Web 和本地聊天控制台独立启动，共用业务模块、配置与存储。

```text
src/glorybond/
├── apps/
│   ├── qq/             NoneBot 插件、事件路由、消息出口与 QQ AI 适配
│   ├── web/            FastAPI 页面、管理后台及原有 Jinja 模板
│   └── console/        本地聊天网页入口与静态资源
├── features/
│   ├── game/           战绩、玩家、英雄、排行与分析
│   ├── subscriptions/  B站和 X 订阅流程
│   ├── chat/           聊天业务、日报提示和轨迹组装
│   ├── kpl.py          职业赛事业务
│   └── facade.py       既有业务门面与跨模块编排
├── agent/              共用模型协议、上下文、工具、记忆、角色与任务
├── accounts/           登录会话、认证、凭据存储与登录 worker
├── integrations/       外部 API 与私有 SDK 的宿主适配
├── storage/            文件缓存、数据库入口与 SQL 定义
├── rendering/          图片、图表和消息卡片绘制
├── config/             配置投影与运行路径
├── runtime.py          进程内服务引用和动态状态
├── time.py             时间转换与业务时间函数
└── common.py           既有通用库导入和日志辅助
```

`apps` 处理渠道输入、身份、权限和交付；`features` 组织用户功能；`integrations` 处理外部协议。比如分享 B站视频由 `apps/qq/handlers/bili_video.py` 接收，经业务门面调用 `integrations/bili_media.py`，文件由 `storage/files.py` 缓存，最后沿 QQ 消息出口发送。订阅使用同一条下载与交付路径。

`agent` 与 `accounts` 不依赖 NoneBot 启动。真正注册机器人事件和定时任务的入口是 `glorybond.apps.qq.plugin`，导入包目录本身不会启动机器人。Web 模板继续使用已有 HTML/CSS/JS，不引入前端构建系统。现有业务门面继续保留稳定调用接口，避免在移动目录时同时改变业务规则。

根目录只保留项目说明、统一依赖、启动脚本及这些职责明确的目录：

| 目录 | 内容 |
| --- | --- |
| `src/` | 应用包和三个私有 SDK 的导入链接 |
| `tests/` | Bot、共享能力和 `tests/web/` 页面测试 |
| `docs/` | 架构、开发、发布说明，`manual/` 功能手册与 `web/` 页面指南 |
| `resources/` | 字体、图片、公开演示素材和 `agent/` 参考目录 |
| `deployment/` | Actions 发布入口、systemd 模板、安装和服务器维护 |
| `tools/` | `debugger/` 本地调试、`maintenance/` 数据维护、`publication/` 发布边界检查、`examples/` 独立示例 |
| `vendor/` | 三个私有 SDK 的固定 submodule 引用 |

SDK 保留各自公开包名 `agent_runtime`、`hok_research`、`hok_camp_client`，通过 `src/` 下的链接指向 `vendor/`，不把实现复制进公开仓库。功能手册的源码索引随路径同步迁移，并由 `tools/maintenance/validate_agent_manual.py` 校验。

`.env`、`config.yaml`、`data/`、`file_transfer/`、`log/` 和已有虚拟环境仍保存在私有运行目录。目录重构不迁移数据库、Redis 键、登录会话或公开 URL。原有本地调试环境 `local_debugger/.venv` 继续复用，调试代码入口改为 `python -m tools.debugger`；可用 `HOK_DEBUG_VENV` 指定其他环境。

启动及验证命令见[开发与部署](DEVELOPMENT.md)。生产发布会更新 Web 的 Python 模块入口并保留原 systemd 用户、环境文件、端口和其他主机设置；更改前保存原 unit，重复发布不会重复迁移。

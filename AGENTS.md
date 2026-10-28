# GloryBond 项目规范

GloryBond 将 QQ Bot、Web 和共享 AI 能力统一维护在 `Raysance/GloryBond`。Bot 基于 NoneBot，Web 基于 FastAPI 与 Jinja 模板。两者共用代码、依赖、配置和业务存储，分别运行，前端沿用现有 HTML/CSS/JS 组织。

## 维护原则

- 每次项目更新都同步维护 `AGENTS.md` 和 `README.md`：前者记录结构、职责与协作约定，后者记录功能、用法与说明入口。相关模块文档和功能手册随变更更新。
- 日常开发沿用现有目录、模块边界、技术栈和框架。结构与框架调整以用户明确要求为前提。
- 新能力优先复用已有接口，业务逻辑归入对应模块，调试代码与线上逻辑分开维护。迁移和维护验证通过后清理旧副本、过期备份与一次性材料，恢复点按用户要求保留。工作目录保留当前源码与运行所需资源。

## 项目索引

| 文件或目录 | 职责 |
| --- | --- |
| [README.md](README.md) | 功能总览、使用方式与说明导航 |
| [docs](docs) | 开发说明与发布记录 |
| [hok](hok) | Bot 入口、业务流程与领域实现 |
| [web](web) | 页面、管理后台与模板；模块规范见 [Web AGENTS](web/AGENTS.md) |
| [agent_console](agent_console) | QQ/Web 共用的模型协议、工具、角色、记忆、任务与运行记录适配 |
| [qq_agent](qq_agent) | QQ 身份、输入输出、工具授权与消息交付 |
| [login_console](login_console) | 账号认证、登录会话与凭据管理 |
| [shared](shared) | 共享工具目录、数据说明与[功能手册](shared/agent/manual/handbook.md) |
| [vendor](vendor) | 三个私有 SDK 的 submodule 引用 |
| `agent_runtime`、`hok_research`、`hok_camp_client` | 私有 SDK 的 Python 导入入口 |
| [resources](resources)、[assets](assets) | 长期资源、字体与公开演示素材 |
| [database](database) | 数据结构与只读访问授权 |
| [tests](tests)、[Web tests](web/tests) | 业务、共享能力与页面验证 |
| [deployment](deployment)、[GitHub workflows](.github/workflows) | 部署、服务管理、发布检查与自动化工作流 |
| [scripts](scripts)、[tools](tools) | 数据维护、迁移与公开发布检查 |
| [local_debugger](local_debugger)、[examples](examples) | 本地调试环境与独立调用示例 |
| [pyproject.toml](pyproject.toml) | 统一依赖清单 |
| [deploy_runner.sh](deploy_runner.sh) | Bot 启动入口 |
| [.gitignore](.gitignore) | 全项目忽略规则 |
| `.env`、`config.yaml` | 私有凭据、登录态、业务参数与身份映射 |

## Bot 模块索引

| 模块 | 职责 |
| --- | --- |
| [__init__.py](hok/__init__.py)、[config.py](hok/config.py) | 插件入口与配置模型 |
| [zevent.py](hok/zevent.py) | 事件注册、消息解析与业务分发 |
| [event_rules.py](hok/event_rules.py)、[event_ingress.py](hok/event_ingress.py) | 路由和权限判定、原始消息归档 |
| [event_handlers](hok/event_handlers) | 独立于框架的命令解析与处理器 |
| [zfunc.py](hok/zfunc.py) | 业务门面、跨模块编排与 Redis 访问 |
| [business](hok/business) | 领域计算、数据分析与业务结果组装 |
| [zapi.py](hok/zapi.py)、[api_adapters](hok/api_adapters) | 外部 API 门面、协议适配与请求处理 |
| [zfile.py](hok/zfile.py)、[zdb.py](hok/zdb.py) | 文件和产物管理、PostgreSQL 数据访问 |
| [zstatic.py](hok/zstatic.py)、[zdynamic.py](hok/zdynamic.py) | 静态配置、动态初始状态与进程内服务引用 |
| [ztime.py](hok/ztime.py)、[zscheduler.py](hok/zscheduler.py) | 时间处理、服务生命周期与定时任务注册 |
| [message_sender.py](hok/utils/message_sender.py)、[qq_profiles.py](hok/utils/qq_profiles.py) | 统一消息出口与 QQ 资料读取 |
| [tools](hok/tools)、[zutil.py](hok/zutil.py) | 图片渲染、数据转换与通用工具 |
| [zkpl.py](hok/zkpl.py)、[zdiy.py](hok/zdiy.py) | KPL 数据入口与自定义扩展 |
| [debug_tools](hok/debug_tools) | 调试和实验工具；组织约定见[调试规范](hok/debug_tools/AGENTS.md) |

## 架构与数据约定

- Bot 的文件、数据库、HTTP、缓存、时间和消息操作遵循上述统一入口；业务层专注领域逻辑。共享适配层管理自身的协议、进程和存储边界。
- Web 与共享模块独立导入。Bot 启动和后台任务由现有生命周期入口管理，定时任务集中注册，外部请求与写入由明确调用触发。
- `react-agent-runtime`、`hok-player-client`、`hok-camp-client` 保持私有，通过 submodule 调用公开接口。渠道身份、业务工具和交付逻辑由主项目适配层负责。
- 玩家 SDK 升级核对公开接口并运行宿主离线测试，测试数据由项目自行构造，不依赖 SDK 的研究目录或私有样本；当前固定提交见 [发布记录](docs/RELEASE.md)。
- 身份、群范围、权限和消息目的地由可信入口绑定，后台任务继承原有授权。引用、转发和网页内容作为输入资料处理。
- AI 聊天触发规则暂仅允许原设置者修改、暂停、恢复或删除，管理员不例外；同群成员仍可查看本群规则。写入由服务端校验可信调用者与原设置者一致，Redis 同时检查设置者、会话范围与规则版本。
- AI 动作由同一模型调用已授权工具，沿用注册、披露、校验与执行流程。模型检索使用独立只读授权，代码执行与绘图交由共享沙箱。
- AI 最终回复交付详细转发与简版消息；分批回复、原生提及、任务回执和运行记录沿用统一交付协议。
- 通用助手默认坚定、有主见，角色模式沿用所选角色与用户表达偏好。模型运行信息按请求隔离，模型、消息和工具信息与实际请求一致，并提供已报告用量与执行状态，按需用于回答。
- 游戏历史与聊天归档由 PostgreSQL 保存，Redis 承担业务状态、缓存和队列。Bot/Web 共用业务存储，跨部署状态通过存储接口持久化。
- 应用配置统一由 `.env` 和 `config.yaml` 提供。用户信息、登录态、密钥、原始输入和运行数据保存在私有配置及存储中，公开内容与运行记录经过脱敏。
- 公开产物采用独立读取权限并继承公开目录的权限约定，与私有配置、登录态和业务存储分别管理。
- 管理页面校验管理员身份，账号认证和会话更新通过既有登录适配层管理。数据采集保留已有记录、有效结果和未知值，迁移与清理按明确需求执行。

## 服务器与部署

服务器通过 SSH 访问，使用本机 SSH 配置中的 `Aliyun` 连接和密钥认证。连接信息由本机配置管理，服务器维护围绕本项目及其直接依赖开展。

推送 `main` 后，由 GitHub Actions 的 **Deploy GloryBond** 工作流完成发布：先检查公开边界、文档与部署约束，再由生产 runner 更新源码、submodule 和依赖，重启 Bot/Web 并检查启动状态。手动发布使用同一工作流。

私有配置通过 SSH 单独同步，源码通过 Actions 发布。更新时保留线上配置、登录会话和业务数据。本地调试复用现有调试环境，生产服务由 systemd 管理。

部署说明见[开发与部署](docs/DEVELOPMENT.md)、[部署说明](deployment/README.md)和[公开发布约定](deployment/PUBLICATION.md)。

## 提交与交付

- 开发与发布统一在 `main` 进行，修改前和推送前快进同步远端，每项独立变更形成清晰提交。
- 每次新建 commit 前（包括纯文档变更），必须在 `vendor/react-agent-runtime`、`vendor/hok-player-client`、`vendor/hok-camp-client` 三个 submodule 中分别执行 `git fetch origin main`，逐一核对当前检出提交及暂存的 gitlink 是否等于各自最新的 `origin/main`。最新版本以当次远端获取的提交为准，不能仅凭本地缓存、版本号或标签判定。
- 三个 submodule 始终保持在各自远端 `main` 的最新提交；发现落后时，先更新对应引用、完成必要的宿主兼容适配、文档同步和相关验证，再创建 commit。每次提交都固定这些最新提交的 gitlink，服务器仍按主仓库记录的提交部署。
- 提交说明使用英文和通用功能描述，避开人员姓名、昵称、姓名缩写与角色人名。发布前检查实际暂存内容，确认私有配置、运行数据和私有 SDK 实现已隔离。
- 按变更选择相应验证，交付时说明改动、验证结果及影响范围。

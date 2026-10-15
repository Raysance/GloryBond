# HOK_QQBot_Web Agent Notes

## 项目总结构

- `app.py`：FastAPI 主应用入口，集中定义页面路由、管理后台路由、Redis 连接、模板渲染和队列写入逻辑。
- `chat_trace.py`：公开聊天运行记录的 token/载荷校验及 Jinja 渲染；`app.py` 的 `/chat-trace` 路由仅委托该模块，Redis 读取仍由入口注入。
- `admin_chat_traces.py`：从共享 DB0 `hok:chat:traces` 有界摘要索引读取管理员运行列表，按群号、状态、摘要/QQ/运行ID筛选并分页，不批量读取完整模型 payload；索引上限来自 NBot 的 DynamicVariables.ChatTraceMaxRecords（默认1000条），过期摘要不展示。
- `database.py`：PostgreSQL 数据访问入口；只负责连接、健康检查与结构化战局 payload 查询。
- `request_analytics.py`：公开业务请求统计、敏感参数清理、IP 脱敏、异步地域解析缓存与后台聚合逻辑；只纳入人类可见业务入口，禁止统计静态资源、`/battle-data`、健康检查或管理后台自身请求。
- `health_diagnostics.py`：管理员手动深度诊断的固定命令执行与安全 JSON 解析；只允许调用 NBot 的 `hok/tools/chat_runtime_diagnostic.py`，不接受来自请求的命令、模型或地址参数，不回传子进程 stderr；同时核对 systemd 当前 NBot 进程的工作目录、重启时间和 chat 凭据指纹是否与诊断进程一致，指纹不写入响应。
- `utils.py`：业务辅助函数，包含王者荣耀官方接口请求、文件读写、战绩存在性检查等通用能力。
- `runtime_config.py`：Web 运行目录与 NBot 共享配置的唯一解析入口；负责兼容 `/opt/hok-qqbot/{nbot,web}`、Aliyun `/srv/modules/hok/apps/` 与显式环境变量布局，只加载 NBot 根目录 `.env` 与 `config.yaml`，并将前者的凭据注入后者的运行时视图。其他模块不得重新硬编码兄弟仓库相对路径或自建配置加载逻辑。
- `templates/`：Jinja2 HTML 模板根目录。
- `templates/CommonPages/`：普通用户侧页面模板，包括全部战绩、单人战绩、周期战绩、战斗详情、查询页、B 站订阅视频详情页等。
- `templates/CommonPages/BenefitVisualizer/`：受益受害贝叶斯收缩可视化单页面资源目录。
- `templates/AdminPages/`：管理后台页面，包括登录、仪表盘、访问地域与请求分析、直接跳转、用户信息编辑、聊天记忆查看。
- `templates/ErrorPages/`：错误页面模板，包括非法访问和链接过期。
- `templates/footer_github.html`：可复用页脚模板。
- `default_json_templates/`：默认 JSON 模板文件，主要用于本地或历史兜底数据参考。
- `tools/`：项目辅助脚本。
- `tools/import_request_analytics.py`：从 Nginx combined access log 幂等回填最近公开业务请求到 Redis 访问分析库；沿用在线采集白名单、凭据清理与地域缓存规则。
- `.github/workflows/`：部署相关 GitHub Actions。

## 部署运行方式

- 部署服务器上的 FastAPI 进程由 `hok-web.service` 统一管理，禁止在发布流程中再使用 `nohup` 或按端口手工结束进程。
- GitHub Actions 在 `/srv/modules/hok/apps/Web` 完成代码同步后，通过 `systemctl restart hok-web.service` 发布，并以 `systemctl is-active` 验证启动结果。
- Aliyun 的 Web 代码物理目录为 `/srv/modules/hok/apps/Web`，与 `apps/NBot` 保持同级，不依赖 `/QQBot/Web` 兼容入口。`hok-web.service` 属于 `hok.target`，与 NoneBot、NapCat、清理定时器统一启停，仍保留原服务名供 CI 单独重启。
- 服务器上的个人网站已独立归属 `/srv/modules/personal-site`，不得再把 `/QQBot/Web/raysance-site` 或 `html/raysance` 当作 HOK 内容维护；它们仅是兼容链接。Clash 独立归属 `/srv/modules/clash`；Nginx、Redis、PostgreSQL、证书与 CI runner 为共享基础设施。
- Aliyun 当前继续使用已验证的主机 Python 运行 Web，日志进入 systemd journal；新主机可以重建专用虚拟环境并调整 unit。独立新装模板仍使用 `/opt/hok-qqbot`、`/etc/hok-qqbot`、`/var/lib/hok-qqbot` 布局，不应与现有服务器路径混用。模块导出及恢复说明在 NBot 仓库的 `deployment/server_modules/README.md`。

## 数据路径约定

- 临时组合查询结果继续以浏览器可访问路径 `file_transfer/temp_files/<filename>.json` 传给模板。
- 单局战绩详情以 PostgreSQL 的 `hok.battle_details` 为主数据源，通过 `/battle-data/{game_seq}` 返回；仅在数据库未命中时读取 QQBot 数据库写入失败所产生的应急 JSON。
- 运行路径统一由 `runtime_config.py` 解析。`BOT_PATH` / `WEB_PATH` 指向两个代码目录，`HOK_NAPCAT_ROOT` 指向 NapCat 安装目录，`HOK_ENV_FILE` / `HOK_CONFIG_FILE` 可选覆盖 NBot 根目录 `.env` / `config.yaml`，`HOK_DATA_DIR` 指向应急数据目录，`HOK_FILE_TRANSFER_DIR` 指向 NBot 与 Web 共享的公开产物目录。Web 不得再读取 `variables_static.json`、`redis.json`、`.env.local` 或其他独立配置。
- 除 PostgreSQL 单局战绩的 `/battle-data/{game_seq}` 适配外，不要为同一份 JSON 数据额外新增 API 代理接口，除非用户明确要求。
- 不要为历史目录、调试目录或示例数据做冗余 fallback。
- `key` 表示 `temp_files` 下对应 JSON 文件名；如未带 `.json`，可在后端补齐 `.json`。
- 对 `key` 做路径穿越防护，只允许纯文件名，不允许目录分隔符、空文件名、`.` 或 `..`。

## 路由与模板风格

- 新增普通页面时优先遵循现有模式：`@app.get(...)` -> `templates.TemplateResponse(...)` -> 向模板传入 `request` 和必要数据路径。
- B 站订阅视频跳转页使用 `/bili-video?key=...`，后端直接从 Redis 读取临时视频 payload 后按 User-Agent 302 分流；电脑端跳转到 B 站官网视频页，移动端跳转到应用宝中转页；不要渲染中间内容页，不要新增额外 JSON 代理接口。应用宝中转页的 `android_schema` 传入 B 站移动端当前唤端实现对应的 `bilibili://video/{aid}?page=0`，缺少 `aid` 时降级到移动端 HTTPS 视频页。
- 页面数据路径尽量在后端计算后传入模板，不要让前端拼接业务路径或 Redis key。
- 管理后台路由保持在 `/admin/...` 命名空间下，并继续使用 `AdminKey` Cookie 和 `SECRET_KEY` 校验。
- 公开 `/health` 只执行不产生外部模型费用的快速服务检查；`/admin/funcs/health-check` 由管理员手动触发 DeepSeek 普通请求及工具续传深度诊断。深度诊断不得接入 Web/NBot 启动、systemd 重启、GitHub Actions 或公开匿名接口，并禁止并发重复执行。
- HOK_QQBot 与 Web 的全部 Redis 数据统一使用 `REDIS_DB`（DB0）和 `hok:` 根命名空间；Web 只创建一个 Redis 客户端。访问分析使用 `hok:web:analytics:*`，查询参数中的 key、AdminKey、token 等凭据禁止写入统计，后台只返回脱敏 IP。地域查询必须异步执行并按 IP 缓存，不得阻塞普通页面响应。
- NBot 与 Web 共享的网页临时载荷保存为 `hok:web:artifact:<token>`，URL 仍只暴露 token；收藏集合为 `hok:battle:liked_ids`；网页分享与底蕴分析队列分别为 `hok:queue:battle:share`、`hok:queue:battle:analyze`。Web 是两条业务队列的生产者，NBot 是消费者，修改名称或载荷结构时必须同步修改两个项目及 NBot 的 DB0 收敛迁移脚本。
- 错误场景优先复用 `templates/ErrorPages/illegal.html` 或 `templates/ErrorPages/expired.html`。
- 不要新增无必要的全局路由、兼容旧路由、调试接口或临时 fallback。

## Chat 运行记录页

- `/chat-trace?key=<16位hex>` 从 `hok:web:artifact:<token>` 读取 NBot 发布的 `kind=chat_trace, version=1` 载荷；已有 48 位 hex 链接兼容读取至自然过期。非法 token 在读取 Redis 前拒绝，缺失/过期/错误类型返回 410，Redis 暂不可用返回 503。
- 管理控制台“AI 运行记录”入口为 `/admin/funcs/chat-traces`，详情为 `/admin/funcs/chat-traces/{key}`，两者必须先验证 AdminKey Cookie，再读取 Redis，返回 no-store/no-referrer/noindex。列表由 Jinja 直接渲染，每页25条，筛选沿用 GET 参数，不新增 JSON 代理；详情复用原轨迹模板并提供返回列表入口。新 NBot 记录标记 visibility=admin，公开 /chat-trace 即使持有 key 也须验证管理员；未标记的旧公开记录按原 TTL 兼容。QQ 消息默认不再附记录网址，运行索引从新版本启用后写入，包含结束的正常/失败/取消/后台提醒；完整私有 JSONL 不迁移或删除。先发布 Web 鉴权与列表，再发布 NBot 新载荷。
- `templates/CommonPages/ChatTrace/` 在宽屏并列显示左侧对话和右侧 DeepSeek Harness 轨迹查看器，1050px 及以下使用对话/轨迹切换。右侧保留输入/模型/工具三条时间带、轮次步骤和概述/参数/结果/Schema/计时详情，以及搜索、折叠、耗时/摘要开关、JSON 导出和原图预览。`conversation.css/js` 单独维护本地 agent studio 风格的浅色气泡、助手正文、折叠执行过程、真实思考、token 明细和双版本回复；样式限定在 `#chat-view`，不得改动轨迹内部样式。回复从持久化 `output.message` 事件读取，按事件 ID 去重并保留阶段性发送，旧记录回退到 question/answer；角色名和详细/群聊版本仅展示实际保存的字段。用量以各轮 API usage 为准，未采集不能显示成零，缓存不重复计入合计。左侧执行步骤只导航到原轨迹详情，不另造工具结果。CSS/JS 使用 Jinja include，禁止增加全局静态路由或重复 JSON 代理接口。
- 页面展示每轮实际发送给业务模型和模型返回的完整 JSON payload，包含消息、系统提示、工具定义、工具结果及模型 API 返回字段；并按 DeepSeek Harness 的模型可见事件方式，在每一轮模型步骤前独立列出 `System Prompt`、`Context Injection` 和全部 `Tool Definitions`。优先从实际 provider request payload 提取，缺失时才读取 NBot 调用适配器前保存的 `context_injection` 快照；上下文步骤不得只显示空统计。所有工具参数和 observation 同样完整展示。每轮参数/结果面板不截断正文，左侧仅作摘要；支持结束原因、token 用量、空正文补试、失败阶段和异常链。凭据由 NBot 发布前脱敏，不采集 HTTP headers；删除旧 2 MiB 载荷限制。旧记录没有采集 payload 时明确标注，禁止伪造补全。
- 分享页使用不可猜测的随机链接和 Redis TTL，响应 `no-store`、`no-referrer`、`noindex`；无第三方脚本。载荷嵌入必须使用 `tojson`，前端对不可信文本使用 `textContent`，禁止拼接 `innerHTML`。图片只允许 `/file_transfer/chat_plot_<uuid>.png`。
- 访问分析纳入 `/chat-trace`，沿用 key 脱敏，不记录问题、答案和工具正文。
- Aliyun `/srv/modules/hok/nginx/site.conf` 的 FastAPI 路由白名单必须包含 `chat-trace`；修改前备份，`nginx -t` 通过后 reload。先发布 Web 路由与反向代理，再发布 NBot 链接生产端。
- 本地两个仓库独立检出且上级 README 缺失时，本功能用户说明维护在 `docs/chat.md`，不向 Desktop 根目录新建仓库外 README。

## Git 提交规范

- 所有代码修改和提交都必须直接在 `main` 分支上完成。
- Commit message 必须使用英文。

## 编码与维护规范

- 保持变更最小化，优先修正根因，不做无关重构。
- 项目现有代码大量使用单文件 HTML/CSS/JS；修改模板时保持当前风格，不引入构建工具。
- 不要因为浏览器资源 404 就在 `app.py` 中补全局资源路由；应修正模板资源引用或使用 Jinja include。
- 发生用户可见页面、功能入口或公开使用方式变更时，必须同步更新上级 `README.md`；路由、模板、配置、部署方式、目录职责等实现细节只记录在 `AGENTS.md` 或开发文档中。
- `Web/.gitignore` 只忽略本地缓存、编译产物、临时 HTML、日志等不必要文件；密钥、真实配置、私有数据等敏感忽略规则统一维护在根目录 `.gitignore`。
- 不要提交 `__pycache__/`、临时 JSON、运行时生成文件或本地环境文件。
- 如需读取中文模板内容，注意 PowerShell 默认编码可能显示乱码；优先用 Python 按 UTF-8 读取或只做结构性检查。

## 校验命令

- Python 语法校验：`python -m py_compile app.py`
- 前端脚本语法校验：`node --check templates\CommonPages\BenefitVisualizer\app.js`
- 搜索旧接口残留：`rg -n 'wzry_benefit_debug|sample\.json|/app\.js|/styles\.css|StaticFiles|benefitvisualizer' app.py templates\CommonPages\BenefitVisualizer`

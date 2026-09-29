# HOK_QQBot_Web Agent Notes

## 项目总结构

- `app.py`：FastAPI 主应用入口，集中定义页面路由、管理后台路由、Redis 连接、模板渲染和队列写入逻辑。
- `chat_trace.py`：公开聊天运行记录的 token/载荷校验及 Jinja 渲染；`app.py` 的 `/chat-trace` 路由仅委托该模块，Redis 读取仍由入口注入。
- `database.py`：PostgreSQL 数据访问入口；只负责连接、健康检查与结构化战局 payload 查询。
- `request_analytics.py`：公开业务请求统计、敏感参数清理、IP 脱敏、异步地域解析缓存与后台聚合逻辑；只纳入人类可见业务入口，禁止统计静态资源、`/battle-data`、健康检查或管理后台自身请求。
- `utils.py`：业务辅助函数，包含王者荣耀官方接口请求、文件读写、战绩存在性检查等通用能力。
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
- GitHub Actions 完成 `/QQBot/Web` 代码同步后，通过 `systemctl restart hok-web.service` 发布，并以 `systemctl is-active` 验证启动结果。
- `hok-web.service` 从 `/QQBot/Web` 启动 `app.py`，依赖 Redis、PostgreSQL 与网络就绪，运行日志统一进入 systemd journal。

## 数据路径约定

- 临时组合查询结果继续以浏览器可访问路径 `file_transfer/temp_files/<filename>.json` 传给模板。
- 单局战绩详情以 PostgreSQL 的 `hok.battle_details` 为主数据源，通过 `/battle-data/{game_seq}` 返回；仅在数据库未命中时读取 QQBot 数据库写入失败所产生的应急 JSON。
- 物理文件根路径由 `BOT_PATH` 环境变量拼接：`os.path.join(os.environ["BOT_PATH"], "file_transfer")`。
- 除 PostgreSQL 单局战绩的 `/battle-data/{game_seq}` 适配外，不要为同一份 JSON 数据额外新增 API 代理接口，除非用户明确要求。
- 不要为历史目录、调试目录或示例数据做冗余 fallback。
- `key` 表示 `temp_files` 下对应 JSON 文件名；如未带 `.json`，可在后端补齐 `.json`。
- 对 `key` 做路径穿越防护，只允许纯文件名，不允许目录分隔符、空文件名、`.` 或 `..`。

## 路由与模板风格

- 新增普通页面时优先遵循现有模式：`@app.get(...)` -> `templates.TemplateResponse(...)` -> 向模板传入 `request` 和必要数据路径。
- B 站订阅视频跳转页使用 `/bili-video?key=...`，后端直接从 Redis 读取临时视频 payload 后按 User-Agent 302 分流；电脑端跳转到 B 站官网视频页，移动端跳转到应用宝中转页；不要渲染中间内容页，不要新增额外 JSON 代理接口。应用宝中转页的 `android_schema` 传入 B 站移动端当前唤端实现对应的 `bilibili://video/{aid}?page=0`，缺少 `aid` 时降级到移动端 HTTPS 视频页。
- 页面数据路径尽量在后端计算后传入模板，不要让前端拼接业务路径或 Redis key。
- 管理后台路由保持在 `/admin/...` 命名空间下，并继续使用 `AdminKey` Cookie 和 `SECRET_KEY` 校验。
- HOK_QQBot 与 Web 的全部 Redis 数据统一使用 `REDIS_DB`（DB0）和 `hok:` 根命名空间；Web 只创建一个 Redis 客户端。访问分析使用 `hok:web:analytics:*`，查询参数中的 key、AdminKey、token 等凭据禁止写入统计，后台只返回脱敏 IP。地域查询必须异步执行并按 IP 缓存，不得阻塞普通页面响应。
- NBot 与 Web 共享的网页临时载荷保存为 `hok:web:artifact:<token>`，URL 仍只暴露 token；收藏集合为 `hok:battle:liked_ids`；网页分享与底蕴分析队列分别为 `hok:queue:battle:share`、`hok:queue:battle:analyze`。Web 是两条业务队列的生产者，NBot 是消费者，修改名称或载荷结构时必须同步修改两个项目及 NBot 的 DB0 收敛迁移脚本。
- 错误场景优先复用 `templates/ErrorPages/illegal.html` 或 `templates/ErrorPages/expired.html`。
- 不要新增无必要的全局路由、兼容旧路由、调试接口或临时 fallback。

## Chat 运行记录页

- `/chat-trace?key=<48位hex>` 从 `hok:web:artifact:<token>` 读取 NBot 发布的 `kind=chat_trace, version=1` 载荷；非法 token 在读取 Redis 前拒绝，缺失/过期/错误类型返回 410，Redis 暂不可用返回 503。
- `templates/CommonPages/ChatTrace/` 遵循 DeepSeek Harness 轨迹查看器的 UI 逻辑：对话/轨迹切换，输入/模型/工具三条时间带，左侧按轮次排列步骤，点击后在右侧概述/参数/结果/Schema/计时标签页查看详情；支持搜索、轮次折叠、耗时/调用摘要开关、脱敏 JSON 导出和图表原图预览；CSS/JS 使用 Jinja include，禁止增加全局静态路由或重复 JSON 代理接口。
- 页面展示可核验的执行记录及所有工具的参数和返回内容，包括记忆、群聊检索、上下文、引用关系和群列表；凭据由 NBot 发布前脱敏，不显示模型私有推理、系统提示或未作为工具结果返回的原始模型上下文。长结果为有限预览，必须保留截断标记。
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

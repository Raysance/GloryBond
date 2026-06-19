# HOK_QQBot_Web Agent Notes

## 项目总结构

- `app.py`：FastAPI 主应用入口，集中定义页面路由、管理后台路由、Redis 连接、模板渲染和队列写入逻辑。
- `utils.py`：业务辅助函数，包含王者荣耀官方接口请求、文件读写、战绩存在性检查等通用能力。
- `templates/`：Jinja2 HTML 模板根目录。
- `templates/CommonPages/`：普通用户侧页面模板，包括全部战绩、单人战绩、周期战绩、战斗详情、查询页等。
- `templates/CommonPages/BenefitVisualizer/`：受益受害贝叶斯收缩可视化单页面资源目录。
- `templates/AdminPages/`：管理后台页面，包括登录、仪表盘、直接跳转、用户信息编辑、聊天记忆查看。
- `templates/ErrorPages/`：错误页面模板，包括非法访问和链接过期。
- `templates/footer_github.html`：可复用页脚模板。
- `default_json_templates/`：默认 JSON 模板文件，主要用于本地或历史兜底数据参考。
- `tools/`：项目辅助脚本。
- `.github/workflows/`：部署相关 GitHub Actions。

## 数据路径约定

- Web 页面使用的战绩 JSON 统一以浏览器可访问路径 `file_transfer/temp_files/<filename>.json` 传给模板。
- 物理文件根路径由 `BOT_PATH` 环境变量拼接：`os.path.join(os.environ["BOT_PATH"], "file_transfer")`。
- 不要为同一份 JSON 数据额外新增 API 代理接口，除非用户明确要求。
- 不要为历史目录、调试目录或示例数据做冗余 fallback。
- `key` 表示 `temp_files` 下对应 JSON 文件名；如未带 `.json`，可在后端补齐 `.json`。
- 对 `key` 做路径穿越防护，只允许纯文件名，不允许目录分隔符、空文件名、`.` 或 `..`。

## 路由与模板风格

- 新增普通页面时优先遵循现有模式：`@app.get(...)` -> `templates.TemplateResponse(...)` -> 向模板传入 `request` 和必要数据路径。
- 页面数据路径尽量在后端计算后传入模板，不要让前端拼接业务路径或 Redis key。
- 管理后台路由保持在 `/admin/...` 命名空间下，并继续使用 `AdminKey` Cookie 和 `SECRET_KEY` 校验。
- 错误场景优先复用 `templates/ErrorPages/illegal.html` 或 `templates/ErrorPages/expired.html`。
- 不要新增无必要的全局路由、兼容旧路由、调试接口或临时 fallback。

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

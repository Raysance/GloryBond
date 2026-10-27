# Bot/Web统一项目

唯一维护仓库是私有 `Raysance-Studio/HOK_QQBot`。Web从原 `HOK_QQBot_Web` 的 `9f72cf2` 导入到 `web/`，原仓库的完整提交历史保留在主仓库标签 `archive/web-before-unification-20261027`、旧仓库及迁移Git bundle中。旧Web仓库退役后不再接收部署推送。

本地在 `HOK_QQBot/` 同时维护Bot和Web；旧独立Web检出移入用户本地私有备份目录。公开展示用的GloryBond仓库不参与本次生产迁移。

## 统一运行

根 `pyproject.toml` 是唯一依赖清单，根 `.env`、`config.yaml` 是两项服务的唯一应用配置。生产使用根 `.venv`。Bot由 `deploy_runner.sh` 启动；Web从根执行 `.venv/bin/python -m web`，Python模块使用 `web.*` 导入，不依赖兄弟仓库或当前工作目录查找配置。

Aliyun代码根为 `/srv/modules/hok/apps/HOK_QQBot`。Bot/Web继续由 `hok-nbot.service`、`hok-web.service` 隔离运行，同属 `hok.target`，共享Git版本、环境和配置。NapCat、公开产物、PostgreSQL、Redis DB0及个人网站不迁移或清理。

根GitHub Actions统一发布两项服务；`deployment/scripts/deploy_project.sh` 保留服务器实际 `.env`、同步固定submodule、必要时更新依赖，再重启Bot/Web。`verify_startup.py` 只检查Bot启动标记及Web `/health`，不调用收费模型或发送测试消息。

## 一次性切换

先将统一代码推送到主仓库。切换窗口暂时禁用旧Bot/Web部署工作流，避免旧路径自动部署。在Aliyun执行新版脚本的预览及正式切换：

```bash
python3 /path/to/unify_project.py
python3 /path/to/unify_project.py --apply
```

脚本拒绝未合并的服务器源码改动，允许保留服务器实际 `.env`。它先生成两仓库Git bundle、凭据副本及恢复记录，再停止Bot/Web；如根 `.env` 缺少只读数据库凭据，则从原 `nbot-host.env` 复制既有 `HOK_CHAT_READONLY_DSN`，不生成账号、不修改数据库权限、不回退写账号。随后将Bot检出原地重命名，导入统一版本、重建共享依赖并更新服务及配置索引。旧Web和分散配置移入 `/srv/modules/hok/backups/unified-project-<UTC时间>/`，不删除运行数据；私有目录禁止公开。

迁移及发布脚本显式绑定当前项目路径，覆盖SSH登录环境中可能保留的 `/QQBot/NBot` 等旧变量，不继承旧shell路径作为应用配置来源。切换失败会按记录恢复旧路径、源码版本、配置及服务。切换成功后保留备份，启用主仓库工作流并执行一次手动发布，确认从新目录完整更新与启动；旧Web工作流保持停用，旧GitHub仓库只保留迁移说明及历史。

## 验证

在统一项目根执行：

```bash
local_debugger/.venv/bin/python -m unittest discover -s tests
local_debugger/.venv/bin/python -m unittest discover -s web/tests
local_debugger/.venv/bin/python -m unittest discover -s deployment/server_modules
```

网页JavaScript测试位于 `web/tests/*.cjs`。新主机的源码包和安装器也使用统一布局，不再接收 `--web-source`，不创建Web独立依赖清单或虚拟环境。

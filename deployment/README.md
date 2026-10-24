# HOK QQBot portable deployment

For the existing Aliyun server's **HOK / personal-site / Clash** module layout,
unified lifecycle, private exports, and restoration instructions, see
[server modules](server_modules/README.md). The `/opt` layout below is a separate
fresh-install template.

## Configuration contract

NBot has exactly two application configuration files, both in its project root:

- `.env` contains credentials only: API keys, tokens, passwords, database DSNs,
  plus the `ENVIRONMENT` and `DRIVER` values required by NoneBot. This private
  repository tracks the file, so every transport bundle is private.
- `config.yaml` contains every non-secret setting, including service endpoints,
  models, proxy settings, Redis, NapCat, stable variables, and dynamic defaults.

The owner explicitly authorizes committing and pushing real credentials in the
existing `.env` to this private repository alongside related code or configuration
changes. Do not exclude `.env`, split out its commit, or ask again solely because it
contains credentials. Unrelated working changes remain outside the current task.
Chat replies, logs, diagnostics, public artifacts, and documentation must continue
to omit or redact credential values.

Do not create `.env.local`, `*.env.example`, `config.yaml.example`, `redis.json`,
or separate static/dynamic-variable files. Runtime paths belong in systemd units
and persistent business state belongs in Redis or PostgreSQL.

The portable filesystem layout is:

```text
/opt/hok-qqbot/
├── nbot/                    NBot source, .env, and config.yaml
└── web/                     FastAPI web service
/var/lib/hok-qqbot/
├── data/                    emergency JSON and static district data
├── file_transfer/           NBot/Web shared public artifacts
└── backups/                 host-local migration backups
/var/log/hok-qqbot/          application file logs; service output is in journald
```

The legacy renderers keep regenerable image caches below
`nbot/resources/wzry_images`. Bundle builds omit generated, KPL, temporary, and
hero-avatar cache contents.

The application modules are:

- `hok-nbot.service`: NoneBot runtime using the project-local virtualenv.
- `hok-web.service`: FastAPI runtime bound to `127.0.0.1:8000` by default.
- `hok-napcat.service`: optional QQ/NapCat runtime. Its command is read from
  `config.yaml` at `NapCat.command`; the NapCat installation is not bundled.
- `hok-temp-files-cleanup.timer`: deletes only old temporary public artifacts.
- `nginx/hok.conf.in`: HTTP reverse proxy and shared-artifact location.

Redis and PostgreSQL are infrastructure dependencies, not application units.
HOK Redis data stays in DB0 under `hok:`; PlanIt DB9 must not be merged into HOK
backups or migrations.

## Build a transport bundle

From the NBot repository, initialize the pinned private agent dependency first.
The cloning/deployment account needs SSH read access to
`git@github.com:Raysance/react-agent-runtime.git`:

```bash
git submodule update --init --recursive
```


```bash
deployment/scripts/build_bundle.sh \
  --web-source ../HOK_QQBot_Web \
  --output dist/hok-qqbot.tar.gz
```

The bundle includes both `.env` and `config.yaml`, excludes generated/runtime
files, and is written with mode `0600`. Native QQ input images (`data/agent_inputs`) and conversation logs are excluded.
The initialized submodule source and the `agent_runtime` symlink are bundled,
so an extracted bundle does not need GitHub access. Database and Redis contents are not put
in the source bundle. Back them up separately before moving an existing server.

## Install on another Linux server

Install Python 3.11+, Redis 6+, PostgreSQL 16 (or compatible remote services),
Nginx, `git`, `tar`, and `findutils`. Extract the bundle, then run:

```bash
sudo deployment/scripts/install.sh \
  --prefix /opt/hok-qqbot \
  --state-dir /var/lib/hok-qqbot \
  --modules nbot,web,cleanup,nginx \
  --domain hok.example.com
```

The installer copies the two root configuration files with the application,
sets `.env` to mode `0600` and `config.yaml` to `0640`, renders systemd units,
and enables selected units. It does not start them unless `--start` is supplied.

After installation:

1. Review `/opt/hok-qqbot/nbot/.env` and `config.yaml`.
2. Initialize PostgreSQL once with `database/schema.sql`.
3. Install NapCat separately when needed and set `NapCat.command` in
   `config.yaml`.
4. Run checks, then restart the selected services.

```bash
sudo /opt/hok-qqbot/nbot/deployment/scripts/doctor.sh \
  --bot-path /opt/hok-qqbot/nbot
sudo systemctl restart hok-nbot.service hok-web.service
```

## Chat and web search

Ordinary chat uses the configured DeepSeek-compatible endpoint directly with
environment-proxy inheritance disabled. Credentials come from `.env`; provider,
model, and behavior settings come from `config.yaml`.

Chat web search calls Alibaba Cloud OpenSearch `ops-web-search-001` directly.
`HOK_ALIYUN_SEARCH_API_KEY` lives in `.env`; endpoint, workspace, service ID,
content type, strategy, and query rewrite live under `AliyunSearch` in
`config.yaml`. The search request never uses Clash or OpenRouter.

Steam, APIMart, and X website subscriptions share the explicit `Proxy.clash_url` route from
`config.yaml`; `HOK_CLASH_PROXY_URL` can override it per process.
On the Aliyun host, this points to the existing Clash service at
`http://127.0.0.1:7890`. For local debugging, forward that server loopback port
over SSH and keep using the project configuration; the same loopback address
on a developer computer does not automatically refer to the server proxy.
X website requests, static bootstrap assets, and post media all use this route.

## Updating and rollback

`restore_application.sh` preserves the server's existing `.env` during source restoration and removed-file cleanup; provision credentials through the existing private file before restarting.

Build and copy a new private bundle, back up PostgreSQL, Redis, and persistent
state, rerun `install.sh` without `--start`, then run `doctor.sh` before
restarting. Restore the previous application tree and virtualenvs together when
rolling back.

## Shared QQ agent

QQ chat now uses the independent runtime pinned in `vendor/react-agent-runtime`.
See [QQ adapter](../qq_agent/README.md) for input/output, memory, roles and tasks.
`QQAgent` in the existing `config.yaml` controls budgets, image limits and default
role. Credentials still come from the existing environment and `.env`; SQL
catalogs and tools are defined under `shared/agent` and `agent_console`.

The main-branch deployment workflow restores application code, backs up the old
copied `agent_runtime` directory under ignored `log/deployment-backups`, restores
the new symlink and runs `git submodule update --init --recursive`. It then checks
imports before restarting NoneBot. `data/history` remains excluded from restores.
The submodule uses SSH because the current Aliyun account has SSH read access to
the private repository. Deployments check out the committed version, never the
latest remote branch. No paid model/tool diagnostics are run during deployment.

QQ runs two local workers, separating business calls from state and task claims.
The existing `zscheduler.py` owns startup, shutdown and task polling. Startup
logs `QQ_AGENT_READY` after worker initialization. PNG outputs and expiring trace
links continue to use the existing Web service. New direct-dialogue history is
isolated by user and channel; previous history and saved facts are preserved.

The legacy chat implementation is removed. Shared read-only SQL limits use
`AgentSQL`; fonts and QQ image collages use `AgentPlots`. Cleanup never drops
database tables or deletes stored conversations/facts during deployment.

`restore_application.sh` removes only source files deleted between the deployed
revision and the requested revision, before resetting the index. This prevents
retired modules from surviving as untracked Python files. It excludes runtime
`data/history` and delegates the copied-core backup to `sync_agent_runtime.sh`.

## 王者玩家客户端

源码固定在 `vendor/hok-player-client`，根目录 `hok_research` 链接至其公开包。
现有递归子模块同步会检出固定提交；服务器必须对该私有仓库拥有 SSH 读取权限。
现有 PyCryptodome 依赖已经满足客户端要求，无需手机、ADB 或运行时 APK。
安装包会携带该包的四份协议/资料 JSON，构建前应初始化两个子模块。

非密钥设置统一位于 `config.yaml#PlayerClient`。现有 `.env` 中的
`HOK_PLAYER_CLIENT_RESOURCES_JSON`、`HOK_PLAYER_CLIENT_SESSION_JSON`、
`HOK_PLAYER_CLIENT_INSTALLATION_JSON` 分别保存导出的运行资源、MSDK 会话和原安装标识。
部署脚本保护服务器 `.env`，首次部署必须通过 SSH 将这三项合并到服务器既有 `.env`，保留其他配置。
程序只在请求时将其写入 `data/player_client/` 的 0600 文件；目录为 0700、被 Git 忽略且部署 bundle 排除。
旧 `account.json` 是旧连接结果，不能替代新的游戏登录。会话失效时人工重新授权并更新 session 项；不自动扫码、重登或重试。

### 使用与限速

`#客户端 帮助` 查看完整用法。例如 `#客户端 战绩 我`、`#客户端 英雄 example_user_10 season`、
`#客户端 英雄详情 example_user_10 166`、`#客户端 搜索 完整昵称 android`。
省略玩家表示真实 QQ 对应的唯一已绑定账号；一个 QQ 对应多个账号时需写账号键。
搜索只返回候选，不自动改绑定。结果经一份聊天记录转发显示，超长明确截断。
战绩 complete 仅指本次响应结束，不能当成全部历史。

适配层复用游戏连接，串行执行，不修改上游。DB0 保存账号共享的最小间隔、分钟/小时滑动窗口和冷却，跨进程/部署生效。
默认查询间隔为 10–12 秒、每分钟 5 次、每小时 120 次；登录组（区服目录与登录）至少间隔 60 秒，每小时最多 6 组。
普通间隔最多前台等待 20 秒，超额/冷却立即拒绝；已知冷却码 262034 暂停 900 秒，登录失败暂停 1800 秒，未知拒绝/网络异常暂停 60 秒。
隐私拒绝码不视为风控；任何失败不自动重试。Redis 不可用时不发送请求。
这些数值是本项目保守默认值，不能保证服务端永不触发风控。

### 初始玩家绑定

同机执行：

```bash
local_debugger/.venv/bin/python scripts/resolve_player_client.py --apply
```

从本机读取服务器数据库时，先在独立终端建立仅本机可访问的 SSH 转发，再运行脚本：

```bash
ssh -N -L 127.0.0.1:16379:127.0.0.1:6379 Aliyun
local_debugger/.venv/bin/python scripts/resolve_player_client.py --ssh Aliyun --redis-port 16379 --apply
```

不带 `--apply` 仍会登录及搜索，但只预览结果；`--players` 可限制账号键。
已绑定账号跳过；同名、无昵称、拒绝均不猜测。批量出错立即停止，修正原因并等待冷却后人工继续。
数据库访问只读，不改 schema；最新昵称按真实对局 epoch/快照日期排序，不按缺少年份的展示日期排序。
保存的 UID、逻辑区服、fake_description_id 与 player_sub_id 均来自新接口，不能由旧 role_id/QQ/营地 ID 替代。

跨主机验证只代表所测时刻的登录和查询可用；服务端仍可能因会话到期、设备环境或后续策略变化要求重新授权。

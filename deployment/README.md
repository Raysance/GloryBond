# HOK QQBot portable deployment

For the existing Aliyun server's **HOK / personal-site / Clash** module layout,
unified lifecycle, private exports, and restoration instructions, see
[server modules](server_modules/README.md). The `/opt` layout below is a separate
fresh-install template.

## Configuration contract

The unified Bot/Web project has exactly two application configuration files, both in its project root:

- `.env` contains credentials, database DSNs, verified login sessions and NoneBot's startup environment values.
- `config.yaml` contains non-secret settings plus private user/account mappings and deployment endpoints.

Both files are ignored by Git and transferred separately over SSH. Code, documentation and deployment methods are public in `Raysance/GloryBond`; private SDKs remain submodules. See [configuration synchronization](../docs/DEVELOPMENT.md) before deploying. Code-only updates retain the current server files, including its latest verified sessions.

Do not create `.env.local`, `*.env.example`, `config.yaml.example`, `redis.json`,
or separate static/dynamic-variable files. Runtime paths belong in systemd units
and persistent business state belongs in Redis or PostgreSQL.

The portable filesystem layout is:

```text
/opt/hok-qqbot/
├── pyproject.toml           One dependency manifest
├── .env / config.yaml       Shared configuration
├── .venv/                   Shared runtime
├── hok/                     NoneBot business core
└── web/                     FastAPI package
/var/lib/hok-qqbot/
├── data/                    emergency JSON and static district data
├── file_transfer/           NBot/Web shared public artifacts
└── backups/                 host-local migration backups
/var/log/hok-qqbot/          application file logs; service output is in journald
```

The legacy renderers keep regenerable image caches below
`resources/wzry_images`. Bundle builds omit generated, KPL, temporary, and
hero-avatar cache contents.

Bot and Web share one checkout, one dependency manifest and one virtualenv. Start Web from the project root with `.venv/bin/python -m web`. The application processes are:

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

From the unified repository, initialize the pinned private agent dependency first.
The cloning/deployment account needs SSH read access to
`git@github.com:Raysance/react-agent-runtime.git`:

```bash
git submodule update --init --recursive
```


```bash
deployment/scripts/build_bundle.sh \
  --output dist/hok-qqbot.tar.gz
```

The bundle excludes `.env`, `config.yaml` and generated/runtime files, and is written with mode `0600`. Native QQ input images (`data/agent_inputs`),
persistent rule media (`data/automation_media`), and conversation logs are excluded.
The initialized submodule source and the `agent_runtime` symlink are bundled,
so an extracted bundle does not need GitHub access. Database and Redis contents are not put
in the source bundle. Back them up separately before moving an existing server;
include private rule media with its Redis rules to preserve image and GIF actions.

## Install on another Linux server

Install Python 3.12+, Redis 6+, PostgreSQL 16 (or compatible remote services),
Nginx, `git`, `tar`, and `findutils`. Extract the bundle, then run:

```bash
sudo deployment/scripts/install.sh \
  --prefix /opt/hok-qqbot \
  --state-dir /var/lib/hok-qqbot \
  --modules nbot,web,cleanup,nginx \
  --domain hok.example.com
```

Before installation, separately synchronize the two private files to the destination root. The installer preserves them, sets `.env` to mode `0600` and `config.yaml` to `0640`, renders systemd units,
and enables selected units. It does not start them unless `--start` is supplied.

After installation:

1. Review `/opt/hok-qqbot/.env` and `config.yaml`.
2. Initialize PostgreSQL once with `database/schema.sql`.
3. Install NapCat separately when needed and set `NapCat.command` in
   `config.yaml`.
4. Run checks, then restart the selected services.

```bash
sudo /opt/hok-qqbot/deployment/scripts/doctor.sh \
  --bot-path /opt/hok-qqbot
sudo systemctl restart hok-nbot.service hok-web.service
```

Public artifacts use a Nginx-readable group and setgid directories, so new JSON
and images remain readable with the services' `UMask=0027`. Every Actions deployment
runs `deployment/scripts/public_artifact_permissions.py` against the shared
`file_transfer` directory before restarting Bot/Web. The helper preserves an
accessible installer public group, otherwise selects the running Nginx workers'
primary group. It skips symlinks inside the artifact tree; private configuration,
input images and database files retain their own permissions. Use `--group` to
select the public read group when running maintenance without Nginx workers.

## Chat and web search

Ordinary chat uses the configured DeepSeek-compatible endpoint directly with
environment-proxy inheritance disabled. Credentials come from `.env`; provider,
model, and behavior settings come from `config.yaml`.

Chat web search uses the configured DeepSeek search adapter. Its endpoint and limits are under `DeepSeekSearch` in `config.yaml`; credentials come from `.env`.

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
restarting. Restore the previous application tree and shared virtualenv together when
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
`#客户端 英雄详情 example_user_10 166`、`#客户端 搜索 完整昵称 all`（默认双端，可指定 android/ios）。
省略玩家表示真实 QQ 对应的唯一已绑定账号；一个 QQ 对应多个账号时需写账号键。
搜索只返回候选，不自动改绑定。结果直接发送中文摘要，支持的资料附统计图片，超长明确截断。
战绩 complete 仅指本次响应结束，不能当成全部历史。

适配层复用游戏连接，串行执行；SDK 修复已完成战绩的尾部静默等待误关闭连接，业务限速仍留在适配层。DB0 保存账号共享的最小间隔、分钟/小时滑动窗口和冷却，跨进程/部署生效。
默认查询间隔为 1–1.2 秒（SDK 本地间隔 0.5 秒）、每分钟 30 次、每小时 120 次；登录组（区服目录与登录）至少间隔 60 秒，每小时最多 6 组。
普通间隔和短分钟窗口最多前台等待 60 秒，超出等待预算的额度或当前冷却立即拒绝；已知冷却码 262034、登录失败及其他拒绝/网络异常的本地冷却统一为 60 秒，提示使用实际剩余时间。
隐私拒绝码不视为风控；任何失败不自动重试。Redis 不可用时不发送请求。
原有统计文案与客户端资料同时查询，发送仍按原有文案、客户端图片排序。游戏统计与英雄页共用同一精确目标的 profile 缓存，图片只下载实际需要的素材。
客户端固定为 `c9b70e7`（版本号 `0.7.3`，在 v0.7.3 标签后增加9个提交），继续通过 `HokClient.from_resources()` 创建。本次升级修复自动心跳与查询并发发送时 DATA 正文及帧头序号不一致的问题，公开接口与返回字段兼容；服务器终止码7/14的成因仍未确认。SDK 研究工具、原生向量与历史发布物已移出运行仓库，宿主离线页面测试使用自行构造的数据与背景。

SDK 在每次 `login()` 中自动查询应用更新配置并采用服务端声明的当前资源版本，现有资源文件可继续使用，宿主无需手改版本或增加同步逻辑。登录成功后，公开 `client.status["resource_version"]` 返回本次实际采用的版本；未登录、断开或 close() 后为 None，不能以静态资源文件的导出版本代替。登录后的连接接收、心跳与状态刷新节奏由 SDK 自动管理；宿主仅调用公开查询和 close()，已移除旧心跳调度、分段保活及对应配置。公开接口报告服务器终止或网络异常时，沿用既有错误冷却与连接释放，不在本次请求中重登或重试；服务器终止原因尚不明确时保留原始类型及协议码，不当作好友离线或无人在线。同一目标资料和英雄来源缓存60秒、最多16项，关闭时清空，不缓存失败或完整战绩对象。
好友名单直接使用 friends()，批量状态使用 refresh_friend_states(timeout=...)，单好友使用 friend_state(PlayerRef, timeout=...)；状态等待上限来自 `PlayerClient.friend_state_wait_seconds=3` 秒。升级后不再传旧快照、require_all 或手动时间；名单完整性与本轮状态更新完整性分别读取 complete / states_refreshed，原始零值与已有状态均按 SDK 返回结果展示，未提供的字段保持未知。管理员限流诊断含来源和剩余秒数，以区分一分钟失败抑制、服务器冷却、配额和繁忙。
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

不带 `--apply` 仍会登录及搜索，但只预览结果；`--players` 可限制账号键；`--refresh` 对已绑定账号也执行双端搜索，保留已验证身份。
默认跳过已绑定账号，`--refresh` 仅用原 UID/逻辑区服/平台消歧，不自动改绑。搜索默认逐项查询 Android 和 iOS，每项请求均经过共享限速；13002 表示该端无记录，仍查询另一端。同名、无昵称、拒绝均不猜测，待确认候选保存于 `pending_players`。`binding_skip_players` 保存人工指定跳过的账号，不发起搜索；`nickname_overrides` 可保存人工确认的当前完整昵称，优先于旧数据库昵称。批量出错立即停止，修正原因并等待冷却后人工继续。
数据库访问只读，不改 schema；最新昵称按真实对局 epoch/快照日期排序，不按缺少年份的展示日期排序。
保存的 UID、逻辑区服、fake_description_id 与 player_sub_id 均来自新接口，不能由旧 role_id/QQ/营地 ID 替代。

跨主机验证只代表所测时刻的登录和查询可用；服务端仍可能因会话到期、设备环境或后续策略变化要求重新授权。

发布验证同时检查本次 systemd InvocationID 与 Uvicorn 的应用启动完成日志，最多等待180秒；启动中自动重启或缺少完成记录时任务失败，避免仅因进程短暂 active 而误报成功。旧游戏接口缓存初始化在启动 hook 中逐项隔离，失败不阻断客户端查询入口。

管理员在 Web 管理控制台选择「账号登录态」，可分别检查王者营地、王者官方客户端和 NapCat QQ 的登录状态。可手动生成二维码，使用希望切换到的 QQ 账号扫码并确认。营地与官方客户端分别授权；成功验证后保存至现有 `.env`，后续查询自动使用更新的登录态。网络错误显示「待确认」，不会自动反复登录。允许扫码账号与原配置不同，新账号验证成功后同步更新登录态、身份及角色/区服配置。营地默认采用唯一角色或服务端唯一主角色，无法确定时由管理员选择，无角色清空旧角色。NapCat 在线时「同步 / 扫码登录」同步当前账号，离线时展示二维码，并更新下次启动的登录账号，继承 Bot 原有 OneBot 连接配置。`AccountSessions.napcat.config_dir` 指向 NapCat 的原生 config 目录，仅用于读取原机器人配置，配置材料不向页面返回。

`config.yaml#AccountSessions.worker_python` 指向 NBot 运行环境（相对 NBot 根目录，默认 `.venv/bin/python`）；本机可改为 `local_debugger/.venv/bin/python`。需要初始化全部子模块并安装当前 `pyproject.toml` 的依赖。NapCat WebUI 必须启用，`AccountSessions.napcat.base_url` 只允许本机地址，HTTPS WebUI 还须在 `tls_fingerprint_sha256` 配置证书 DER 的 SHA256 指纹（证书更换后需同步更新），WebUI token 配置在唯一 `.env` 的 `HOK_NAPCAT_WEBUI_TOKEN`。页面不会公开 WebUI token、二维码原始链接或服务凭据。扫码会话最长保留4分钟；QQ 可提前使二维码失效，页面会提示重新生成。服务发布重启后需重新生成。NapCat QQ 会话由自身保存，无需复制登录文件。

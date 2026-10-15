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

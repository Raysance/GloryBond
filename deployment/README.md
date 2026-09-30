# HOK QQBot portable deployment

For the existing Aliyun server's **HOK / personal-site / Clash** module layout,
unified lifecycle, full private exports, and restoration instructions, see
[server modules](server_modules/README.md). The `/opt` layout below is a separate
fresh-install template, not the current Aliyun filesystem layout.

This directory packages the HOK stack as independent Linux modules. Application
code, host configuration, persistent state, and logs are deliberately separated:

```text
/opt/hok-qqbot/              application code
├── nbot/                    NoneBot and HOK business logic
└── web/                     FastAPI web service
/etc/hok-qqbot/              secrets and host-specific configuration
├── common.env               shared paths, database DSN, ports and proxy
├── nbot.env                 NoneBot and OneBot settings
├── napcat.env               optional NapCat start command
├── config.yaml              HOK API and Web settings
├── redis.json               Redis endpoint and DB0 compatibility keys
├── variables_static.json    users, roles and stable mappings
└── variables_dynamic.json   dynamic defaults
/var/lib/hok-qqbot/          persistent and shared runtime state
├── data/                    PostgreSQL emergency JSON and static district data
├── file_transfer/           NBot/Web shared public artifacts
└── backups/                 host-local migration backups
/var/log/hok-qqbot/          application file logs; service output is in journald
```

The legacy renderers still maintain regenerable image caches below
`nbot/resources/wzry_images`; the installer grants the runtime account write
access only to that asset subtree. Bundle builds omit generated, KPL, temporary,
and hero-avatar cache contents so they cannot silently become migration state.

The portable application modules are:

- `hok-nbot.service`: NoneBot runtime. It uses the project-local virtualenv and
  no longer embeds a proxy or a Miniconda path.
- `hok-web.service`: FastAPI runtime bound to `127.0.0.1:8000` by default.
- `hok-napcat.service`: optional QQ/NapCat runtime. The executable command stays
  host-specific in `napcat.env`; the NapCat installation itself is not bundled.
- `hok-temp-files-cleanup.timer`: deletes only files older than seven days in
  the shared `file_transfer/temp_files` directory.
- `nginx/hok.conf.in`: an HTTP reverse-proxy and shared artifact location.
  TLS certificates remain the host administrator's responsibility.

Redis and PostgreSQL are infrastructure dependencies rather than application
units. This avoids assuming distribution-specific unit names such as
`postgresql-16.service`. Both may be local or remote as long as `redis.json` and
`HOK_DATABASE_DSN` point to them. HOK Redis data must remain in DB0 under the
`hok:` namespace; PlanIt DB9 must not be merged into the HOK backup or migration.
Group-chat history is PostgreSQL-backed; legacy DB0 `hok:chat:group:*` lists are
retained only as migration/recovery input and are merged by the application.

## Build a transport bundle

From the NBot repository:

```bash
deployment/scripts/build_bundle.sh \
  --web-source ../HOK_QQBot_Web \
  --output dist/hok-qqbot.tar.gz
```

The default bundle excludes Git metadata, virtualenvs, logs, generated files,
`config.yaml`, `.env`, and `.env.local`. `variables_static.json` and
`variables_dynamic.json` are included because they currently contain required
application mappings; treat the resulting archive as private. To carry the API
configuration and OneBot token too, add `--include-private-config`. That option
places them under `private-config/` and makes the archive mode `0600`. When
present, `.env.local` is included only as `private-config/chat.env`; copy its
chat settings into the target service's private environment file before use.

Database and Redis contents are intentionally not placed in the source bundle.
Before moving an existing server, make separate recoverable backups:

```bash
pg_dump --format=custom "$HOK_DATABASE_DSN" > hok-postgres.dump
redis-cli --rdb redis-full.rdb
```

The Redis command snapshots the whole Redis server, including non-HOK databases.
Store and restore it only as a full-server backup. Use
`scripts/consolidate_redis_to_db0.py` for the existing HOK key migration, and
always keep its generated DUMP backup.

## Install on another Linux server

Install Python 3.10+, the Python venv package, Redis 6+, PostgreSQL 16 (or a
compatible remote service), Nginx, `git`, `tar`, and `findutils`. Extract the
bundle, then run:

```bash
sudo deployment/scripts/install.sh \
  --prefix /opt/hok-qqbot \
  --config-dir /etc/hok-qqbot \
  --state-dir /var/lib/hok-qqbot \
  --modules nbot,web,cleanup,nginx \
  --domain hok.example.com
```

The installer is idempotent for host configuration: it never overwrites an
existing file under `/etc/hok-qqbot`. It installs source trees and virtualenvs,
renders systemd units, and enables selected units. It does not start them unless
`--start` is supplied.

After the first install:

1. Replace every placeholder in `/etc/hok-qqbot/config.yaml` and `nbot.env`.
2. Review `common.env`, especially `HOK_DATABASE_DSN`, proxy variables, and
   external Redis coordinates.
   When Nginx uses a nonstandard worker account, rerun the installer with
   `--nginx-user NAME`; it grants only that account read access through the
   dedicated `hok-public` group (or `<runtime-group>-public`), which can read
   only the public artifact tree, not private configuration or history data.
3. Initialize the database once with `database/schema.sql`, using an account
   allowed to create the `hok` schema.
   On an existing installation, run
   `scripts/migrate_group_chat_history_to_postgres.py --apply` with a private
   backup directory before restarting NBot, then rerun it after the old process
   has stopped to capture any deployment-window Redis writes. The migration is
   idempotent and does not delete Redis history.
4. Install and configure NapCat separately. If required, set an `xvfb-run`
   command in `napcat.env`, install the optional module with
   `--modules napcat`, and align its reverse WebSocket token with `nbot.env`.
5. Run the checks, then start the selected services.

```bash
sudo /opt/hok-qqbot/nbot/deployment/scripts/doctor.sh
sudo systemctl restart hok-nbot.service hok-web.service
sudo systemctl start hok-temp-files-cleanup.timer
sudo systemctl reload nginx
```

Use `journalctl -u hok-nbot.service -u hok-web.service -f` for process output.
The bot's searchable HOK exception log remains under
`/var/log/hok-qqbot/nbot/error.log`.

## Chat API

Ordinary chat and the shared `ai_api` / `ai_function` helpers temporarily use
official DeepSeek Chat Completions at `https://api.deepseek.com`, with
`deepseek-flash`. The connection is direct and uses `trust_env=False`, so it does
not inherit host proxy variables. The adapter preserves tool calls, tool results,
and `reasoning_content` across the multi-round chat loop. DeepSeek thinking mode
does not support named or required tool choice, so the adapter disables thinking
only for forced workflow requests; automatic tool turns retain thinking mode.

New installations should set `HOK_CHAT_API_KEY` in the service's private
environment file. The current legacy configuration may reuse
`QQBot.deepseek_key` only when the endpoint host is exactly `api.deepseek.com`.
Local debugging also loads the Git-ignored `.env.local` beneath `BOT_PATH` when
`HOK_ENV_FILE` is not set. `ChatAPI.base_url`, `model`, `proxy_url`, and an
optional `api_key` are read from the active `config.yaml`; `HOK_CHAT_BASE_URL`,
`HOK_CHAT_MODEL`, `HOK_CHAT_PROXY_URL`, and `HOK_CHAT_API_KEY` override them.
An explicitly empty `HOK_CHAT_PROXY_URL` disables a configured proxy.

Chat web search uses OpenRouter's `openrouter:web_search` server tool. Its API
key defaults to `openrouter_api_key` in `variables_static.json`; optional
`HOK_OPENROUTER_API_KEY`, `HOK_OPENROUTER_BASE_URL`, `HOK_OPENROUTER_SEARCH_MODEL`, and
`HOK_OPENROUTER_SEARCH_ENGINE` override `OpenRouterSearch`. OpenRouter requests
use the Clash route configured by `HOK_CLASH_PROXY_URL` and never fall back to a
direct connection. The old `&` switch is not used by chat.

OpenRouter web search remains separate and continues to require the configured
Clash route. Changing ordinary chat to direct DeepSeek does not alter Steam,
APIMart, or OpenRouter routing.

Steam, APIMart, and OpenRouter search use the separate `Proxy.clash_url` route. The default template
uses `http://127.0.0.1:7890`; `socks5h://127.0.0.1:7891` is also supported. Set
`HOK_CLASH_PROXY_URL` to override it per host. These adapters disable inherited
environment proxies and fail when their dedicated Clash route is missing, so
they never silently make a direct request.

## Updating and rollback

Build and copy a new bundle, back up `/etc/hok-qqbot`, PostgreSQL, Redis, and
`/var/lib/hok-qqbot`, then rerun `install.sh` without `--start`. Run `doctor.sh`
before restarting services. For a rollback, restore the previous `/opt` source
tree and virtualenvs together; restore state only when the release changed its
schema or a migration was applied.

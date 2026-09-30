# Server modules

This layer groups the existing Aliyun deployment into three independently managed
application modules under `/srv/modules`. Each module owns its code, configuration,
state, service definitions, and Nginx route configuration. The host continues to
provide systemd, Nginx, Redis, PostgreSQL, certificate renewal, and the GitHub Actions
runner.

The module layout preserves the deployed applications and their existing CI
workflows. The separate [portable HOK installer](../README.md) remains available
for a fresh `/opt/hok-qqbot` installation; it does not automatically restore an
export made by this server-module layer.

## Layout and ownership

```text
/srv/modules/
├── hok/
│   ├── module.json
│   ├── apps/
│   │   ├── NBot/                  NoneBot source and required assets
│   │   ├── Web/                   HOK FastAPI source
│   │   └── napcat/                QQ/NapCat installation
│   ├── config/
│   │   ├── common.env             host paths and runtime configuration
│   │   ├── nbot-host.env          host CLI path and outbound proxy
│   │   ├── redis.json             Redis connection configuration
│   │   ├── config.yaml            link to the existing tracked configuration
│   │   ├── variables_static.json  link to the existing tracked configuration
│   │   └── variables_dynamic.json link to the existing tracked configuration
│   ├── data/
│   │   ├── nbot/                  link to app data (includes Git-tracked seeds)
│   │   ├── file_transfer/         shared public artifacts
│   │   └── qq-profile/            QQ login and application profile
│   ├── logs/
│   │   ├── nbot/
│   ├── backups/                  existing HOK backups, kept on the host
│   ├── systemd/
│   └── nginx/
├── personal-site/
│   ├── module.json
│   ├── apps/site/                Astro source deployment output
│   ├── public/                   published static website
│   ├── config/oauth.env          private GitHub OAuth and agent API settings
│   ├── state/                    deployment.json
│   ├── runtime/node              Node executable for the OAuth service
│   ├── systemd/
│   └── nginx/
└── clash/
    ├── module.json
    ├── apps/engine/              existing Clash application and scripts
    │   └── bin/                  existing platform-specific executables
    ├── config/                   complete former conf directory
    ├── logs/
    ├── systemd/
    └── nginx/                    only when the module has public routes
```

`NBot` and `Web` retain their physical capitalization. Do not substitute lowercase
paths from the separate `/opt` installer when editing this deployment.

The HOK configuration directory provides a single configuration entry point. The
three existing Git-managed YAML/JSON files remain in their original source tree,
with links from `config/`, so current Git updates retain their behavior. Secrets
must not be copied into public examples or new source-controlled files. Runtime
state remains in Redis, PostgreSQL, or `data/`, independently of those defaults.
The existing NBot `apps/NBot/data/` directory also contains tracked seed files;
`data/nbot` indexes that real directory. Do not reverse this link while the current
CI uses `git restore`, which would replace a tracked directory's outward link.

The historical BotDemo, Lagrange, and NapCat installer trees were removed after
the module migration was validated. Their files remain recoverable from the
verified complete HOK export, and BotDemo's Git history is retained as a bundle
under the migration backup root. They are not runtime dependencies.

## Service lifecycle

| Module | Group entry point | Managed application processes |
| --- | --- | --- |
| HOK | `hok.target` | NoneBot, HOK Web, QQ/NapCat, temporary-file cleanup |
| Personal website | `personal-site.target` | Decap OAuth and deployment-status API |
| Clash | `clash.target` | Clash proxy engine |

Each `module.json` records `name`, `target`, `members`, `shared_dependencies`,
`legacy_links`, and `portable_notes`. Its member list is authoritative for the
installed service names. Member units participate in their target's stop/restart
lifecycle through `PartOf=`; existing service names remain usable by CI.

Nginx, Redis, PostgreSQL, certificate renewal, and the Actions runner are shared
host services. They are not `PartOf=` any application target. The runner is
installed at `/srv/modules/actions-runner`; its systemd registration remains a
host integration point. Stopping HOK must not stop the Redis instance used by
PlanIt; PlanIt remains in Redis DB9.

Use the installed `modulectl` command, or Python 3.10+ with the bundled
`ops/modulectl.py` (the host's default Python may be older):

```bash
sudo modulectl status hok
sudo modulectl restart hok
sudo modulectl stop personal-site
sudo modulectl start personal-site
sudo modulectl status clash
```

Commands default to `/srv/modules`; use `--root /another/modules/path` when
inspecting a different installed root. systemd units and application configuration
still need their paths adjusted before running a relocated installation.

The targets group application processes. Stopping `personal-site.target` stops
OAuth/API handling but the shared Nginx process continues serving the published
static website. Likewise, existing HOK static artifacts can remain accessible
after the HOK processes stop. Taking a whole domain offline is a separate Nginx
configuration change. A target's active state alone is not an application health
check; inspect its member units and the relevant HTTP endpoints.

Clash has its own lifecycle. Applications configured to use its local proxy can
lose outbound connectivity while Clash is stopped, even though their own services
remain active.

## Updates and host integration

The former `/QQBot` HOK links, `/root/Napcat`, `/root/.config/QQ`, website links,
and `/clash-for-linux` were retired after their workflows, units, and runtime
configuration moved to canonical module paths. The installed manifests therefore
have an empty `legacy_links` object. `/QQBot` now contains only the independent
PlanIt and traculator applications.

Files under `/etc/systemd/system` are links to the canonical definitions in each
module's `systemd/` directory. This is required systemd host integration, not a
second service configuration. Nginx similarly includes the module-owned snippets.

The personal website remains deployed from `Raysance-Studio/personal-website`
branch `main`. Its `apps/site` directory is a downloaded production source output,
not an independent Git checkout. The workflow reads the requested commit from
`/srv/modules/personal-site/repository.git`, builds in `apps/site`, publishes
`dist/` directly to `public/`, writes deployment status, and restarts
`raysance-decap-oauth.service`. Editing the server output is not a durable source
change and can be overwritten by the next publish. HOK's Git-based deployments
also use their canonical module paths while retaining individual service names.
Changes to deployment workflows belong in their respective source repositories.

OAuth uses `CONTENT_ROOT` and `DEPLOYMENT_STATUS_FILE` from its environment when
set. Keep the config readable by its service account (`raysance-cms`) with the
existing `root:raysance-cms` ownership and mode `0640`; the application needs only
read access to the site content and deployment-status file.

## Private module exports

Export on the server, where the module directories and databases are available:

```bash
sudo modulectl export hok --quiesce --output-dir /srv/module-exports
sudo modulectl export personal-site --output-dir /srv/module-exports
sudo modulectl export clash --output-dir /srv/module-exports
```

The output is `<module>-<UTC timestamp>.tar.gz` plus a `.sha256` checksum. Each
archive contains one `<module>/` root and an `export-manifest.json`. The archive
preserves symbolic links; compatibility links and links to shared host services
must be reviewed during restoration.

Exports include application code, required assets, current configuration, and
persistent state. They are private backups: HOK data can include account mappings,
chat history, API tokens, and a QQ login profile; website configuration includes
OAuth secrets; Clash configuration can include proxy subscriptions and passwords.
Transfer archives over SSH and retain their restrictive permissions.

Rebuildable environments (`.venv`, `node_modules`), Git metadata, caches, log and
backup contents are excluded; their directory structure is retained. Compressed
runtime assets are included regardless of filename suffix. The export does not create
a disk image or copy shared Nginx/Redis/PostgreSQL installations. Runtime binaries
that are part of a module are included, but retain their original architecture and
system-library requirements.

HOK exports also create fresh snapshots:

- `snapshots/postgresql.dump`: a custom-format `pg_dump` of the HOK database.
- `snapshots/redis-db0-hok.jsonl`: only DB0 keys whose names begin with `hok:`.

The Redis snapshot starts with metadata; each following record contains
`key_b64`, `dump_b64`, `ttl_ms`, `captured_at_ms`, and `expires_at_ms`. No PlanIt DB9
keys or unrelated Redis namespaces belong in this archive. The exporter requires
a Python interpreter with the Redis client installed and a compatible `pg_dump`;
override their paths with `--snapshot-python /path/to/python` and
`--pg-dump /path/to/pg_dump` when necessary.

An online export can observe application writes while it is collecting files and
Redis records. PostgreSQL provides its own consistent database dump, but separate
file, Redis, and PostgreSQL captures do not form one cross-system transaction. For
a migration cutover requiring a common quiet point, stop the HOK target, export,
then resume it if the source host must remain in service. `--quiesce` automates
this for a fully running target: it stops only that module, exports, and restarts
it in a `finally` path even on export failure. An entirely stopped module stays
stopped; mixed or failed initial states are rejected. Shared database services
remain active. The manifest records `capture_mode` and the initial unit states.

## Restore on another Linux server

1. Verify the archive checksum and inspect `export-manifest.json` and `module.json`.
   Extract into a staging directory first. Confirm the target module does not
   contain an existing installation before placing it under `/srv/modules`.
2. Install systemd, Nginx, certificate tooling, and the required language and
   application runtimes. HOK additionally needs Redis, PostgreSQL and client tools,
   Python with venv support, its declared Python dependencies, fonts and image
   dependencies, and a compatible QQ/NapCat installation with its display/runtime
   libraries. Recreate excluded virtual environments on the destination.
   HOK's `runtime/nbot-requirements.txt` and `runtime/web-requirements.txt`
   record the installed distributions; review platform/version compatibility
   before rebuilding. The original `nb` CLI comes from the host's Python
   environment, not the NBot virtualenv; install the CLI and update `PATH` or
   adapt the startup wrapper on the destination.
3. Review all environment files, manifests, units, Nginx snippets, absolute paths,
   service users, file ownership, listening ports, domain names, and proxy settings.
   Install host integration links for systemd and Nginx, but do not recreate the
   retired `/QQBot`, `/root`, website, or Clash compatibility paths.
4. Restore HOK PostgreSQL into a prepared destination database using `pg_restore`
   with the intended owner/role. The dump does not provision cluster-level roles or
   passwords. Restore it before starting the applications. Avoid destructive
   restore options against an existing database containing useful data.
5. Restore HOK Redis records only into DB0. Base64-decode each key and DUMP payload,
   verify the decoded key begins with `hok:`, and use Redis `RESTORE`. For expiring
   keys, compute the remaining TTL from `expires_at_ms` at restore time and skip
   expired records; permanent keys use a zero TTL. Do not restart the full original
   TTL after transport. By default, handle existing-key conflicts explicitly rather
   than replacing live destination state. There is no automatic Redis restore
   command in `modulectl.py`.
6. For the website, use the bundled `public/` immediately as the published output.
   Rebuilding requires Node 22 and npm dependencies from `apps/site/package-lock.json`.
   Replace the old runner-specific `/root/.nvm/versions/node/v22.22.3` build path in
   the source workflow when provisioning a different runner. Configure OAuth with
   the destination site's origin and GitHub callback registration. Restore
   `state/deployment.json` and validate the read-only status API.
7. For Clash, install a matching engine binary if the bundled executable does not
   match the destination architecture. Validate the complete configuration,
   subscription access, local proxy/controller ports, and application proxy URLs
   before enabling the service.
8. Install/review module-owned systemd definitions and their links or drop-ins, run
   `systemd-analyze verify` on the installed units, then `systemctl daemon-reload`.
   Include the module Nginx snippets from the destination host configuration,
   provision certificates for its domains, and run `nginx -t` before reloading.
9. Start the shared dependencies, then the relevant module targets. Check every
   member's status, HOK's `/health` endpoint, the website homepage, OAuth `/healthz`
   on its local port, and a representative outbound request through Clash. For QQ,
   confirm login and OneBot connectivity; moving a saved profile may still require
   interactive login on the destination host.

Existing Aliyun runtimes include x86-64 binaries and Python environments tied to
their original interpreter/Conda installation. Those environments are not portable
by copying their directories. The module archive provides the application and
state boundary; host packages, compatible binaries, Python dependencies, service
accounts, TLS certificates, DNS, and CI-runner registration must be provisioned on
the destination. A successful archive export alone does not verify a clean-host
deployment.

## Operational validation and recovery

Keep migration-time backups on the source host until the new layout has passed
member-service checks and HTTP/QQ connectivity checks. For rollback, stop affected
application processes before restoring their previous paths and unit definitions,
then reload systemd and validate Nginx before restarting. Retired compatibility
links are not backups and are not required by the current deployment.

Use `journalctl` with the member service names for process output. Module file logs
remain under `logs/`; they are intentionally excluded from ordinary exports. The
HOK temporary-file cleanup timer must continue to target only the intended shared
temporary-artifact directory, not the full module or persistent `data/` tree.

The Aliyun adoption script creates `/srv/module-backups/<timestamp>/journal.json`
and backs up every replaced file before writing. After reviewing the journal,
an operator can revert that adoption with Python 3.10+:

```bash
/root/miniconda3/bin/python /srv/modules/bin/migrate_aliyun.py \
  --rollback /srv/module-backups/<adoption-timestamp>
```

This command stops the affected modules and temporarily pauses the deployment
runner. Do not use an `-ops` maintenance journal as an adoption rollback: those
journals only contain tool/config file backups, not original service states.
Review changes made since adoption before reverting; compatibility links are not
independent copies of data. Never run this host-specific script on a clean server
as an installer.

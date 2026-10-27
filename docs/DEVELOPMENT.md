# Development and deployment

`Raysance/GloryBond` is the only maintained application repository. Bot (`hok/`), Web (`web/`), adapters, tests, README, AGENTS, manuals and deployment methods are public. The former organization application repositories are retired. The three SDK repositories remain private and are referenced by fixed submodules.

## Local setup

Initialize dependencies with `git submodule update --init --recursive` using an SSH account authorized for `hok-player-client`, `hok-camp-client` and `react-agent-runtime`. Their implementations must never be copied into this repository or a public Actions artifact.

Python 3.12+ is required by the application syntax. The root `pyproject.toml` is the only application dependency manifest. Production shares one root `.venv`; existing local debugging uses `local_debugger/.venv`. Bot starts through `./deploy_runner.sh`, Web through `python -m web`. Importing Web does not start NoneBot.

Prepare the real root `.env` and `config.yaml` separately. Both are ignored by Git. `.env` contains keys, tokens, passwords, database DSNs and verified login sessions; `config.yaml` contains settings plus private user/account mappings. They are never public templates or part of source bundles. `HOK_ENV_FILE` and `HOK_CONFIG_FILE` can explicitly override their paths.

## Production updates

A code-only change is committed and pushed to `main`. The GloryBond Actions workflow uses the dedicated `hok-production` runner, updates the shared checkout and pinned submodules, verifies imports, restarts Bot/Web and checks startup. Existing live configuration is retained. Missing private configuration stops deployment before source changes or service restarts.

For a configuration change, back up and verify the intended local files, then synchronize them separately over SSH:

```bash
local_debugger/.venv/bin/python deployment/scripts/sync_private_config.py \
  --host <ssh-alias> --project-root /srv/modules/hok/apps/HOK_QQBot --check
local_debugger/.venv/bin/python deployment/scripts/sync_private_config.py \
  --host <ssh-alias> --project-root /srv/modules/hok/apps/HOK_QQBot
```

The tool sends contents on SSH stdin, locks against login-session writers, checks that the remote version did not change during transfer, creates a private remote backup, replaces files atomically and suppresses credential output. Synchronizing configuration does not restart services. Follow with the usual main push, or dispatch the deploy workflow if only configuration changed. Do not replace newer server login sessions with an older local copy.

## Checks and manuals

Run publication checks against the actual index with `python tools/verify_repository.py`. `--history` additionally inspects reachable history. For the one-time migration, `--inventory-source <private-backup.git>` checks against the historical credential and user inventory without storing it in Git.

Functional manuals are complete in `shared/agent/manual/`; Web guides are in `web/docs/`. Validate the manual using `python scripts/validate_agent_manual.py`. Source history/provenance is described in [RELEASE.md](RELEASE.md), and configuration ownership in [publication rules](../deployment/PUBLICATION.md).

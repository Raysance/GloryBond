# Development and deployment

`Raysance/GloryBond` is the only maintained application repository. Bot (`hok/`), Web (`web/`), adapters, tests, README, AGENTS, manuals and deployment methods are public. The former organization application repositories are retired. The three SDK repositories remain private and are referenced by fixed submodules.

## Local setup

Initialize dependencies with `git submodule update --init --recursive` using an SSH account authorized for `hok-player-client`, `hok-camp-client` and `react-agent-runtime`. Their implementations must never be copied into this repository or a public Actions artifact.

Before every commit, including documentation-only changes, run `git fetch origin main` in each of the three submodules. Both the checked-out commits and staged gitlinks must match their freshly fetched `origin/main`. Update outdated references, adapt the host if necessary, synchronize documentation and complete relevant validation before committing. Version strings and release tags alone do not establish freshness. Deployment continues to use the exact gitlinks recorded by the application commit.

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

The official game client is currently disabled with `PlayerClient.enabled=false` in local and production private configuration. This flag covers Camp routing for online status, skipping the client battle source, legacy hero routing, explicit client commands and official account checks/QR/polling. Camp and NapCat authentication remain available. Change only the intended config field on the server under the existing credentials lock; retain its current `.env`, sessions, bindings and history. Restart through the deployment workflow so existing client connections are closed. Verify the disabled paths with `local_debugger/.venv/bin/python -m unittest tests.test_player_client_disabled tests.test_account_sessions tests.test_online_status tests.test_event_hero_handlers`.

After updating the player SDK gitlink, run the host's offline compatibility tests with `local_debugger/.venv/bin/python -m unittest discover -s tests -p 'test_player_client*.py'`. Page tests construct synthetic public response models and image backgrounds; they do not depend on the SDK's research fixtures or private screenshot templates. Other report-rendering tests still require the configured local reference screenshots. Native protocol equivalence remains the SDK's responsibility.

For 1042 login notifications, also run `local_debugger/.venv/bin/python -m unittest tests.test_client_online_status tests.test_online_cache`. The SDK consumes zero results and raises `LobbyLoginLimited` for all nonzero results, including unknown codes. Host summaries preserve numeric metadata and omit server text, links and payloads. An account restriction does not count as an empty friend list. Same-APK resource versions use the existing update service; new APK/schema/authentication behavior needs SDK verification.

Run publication checks against the actual index with `python tools/verify_repository.py`. `--history` additionally inspects reachable history.

Functional manuals are complete in `shared/agent/manual/`; Web guides are in `web/docs/`. Validate the manual using `python scripts/validate_agent_manual.py`. Source history/provenance is described in [RELEASE.md](RELEASE.md), and configuration ownership in [publication rules](../deployment/PUBLICATION.md).

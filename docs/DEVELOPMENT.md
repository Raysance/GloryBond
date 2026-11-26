# Development and deployment

`Raysance/GloryBond` is the only maintained application repository. Application code lives in `src/glorybond`, with separate QQ, Web and console entry points under `apps`. Tests, tools, manuals and deployment files have their own root directories. See [architecture](ARCHITECTURE.md). The three SDK repositories remain private and are referenced by fixed submodules; import links live under `src/`.

## Local setup

Initialize dependencies with `git submodule update --init --recursive` using an SSH account authorized for `hok-player-client`, `hok-camp-client` and `react-agent-runtime`. Their implementations must never be copied into this repository or a public Actions artifact.

Before every commit, including documentation-only changes, run `git fetch origin main` in each of the three submodules. Both the checked-out commits and staged gitlinks must match their freshly fetched `origin/main`. Update outdated references, adapt the host if necessary, synchronize documentation and complete relevant validation before committing. Version strings and release tags alone do not establish freshness. Deployment continues to use the exact gitlinks recorded by the application commit.

The application, Camp SDK and their CI use Python 3.13, matching production. Other Python minor versions are not maintained as compatibility targets. The root `pyproject.toml` is the only application dependency manifest. Install it with `python -m pip install -e .` after initializing submodules. Production shares one root `.venv`; local debugging reuses `local_debugger/.venv`, created or updated with `python3.13 tools/debugger/setup_env.py --python python3.13`. Bot starts through `./deploy_runner.sh`, Web through `python -m glorybond.apps.web`, and the local chat console through `python -m glorybond.apps.console`. Importing application packages does not start NoneBot; only the QQ plugin entry registers its handlers.

Development tools run through `python -m tools.debugger <script-or-module>`, or `python tools/debugger/run.py <script-or-module>` to use the existing debug environment. Tests run with `python -m unittest discover -s tests`; Web tests are included. Frontend tests use `node tests/web/<test-name>.cjs`. Application imports always use `glorybond.*`, while private SDK imports retain their own public package names.

Prepare the real root `.env` and `config.yaml` separately. Both are ignored by Git. `.env` contains other-service keys, passwords, database DSNs and login sessions; Camp sessions are owned by its SDK in `HOK_DATA_DIR/account_sessions/camp-session.json`; `config.yaml` contains settings plus private user/account mappings. They are never public templates or part of source bundles. `HOK_ENV_FILE` and `HOK_CONFIG_FILE` can explicitly override their paths.

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

After updating the player SDK gitlink, run the host's offline compatibility tests with `local_debugger/.venv/bin/python -m unittest discover -s tests -p 'test_player_client*.py'`. Page tests construct synthetic public response models and image backgrounds; they do not depend on the SDK's research fixtures or private screenshot templates. Legacy report-rendering tests also inject synthetic backgrounds; private reference screenshots are not required by the offline suite. Native protocol equivalence remains the SDK's responsibility.

For 1042 login notifications, also run `local_debugger/.venv/bin/python -m unittest tests.test_client_online_status tests.test_online_cache`. The SDK consumes zero results and raises `LobbyLoginLimited` for all nonzero results, including unknown codes. Host summaries preserve numeric metadata and omit server text, links and payloads. An account restriction does not count as an empty friend list. Same-APK resource versions use the existing update service; new APK/schema/authentication behavior needs SDK verification.

Run publication checks against the actual index with `python tools/publication/verify_repository.py`. `--history` additionally inspects reachable history.

Functional manuals are complete in `docs/manual/`; Web guides are in `docs/web/`. Validate the manual using `python tools/maintenance/validate_agent_manual.py`. Source history/provenance is described in [RELEASE.md](RELEASE.md), and configuration ownership in [publication rules](../deployment/PUBLICATION.md).

## Camp SDK integration

Camp protocol code is owned by the private `hok-camp-client` package. Bot/Web call its named public methods through `src/glorybond/integrations/camp.py`; the application supplies only the private SDK session-file path and retains authorization, artifact storage, business transformations and presentation. No public application source contains a copy of the Camp crypto or request builders. See [Camp SDK contracts](camp-sdk.md).

Camp CI has one Python 3.13 test job with the video extra, repository checks and a build check, each run once. SDK delivery uses repository commits and the application's fixed gitlink; routine updates do not create GitHub Releases or upload distribution attachments.

After updating its gitlink, run `local_debugger/.venv/bin/python -m unittest tests.test_camp_sdk_boundary tests.test_event_live_watch tests.test_watch_lineup tests.test_watch_strength_template tests.test_wzry_pagination_request tests.test_account_sessions tests.test_battle_list_pagination tests.test_battle_watch tests.test_honor_power_query` and `local_debugger/.venv/bin/python -m unittest discover -s tests/web`. Lineup queue/receipt tests use the optional `fakeredis[lua]` test dependency. These use fixtures/mocks and must not trigger QR login or live Camp requests. The SDK separately verifies wire contracts, encryption, role normalization, rate limiting, retained-frame lifecycle and packaging.

Camp deployment runs the private SDK offline migration tool once to import the existing complete dotenv session into its private state file. It never overwrites an existing file or contacts Camp. Login switches use temporary SDK files; after verification and lease checks the SDK performs a version-checked atomic replacement. Bot/Web only call `reload_session` and never deserialize tokens. Back up this SDK-owned private file separately with other runtime state; never put it under public artifacts.

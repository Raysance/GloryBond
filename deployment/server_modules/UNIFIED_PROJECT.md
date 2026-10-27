# Bot/Web unified project

The sole development and release repository is `Raysance/GloryBond`. Bot remains in `hok/`, Web in `web/`. Their original application histories have been sanitized and imported with original commit messages; the former `Raysance-Studio/HOK_QQBot` and `HOK_QQBot_Web` repositories are retired archives. Private SDKs remain fixed submodules.

The production checkout remains `/srv/modules/hok/apps/HOK_QQBot`. Both `hok-nbot.service` and `hok-web.service` share this checkout, the root `.venv` and the real root `.env` / `config.yaml`. These files are ignored and transferred separately via SSH; no live settings are in Git. `hok.target`, NapCat, Redis DB0, PostgreSQL and public artifact paths retain their roles.

The dedicated GloryBond `hok-production` runner executes the root Actions workflow. It fetches main from GloryBond, preserves both private files, synchronizes SDK pins, checks imports, restarts both application services and verifies startup. The separate organization runner used by other projects is unchanged. A missing configuration file stops the release before source changes or service restarts.

For a new server use `deployment/README.md`; for configuration synchronization use `docs/DEVELOPMENT.md`. Keep private repository bundles and live configuration backups outside the checkout. A source rollback uses a sanitized GloryBond commit through `deployment/scripts/deploy_project.sh`; restoring private configuration is a separate, explicit action. Do not point origin back to a retired repository or import its unsanitized Git history.

Verify with the focused test suites in `tests/`, `web/tests/` and `deployment/server_modules/`, the private-configuration deployment tests under `deployment/tests/`, and `tools/verify_repository.py`. None of the verification commands should send test messages or request paid model content.

# Public snapshot development

This repository contains the public NBot/Web source snapshot and user documentation. Source revision identifiers are recorded in [RELEASE.md](RELEASE.md). Deployment credentials, personal mappings, runtime records, private server operations and newly generated binary assets are excluded.

## Agent dependency

`NBot/vendor/react-agent-runtime` remains a private Git submodule, pinned to the source application's recorded commit. The public snapshot exports its reference and the relative `NBot/agent_runtime` compatibility link, **not the private runtime implementation**. Running the AI agent requires authorized access to that dependency. Ordinary clones and public CodeQL checkout do not automatically retrieve it.

If you have access, initialize it with `git submodule update --init NBot/vendor/react-agent-runtime`. Do not replace the pinned commit with an unverified public package of the same name. Other business code, external adapters, tool schemas, manual documents and Web templates remain visible for inspection.

## Configuration and data

Prepare your own `NBot/.env` and `NBot/config.yaml`, or point `HOK_ENV_FILE` and `HOK_CONFIG_FILE` at private files. These two files are the application's sole credential and non-secret settings sources; this public repository intentionally provides no live configuration, user list or extra example configuration files. Follow `NBot/AGENTS.md` for the configuration interfaces and integration boundaries, subject to the public safety rules in the root `AGENTS.md`.

Sample payload files preserve field structure with empty strings and zero values. They are schema references, not playable match histories. Public district data and previously published demonstration assets are included; private screenshots, chat attachments and live exports are not copied.

The public mirror removes configured credential literals from Python fallback strings and anonymizes deployment identity literals. Configure required database and API credentials explicitly; do not expect any production default password.

## Updating the public mirror

Use `tools/sync_public_snapshot.py --nbot <source checkout> --web <source checkout>` to inspect the planned sync, then add `--apply` after review. Run it with the source project's existing local-debugger Python environment, which provides PyYAML and python-dotenv. It copies only tracked source files from clean mirror directories, omits deployment/configuration/runtime data, redacts sample values and identity literals, rejects remaining configured credential values, and preserves the private runtime dependency reference. Review changes to README and public governance documents separately.

After updating, review the staged tree for ignored or private files, validate Python/JS syntax and local documentation links, and run `NBot/scripts/validate_agent_manual.py` from `NBot/` with the source virtual environment. The mirror's copied tests may require your own configuration and authorized agent runtime checkout; public checkout alone is not a turnkey deployment.

Before publishing, stage the reviewed snapshot and run `tools/verify_public_snapshot.py --nbot-private-source <source checkout>`. It checks the actual Git index for excluded files, configured credential and identity literals, empty sample values and the private dependency reference. It does not output secret values or include dependency contents in the published tree.

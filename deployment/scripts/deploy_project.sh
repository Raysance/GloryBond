#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(pwd)"
cd "$project_root"
export BOT_PATH="$project_root"
export WEB_PATH="$project_root/web"
export HOK_ENV_FILE="$project_root/.env"
export HOK_CONFIG_FILE="$project_root/config.yaml"
export HOK_DATA_DIR="$project_root/data"
export HOK_FILE_TRANSFER_DIR="$project_root/file_transfer"
export HOK_LOG_DIR="$project_root/log"
revision="${1:-origin/main}"
git fetch origin main
for private_file in .env config.yaml; do
    if [[ ! -r "$private_file" ]]; then
        printf 'HOK_DEPLOY_ERROR: sync private configuration before deploying\n' >&2
        exit 66
    fi
done
install_dependencies=false
if ! git diff --quiet HEAD "$revision" -- pyproject.toml || [[ ! -x .venv/bin/nb ]]; then
    install_dependencies=true
fi
git show "$revision":deployment/scripts/restore_application.sh | bash -s -- . "$revision"
if [[ "$install_dependencies" == true ]]; then
    .venv/bin/python -m pip install --no-build-isolation --editable .
fi
.venv/bin/python -c 'from agent_runtime import AgentRuntime; from qq_agent import QQAgentService; from hok_research import HokClient; from hok_camp_client import CampClient; import login_console.worker; import web.app'
systemctl restart hok-nbot.service hok-web.service
.venv/bin/python deployment/scripts/verify_startup.py

#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_root="${BOT_PATH:-$script_dir}"
venv_dir="${HOK_NBOT_VENV:-$project_root/.venv}"
nb_bin="${HOK_NB_BIN:-$venv_dir/bin/nb}"
log_dir="${HOK_LOG_DIR:-$project_root/log}"

if [[ ! -x "$nb_bin" ]]; then
    printf 'HOK_NBOT_START_ERROR: executable not found: %s\n' "$nb_bin" >&2
    exit 127
fi

mkdir -p "$log_dir"
cd "$project_root"
export BOT_PATH="$project_root"
export RUNNER_TRACKING_ID=0

exec "$nb_bin" run

#!/usr/bin/env bash
set -Eeuo pipefail

project_root="${BOT_PATH:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
config_file="${HOK_CONFIG_FILE:-$project_root/config.yaml}"
python_bin="${HOK_NBOT_PYTHON:-$project_root/.venv/bin/python}"

if [[ ! -x "$python_bin" || ! -r "$config_file" ]]; then
    printf 'HOK_NAPCAT_START_ERROR: config or Python runtime is unavailable\n' >&2
    exit 64
fi

napcat_command="$($python_bin - "$config_file" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    config = yaml.safe_load(stream) or {}
print(str((config.get("NapCat") or {}).get("command") or ""))
PY
)"
if [[ -z "$napcat_command" ]]; then
    printf 'HOK_NAPCAT_START_ERROR: NapCat.command is not configured\n' >&2
    exit 64
fi

exec /bin/bash -lc "$napcat_command"

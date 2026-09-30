#!/usr/bin/env bash
set -Eeuo pipefail

config_dir="/etc/hok-qqbot"
while (($#)); do
    case "$1" in
        --config-dir) config_dir="$2"; shift 2 ;;
        -h|--help)
            printf 'Usage: deployment/scripts/doctor.sh [--config-dir PATH]\n'
            exit 0
            ;;
        *) printf 'HOK_DOCTOR_ERROR: unknown option: %s\n' "$1" >&2; exit 64 ;;
    esac
done

failures=0
ok() { printf 'OK    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }

common_env="$config_dir/common.env"
if [[ ! -r "$common_env" ]]; then
    fail "missing readable $common_env"
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$common_env"
set +a

required_files=(
    "$config_dir/nbot.env"
    "$HOK_CONFIG_FILE"
    "$HOK_STATIC_VARIABLES_FILE"
    "$HOK_DYNAMIC_VARIABLES_FILE"
    "$REDIS_CONF"
)
for file in "${required_files[@]}"; do
    if [[ -r "$file" ]]; then
        ok "readable config: $file"
    else
        fail "missing readable config: $file"
    fi
done

if grep -RqsE 'replace-me|replace-with-a-random' "$HOK_CONFIG_FILE" "$config_dir/nbot.env"; then
    fail "placeholder secrets remain in $config_dir"
else
    ok "configuration placeholders replaced"
fi

for dir in "$BOT_PATH" "$WEB_PATH" "$HOK_DATA_DIR" "$HOK_FILE_TRANSFER_DIR" "$HOK_LOG_DIR"; do
    if [[ -d "$dir" ]]; then
        ok "directory exists: $dir"
    else
        fail "directory missing: $dir"
    fi
done

nbot_python="$BOT_PATH/.venv/bin/python"
if [[ -x "$nbot_python" && -x "$BOT_PATH/.venv/bin/nb" ]]; then
    if "$nbot_python" -c 'import nonebot, redis, psycopg' >/dev/null 2>&1; then
        ok "NBot virtualenv imports"
    else
        fail "NBot virtualenv cannot import required modules"
    fi
else
    fail "NBot virtualenv is incomplete"
fi

web_python="$WEB_PATH/.venv/bin/python"
if [[ -x "$web_python" ]]; then
    if "$web_python" -m py_compile "$WEB_PATH/app.py" "$WEB_PATH/runtime_config.py"; then
        ok "Web source compiles"
    else
        fail "Web source compile failed"
    fi
else
    fail "Web virtualenv is incomplete"
fi

if [[ -x "$nbot_python" && -r "$REDIS_CONF" ]]; then
    if "$nbot_python" - "$REDIS_CONF" <<'PY'
import json
import sys
import redis

with open(sys.argv[1], encoding="utf-8") as config_file:
    config = json.load(config_file)
client = redis.Redis(
    host=config["REDIS_HOST"],
    port=int(config["REDIS_PORT"]),
    db=int(config["REDIS_DB"]),
    socket_timeout=2,
)
raise SystemExit(0 if client.ping() else 1)
PY
    then
        ok "Redis DB0 is reachable"
    else
        fail "Redis DB0 is unreachable"
    fi
fi

if command -v psql >/dev/null 2>&1; then
    if psql "$HOK_DATABASE_DSN" -Atqc 'SELECT 1' >/dev/null 2>&1; then
        ok "PostgreSQL is reachable"
    else
        fail "PostgreSQL is unreachable"
    fi
else
    warn "psql is unavailable; skipped PostgreSQL connectivity check"
fi

if command -v systemctl >/dev/null 2>&1; then
    for unit in hok-napcat.service hok-nbot.service hok-web.service hok-temp-files-cleanup.timer; do
        if systemctl cat "$unit" >/dev/null 2>&1; then
            if systemctl is-active --quiet "$unit"; then
                ok "$unit is active"
            else
                warn "$unit is installed but inactive"
            fi
        fi
    done
fi

if command -v curl >/dev/null 2>&1; then
    if curl --fail --silent --max-time 3 \
        "http://${HOK_WEB_HOST:-127.0.0.1}:${HOK_WEB_PORT:-8000}/health" >/dev/null; then
        ok "Web /health responds"
    else
        warn "Web /health is not responding"
    fi
fi

if ((failures)); then
    printf 'HOK doctor found %d blocking issue(s).\n' "$failures" >&2
    exit 1
fi
printf 'HOK doctor completed without blocking issues.\n'

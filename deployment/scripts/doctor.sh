#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
bot_path="$(CDPATH= cd -- "$script_dir/../.." && pwd)"
while (($#)); do
    case "$1" in
        --bot-path) bot_path="$2"; shift 2 ;;
        -h|--help)
            printf 'Usage: deployment/scripts/doctor.sh [--bot-path PATH]\n'
            exit 0
            ;;
        *) printf 'HOK_DOCTOR_ERROR: unknown option: %s\n' "$1" >&2; exit 64 ;;
    esac
done

failures=0
ok() { printf 'OK    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }

credential_file="$bot_path/.env"
if [[ ! -r "$credential_file" ]]; then
    fail "missing readable $credential_file"
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$credential_file"
set +a

BOT_PATH="${BOT_PATH:-$bot_path}"
WEB_PATH="${WEB_PATH:-$BOT_PATH/web}"
HOK_CONFIG_FILE="${HOK_CONFIG_FILE:-$BOT_PATH/config.yaml}"
HOK_DATA_DIR="${HOK_DATA_DIR:-$BOT_PATH/data}"
HOK_FILE_TRANSFER_DIR="${HOK_FILE_TRANSFER_DIR:-$BOT_PATH/file_transfer}"
HOK_LOG_DIR="${HOK_LOG_DIR:-$BOT_PATH/log}"

required_files=(
    "$BOT_PATH/.env"
    "$HOK_CONFIG_FILE"
)
for file in "${required_files[@]}"; do
    if [[ -r "$file" ]]; then
        ok "readable config: $file"
    else
        fail "missing readable config: $file"
    fi
done

if grep -RqsE 'replace-me|replace-with-a-random' "$HOK_CONFIG_FILE" "$BOT_PATH/.env"; then
    fail "configuration placeholders remain"
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

web_python="$nbot_python"
if [[ -x "$web_python" ]]; then
    if "$web_python" -m py_compile "$WEB_PATH/app.py" "$WEB_PATH/runtime_config.py"; then
        ok "Web source compiles in the shared virtualenv"
    else
        fail "Web source compile failed"
    fi
else
    fail "Web virtualenv is incomplete"
fi

if [[ -x "$nbot_python" && -r "$HOK_CONFIG_FILE" ]]; then
    if "$nbot_python" - "$HOK_CONFIG_FILE" <<'PY'
import sys
import redis
import yaml

with open(sys.argv[1], encoding="utf-8") as config_file:
    config = (yaml.safe_load(config_file) or {})["Redis"]
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

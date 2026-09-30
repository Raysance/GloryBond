#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -z "${HOK_NAPCAT_COMMAND:-}" ]]; then
    printf 'HOK_NAPCAT_START_ERROR: HOK_NAPCAT_COMMAND is not configured\n' >&2
    exit 64
fi

exec /bin/bash -lc "$HOK_NAPCAT_COMMAND"

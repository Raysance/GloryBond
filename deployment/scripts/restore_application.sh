#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="${1:-.}"
revision="${2:-origin/main}"
cd "$project_dir"

# Determine removed tracked source files before reset makes them untracked.
# History is runtime data; the former copied engine has its own backup step.
git diff --no-renames --name-only --diff-filter=D -z HEAD "$revision" -- . \
    ':(exclude)data/history' ':(exclude)agent_runtime' |
    while IFS= read -r -d '' removed_path; do
        if [[ -f "$removed_path" || -L "$removed_path" ]]; then
            rm -- "$removed_path"
        fi
    done
git reset --mixed "$revision"
git restore --source="$revision" --worktree -- . \
    ':(exclude)data/history' ':(exclude)agent_runtime'
bash deployment/scripts/sync_agent_runtime.sh . "$revision"

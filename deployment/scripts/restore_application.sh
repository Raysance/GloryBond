#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="${1:-.}"
revision="${2:-origin/main}"
cd "$project_dir"
for private_file in .env config.yaml; do
    if [[ ! -r "$private_file" ]]; then
        printf 'HOK_DEPLOY_ERROR: sync private configuration before deploying\n' >&2
        exit 66
    fi
done

# Determine removed tracked source files before reset makes them untracked.
# History is runtime data; the former copied engine has its own backup step.
git diff --no-renames --name-only --diff-filter=D -z HEAD "$revision" -- . \
    ':(exclude)data/history' ':(exclude)agent_runtime' ':(exclude).env' ':(exclude)config.yaml' |
    while IFS= read -r -d '' removed_path; do
        if [[ -f "$removed_path" || -L "$removed_path" ]]; then
            rm -- "$removed_path"
        fi
    done
git reset --mixed "$revision"
git restore --source="$revision" --worktree -- . \
    ':(exclude)data/history' ':(exclude)agent_runtime' ':(exclude).env' ':(exclude)config.yaml'
bash deployment/scripts/sync_agent_runtime.sh . "$revision"

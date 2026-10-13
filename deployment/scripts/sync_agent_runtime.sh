#!/usr/bin/env bash
set -Eeuo pipefail

# Run after restoring the new parent revision except agent_runtime. Preserve
# the old copied package (including ignored caches) before installing the link.
project_dir="${1:-.}"
revision="${2:-HEAD}"
cd "$project_dir"
if [[ -d agent_runtime && ! -L agent_runtime ]]; then
    mkdir -p log/deployment-backups
    backup_dir="$(mktemp -d log/deployment-backups/agent-runtime.XXXXXX)"
    mv agent_runtime "$backup_dir/agent_runtime"
fi
git restore --source="$revision" --worktree -- agent_runtime
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10"
git submodule sync --recursive
git submodule update --init --recursive
test -f vendor/react-agent-runtime/src/agent_runtime/__init__.py
test -L agent_runtime

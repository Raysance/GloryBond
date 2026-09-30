#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: deployment/scripts/build_bundle.sh [options]

Options:
  --web-source PATH        HOK_QQBot_Web source directory
  --output PATH            Output .tar.gz path
  -h, --help               Show this help
EOF
}

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
deployment_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
nbot_source="$(CDPATH= cd -- "$deployment_root/.." && pwd)"
web_source=""
output_path=""

while (($#)); do
    case "$1" in
        --web-source) web_source="$2"; shift 2 ;;
        --output) output_path="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'HOK_BUNDLE_ERROR: unknown option: %s\n' "$1" >&2; exit 64 ;;
    esac
done

if [[ -z "$web_source" ]]; then
    candidate="$nbot_source/../HOK_QQBot_Web"
    if [[ -f "$candidate/app.py" && -f "$candidate/requirements.txt" ]]; then
        web_source="$(CDPATH= cd -- "$candidate" && pwd)"
    fi
fi
if [[ -z "$web_source" || ! -f "$web_source/app.py" ]]; then
    printf 'HOK_BUNDLE_ERROR: provide --web-source for HOK_QQBot_Web\n' >&2
    exit 66
fi

version="$(git -C "$nbot_source" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
if [[ -z "$output_path" ]]; then
    output_path="$nbot_source/dist/hok-qqbot-$version.tar.gz"
fi
mkdir -p "$(dirname -- "$output_path")"
output_path="$(CDPATH= cd -- "$(dirname -- "$output_path")" && pwd)/$(basename -- "$output_path")"

stage_root="$(mktemp -d)"
trap 'rm -rf -- "$stage_root"' EXIT
bundle_root="$stage_root/hok-qqbot-$version"
mkdir -p "$bundle_root/nbot" "$bundle_root/web"

copy_source() {
    local source_dir="$1"
    local target_dir="$2"
    tar -C "$source_dir" \
        --exclude='.git' --exclude='.venv' \
        --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='.DS_Store' --exclude='log' --exclude='file_transfer' \
        --exclude='dist' --exclude='deployment' --exclude='local_debugger/.venv' \
        --exclude='data/history/*' --exclude='data/herotier/*' \
        --exclude='data/herorank/*' --exclude='data/news/*' \
        --exclude='resources/wzry_images/hero_avatars/*' \
        --exclude='resources/wzry_images/generated/*' \
        --exclude='resources/wzry_images/kpl/*' \
        --exclude='resources/wzry_images/tmp/*' \
        -cf - . | tar -C "$target_dir" -xf -
}

copy_source "$nbot_source" "$bundle_root/nbot"
copy_source "$web_source" "$bundle_root/web"
cp -a "$deployment_root" "$bundle_root/deployment"

tar -C "$stage_root" -czf "$output_path" "$(basename -- "$bundle_root")"
chmod 0600 "$output_path"

printf 'Bundle: %s\n' "$output_path"
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$output_path"
else
    shasum -a 256 "$output_path"
fi

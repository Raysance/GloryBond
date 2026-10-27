#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: sudo deployment/scripts/install.sh [options]

Options:
  --prefix PATH          Stack code root (default: /opt/hok-qqbot)
  --state-dir PATH       Persistent state root (default: /var/lib/hok-qqbot)
  --log-dir PATH         Runtime log root (default: /var/log/hok-qqbot)
  --user NAME            Runtime user (default: hok)
  --group NAME           Runtime group (default: same as user)
  --modules LIST         Comma-separated nbot,web,napcat,cleanup,nginx
                         (default: nbot,web,cleanup)
  --domain NAME          Nginx server_name (required with nginx module)
  --nginx-user NAME      Nginx worker user (auto-detected if omitted)
  --python PATH          Python interpreter (default: python3)
  --skip-python          Do not create the shared virtualenv or install Python packages
  --start                Enable and start installed modules after validation
  -h, --help             Show this help
EOF
}

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
deployment_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
source_parent="$(CDPATH= cd -- "$deployment_root/.." && pwd)"

if [[ -f "$source_parent/pyproject.toml" ]]; then
    nbot_source="$source_parent"
else
    printf 'HOK_INSTALL_ERROR: cannot locate the NBot source tree\n' >&2
    exit 66
fi

prefix="/opt/hok-qqbot"
state_dir="/var/lib/hok-qqbot"
log_dir="/var/log/hok-qqbot"
run_user="hok"
run_group=""
modules="nbot,web,cleanup"
server_name=""
nginx_user=""
python_bin="python3"
skip_python=false
start_services=false

while (($#)); do
    case "$1" in
        --prefix) prefix="$2"; shift 2 ;;
        --state-dir) state_dir="$2"; shift 2 ;;
        --log-dir) log_dir="$2"; shift 2 ;;
        --user) run_user="$2"; shift 2 ;;
        --group) run_group="$2"; shift 2 ;;
        --modules) modules="$2"; shift 2 ;;
        --domain) server_name="$2"; shift 2 ;;
        --nginx-user) nginx_user="$2"; shift 2 ;;
        --python) python_bin="$2"; shift 2 ;;
        --skip-python) skip_python=true; shift ;;
        --start) start_services=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'HOK_INSTALL_ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done

run_group="${run_group:-$run_user}"
public_group="${run_group}-public"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    printf 'HOK_INSTALL_ERROR: run this installer as root\n' >&2
    exit 77
fi

for path in "$prefix" "$state_dir" "$log_dir"; do
    if [[ -z "$path" || "$path" == "/" ]]; then
        printf 'HOK_INSTALL_ERROR: unsafe target path: %s\n' "$path" >&2
        exit 64
    fi
done

has_module() {
    [[ ",$modules," == *",$1,"* ]]
}

for requested in ${modules//,/ }; do
    case "$requested" in
        nbot|web|napcat|cleanup|nginx) ;;
        *) printf 'HOK_INSTALL_ERROR: unsupported module: %s\n' "$requested" >&2; exit 64 ;;
    esac
done

if has_module web && [[ ! -f "$nbot_source/web/app.py" ]]; then
    printf 'HOK_INSTALL_ERROR: unified web source is missing\n' >&2
    exit 66
fi
if has_module nginx && [[ -z "$server_name" ]]; then
    printf 'HOK_INSTALL_ERROR: nginx module requires --domain\n' >&2
    exit 64
fi

if ! getent group "$run_group" >/dev/null; then
    groupadd --system "$run_group"
fi
if ! getent group "$public_group" >/dev/null; then
    groupadd --system "$public_group"
fi
if ! id "$run_user" >/dev/null 2>&1; then
    nologin_bin="$(command -v nologin || printf '/bin/false')"
    useradd --system --gid "$run_group" --home-dir "$state_dir" --shell "$nologin_bin" "$run_user"
fi

nbot_root="$prefix"
web_root="$prefix/web"
file_transfer_dir="$state_dir/file_transfer"
find_bin="$(command -v find)"

install -d -o root -g "$run_group" -m 0750 "$prefix"
install -d -o "$run_user" -g "$run_group" -m 0750 \
    "$state_dir" "$state_dir/data" "$state_dir/data/agent_inputs" "$state_dir/data/history" \
    "$state_dir/data/history/battles" "$state_dir/data/history/personal" \
    "$state_dir/data/history/power" "$state_dir/data/history/power_failed" \
    "$state_dir/data/herorank" "$state_dir/data/herotier" "$state_dir/data/news" \
    "$state_dir/backups/redis" "$file_transfer_dir" "$file_transfer_dir/temp_files" \
    "$log_dir" "$log_dir/nbot"

copy_tree() {
    local source_dir="$1"
    local target_dir="$2"
    if [[ "$(realpath -m "$source_dir")" == "$(realpath -m "$target_dir")" ]]; then
        return
    fi
    install -d -m 0755 "$target_dir"
    tar -C "$source_dir" \
        --exclude='.git' --exclude='.venv' --exclude='.local' \
        --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='.DS_Store' --exclude='._*' --exclude='log' --exclude='file_transfer' \
        --exclude='data/history/*' --exclude='data/herotier/*' \
        --exclude='data/herorank/*' --exclude='data/news/*' \
        --exclude='build' --exclude='dist' --exclude='*.egg-info' --exclude='local_debugger/.venv' \
        --exclude='data/automation_media' --exclude='data/agent_inputs' --exclude='data/player_client' --exclude='data/account_sessions' \
        --exclude='resources/wzry_images/hero_avatars/*' \
        --exclude='resources/wzry_images/generated/*' \
        --exclude='resources/wzry_images/kpl/*' \
        --exclude='resources/wzry_images/tmp/*' \
        -cf - . | tar -C "$target_dir" --no-same-owner -xf -
}

if has_module nbot || has_module web || has_module cleanup || has_module napcat; then
    if [[ ! -f "$nbot_source/vendor/hok-camp-client/src/hok_camp_client/__init__.py" || ! -f "$nbot_source/vendor/react-agent-runtime/src/agent_runtime/__init__.py" || ! -f "$nbot_source/vendor/hok-player-client/src/hok_research/__init__.py" ]]; then
        printf 'HOK_INSTALL_ERROR: agent submodule source is missing\n' >&2
        exit 66
    fi
    if [[ -d "$nbot_root/agent_runtime" && ! -L "$nbot_root/agent_runtime" ]]; then
        backup_dir="$(mktemp -d "$state_dir/backups/agent-runtime.XXXXXX")"
        mv "$nbot_root/agent_runtime" "$backup_dir/agent_runtime"
    fi
    copy_tree "$nbot_source" "$nbot_root"
    copy_tree "$deployment_root" "$nbot_root/deployment"
    chmod 0755 "$nbot_root/deploy_runner.sh" "$nbot_root/deployment/bin/run-napcat.sh"
    install -d -o "$run_user" -g "$run_group" -m 0750 \
        "$nbot_root/resources/wzry_images/hero_avatars" \
        "$nbot_root/resources/wzry_images/generated" \
        "$nbot_root/resources/wzry_images/kpl" \
        "$nbot_root/resources/wzry_images/tmp"
    chown -R "$run_user:$run_group" "$nbot_root/resources/wzry_images"
fi

render_template() {
    local source_file="$1"
    local target_file="$2"
    sed \
        -e "s|@STACK_ROOT@|$prefix|g" \
        -e "s|@NBOT_ROOT@|$nbot_root|g" \
        -e "s|@WEB_ROOT@|$web_root|g" \
        -e "s|@STATE_DIR@|$state_dir|g" \
        -e "s|@LOG_DIR@|$log_dir|g" \
        -e "s|@RUN_USER@|$run_user|g" \
        -e "s|@RUN_GROUP@|$run_group|g" \
        -e "s|@FILE_TRANSFER_DIR@|$file_transfer_dir|g" \
        -e "s|@NAPCAT_RUNNER@|$nbot_root/deployment/bin/run-napcat.sh|g" \
        -e "s|@FIND_BIN@|$find_bin|g" \
        -e "s|@SERVER_NAME@|$server_name|g" \
        -e 's|@WEB_PORT@|8000|g' \
        "$source_file" > "$target_file"
}

chmod 0600 "$nbot_root/.env"
chmod 0640 "$nbot_root/config.yaml"

if [[ -d "$nbot_source/data/honor" ]]; then
    install -d -o "$run_user" -g "$run_group" -m 0750 "$state_dir/data/honor"
    cp -a "$nbot_source/data/honor/." "$state_dir/data/honor/"
fi
chown -R "$run_user:$run_group" "$state_dir" "$log_dir"

# Nginx may traverse the state root and read only public artifacts. Keeping it
# out of the application group prevents access to private configuration/data.
chown "$run_user:$public_group" "$state_dir"
chmod 0710 "$state_dir"
chgrp -hR "$public_group" "$file_transfer_dir"
find "$file_transfer_dir" -type d -exec chmod g+rx,g+s,o-rwx {} +
find "$file_transfer_dir" -type f -exec chmod g+r,o-rwx {} +

if [[ "$skip_python" == false ]]; then
    command -v "$python_bin" >/dev/null || {
        printf 'HOK_INSTALL_ERROR: Python executable not found: %s\n' "$python_bin" >&2
        exit 69
    }
    if has_module nbot || has_module web; then
        "$python_bin" -m venv "$nbot_root/.venv"
        "$nbot_root/.venv/bin/python" -m pip install --upgrade pip
        "$nbot_root/.venv/bin/python" -m pip install "$nbot_root"
        "$nbot_root/.venv/bin/python" -c 'from agent_runtime import AgentRuntime, ModelRequest; from qq_agent import QQAgentService'
        if [[ ! -x "$nbot_root/.venv/bin/nb" ]]; then
            printf 'HOK_INSTALL_ERROR: nb-cli did not install %s/.venv/bin/nb\n' "$nbot_root" >&2
            exit 69
        fi
        "$nbot_root/.venv/bin/nb" --help >/dev/null
    fi

fi

install_unit() {
    local unit_name="$1"
    local template_name="$2"
    render_template "$deployment_root/systemd/$template_name" "/etc/systemd/system/$unit_name"
    chmod 0644 "/etc/systemd/system/$unit_name"
}

installed_units=()
if has_module nbot; then
    install_unit hok-nbot.service hok-nbot.service.in
    installed_units+=(hok-nbot.service)
fi
if has_module web; then
    install_unit hok-web.service hok-web.service.in
    installed_units+=(hok-web.service)
fi
if has_module napcat; then
    install_unit hok-napcat.service hok-napcat.service.in
    installed_units+=(hok-napcat.service)
fi
if has_module cleanup; then
    install_unit hok-temp-files-cleanup.service hok-temp-files-cleanup.service.in
    install -m 0644 "$deployment_root/systemd/hok-temp-files-cleanup.timer" \
        /etc/systemd/system/hok-temp-files-cleanup.timer
    installed_units+=(hok-temp-files-cleanup.timer)
fi

if has_module nginx; then
    if [[ -z "$nginx_user" ]]; then
        for candidate in nginx www-data; do
            if id "$candidate" >/dev/null 2>&1; then
                nginx_user="$candidate"
                break
            fi
        done
    fi
    if [[ -z "$nginx_user" ]]; then
        printf 'HOK_INSTALL_ERROR: cannot detect Nginx user; pass --nginx-user\n' >&2
        exit 65
    fi
    usermod -a -G "$public_group" "$nginx_user"
    install -d -m 0755 /etc/nginx/conf.d
    nginx_target="/etc/nginx/conf.d/hok-qqbot.conf"
    render_template "$deployment_root/nginx/hok.conf.in" "$nginx_target"
    nginx -t
fi

systemctl daemon-reload
for unit in "${installed_units[@]}"; do
    systemctl enable "$unit"
done

if [[ "$start_services" == true ]]; then
    for unit in hok-napcat.service hok-nbot.service hok-web.service hok-temp-files-cleanup.timer; do
        if [[ " ${installed_units[*]} " == *" $unit "* ]]; then
            systemctl restart "$unit"
        fi
    done
    if has_module nginx; then
        systemctl restart nginx
    fi
fi

printf 'HOK install complete. Review %s/.env and %s/config.yaml, then run:\n' "$nbot_root" "$nbot_root"
printf '  %s/deployment/scripts/doctor.sh --bot-path %s\n' "$nbot_root" "$nbot_root"

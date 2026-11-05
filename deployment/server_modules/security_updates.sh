#!/usr/bin/env bash
# Root-owned, host-configured maintenance using vendor DNF repositories.
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export LANG=C
umask 077

config=/etc/glorybond-maintenance/config.sh
[[ -f "$config" && ! -L "$config" && $(stat -c %u "$config") == 0 ]]
[[ $(stat -c %a "$config") == 600 ]]
# This is a private, root-owned host configuration, never application input.
# shellcheck source=/dev/null
source "$config"
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/maintenance.lock"
flock -n 9 || exit 0
mode=${1:---check}
os_repos=(--disablerepo='*')
for repo in "${OS_REPOS[@]}"; do os_repos+=("--enablerepo=$repo"); done
common=(--setopt=timeout=20 --setopt=retries=1)
pg_repos=(--disablerepo='*' --enablerepo=pgdg16 --enablerepo=pgdg-common --disableplugin=releasever_adapter --releasever=8.10)

status() {
    printf '%s %s\n' "$(date -Iseconds)" "$*" | tee "$STATE_DIR/status.tmp"
    mv "$STATE_DIR/status.tmp" "$STATE_DIR/status"
}

health() {
    local unit i code
    nginx -t || return 1
    sshd -t || return 1
    for unit in "${CRITICAL_UNITS[@]}"; do systemctl is-active --quiet "$unit" || return 1; done
    for i in "${!HEALTH_URLS[@]}"; do
        code=$(curl --noproxy '*' --silent --show-error --max-time 15 \
            "${CURL_RESOLVE[@]}" -o /dev/null -w '%{http_code}' "${HEALTH_URLS[$i]}") || return 1
        [[ "$code" == "${HEALTH_CODES[$i]}" ]] || return 1
    done
    redis-cli ping | grep -qx PONG || return 1
    runuser -u postgres -- /usr/pgsql-16/bin/psql -XAtqc 'SELECT 1' | grep -qx 1
}

preflight() {
    # Never overlap deployment jobs or continue from an already unhealthy host.
    ! pgrep -f '[/]Runner.Worker' >/dev/null || return 1
    health || return 1
    local free_bytes
    free_bytes=$(df -B1 --output=avail "$STATE_DIR" | tail -1)
    ((free_bytes >= MIN_FREE_BYTES))
}

backup() {
    local pending="$STATE_DIR/backup.pending"
    # Keep the previous completed restore point until a new one is complete.
    rm -rf -- "$pending"
    mkdir -m 700 "$pending"
    rpm -qa | sort >"$pending/packages.txt"
    grubby --default-kernel >"$pending/default-kernel.txt"
    tar -czf "$pending/config.tar.gz" -- "${BACKUP_PATHS[@]}"
    runuser -u postgres -- /usr/pgsql-16/bin/pg_dumpall | gzip >"$pending/postgresql.sql.gz"
    gzip -t "$pending/postgresql.sql.gz"
    redis-cli --rdb "$pending/redis.rdb"
    redis-check-rdb "$pending/redis.rdb" >"$pending/redis-check.txt"
    rm -rf -- "$STATE_DIR/backup.previous"
    if [[ -d "$STATE_DIR/backup.latest" ]]; then
        mv "$STATE_DIR/backup.latest" "$STATE_DIR/backup.previous"
    fi
    mv "$pending" "$STATE_DIR/backup.latest"
    # The new config and database restore point has passed validation.
    rm -rf -- "$STATE_DIR/backup.previous"
}

candidate_check() {
    local result=0
    dnf -q "${common[@]}" check-update "$@" >"$STATE_DIR/candidates.txt" 2>&1 || result=$?
    [[ $result == 0 || $result == 100 ]] || return 1
    [[ $result == 100 ]] && changes=1
    return 0
}

rollback_node() {
    if [[ ${node_changed:-0} == 1 && -f "$NODE_BINARY.previous" ]]; then
        cp -p "$NODE_BINARY.previous" "$NODE_BINARY.rollback"
        mv -f "$NODE_BINARY.rollback" "$NODE_BINARY"
        systemctl restart "$NODE_SERVICE" || true
    fi
}

failed() {
    local result=$?
    trap - ERR
    rollback_node
    status "FAILED mode=$mode exit=$result; inspect journal before retrying"
    exit "$result"
}
trap failed ERR

case "$mode" in
    --check)
        preflight
        changes=0
        candidate_check "${os_repos[@]}" --security --exclude=nginx-filesystem
        candidate_check "${os_repos[@]}" ca-certificates 'glibc*'
        candidate_check --disablerepo='*' --enablerepo=nginx-stable nginx
        candidate_check "${pg_repos[@]}" 'postgresql16*'
        /usr/bin/python3 "$NODE_UPDATER" --binary "$NODE_BINARY" --major "$NODE_MAJOR"
        printf 'Package updates available: %s\n' "$changes"
        ;;
    --apply)
        preflight
        [[ ! -e "$STATE_DIR/transaction.pending" ]]
        status 'CHECKING_UPDATES'
        dnf -q "${common[@]}" "${os_repos[@]}" --refresh makecache
        changes=0
        candidate_check "${os_repos[@]}" --security --exclude=nginx-filesystem
        candidate_check "${os_repos[@]}" ca-certificates 'glibc*'
        candidate_check --disablerepo='*' --enablerepo=nginx-stable nginx
        candidate_check "${pg_repos[@]}" 'postgresql16*'
        /usr/bin/python3 "$NODE_UPDATER" --binary "$NODE_BINARY" --major "$NODE_MAJOR" >"$STATE_DIR/node-candidate.json"
        if /usr/bin/python3 -c 'import json,sys; sys.exit(not json.load(open(sys.argv[1]))["changed"])' "$STATE_DIR/node-candidate.json"; then changes=1; fi
        if [[ $changes == 0 ]]; then status 'HEALTHY_NO_UPDATES'; exit 0; fi
        backup
        # A completed backup can consume space; check again before RPM writes.
        preflight
        rpm -qa | sort >"$STATE_DIR/packages.before"
        touch "$STATE_DIR/transaction.pending"
        dnf -y "${common[@]}" "${os_repos[@]}" upgrade --security --exclude=nginx-filesystem
        dnf -y "${common[@]}" "${os_repos[@]}" upgrade ca-certificates 'glibc*'
        dnf -y "${common[@]}" --disablerepo='*' --enablerepo=nginx-stable upgrade nginx
        dnf -y "${common[@]}" "${pg_repos[@]}" upgrade 'postgresql16*'
        old_node=$("$NODE_BINARY" --version)
        /usr/bin/python3 "$NODE_UPDATER" --binary "$NODE_BINARY" --major "$NODE_MAJOR" --apply
        node_changed=0
        if [[ $("$NODE_BINARY" --version) != "$old_node" ]]; then node_changed=1; fi
        nginx -t
        sshd -t
        dnf "${os_repos[@]}" needs-restarting -s >"$STATE_DIR/restart-needed.txt"
        # Restart only affected, prechecked services, with dependencies first.
        for unit in "${RESTART_UNITS[@]}"; do
            if grep -Fxq "$unit" "$STATE_DIR/restart-needed.txt" || \
               [[ "$unit" == "$NODE_SERVICE" && $node_changed == 1 ]]; then
                systemctl restart "$unit"
            fi
        done
        for attempt in $(seq 1 24); do
            if health; then
                node_changed=0
                rm -f "$STATE_DIR/transaction.pending"
                status 'HEALTHY_UPDATED'
                rm -rf -- "$STATE_DIR/backup.previous"
                exit 0
            fi
            sleep 5
        done
        false
        ;;
    --reboot-if-needed)
        preflight
        [[ ! -e "$STATE_DIR/transaction.pending" ]]
        # A failed or partial transaction must never trigger an unattended reboot.
        grep -q 'HEALTHY_' "$STATE_DIR/status"
        result=0
        dnf "${os_repos[@]}" needs-restarting -r || result=$?
        [[ $result == 0 || $result == 1 ]]
        if [[ $result == 1 ]]; then
            kernel=$(rpm -q kernel-core --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort -V | tail -1)
            [[ -s "/boot/vmlinuz-$kernel" && -s "/boot/initramfs-$kernel.img" ]]
            grubby --set-default="/boot/vmlinuz-$kernel"
            status "REBOOT_SCHEDULED kernel=$kernel"
            shutdown -r +1 'Scheduled security maintenance'
        fi
        ;;
    --verify)
        health
        status "HEALTHY_VERIFIED kernel=$(uname -r)"
        ;;
    *) printf 'Usage: %s --check|--apply|--reboot-if-needed|--verify\n' "$0" >&2; exit 64 ;;
esac

# 主机安全维护

应用发布和主机补丁是两个独立流程。GitHub Actions 更新 GloryBond 源码、固定 SDK 和 Python 依赖；本目录的维护入口负责 Linux 与共享服务补丁。

## 软件来源与兼容范围

- Alibaba Cloud Linux 3 使用现有官方 `alinux3-os`、`alinux3-updates`、`alinux3-module`、`alinux3-plus` 仓库，以 `dnf upgrade --security` 安装发行版回补补丁。保留包签名校验，不替换为上游通用内核，也不跨发行版升级。
- CA 证书和 glibc 同时检查官方仓库后续更新。RPM 主版本看起来较旧不等于没有补丁，应核对完整 release 和厂商公告。
- Nginx 使用 nginx.org 的 EL8 稳定版仓库，验证官方签名密钥后由 RPM 管理。现有站点和 Certbot 仍使用原配置目录；兼容入口显式传入原 prefix 和配置路径，systemd 保留实际 PID 文件和 worker 身份。
- PostgreSQL 保持 16 系列，使用官方 PGDG EL8.10 仓库。仅该命令关闭 Alibaba `releasever_adapter` 并指定 `--releasever=8.10`，避免将 Alibaba Linux 的版本号 3 传给 PGDG，或让适配插件错误解析已指定的 EL 版本。此设置不应用于系统仓库。
- 独立 Node 程序从 `https://nodejs.org/dist/` 查询当前主版本的最新正式 Linux x64 版本，核对同源 HTTPS 清单中的 SHA-256，验证解包后实际版本，再原子替换。只提取精确的 `bin/node` 成员，不运行下载的安装脚本，不更换主版本；保留 `.previous` 供服务检查失败时恢复。
- 不自动改动 QQ 会话、应用配置、业务数据、私有 SDK 或未纳入配置的其他软件源。GitHub Runner 自带运行时由 Runner 自身管理。

## 主机安装与私有配置

将 `security_updates.sh` 和 `update_node_runtime.py` 安装到 `/usr/local/libexec/glorybond-maintenance/`，设置 root 所有、0755。将本目录六个 `glorybond-security-*.service` / `.timer` 文件安装到 `/etc/systemd/system/`。

维护入口只读取 root 所有、0600 且非符号链接的 `/etc/glorybond-maintenance/config.sh`。该文件包含实际主机的 `STATE_DIR`、`MIN_FREE_BYTES`、`OS_REPOS`、`NODE_BINARY`、`NODE_MAJOR`、`NODE_SERVICE`、`NODE_UPDATER`，以及 `CRITICAL_UNITS`、`RESTART_UNITS`、`HEALTH_URLS`、`HEALTH_CODES`、`CURL_RESOLVE`、`BACKUP_PATHS` 数组。地址、部署路径及配置备份属于私有主机资料，不提交到仓库。检查列表须覆盖原有应用、数据库、SSH、代理和部署 runner；HTTP 检查使用实际基线状态码，TLS 检查不跳过证书验证。

当前检查适配本机 Redis 与 PostgreSQL 的既有访问方式。迁移到需要额外认证的主机时，应通过私有凭据接口适配，不能把密码加入命令行或公开配置。

启用前先完成只读检查，再启用定时器：

```sh
/usr/local/libexec/glorybond-maintenance/security_updates.sh --check
systemctl daemon-reload
systemctl enable --now glorybond-security-updates.timer glorybond-security-reboot.timer glorybond-security-verify.timer
```

## 执行与恢复

默认时区为 Asia/Shanghai，每天 04:15–04:20 检查并安装更新；05:00 仅在 DNF 判定需要重启、没有未完成事务、关键服务健康且没有 Runner 作业时安排一分钟后重启。两个日历定时器均不补跑错过的窗口，避免白天突然维护。开机三分钟后检查服务状态。

维护持有独占锁，更新前后检查配置语法、关键服务、HTTP 状态、Redis 与 PostgreSQL 连接。只重启 DNF 判定受影响且已纳入维护顺序的服务；独立 Node 替换时重启对应服务。数据库先于应用，服务健康最多等待两分钟恢复。新内核必须具有内核镜像与 initramfs，重启前设置为默认启动项；发行版正常保留旧内核供回退。

只有发现更新时才创建恢复点，包括配置归档、包清单、默认内核、PostgreSQL 全库逻辑转储和 Redis 全实例 RDB。它们分别保证各自的备份完整性，不宣称跨数据库/Redis 的统一静止点。验证新备份后替换上一份自动恢复点，避免小容量系统盘无限累积；手动维护的外置恢复点独立保存。状态目录及备份仅 root 可读。

更新期间写入 `transaction.pending`，所有检查通过才移除。失败会保留标记、记录失败状态并阻止后续自动更新和重启；独立 Node 更新失败时恢复原二进制。系统 RPM 不进行未经判断的自动降级。排查并修复服务、完成校验后，管理员才可清除未完成标记并重试。

```sh
systemctl list-timers 'glorybond-security-*'
journalctl -u glorybond-security-updates -u glorybond-security-reboot -u glorybond-security-verify
/usr/local/libexec/glorybond-maintenance/security_updates.sh --verify
uname -r
grubby --default-kernel
```

自动维护覆盖配置清单中的运行环境；健康检查通过表示这些检查项可用，不替代所有业务功能的测试。新增服务或运行时后同步维护私有检查清单。

## 官方依据

- [Alibaba Cloud Linux 内核漏洞修复与重启说明](https://help.aliyun.com/zh/alinux/product-overview/cve-2026-98432-vulnerability-announcement)
- [Nginx 官方 Linux 软件包与签名校验](https://nginx.org/en/linux_packages.html)
- [DNF 命令与安全更新过滤](https://dnf.readthedocs.io/en/stable/command_ref.html)
- [Node.js 官方发行目录](https://nodejs.org/dist/)

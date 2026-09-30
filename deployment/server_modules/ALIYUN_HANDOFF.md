# Aliyun 模块化改造交接

执行日期：2026-09-29。已通过 SSH 配置中的 `Aliyun` 在真实服务器完成迁移。

## 模块入口

| 模块 | 物理根目录 | 统一 systemd 入口 |
| --- | --- | --- |
| HOK | `/srv/modules/hok` | `hok.target` |
| 个人网站 | `/srv/modules/personal-site` | `personal-site.target` |
| Clash | `/srv/modules/clash` | `clash.target` |

HOK 包含 NoneBot、Web、QQ/NapCat、临时文件清理定时器、配置、数据与资源。
网站模块包含已部署源码、发布后的静态站点、OAuth/API、Node 运行文件和部署状态。
Clash 模块包含引擎、配置、规则、Dashboard 和日志目录。

每个模块提供 `module.json`、`systemd/`、`nginx/`、`ops/` 与自己的说明文件。
代码、配置入口、运行状态和日志均有明确归属。已有 Git 管理的配置及数据种子
保留原物理位置，通过模块目录中的链接集中索引，避免现有 CI 将目录链接还原。

Nginx、Redis、PostgreSQL、证书续期与 Actions runner 保持共享，不随模块停止。
PlanIt 的 Redis DB9 未迁移、未导出、未清理。仍被运行时、个人网站或共享 Actions
runner 使用的 `/QQBot`、NapCat、网站和 Clash 路径保留兼容链接；它们不是额外副本。
BotDemo、Lagrange 与旧 NapCat installer 已于 2026-09-30 在校验完整导出并额外保存
BotDemo Git bundle 后删除，对应的三个 `/QQBot` 链接也已移除。

## 日常命令

```bash
ssh Aliyun
modulectl status hok
modulectl restart hok
modulectl status personal-site
modulectl restart personal-site
modulectl status clash
modulectl restart clash
```

`start`、`stop`、`restart` 会等待目标及全部子服务状态收敛，默认 120 秒；
可以通过 `--wait-timeout` 调整。`status` 立即返回目标、成员和共享依赖状态。
个人网站的 target 仅控制 OAuth/API；停止后静态页面仍由共享 Nginx 提供。

## 私有迁移包

服务器输出目录为 `/srv/module-exports`，目录权限 `0700`，压缩包和校验文件 `0600`。
交付使用下列完整文件。校验通过后，本次生成的早期中间包已清理；其中的数据内容
保留在最终完整包中，原有数据库备份与目录迁移回滚记录没有删除。

- `hok-20260929T074933.621152Z-complete.tar.gz`
- `personal-site-20260929T075627.374648Z.tar.gz`
- `clash-20260929T075634.285314Z.tar.gz`

每个压缩包旁均有 `.sha256` 文件。HOK 包含 PostgreSQL custom dump 和 DB0 中
290 个 `hok:*` 键的 DUMP/TTL 快照；导出期间 HOK 自身停止，共享数据库保持运行。
QQ 会话文件在停机期间读取。最终 HOK 包对原快照做离线补包，补齐 NapCat 内置
运行依赖并更新管理工具，数据库、Redis、QQ 及其他原始文件内容不变。

正式包约为 HOK 1.8 GB、个人网站 76 MB、Clash 17 MB。三个整包 SHA-256 均已
验证，内部文件清单分别验证 7,714、527、469 个文件。

包内 `export-manifest.json` 记录每个文件的 SHA-256、权限、链接、捕获方式与
数据库快照信息。今后重新导出可执行：

```bash
modulectl export hok --quiesce
modulectl export personal-site --quiesce
modulectl export clash --quiesce
```

`--quiesce` 会停止所选模块，在成功或失败后恢复原先运行状态；模块原本全部停止时
保持停止，混合或失败状态直接拒绝。请避开 CI 发布，保持打包期间源码不被覆盖。

这些包包含密钥、订阅配置、账户映射和 QQ 会话，不要上传公开仓库或公开文件站。
使用 SSH/SCP 传输，并在下载前设置 `umask 077`。

## 验收与限制

- 三个 target、全部成员、共享数据库、Nginx 与 Actions runner 均已恢复运行。
- 网站首页 HTTP 200，HOK `/health` HTTP 200，OAuth `/healthz` HTTP 204。
- Clash 代理出站检查 HTTP 204。
- QQ 与 NoneBot 在 `127.0.0.1:8080` 建立连接，迁移后抽查无启动异常。
- 服务器 NBot/Web Git 跟踪文件无改动；原 CI 服务名称保持不变。
- NapCat 和 QQ 会话目录保持 `root:root 0700`。
- NBot 与 Web Actions 已改为直接在 `/srv/modules/hok/apps/{NBot,Web}` 发布，不再依赖
  `/QQBot/NBot` 或 `/QQBot/Web` 作为自身代码同步入口。

未在第二台全新 Linux 主机实测。目标主机需要匹配的系统依赖、Python 环境、
Redis/PostgreSQL、服务用户、TLS 证书和域名配置；二进制目前来自 x86-64 Linux。
Python 虚拟环境和网站 npm 依赖需重建，NapCat 自带 vendor 依赖已完整打包。
恢复步骤与数据恢复注意事项见 [README](README.md)。

## 回滚与源码状态

原始目录/服务迁移日志与配置备份：

```text
/srv/module-backups/20260929T073049Z
```

后续 `*-ops` 目录仅保存管理工具和配置更新的文件备份，不是完整迁移回滚入口。
需要回滚时，先检查迁移后是否新增部署或数据变更，再依 README 的专用命令执行。
旧路径链接本身不能作为备份使用。

本地 `HOK_QQBot` 与 `HOK_QQBot_Web` 的部署配置改造和架构规范已分别提交并推送；
服务器 Actions 已从模块物理目录完成发布。旧实现清理的附加备份位于
`/srv/module-backups/20260930T001926Z-legacy-cleanup`。

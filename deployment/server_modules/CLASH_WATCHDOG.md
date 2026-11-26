# 共享代理连通性维护

Clash 原生 `fallback` 组每 300 秒测试线路，按新加坡、日本、美国等备用地区顺序选择可用节点。
`Ghelper` 选择该组，`profile.store-selected` 保留选择；已有自动测速组也使用 HTTPS 探测和 300 秒间隔。
业务仍通过显式的本机 HTTP 代理访问，不设置全局代理环境变量。

[clash_watchdog.py](clash_watchdog.py) 由独立 systemd timer 每 5 分钟运行：

- 通过实际代理访问两个独立 HTTPS 检测地址，任一返回约定状态即视为可连接。
- 连接失败时切回原生故障切换组；仍失败可提前刷新订阅。
- 正常情况下每天刷新订阅；失败刷新之间至少间隔 1 小时，避免持续请求。
- 订阅地址从模块原有 `.env` 中的 `CLASH_URL` 读取，只解析、不执行该文件。先直连，失败后尝试当前代理；下载限制 5 MiB。
- 只更新节点及已有组的成员，保留本机端口、密钥、面板、DNS、规则和未知字段。订阅导致自定义组引用失效时拒绝更新。
- 候选配置先通过 Clash 离线检查，再保存私有恢复副本、原子替换并热加载；加载失败恢复原配置。仅自动轮换本工具生成的最近 10 份副本，其他恢复点保留。
- 运行锁避免重叠；状态持久化。日志仅记录连接状态、是否刷新及错误类型，不记录订阅 URL、密钥、响应正文或原始异常。

探测只能说明所测地址和线路可用，业务 API 的鉴权、限流及站点自身错误仍由相应模块处理。

## 当前主机

源码发布后，将本目录脚本安装到 `/srv/modules/clash/ops/clash_watchdog.py`，服务和定时器安装到
`/srv/modules/clash/systemd/` 并链接到 `/etc/systemd/system/`。模板采用现有系统 Python 3.13，
需有 `requests` 和 `PyYAML`，不依赖 Bot 虚拟环境。该定时器与手动主机安全更新互相独立。

私有 `/srv/modules/clash/config/watchdog.json`（0600）保存以下设置：

```json
{
  "config": "/srv/modules/clash/config/config.yaml",
  "binary": "/srv/modules/clash/apps/engine/bin/clash-linux-amd64",
  "subscription_env": "/srv/modules/clash/apps/engine/.env",
  "state": "/srv/modules/clash/data/watchdog/state.json",
  "selector": "Ghelper",
  "fallback": "自动故障切换",
  "preferred_regions": ["新加坡", "日本", "西雅图"],
  "proxy": "http://127.0.0.1:7890"
}
```

```bash
systemctl daemon-reload
systemctl enable --now clash-watchdog.timer
systemctl start clash-watchdog.service
systemctl list-timers clash-watchdog.timer
journalctl -u clash-watchdog.service -n 10 --no-pager
```

手动提前刷新可运行服务 `ExecStart` 的命令并加 `--refresh`。暂停自动维护用
`systemctl disable --now clash-watchdog.timer`；Clash 自身的备用组仍然生效。
恢复配置时先离线校验，再通过受认证的本机控制器热加载。不要把配置或订阅输出到终端。

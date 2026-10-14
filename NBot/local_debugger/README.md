# local_debugger

`local_debugger` 是根目录下的本地调试器运行时，用于让 `hok/debug_tools` 脚本在不启动 NoneBot 插件入口的情况下导入项目模块。

## 持久 Python 环境

调试依赖统一安装到 `local_debugger/.venv`。该目录不纳入 Git，但会保留在本机项目目录中，因此 Codex 切换 session 后可直接复用，无需重新配置或安装。

首次创建或依赖变更后执行：

```bash
python3 local_debugger/setup_env.py
```

运行调试脚本时推荐使用包装入口。若环境还不存在，它会先自动创建：

```bash
python3 local_debugger/run.py hok/debug_tools/history_map_export_cli/export_official_grade_summary.py 2026-06-01 --end-date 2026-06-09
```

也可以直接使用固定解释器：

```bash
local_debugger/.venv/bin/python -m local_debugger <调试脚本> [参数...]
```

虚拟环境保存的是本机运行产物，不应提交或复制到其他机器；需要在新机器上用 `setup_env.py` 重建。

推荐用法：

```python
from local_debugger import bootstrap, import_hok_module

bootstrap()
zfunc = import_hok_module("zfunc")
result = zfunc.Analyses.get_benefit_data()
```

它会准备：

- 项目根目录 `sys.path`
- 项目根目录 `config.yaml` 中的 `Redis`
- 项目根目录下的 `file_transfer/` 静态产物根目录
- 缺失的 import-time 依赖占位
- 不执行 `hok/__init__.py` 的 `hok` 命名空间

已有环境时，也可以用模块入口启动任意调试脚本：

```powershell
local_debugger/.venv/bin/python -m local_debugger hok/debug_tools/history_map_export_cli/export_official_grade_summary.py 2026-06-01 --end-date 2026-06-09
```

独立 agent 依赖使用 Git submodule；首次克隆后先执行 `git submodule update --init --recursive`，再启动本地工具。QQ 接入与本地界面共用该固定版本内核。

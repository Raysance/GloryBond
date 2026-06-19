# local_debugger

`local_debugger` 是根目录下的本地调试器运行时，用于让 `hok/debug_tools` 脚本在不启动 NoneBot 插件入口的情况下导入项目模块。

推荐用法：

```python
from local_debugger import bootstrap, import_hok_module

bootstrap()
zfunc = import_hok_module("zfunc")
result = zfunc.Analyses.get_benefit_data()
```

它会准备：

- 项目根目录 `sys.path`
- 本地 `REDIS_CONF`
- 项目根目录下的 `file_transfer/` 静态产物根目录
- 缺失的 import-time 依赖占位
- 不执行 `hok/__init__.py` 的 `hok` 命名空间

也可以用它启动任意调试脚本：

```powershell
python -m local_debugger hok/debug_tools/history_map_export_cli/export_official_grade_summary.py 2026-06-01 --end-date 2026-06-09
```

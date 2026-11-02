# Agent 数据查询与运行边界

QQ 与本地网页使用 `vendor/react-agent-runtime` 的同一个内核。工具注册与权限绑定在
外部 `agent_console` / `qq_agent`，不再维护 Hok 专属工具注册器或 schema。

模型权威目录为 `shared/agent/hok_sql/catalog.json` 与
`shared/agent/chat_sql/catalog.json`；语义视图定义为 `hok_sql/views.json`。
目录同时用于模型披露和 `agent_console/tools/sql_validation.py` 的 AST 校验。

## 查询流程

1. 入口绑定真实用户和可信群范围。群聊仅当前群，普通私聊无群聊权限，已验证管理员
   私聊允许跨群。模型不能改变授权。
2. 资料足够时直接回答；需要历史资料时才检索，需要其他能力时按类别发现。首轮已授权检索与发现可同轮调用，不设置固定聊天前置工具；重复发现不重传已有目录。
3. 发现 `game_data` / `chat_data` 后，模型动态生成 SQL，调用
   `analyze_game_database` / `analyze_chat_database`。
4. worker 先整批 AST 校验，再在独立只读账号/事务中执行。整批任一项无效时不访问
   数据库。每项保留状态、截断说明和 dataset_id；游戏查询只允许目录语义视图。

只读账号仍由 `database/chat_readonly.sql` 配置，不回退业务写账号。私有群聊表与
payload 不向模型开放；群聊 SQL 只查询 `hok.chat_history_messages` 安全视图，事务
注入可信 `hok.chat_group_scope`。统计只覆盖 PostgreSQL 归档，不用 BM25 命中数估算
总体，也不包含尚未迁移的应急 Redis 记录。worker 始终从应用版本的受信视图定义
编译只读 CTE，不受服务器同名旧视图影响，不执行 DDL；生成名称避免与模型 CTE 冲突。
阵容视图以一次分组映射已配置参赛者，再按对局与角色关联，保留多玩家视角、别名选择、
未知身份与空阵营语义，避免逐参赛者反复扫描整份玩家来源。单条 SQL 仍受5秒时限保护。
玩家对局与阵容视图的 `is_mvp` 是对应参赛者的可空布尔列，统一接受源 true/false 与 1/0；
缺失或未知值保留 NULL。统计优先使用该类型列，不将原始 JSON 的 "false" 文本转为整数。
SQL 返回的 coverage 明示归档边界；空结果或末条记录时间不能推断真实活动停止、未上线或未发生。

QQ 近期背景及本轮后续历史读取使用同一入口时间上界。背景明确区分实际作者、原提问者、
提及对象与引用；引用优先用于定位对象，不从他人旧发言推断当前调用者身份或个人偏好。

SQL 行数、列数、结果字节及超时由根 `config.yaml#AgentSQL` 管理。模型预算分别为
QQAgent/LocalAgent.budget，工具参数限制在共享工具模型中。不存在旧 schema/check
票据链、旧问题模板或第二套 SQL 执行器。

## 产物与状态

绘图用 `render_plot` 或隔离 `execute_python`；主题在 `shared/agent/plots/catalog.json`。
Python 只在关闭网络、清空凭据环境的 Linux bubblewrap 中执行。图表由 QQ 出口校验、
落盘及合图，字体和合图设置为 AgentPlots。联网搜索经阿里云 OpenSearch 返回真实来源。

事实、历史检索的纯函数在 `agent_console/tools/memory.py`，适配器直接传入 worker。
长期事实按可信用户存于 DB0 `hok:memory:facts:<QQ>`，角色和偏好由共享角色服务维护。
直接上下文、工具事件和任务由注入的 StatePort 管理，QQ 对话按群和用户隔离。
`forget_me` 清除本人事实和当前 QQ 会话上下文，不删除归档、调试日志或其他会话。

QQ 消息、图片和轨迹沿用现有出口。trace 请求/响应及工具结果脱敏保存，并生成可查看
的运行记录；原生输入图片与本地调试日志按忽略目录保存。代码清理不执行数据库迁移
或删除旧持久数据。

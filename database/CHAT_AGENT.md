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

主成员及额外成员共用参考目录中的 `player_key`。每个游戏查询批次重新读取配置，
将营地/角色 ID 通过 AST 常量编译为内部 `chat_configured_players` CTE，返回
`reference_version`；内部关系和身份 ID 不加入模型 SQL 白名单。双方角色 ID 存在时
必须相等，双方营地 ID 同时存在时也必须一致；角色缺失时仅允许无多角色歧义的营地 ID
匹配。QQ、昵称及 `sameuser` 不补全游戏账号，冲突配置不用于生成匹配。

本人战绩仍按最新快照去重。缺少本人战绩的配置成员从已有同局详情补出个人视角，
只借用同局时间、模式和时长，英雄、KDA、评分、MVP、装备均取本人参赛数据。
胜负按已知阵营转换，未知阵营、胜负以及缺失的段位变化保留 NULL。对局、装备和阵容
返回 `record_source`（`battle_record` 或 `battle_participant`），每个账号同局只有一个视角。
个人快照和底蕴按同一配置映射已有记录，不要求该账号进入每日主成员快照。
额外成员的同局样本不代表完整个人战绩；只有详情、没有战绩时间与模式锚点的对局
不会补出对局行。无需数据库迁移、新表、额外读取授权或重新采集。

`analyze_game_database.scope` 在对局、装备和阵容关系聚合前统一筛选，默认
`mode=official,time_basis=calendar`。`start_at/end_at` 是含时区的左闭右开边界，
由程序转换为开局秒值；自然时间口径禁止按 `snapshot_date` 过滤、分组或排序对局。
只有明确业务日查询才使用 `time_basis=business`，边界为北京时间零点。
资料快照与底蕴评估关系保留自身时钟，不套用对局范围。范围随 observation 批次返回，
模型不能将不同时间或模式的诊断结果当作同一比较样本。
对局读取另受可信入口时间 `as_of` 上界约束，模型指定更晚的结束时间也不能读到本轮之后的对局。

成功 observation 附 `column_totals`，使用十进制计算返回行中数值列的和与非空行数，
并声明是否截断；该结果不推断业务含义。ID、均值、比率及队友行数不能作为可加场次，
截断数据的合计不能作为总体。参考查询的 `term_resolution` 区分精确匹配、包含候选、
歧义和未匹配，不凭拼音缩写补全未知身份。

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

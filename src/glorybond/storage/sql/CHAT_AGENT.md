# Agent 数据查询与运行边界

QQ 与本地网页使用 `vendor/react-agent-runtime` 的同一个内核。工具注册与权限绑定在
外部 `glorybond.agent` / `glorybond.apps.qq.agent`，不再维护 Hok 专属工具注册器或 schema。

模型权威目录为 `resources/agent/hok_sql/catalog.json` 与
`resources/agent/power_sql/catalog.json`、`resources/agent/chat_sql/catalog.json`；战绩和底蕴语义定义分别为 `hok_sql/views.json`、`power_sql/views.json`。
目录同时用于模型披露和 `src/glorybond/agent/tools/sql_validation.py` 的 AST 校验。

## 查询流程

1. 入口绑定真实用户和可信群范围。群聊仅当前群，普通私聊无群聊权限，已验证管理员
   私聊允许跨群。模型不能改变授权。
2. 资料足够时直接回答；需要历史资料时才检索，需要其他能力时按类别发现。首轮已授权检索与发现可同轮调用，不设置固定聊天前置工具；重复发现不重传已有目录。
3. 发现 `game_data` / `power_data` / `chat_data` 后，模型读取各自目录并生成 SQL，调用
   `analyze_game_database` / `analyze_power_database` / `analyze_chat_database`。三个目录分别校验，不能跨域查询。
4. worker 先整批 AST 校验，再在独立只读账号/事务中执行。整批任一项无效时不访问
   数据库。每项保留状态、截断说明和 dataset_id；游戏查询只允许目录语义视图。

游戏目录允许跨白名单语义关系的 JOIN/EXISTS。优先直接使用已有字段；同一玩家同局关联使用(player_key,game_seq)，一对多先聚合或 EXISTS，避免重复统计；未知胜负不计入胜率分母。所有关系在聚合前使用同一 scope。底蕴和聊天目录的单关系约束不变。参考数据 namespace 仅限制输入 ID 字段，查询昵称/别名须省略。

SQL 白名单按 sqlglot 规范名称校验，包括 PostgreSQL `BOOL_AND/BOOL_OR` 和数组
`@>`、`<@`、`&&`。命名参数写为未加引号的 `:name` 或 `%(name)s`，值放在
`params` 中；缺失、多余、位置参数及非 JSON 标量均拒绝，不改写含义不明确的 SQL。

只读账号仍由 `src/glorybond/storage/sql/chat_readonly.sql` 配置，不回退业务写账号。私有群聊表与
payload 不向模型开放；群聊 SQL 只查询 `hok.chat_history_messages` 安全视图，事务
注入可信 `hok.chat_group_scope`。统计只覆盖 PostgreSQL 归档，不用 BM25 命中数估算
总体，也不包含尚未迁移的应急 Redis 记录。worker 始终从应用版本的受信视图定义
编译只读 CTE，不受服务器同名旧视图影响，不执行 DDL；生成名称避免与模型 CTE 冲突。
阵容视图以一次分组映射已配置参赛者，再按对局与角色关联，保留多玩家视角、别名选择、
未知身份与空阵营语义。去重键与个人事实分别以不含 JSON 的窄 CTE 复用，详情在最终投影时关联，
避免在多个分支反复排序和物化完整原始载荷。账号匹配拆成互斥的角色/营地 ID 等值关联。
只有模型对同一语义关系的每处引用都明确使用成员等值或常量 `IN` 条件时，才将成员并集下推到该关系。
共享事实只被这些已限定成员的战绩、装备关系消费时，进一步在 `chat_player_battle_facts` 物化前筛选成员，
避免先生成全员事实再取个人最后一场或统计结果。多处引用取成员并集；任一引用未限定、仅有 OR 或子查询
条件时保留完整事实。编译器检查语义依赖图，阵容身份映射、底蕴活动历史及其他消费者阻止此共享事实裁剪；
内部同局锚点和配置身份映射始终完整，额外成员仍可借用其他玩家的同局时间锚点并保留本人战绩优先规则。
无需新增索引、数据库迁移或全局查询计划参数。回归验证覆盖 `tests.test_agent_sql_views`、
`tests.test_agent_extra_players`、`tests.test_agent_query_scope`、`tests.test_agent_power_sql`。
带 LIMIT 的查询使用普通游标，使数据库可以选择并行计划。
单条 SQL 默认30秒，`AgentSQL.statement_timeout_ms` 支持1000至60000毫秒；连接时限由
`connect_timeout_seconds` 在1至10秒内配置，锁等待仍为5秒。最多6条批量查询，RPC/工具
时限分别为400/410秒，超时项回滚后仍可返回其他已成功结果。原先配置中的5000会被尊重，
升级时需将私有配置改为30000；不需迁移游戏数据或变更读取授权。
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
资料快照保留自身时钟。独立底蕴工具的两种关系统一使用归档开局时间；`evaluated_at` 仅表示评估时间。
开局时间未知的底蕴不进入指定时间区间；无时间筛选时可读取并明确未知。范围随 observation 批次返回，
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

绘图用 `render_plot` 或隔离 `execute_python`；主题在 `resources/agent/plots/catalog.json`。
Python 只在关闭网络、清空凭据环境的 Linux bubblewrap 中执行。图表由 QQ 出口校验、
落盘及合图，字体和合图设置为 AgentPlots。联网搜索经阿里云 OpenSearch 返回真实来源。

事实、历史检索的纯函数在 `src/glorybond/agent/tools/memory.py`，适配器直接传入 worker。
长期事实按可信用户存于 DB0 `hok:memory:facts:<QQ>`，角色和偏好由共享角色服务维护。
直接上下文、工具事件和任务由注入的 StatePort 管理，QQ 对话按群和用户隔离。
`forget_me` 清除本人事实和当前 QQ 会话上下文，不删除归档、调试日志或其他会话。

QQ 消息、图片和轨迹沿用现有出口。trace 请求/响应及工具结果脱敏保存，并生成可查看
的运行记录；原生输入图片与本地调试日志按忽略目录保存。代码清理不执行数据库迁移
或删除旧持久数据。

## 底蕴 JSON 查询

`analyze_power_database` 使用现有 `GameSQLArgs`，同批最多6条只读 SQL，`scope` 与战绩工具一致。`chat_battle_power` 每局一行，`payload` 包含完整业务 JSON；`player_keys @> ARRAY[:player]` 筛选包含某成员的对局，多成员用数组交集。`chat_battle_power_players` 每个 `(game_seq,participant_index)` 一行，`participant_payload` 保留个人业务字段。按 `player_key IN (:p1,:p2)` 可查询指定成员；同一关系自连接可分析该成员的全部队友和对手，包括 `player_key IS NULL` 的未登记玩家。不同关系不可在一条 SQL 中混接。

原始 `mySide/opSide` 和 `gameResult` 保留采集视角；整局 `players` 追加可信 `playerKey` 与 `participantIndex`。参赛者视图直接提供本人/对手底蕴、梯度和转换后的胜负，未知阵营不猜测。内部账号与服务器 ID、头像 URL、原始错误正文不公开，`requestErrorCount` 保留错误数量；其他业务字段，包括已有 `matchup`、`aiAnalysis` 和将来新增业务字段，继续保留。不会调用营地或重新评估。

模型发现 `power_data` 时获得字段说明、统计口径及完整参数/SQL示例。能力目录同时说明同局历史指标、授权和人机标记的来源。先用少量 JSON 样本核对字段和值域，再在数据库聚合；结果可复用原有 dataset、绘图和沙箱工具。QQ/Web 共用此工具；不新增数据库表、授权或迁移。验证使用 `tests.test_agent_power_sql`、`tests.test_agent_extra_players`；PostgreSQL JSON 验证可通过 `HOK_TEST_POSTGRES_DSN` 启用 `tests.test_agent_power_postgres`，只执行合成数据 SELECT。

`match_average_level` 为双方底蕴平均，任一侧无有效值时返回 NULL。参赛者的 `previous_game_time_epoch`、`gap_since_previous_game_seconds` 与前后 `record_source` 来自全模式 `chat_player_battle_facts`，在本轮范围筛选前计算窗口，避免筛掉未评估局、其他模式或区间前一局后制造活动断档。此间隔只反映已收录记录；评估行序不是完整比赛序列。

内部 `chat_power_team_flags` 按 `(game_seq,side)` 聚合完整阵容。人数为5、授权字段全部明确false/0且团队底蕴0/NULL时，项目人机队标记为true；人数或授权信息不全为NULL，有授权者或有效团队底蕴则为false。`participant_side_is_bot` / `rival_side_is_bot` 提供个人视角，整局 `my_side_is_bot` / `opponent_side_is_bot` 保留采集视角。标记不使用player_key、昵称或错误次数。统计分别报告标记未知、人机样本及有效底蕴分母。

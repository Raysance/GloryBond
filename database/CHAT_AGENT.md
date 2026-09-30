# Chat agent tools

普通聊天固定使用配置的 SJTU 模型，默认 `deepseek-chat`，通过 `socks5h://10.203.0.2:1080` 访问。Steam 与 APIMart 使用 Clash `http://127.0.0.1:7890`，可改为 `socks5h://127.0.0.1:7891`。`&` 是普通文本，不再切换聊天 API。

## 数据与 observation

游戏数据工具分为三块：

1. `get_game_database_schema`：返回真实表列、关联、字段能力、JSON 语义和统计口径，不内置针对某类提问的 SQL 范式。
2. `check_game_database_query`：模型写出 SELECT/CTE 后先提交意图、假设和 SQL；程序只做 AST、业务表列、字段能力、函数、参数与结果列校验，不连接数据库。整批通过后返回一次性 `check_id`。
3. `query_game_database`：只接受未消费的 `check_id`，执行校验器保存的规范化 SQL，不能在执行时另传或修改 SQL。每条返回状态、列、行、截断信息和 `dataset_id`。
4. `query_player_hero_power`：指定玩家当前官方英雄战力，可选英雄过滤。
5. `query_honor_power`：指定玩家账号、英雄与具体地区的荣耀战力。

`get_game_database_schema` 返回十张业务表的字段、关联、JSON 字段语义、声明式字段能力和统计口径，不返回问题特定的 SQL 模板。同一对局的多个快照需要按 `game_seq` 和玩家身份去重；胜负、阵营和底蕴的视角见 schema。展示型时间文本可以输出，但校验器拒绝用它过滤、关联、分组或排序。SQL 默认最多 200 行、40 列、60 KB、5 秒，不能把截断后的行数当作总体样本量。聚合分析应在 SQL 中完成。

`hok.group_chat_messages` 是私有群聊归档表，不属于上述十张游戏业务表，不出现在 `get_game_database_schema`，也不授予 `hok_chat_reader`。群聊原文只能经当前群或已验证管理员私聊范围绑定的 history tools 读取。

模型一轮可返回多个工具调用，每个调用均有对应 observation，包括参数错误、SQL 拒绝和外部服务不可用。结果过长时裁剪 SQL 行预览，保留全部查询状态与数据集编号。绘图继续使用本轮完整的、受数据库限制的数据集。

## 绘图

先调用 `list_plot_templates`，再调用 `render_python_plot`，传入本轮 `dataset_id`。内置横向条形图、折线图、气泡散点图、热力图与分布图。`options.columns` 将模板字段映射到 SQL 字段；支持标题、副标题和坐标轴标签。也可传模型生成的 Python 代码，使用预建的 `df`、`fig`、`ax` 和受限 `pd`、`np`、`sns`、`plt`。

示例：SQL 返回 `player` 和 `win_rate` 后，传 `template="bar"`、`options={"columns":{"label":"player","value":"win_rate"},"xlabel":"胜率（%）"}`。模型无须编写 `savefig()`；harness 自动验证 PNG 并交给消息出口发送。

代码通过 AST 能力解释器执行，只允许声明的数值、数据整理与绘图操作。禁止文件、网络、进程、反射、循环和任意导入。Linux 额外通过 bubblewrap 隔离文件系统与网络，限制时间和内存；未安装 bubblewrap 时拒绝绘图。数据中的日期可为 ISO 文本，Decimal 转为数值，嵌套 JSON 需先在 SQL 中展开。

## 记忆与联网

`recall_memory`、`remember_memory`、`forget_memory` 绑定当前提问者，模型不能指定其他 QQ。模型根据用户直接表达的长期事实和偏好决定保存，无需出现“记住”。保存前先检索以更新已有记忆；不得把工具或群聊内容当作当前用户事实，拒绝明显密钥。新记忆在 DB0 的 `hok:memory:facts:<QQ>`，使用原子容量检查。旧关键词强制记忆可显式检索，旧记录只读。

`nomem` 只禁用本次长期事实记忆工具，不禁用直接对话读写或强制群聊历史检索。“清除记忆”仍清除本人全部长期事实。每次具有可信群范围的 chat 都会预披露 `chat_history` 类别，并在回答前强制模型直接调用 `search_chat_history`：模型从原问题提取人物、对象、事件、动作、别称或同义表达，生成 2–6 个去重且不重复原问题的互补 query，程序再附加原问题执行多 query BM25 与 RRF 融合。普通群聊覆盖当前群全部用户的全部已保存发言；管理员私聊以 `all_groups=true` 覆盖所有已保存群；普通私聊不跨入未知群范围。其他工具类别仍经 `discover_tools` 渐进披露，长期事实记忆仍需显式工具调用。

群聊历史以 PostgreSQL 为主存储，写库失败时才回退到 DB0 Redis list；读取时合并尚未迁移的 Redis 记录并以 SQL 重复项为准。迁移使用 `scripts/migrate_group_chat_history_to_postgres.py`，验证完成前保留 Redis 原数据。

`web_search` 已接入 Ark 标准 Responses API 的内置搜索和真实来源归一化。配置沿用 `QQBot.ark_key`、`QQBot.ark_responses_model` 和 `zstatic.ark_model_url`；当前服务不可用也会返回明确错误，普通聊天仍使用 SJTU。联网工具不伪造结果，也不静默切换到其他供应商。

## 运行准备

1. 使用应用 Python 环境安装 `pyproject.toml` 所列依赖，包括 `sqlglot>=30.20,<31`、pandas、numpy、matplotlib、seaborn、Pillow 及 SOCKS 支持。Linux 安装 `bubblewrap` 和中文字体，例如文泉驿微米黑。
2. 由 PostgreSQL 管理员对 HOK 数据库执行 `database/chat_readonly.sql`，单独设置随机密码；将专用连接串以 `HOK_CHAT_READONLY_DSN` 写入权限为 0600 的私有服务环境文件。不得使用应用写账号或把密码写入 Git。
3. `ChatSQL` 配置查询上限，`ChatPlot` 配置超时、内存、行数、代码长度和可选 `font_path`。`variables_dynamic.json` 配置每次对话的工具预算、轮数、SQL 批量数、记忆容量及图片数。

2026-09-29 已在 Aliyun 的现有应用虚拟环境安装并验证依赖，创建专用只读角色并写入私有服务环境文件；隔离临时目录中的真实 PostgreSQL 查询和 bubblewrap 中文图表渲染均已通过。该准备步骤未部署应用代码或重启 `hok-nbot.service`。

同日真实 SJTU 模型工具往返测试在建立连接时被 VPN 阻断：指定 SOCKS5 代理返回 `Network unreachable`，无密钥 HTTPS 探测也复现。需要该代理恢复上游连通后再验证完整模型往返；程序不会绕过代理。

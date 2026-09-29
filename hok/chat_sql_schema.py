"""Verified gameplay schema and semantics for the chat SQL observation tool.

Keep this catalogue aligned with database/schema.sql and zdb's ingestion code.
It contains no credentials, filesystem paths, or import-manifest metadata.
"""

from copy import deepcopy


CHAT_SQL_ROLE = "hok_chat_reader"


def _columns(definition):
    return dict(item.split(":", 1) for item in definition.split())


CHAT_SQL_TABLES = {
    "history_players": {
        "description": "每日玩家快照；主键(snapshot_date, player_index)，player_key 为关联玩家标识。",
        "columns": _columns("""
            snapshot_date:date player_key:text player_index:integer user_id:bigint role_id:bigint
            nickname:text rank_name:text rank_star:integer star:integer star_up:integer
            today_num:integer total_num:integer visible:boolean map_count:jsonb peak_up:jsonb
            gaming_info:jsonb payload:jsonb updated_at:timestamptz
        """),
    },
    "battle_records": {
        "description": "每日快照中的玩家视角战绩；主键(snapshot_date, player_index, detail_index)。",
        "columns": _columns("""
            snapshot_date:date player_key:text player_index:integer detail_index:integer
            user_id:bigint role_id:bigint game_seq:bigint game_time_label:text game_time_epoch:bigint
            hero_name:text map_name:text map_type:integer star_after_game:integer
            peak_grade_after:integer peak_grade_before:integer kill_count:integer death_count:integer
            assist_count:integer result:text game_grade:numeric duration_seconds:integer
            params:jsonb others:jsonb payload:jsonb
        """),
    },
    "battle_details": {
        "description": "每场完整对局一行；game_seq 主键，payload 是官方完整战局对象。",
        "columns": _columns("""
            game_seq:bigint game_type:integer map_name:text event_time_label:text start_time_label:text
            duration_seconds:integer payload:jsonb updated_at:timestamptz
        """),
    },
    "battle_participants": {
        "description": "每场所有参赛者，包括未关联玩家；主键(game_seq, participant_index)。",
        "columns": _columns("""
            game_seq:bigint participant_index:integer camp:text role_id:bigint user_id:bigint
            role_name:text hero_id:bigint hero_name:text kill_count:integer death_count:integer
            assist_count:integer game_grade:numeric gold:integer payload:jsonb
        """),
    },
    "personal_snapshots": {
        "description": "营地个人采集快照；主键(snapshot_date, user_id)，是采集时状态而非实时在线状态。",
        "columns": _columns("""
            snapshot_date:date user_id:bigint target_role_id:bigint invisible:boolean is_gaming:boolean
            battle_count:integer payload:jsonb updated_at:timestamptz
        """),
    },
    "battle_power": {
        "description": "每场已计算的底蕴评估；game_seq 主键，role_id 标记存储的我方视角。",
        "columns": _columns("""
            game_seq:bigint role_id:bigint map_name:text game_result:text game_time:text evaluated_at:text
            my_side_level:numeric opponent_side_level:numeric my_side_tier:numeric
            opponent_side_tier:numeric payload:jsonb updated_at:timestamptz
        """),
    },
    "battle_power_players": {
        "description": "底蕴评估中的参赛者；主键(game_seq, participant_index)，只覆盖已评估对局。",
        "columns": _columns("""
            game_seq:bigint participant_index:integer role_id:bigint user_id:bigint nickname:text
            side:text hero_name:text hero_power:integer hero_win_rate:numeric
            hero_average_score:numeric single_level:numeric payload:jsonb
        """),
    },
    "hero_tier_scores": {
        "description": "历史英雄梯度数值；主键(snapshot_date, hero_name)，与个人英雄战力不同。",
        "columns": _columns("snapshot_date:date hero_name:text score:numeric updated_at:timestamptz"),
    },
    "hero_rank_snapshots": {
        "description": "官方英雄榜每日快照；主键(snapshot_date, rank_id)，榜单范围由title/filter_data区分。",
        "columns": _columns("""
            snapshot_date:date rank_id:integer title:text update_time:text sort_field:text
            sort_type:text filter_data:jsonb payload:jsonb updated_at:timestamptz
        """),
    },
    "hero_rank_entries": {
        "description": "榜单英雄条目；主键(snapshot_date, rank_id, rank_index)，rank_index 从0开始。",
        "columns": _columns("""
            snapshot_date:date rank_id:integer rank_index:integer hero_id:bigint hero_name:text
            hero_career:text tier_rank:text ban_rate:numeric show_rate:numeric win_rate:numeric
            pick_count:bigint ban_count:bigint payload:jsonb
        """),
    },
}

CHAT_SQL_SEMANTICS = [
    "SQL 方言 PostgreSQL。仅单条 SELECT 或非递归 WITH ... SELECT，可 JOIN/聚合/窗口/JSON。必须显式列名，COUNT(*) 可用。表加 hok. 前缀；不给文件路径、系统目录或导入清单访问权。",
    "同名昵称不保证身份唯一。用 player_key、role_id 或 user_id 确定身份，QQ号不是营地 user_id；先按提供的关联玩家目录或 history_players 查明身份。",
    "history_players 是每日快照。最新资料使用 DISTINCT ON (player_key) 并 ORDER BY player_key,snapshot_date DESC,player_index DESC；不能把每日 total_num 累加当作场次。visible/invisible 表示采集时可见性，缺数据不代表零。",
    "battle_records 同一对局可有多个玩家视角，也可能出现在多个快照。统计每名玩家先按(role_id或player_key, game_seq)去重并选最新快照；game_seq 为 NULL 时以原主键保留，不能把所有 NULL 合成一局。统计比赛总数用 COUNT(DISTINCT game_seq)，统计参赛人次则保留每人一行。",
    "battle_records 与 history_players 用(snapshot_date,player_index)连接；battle_records.game_seq 对 battle_details.game_seq；参赛者表、底蕴表都通过 game_seq 连接。按目标玩家追加 role_id 等值，防止每条战绩被10名参赛者或多张快照重复放大。",
    "battle_records.result 为中文 '胜利' 或 '失败'，不是1/2。map_type=1排位、-1巅峰、0其他。star_after_game 是折算总星数，非排位常为-1；peak_grade_after/before 非巅峰常为-1。rank_star 是当前段位内星数，star 为折算星数。",
    "默认正式5v5口径与 battle_metrics.check_btl_official 一致：map_name ~ '(排位|巅峰|战队)' AND map_name !~* '(1v1|2v2|3v3)'。用户明确要求匹配、娱乐或全部时另选过滤，并在结论说明。英雄统计未给时期时默认当前赛季，按会话给出的赛季起止日期过滤。",
    "日期以 Asia/Shanghai 为准。snapshot_date 是业务日快照；精确小时范围使用 game_time_epoch（秒）及 to_timestamp(game_time_epoch)；会话给出当前日期。日期窗口推荐 >=起点 AND <下一天。game_time_label 是展示标签，不可靠地用于排序；updated_at 是写库时间，不是开局时间。",
    "game_grade 是个人评分。胜率=胜局/有效场次（0到1）；KDA=(kill_count+assist_count)/GREATEST(death_count,1)，需说明按单局平均或汇总KDA。缺失评分用NULL排除，不强行填0；比较需返回样本数和时间范围。",
    "battle_participants.camp 是官方 basicInfo.acntCamp 的文本值；同一game_seq且camp相等为队友，不同为对手。participant_index及red/blue列表顺序不等于目标玩家阵营。payload.battleRecords.position 是分路，payload.battleStats 含伤害/承伤/参团等更多字段。",
    "battle_details.payload.head 只是最后写入者视角，不能用它判断任意玩家胜负。优先使用目标玩家 battle_records.result；仅查未关联参赛者时，把其camp与payload.redTeam/blueTeam.acntCamp比较，匹配队伍的gameResult=1为胜利。",
    "battle_power.role_id 是原始视角；battle_power_players.side='my'/'op' 相对这一视角。对任意目标玩家，side='my'时own=my_side_level，否则own=opponent_side_level；对手相反。game_result同样属于原始视角，任意玩家胜负应按其战绩读取。",
    "single_level 为已计算个人底蕴，未授权玩家可能是0，须结合payload->>'isAuth'排除未知。阵营底蕴在生成时按授权人数折算为5人，不可直接把全部single_level相加替代。个人相对底蕴=single_level/本场所有single_level>0的均值*100；阵营差=own_level-rival_level。只覆盖已评估局，必须报告覆盖场次。",
    "battle_power_players.hero_power 是评估时该英雄战力，hero_win_rate 为0到1，hero_average_score 为采集到的历史均分；payload含starNum、peakScore、mvpRate、recentWinRate、heroShowCnt等。需要当前玩家英雄战力时使用独立工具，地区荣耀门槛使用荣耀战力工具。",
    "团队贡献系数原口径：(5*个人评分/阵营总评分)*POWER(5*个人gold/阵营总gold,-0.5)；穿学识宝石/近卫/极影等辅助装备乘0.9（payload.battleRecords.finalEquips[*].equipName）。分母非正或金钱缺失返回NULL。受益度及代表局指数不是数据库现成字段；自定义比较须解释公式，不能冒称复现完整旧指数。",
    "hero_rank_entries 的 ban_rate/show_rate/win_rate 按原API数值存储，写库未统一百分比单位；先检查样本/分布再判断0到1或0到100。不同rank_id对应不同筛选范围，不可混合；与快照用(snapshot_date,rank_id)连接。",
    "JSON路径区分大小写。先使用已知规范列；需要新增payload字段时先取少量样本/JSON键验证，不能猜测不存在字段。底蕴players与participant的participant_index来源不同，跨这两表按game_seq+role_id连接。",
]

CHAT_SQL_JSON_FIELDS = {
    "battle_participants.payload.battleStats": {
        "totalHeroHurtCnt": "对英雄伤害",
        "totalHurtCnt": "总伤害",
        "totalBeheroHurtCnt": "承受英雄伤害",
        "totalBehurtCnt": "总承伤",
        "buildingDamage": "对建筑伤害",
        "healCnt": "治疗量",
        "ctrlTime": "控制时长，来源单位需按样本核对",
        "joinGamePercent": "参团率，实库样本为0到1的字符串，取文本后转numeric",
        "hurtTransRate": "伤害转化率，实库样本含0.5、1、1.9；不是固定0到1",
        "money": "金钱，对应规范列gold",
        "fightPower": "当局英雄战力",
        "addFightPower": "当局战力变化",
        "kda": "来源KDA；比较时可由规范K/D/A列自定义聚合口径",
        "mvp": "来源MVP标记，先检查值域再判断",
        "towerCnt": "推塔数",
        "killSoldier": "补兵数",
        "monsterCoin": "野怪经济",
        "tripleKillCnt": "三杀次数",
        "UltraKillCnt": "四杀次数（U大写）",
        "rampageCnt": "五杀次数",
        "godLikeCnt": "超神次数",
    },
    "battle_participants.payload.battleRecords": {
        "position": "项目映射0对抗路、1中路、2发育路、3打野、4游走；其他值未知",
        "finalEquips": "装备对象数组；equipName为装备名",
        "usedHero": "英雄对象（heroId、heroName、heroIcon）",
        "skill": "召唤师技能对象，需查看少量样本确定子字段",
    },
    "history_players.payload": {
        "btl_aver": "当天正式对局评分均值",
        "btl_contribute_aver": "当天正式对局贡献系数均值",
        "up_tourna": "当天排位变化汇总，来源口径",
        "up_peak": "当天巅峰分变化汇总",
        "unaccessible_battles": "采集未覆盖场次信息；不能把缺失等同于未玩",
    },
    "battle_power_players.payload": {
        "isAuth": "营地授权布尔值",
        "starNum": "折算总星数",
        "peakScore": "评估时巅峰分",
        "equivStar": "用于底蕴公式的折算星级",
        "powerNum": "评估时总战斗力",
        "mvpRate": "历史MVP率（0到1）",
        "recentWinRate": "评估时近期正式场次胜率（0到1）",
        "recentAvgScore": "评估时近期正式场次评分均值",
        "heroShowCnt": "该英雄历史总场次",
        "winNum": "该英雄历史胜场",
        "loseNum": "该英雄历史败场",
        "maxHeroPower": "最高英雄战力",
        "betterHeroPower": "底蕴计算采用的高战力英雄基准",
    },
}

CHAT_SQL_EXAMPLES = [
    {
        "purpose": "查看最近有数据的日期与玩家，不伪造当前在线情况",
        "sql": "SELECT player_key, nickname, role_id, user_id, MAX(snapshot_date) AS last_date FROM hok.history_players GROUP BY player_key, nickname, role_id, user_id ORDER BY last_date DESC LIMIT 30",
    },
    {
        "purpose": "指定时间内按玩家比较正式对局评分和胜率；替换日期后执行",
        "sql": "WITH ranked AS (SELECT player_key, role_id, game_seq, hero_name, result, game_grade, ROW_NUMBER() OVER (PARTITION BY player_key, COALESCE(game_seq::text, snapshot_date::text || ':' || player_index::text || ':' || detail_index::text) ORDER BY snapshot_date DESC, detail_index DESC) AS rn FROM hok.battle_records WHERE snapshot_date >= DATE '2026-09-01' AND snapshot_date < DATE '2026-10-01' AND map_name ~ '(排位|巅峰|战队)' AND map_name !~* '(1v1|2v2|3v3)') SELECT player_key, COUNT(*) AS games, ROUND(AVG(CASE WHEN result='胜利' THEN 1.0 ELSE 0.0 END), 4) AS win_rate, ROUND(AVG(game_grade), 3) AS avg_grade FROM ranked WHERE rn=1 GROUP BY player_key ORDER BY avg_grade DESC",
    },
    {
        "purpose": "跨玩家同队/对手次数，先限定两位玩家和时期后执行",
        "sql": "SELECT a.role_id AS player_a, b.role_id AS player_b, COUNT(DISTINCT a.game_seq) FILTER (WHERE a.camp=b.camp) AS teammate_games, COUNT(DISTINCT a.game_seq) FILTER (WHERE a.camp<>b.camp) AS opponent_games FROM hok.battle_participants a JOIN hok.battle_participants b ON a.game_seq=b.game_seq AND a.role_id<b.role_id GROUP BY a.role_id,b.role_id ORDER BY teammate_games DESC LIMIT 20",
    },
    {
        "purpose": "按目标玩家而非缓存视角比较历史底蕴",
        "sql": "SELECT p.role_id, p.hero_name, p.game_seq, p.single_level, CASE WHEN p.side='my' THEN b.my_side_level ELSE b.opponent_side_level END AS own_level, CASE WHEN p.side='my' THEN b.opponent_side_level ELSE b.my_side_level END AS opponent_level FROM hok.battle_power_players p JOIN hok.battle_power b ON b.game_seq=p.game_seq WHERE p.single_level>0 ORDER BY p.game_seq DESC LIMIT 20",
    },
]


def schema_catalog():
    """Return a fresh, JSON-safe description suitable for a tool observation."""
    return {
        "dialect": "postgresql",
        "schema": "hok",
        "timezone": "Asia/Shanghai",
        "tables": deepcopy(CHAT_SQL_TABLES),
        "semantics": list(CHAT_SQL_SEMANTICS),
        "json_fields": deepcopy(CHAT_SQL_JSON_FIELDS),
        "examples": deepcopy(CHAT_SQL_EXAMPLES),
    }

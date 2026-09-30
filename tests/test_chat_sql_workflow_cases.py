"""Representative natural-language SQL workflows for the unified analysis tool."""

import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


TOOLS = import_hok_module("chat_tools")
ZFUNC = import_hok_module("zfunc")


CASES = [
    (
        "统计本赛季每个玩家的正式对局胜率，至少打了10局，按胜率从高到低。",
        """
        WITH dedup AS (
          SELECT DISTINCT ON (r.player_key, r.game_seq)
                 r.player_key, r.game_seq, r.result, r.snapshot_date
          FROM hok.battle_records AS r
          WHERE r.game_seq IS NOT NULL
            AND r.snapshot_date >= DATE '2026-07-01'
            AND r.map_name ~ '(排位|巅峰|战队)'
            AND r.map_name !~* '(1v1|2v2|3v3)'
          ORDER BY r.player_key, r.game_seq, r.snapshot_date DESC, r.detail_index DESC
        )
        SELECT d.player_key, COUNT(*) AS games,
               SUM(CASE WHEN d.result = '胜利' THEN 1 ELSE 0 END) AS wins,
               AVG(CASE WHEN d.result = '胜利' THEN 1.0 ELSE 0.0 END) AS win_rate,
               MIN(d.snapshot_date) AS first_day, MAX(d.snapshot_date) AS last_day
        FROM dedup AS d
        GROUP BY d.player_key
        HAVING COUNT(*) >= 10
        ORDER BY win_rate DESC
        """,
    ),
    (
        "谁和示例玩家41同队次数最多？给出共同场次、胜场和胜率，重复战绩只能算一局。",
        """
        WITH target AS (
          SELECT DISTINCT ON (r.role_id, r.game_seq)
                 r.role_id, r.game_seq, r.result, r.snapshot_date
          FROM hok.battle_records AS r
          WHERE r.player_key = 'example_user_5' AND r.game_seq IS NOT NULL
          ORDER BY r.role_id, r.game_seq, r.snapshot_date DESC, r.detail_index DESC
        )
        SELECT mate.role_name AS teammate, COUNT(DISTINCT t.game_seq) AS games,
               COUNT(DISTINCT CASE WHEN t.result = '胜利' THEN t.game_seq END) AS wins,
               COUNT(DISTINCT CASE WHEN t.result = '胜利' THEN t.game_seq END)::numeric
                 / NULLIF(COUNT(DISTINCT t.game_seq), 0) AS win_rate,
               MIN(t.snapshot_date) AS first_day, MAX(t.snapshot_date) AS last_day
        FROM target AS t
        JOIN hok.battle_participants AS self_p
          ON self_p.game_seq = t.game_seq AND self_p.role_id = t.role_id
        JOIN hok.battle_participants AS mate
          ON mate.game_seq = t.game_seq AND mate.camp = self_p.camp AND mate.role_id <> t.role_id
        GROUP BY mate.role_name
        ORDER BY games DESC
        """,
    ),
    (
        "比较示例玩家41和示例玩家38最近30天的常用英雄、场次、胜率和平均评分。",
        """
        WITH dedup AS (
          SELECT DISTINCT ON (r.player_key, r.game_seq)
                 r.player_key, r.game_seq, r.hero_name, r.result, r.game_grade, r.game_time_epoch
          FROM hok.battle_records AS r
          WHERE r.player_key IN ('example_user_5', 'wy')
            AND r.game_seq IS NOT NULL
            AND TO_TIMESTAMP(r.game_time_epoch) >= CURRENT_TIMESTAMP - INTERVAL '30 days'
          ORDER BY r.player_key, r.game_seq, r.snapshot_date DESC, r.detail_index DESC
        )
        SELECT d.player_key, d.hero_name, COUNT(*) AS games,
               AVG(CASE WHEN d.result = '胜利' THEN 1.0 ELSE 0.0 END) AS win_rate,
               AVG(d.game_grade) AS average_grade,
               MIN(TO_TIMESTAMP(d.game_time_epoch)) AS first_game,
               MAX(TO_TIMESTAMP(d.game_time_epoch)) AS last_game
        FROM dedup AS d
        GROUP BY d.player_key, d.hero_name
        ORDER BY d.player_key, games DESC
        """,
    ),
    (
        "找出每个玩家本赛季表现最差的三个英雄，只看至少使用5局的英雄。",
        """
        WITH dedup AS (
          SELECT DISTINCT ON (r.player_key, r.game_seq)
                 r.player_key, r.game_seq, r.hero_name, r.result, r.game_grade, r.snapshot_date
          FROM hok.battle_records AS r
          WHERE r.game_seq IS NOT NULL AND r.snapshot_date >= DATE '2026-07-01'
          ORDER BY r.player_key, r.game_seq, r.snapshot_date DESC, r.detail_index DESC
        ), aggregated AS (
          SELECT d.player_key, d.hero_name, COUNT(*) AS games,
                 AVG(CASE WHEN d.result = '胜利' THEN 1.0 ELSE 0.0 END) AS win_rate,
                 AVG(d.game_grade) AS average_grade
          FROM dedup AS d
          GROUP BY d.player_key, d.hero_name
          HAVING COUNT(*) >= 5
        ), ranked AS (
          SELECT a.player_key, a.hero_name, a.games, a.win_rate, a.average_grade,
                 ROW_NUMBER() OVER (
                   PARTITION BY a.player_key
                   ORDER BY a.win_rate ASC, a.average_grade ASC NULLS FIRST, a.games DESC
                 ) AS bad_rank
          FROM aggregated AS a
        )
        SELECT k.player_key, k.hero_name, k.games, k.win_rate, k.average_grade, k.bad_rank
        FROM ranked AS k
        WHERE k.bad_rank <= 3
        ORDER BY k.player_key, k.bad_rank
        """,
    ),
    (
        "分析游走位出辅助装和不出辅助装时的平均评分差异，并报告样本量。",
        """
        WITH roaming AS (
          SELECT p.game_seq, p.role_id, p.game_grade,
                 CASE WHEN EXISTS (
                   SELECT 1
                   FROM JSONB_ARRAY_ELEMENTS(p.payload->'battleRecords'->'finalEquips') AS equip(value)
                   WHERE equip.value->>'equipName' ~ '(学识宝石|近卫|极影)'
                 ) THEN '有辅助装' ELSE '无辅助装' END AS equipment_group
          FROM hok.battle_participants AS p
          WHERE p.payload->'battleRecords'->>'position' = '4'
        )
        SELECT r.equipment_group, COUNT(*) AS samples, AVG(r.game_grade) AS average_grade
        FROM roaming AS r
        GROUP BY r.equipment_group
        ORDER BY r.equipment_group
        """,
    ),
    (
        "统计最近半年所有玩家每个自然周的正式对局总场次趋势，并说明数据覆盖日期。",
        """
        WITH dedup AS (
          SELECT DISTINCT ON (r.player_key, r.game_seq)
                 r.player_key, r.game_seq, r.game_time_epoch
          FROM hok.battle_records AS r
          WHERE r.game_seq IS NOT NULL
            AND TO_TIMESTAMP(r.game_time_epoch) >= CURRENT_TIMESTAMP - INTERVAL '6 months'
            AND r.map_name ~ '(排位|巅峰|战队)'
            AND r.map_name !~* '(1v1|2v2|3v3)'
          ORDER BY r.player_key, r.game_seq, r.snapshot_date DESC, r.detail_index DESC
        )
        SELECT DATE_TRUNC('week', TO_TIMESTAMP(d.game_time_epoch)) AS week_start,
               COUNT(*) AS player_games, COUNT(DISTINCT d.game_seq) AS unique_games,
               MIN(TO_TIMESTAMP(d.game_time_epoch)) AS first_game,
               MAX(TO_TIMESTAMP(d.game_time_epoch)) AS last_game
        FROM dedup AS d
        GROUP BY week_start
        ORDER BY week_start
        """,
    ),
]


class NaturalLanguageSQLWorkflowTests(unittest.TestCase):
    def test_diverse_questions_use_one_validated_execution_call_each(self):
        for question, sql in CASES:
            with self.subTest(question=question):
                tools = TOOLS.HOKChatTools(original_query=question)
                discovery = tools.execute("discover_tools", {"categories": ["game_data"]})
                self.assertIn("game_data", discovery["authoritative_context"])
                self.assertEqual(tools.required_workflow_tool(["game_data"]),
                                 "analyze_game_database")
                with patch.object(
                    ZFUNC,
                    "chat_query_database",
                    return_value={"ok": True, "rows": [{"sample": 1}], "columns": ["sample"]},
                ) as execute:
                    result = tools.execute("analyze_game_database", {"queries": [
                        {"sql": sql, "intent": question, "assumptions": ["按问题所述口径"]},
                    ]})
                self.assertTrue(result["completed"], result)
                self.assertEqual(result["observations"][0]["dataset_id"], "dataset_1")
                execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()

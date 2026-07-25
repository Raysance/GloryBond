import importlib.util
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "hok" / "tools" / "representative_battle.py"
SPEC = importlib.util.spec_from_file_location("representative_battle", MODULE_PATH)
REPRESENTATIVE_BATTLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPRESENTATIVE_BATTLE)

with (PROJECT_ROOT / "variables_static.json").open(encoding="utf-8") as file:
    RULES = json.load(file)["representative_battle_rules"]


def make_battle(**overrides):
    battle = {
        "GameSeq": 10001,
        "GameGrade": 10,
        "Result": "胜利",
        "Duration_Second": 1200,
        "MapName": "排位赛",
        "KillCnt": 5,
        "DeadCnt": 3,
        "AssistCnt": 5,
        "Others": "",
    }
    battle.update(overrides)
    return battle


def make_role(
    roleid,
    camp,
    grade,
    kills,
    damage,
    taken,
    money,
    *,
    participation=0,
    mvp=0,
    godlike=0,
    multi=None,
):
    stats = {
        "gradeGame": grade,
        "killCnt": kills,
        "totalHeroHurtCnt": damage,
        "totalBeheroHurtCnt": taken,
        "money": money,
        "joinGamePercent": participation,
        "mvp": mvp,
        "godLikeCnt": godlike,
    }
    if multi:
        stats[multi] = 1
    return {
        "basicInfo": {"roleId": roleid, "acntCamp": camp},
        "battleStats": stats,
        "battleRecords": {
            "highLight": [
                {"name": "关键群控", "desc": "该字段不参与代表性评分", "times": 1},
            ],
        },
    }


def make_detail(my_role, teammates, enemies):
    return {
        "head": {"acntCamp": 1},
        "redTeam": {"acntCamp": 1},
        "redRoles": [my_role, *teammates],
        "blueRoles": enemies,
    }


class RepresentativeBattleTests(unittest.TestCase):
    def test_category_weights_apply_calibration_with_100_point_cap(self):
        categories = RULES["categories"]
        good_total = sum(item["weight"] for item in categories["good"]["factors"].values())
        bad_total = sum(item["weight"] for item in categories["bad"]["factors"].values())
        extreme_total = sum(item["weight"] for item in categories["extreme"]["factors"].values())

        self.assertEqual(RULES["score_cap"], 100)
        self.assertEqual(good_total, 100)
        self.assertEqual(bad_total, 118.5)
        self.assertEqual(extreme_total, 204)

    def test_only_verified_btlist_fields_are_normalized(self):
        keywords = REPRESENTATIVE_BATTLE.build_battle_keywords({
            "mvpcnt": 1,
            "firstBlood": 1,
            "godLikeCnt": 1,
            "hero1RampageCnt": 1,
            "evaluateUrlV2": "https://example/gold_support.png",
            "desc": "翻盘局",
        })

        self.assertEqual(keywords, "MVP 一血 超神 五连绝世")

    def test_good_match_selects_good_category_and_clear_tags(self):
        my_role = make_role(
            1, 1, 16, 15, 50000, 40000, 10000,
            participation=0.9, mvp=1, godlike=1, multi="rampageCnt",
        )
        teammates = [
            make_role(index, 1, 8, 2, 12500, 15000, 10000)
            for index in range(2, 6)
        ]
        enemies = [
            make_role(index, 2, 9, 2, 20000, 20000, 10000)
            for index in range(10, 15)
        ]
        detail = make_detail(my_role, teammates, enemies)
        battle = make_battle(
            GameGrade=16,
            KillCnt=15,
            DeadCnt=0,
            AssistCnt=10,
            Others="MVP 一血 超神 五连绝世",
        )

        result = REPRESENTATIVE_BATTLE.score_candidate(battle, detail, 1, RULES)

        self.assertEqual(result["representative_category"], "高光封神")
        self.assertLessEqual(result["score"], 100)
        self.assertIn("【高分封神】", result["tags"])
        self.assertIn("【KDA爆表】", result["tags"])
        self.assertIn("【输出拉满】", result["tags"])
        self.assertIn("【五连绝世】", result["tags"])
        self.assertTrue(all("+" not in tag for tag in result["tags"]))

    def test_bad_match_selects_bad_category(self):
        my_role = make_role(1, 1, 3, 0, 2000, 2000, 20000, participation=0.05)
        teammates = [
            make_role(index, 1, 10, 3, 20000, 20000, 8000)
            for index in range(2, 6)
        ]
        enemies = [
            make_role(index, 2, 9, 3, 18000, 18000, 10000)
            for index in range(10, 15)
        ]
        detail = make_detail(my_role, teammates, enemies)
        battle = make_battle(
            GameGrade=3,
            Result="失败",
            KillCnt=0,
            DeadCnt=12,
            AssistCnt=0,
        )

        result = REPRESENTATIVE_BATTLE.score_candidate(battle, detail, 1, RULES)

        self.assertEqual(result["representative_category"], "峡谷渡劫")
        self.assertEqual(result["score"], 100)
        self.assertEqual(
            set(result["tags"]),
            {"【低分触底】", "【队内评分掉队】", "【KDA失守】", "【吃钱不办事】", "【泉水常驻】"},
        )

    def test_extreme_match_selects_extreme_category(self):
        my_role = make_role(1, 1, 5, 2, 10000, 10000, 10000)
        teammates = [
            make_role(index, 1, 5, 2, 10000, 10000, 10000)
            for index in range(2, 6)
        ]
        enemies = [
            make_role(index, 2, 10, 2, 10000, 10000, 10000)
            for index in range(10, 15)
        ]
        detail = make_detail(my_role, teammates, enemies)
        battle = make_battle(
            GameGrade=5,
            Result="胜利",
            Duration_Second=2400,
            KillCnt=2,
            DeadCnt=4,
            AssistCnt=2,
        )

        result = REPRESENTATIVE_BATTLE.score_candidate(battle, detail, 1, RULES)

        self.assertEqual(result["representative_category"], "离谱剧本")
        self.assertEqual(result["score"], 100)
        self.assertEqual(set(result["tags"]), {"【超长膀胱局】", "【评分逆风赢了】"})

    def test_relative_grade_uses_teammate_average_and_extremes(self):
        teammates = [
            make_role(2, 1, 6, 1, 10000, 10000, 10000),
            make_role(3, 1, 8, 1, 10000, 10000, 10000),
            make_role(4, 1, 10, 1, 10000, 10000, 10000),
            make_role(5, 1, 12, 1, 10000, 10000, 10000),
        ]
        enemies = [
            make_role(index, 2, 9, 1, 10000, 10000, 10000)
            for index in range(10, 15)
        ]

        high_role = make_role(1, 1, 10.5, 1, 10000, 10000, 10000)
        high_result = REPRESENTATIVE_BATTLE.score_candidate(
            make_battle(GameGrade=10.5),
            make_detail(high_role, teammates, enemies),
            1,
            RULES,
        )
        high_factor = next(
            item
            for item in high_result["category_breakdowns"]["高光封神"]
            if item["factor"] == "队内高分C位"
        )

        low_role = make_role(1, 1, 7.5, 1, 10000, 10000, 10000)
        low_result = REPRESENTATIVE_BATTLE.score_candidate(
            make_battle(GameGrade=7.5),
            make_detail(low_role, teammates, enemies),
            1,
            RULES,
        )
        low_factor = next(
            item
            for item in low_result["category_breakdowns"]["峡谷渡劫"]
            if item["factor"] == "队内评分掉队"
        )

        self.assertEqual(high_result["detail_metrics"]["TeammateAverageGrade"], 9)
        self.assertEqual(high_result["detail_metrics"]["HighRelativeGradePercent"], 50)
        self.assertEqual(high_factor["contribution"], 7.5)
        self.assertEqual(low_result["detail_metrics"]["LowRelativeGradePercent"], 50)
        self.assertEqual(low_factor["contribution"], 11.85)

    def test_unconfigured_json_content_does_not_create_tags(self):
        battle = make_battle(Others="关键抢夺 团灭 躺赢 First Blood")
        result = REPRESENTATIVE_BATTLE.score_candidate(battle, None, 1, RULES)
        all_factors = {
            item["factor"]
            for breakdown in result["category_breakdowns"].values()
            for item in breakdown
        }

        self.assertNotIn("关键抢夺", all_factors)
        self.assertNotIn("团灭", all_factors)
        self.assertNotIn("躺赢", all_factors)

    def test_official_detail_example_uses_only_configured_factors(self):
        detail = json.loads(
            (PROJECT_ROOT / "resources" / "wzry_data_format" / "btldetail.json").read_text(encoding="utf-8")
        )
        head = detail["head"]
        battle = {
            "GameSeq": 1,
            "GameGrade": head["gradeGame"],
            "Result": "胜利" if head["gameResult"] else "失败",
            "Duration_Second": detail["battle"]["usedTime"],
            "MapName": head["mapName"],
            "KillCnt": head["killCnt"],
            "DeadCnt": head["deadCnt"],
            "AssistCnt": head["assistCnt"],
            "Others": "",
        }
        result = REPRESENTATIVE_BATTLE.score_candidate(battle, detail, head["roleId"], RULES)
        configured_labels = {
            item.get("label")
            for category in RULES["categories"].values()
            for item in category["factors"].values()
            if item.get("label")
        }
        configured_labels.update({
            RULES["categories"]["extreme"]["factors"]["duration"]["long_label"],
            RULES["categories"]["extreme"]["factors"]["duration"]["short_label"],
            RULES["categories"]["extreme"]["factors"]["result_grade_contradiction"]["win_label"],
            RULES["categories"]["extreme"]["factors"]["result_grade_contradiction"]["loss_label"],
        })
        actual_labels = {
            item["factor"]
            for breakdown in result["category_breakdowns"].values()
            for item in breakdown
        }

        self.assertTrue(result["has_detail"])
        self.assertTrue(all(0 <= score <= 100 for score in result["category_scores"].values()))
        self.assertTrue(actual_labels <= configured_labels)
        self.assertNotIn("关键群控", actual_labels)

    def test_hard_filters_reject_invalid_duration(self):
        eligible, reasons = REPRESENTATIVE_BATTLE.validate_candidate(
            make_battle(Duration_Second=120),
            RULES,
        )

        self.assertFalse(eligible)
        self.assertIn("时长低于300秒", reasons)

    def test_ranking_key_is_deterministic_after_score(self):
        first = {
            "RepScore": 80,
            "ScoreBreakdown": [{}, {}],
            "HasDetail": True,
            "Grade": 10,
            "Duration": 1000,
            "GameTimeTimestamp": 1,
        }
        second = {
            "RepScore": 80,
            "ScoreBreakdown": [{}, {}, {}],
            "HasDetail": True,
            "Grade": 9,
            "Duration": 900,
            "GameTimeTimestamp": 2,
        }

        self.assertGreater(
            REPRESENTATIVE_BATTLE.ranking_key(second),
            REPRESENTATIVE_BATTLE.ranking_key(first),
        )


if __name__ == "__main__":
    unittest.main()

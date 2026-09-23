import unittest

from local_debugger import import_hok_module


BATTLE_DETAIL = import_hok_module("business.battle_detail")
GEN_BATTLE = import_hok_module("tools.gen_battle_res")
ZFILE = import_hok_module("zfile")
ZFUNC = import_hok_module("zfunc")


class FakeAnalyses:
    @staticmethod
    def get_extreme_data(time_gap):
        return [4.2, 12.3456, "bob", "alice", "英雄B", "英雄A"]


class BattleDetailBusinessTests(unittest.TestCase):
    def test_view_process_formats_extreme_scores(self):
        original_analyses = ZFUNC.Analyses
        original_namenick = BATTLE_DETAIL.namenick
        ZFUNC.Analyses = FakeAnalyses
        BATTLE_DETAIL.namenick = {"alice": "Alice", "bob": "Bob"}
        try:
            result = ZFUNC.view_process("e", time_gap=5)
        finally:
            ZFUNC.Analyses = original_analyses
            BATTLE_DETAIL.namenick = original_namenick

        self.assertIn("近5天最高最低评分", result)
        self.assertIn("↑Alice的英雄A：12.346分", result)
        self.assertIn("↓Bob的英雄B：4.2分", result)

    def test_battle_detail_keeps_link_image_and_related_player_text(self):
        originals = {
            "userlist": BATTLE_DETAIL.userlist,
            "extra_useridlist": BATTLE_DETAIL.extra_useridlist,
            "namenick": BATTLE_DETAIL.namenick,
            "extra_namenick": BATTLE_DETAIL.extra_namenick,
            "fetch": ZFUNC.fetch_battle,
            "check": ZFUNC.check_btl_official_with_matching,
            "contribution": ZFUNC.calculate_battle_contribution_factor,
            "make_hash": ZFUNC.WebArtifacts.__dict__["make_hash"],
            "route_link": ZFUNC.WebArtifacts.__dict__["history_route_link"],
            "web_path": ZFILE.web_history_json_path,
            "image_path": ZFILE.battle_exhibit_image_path,
            "writer": ZFILE.writerl,
            "generator": GEN_BATTLE.generate_battle_ui_image,
        }
        BATTLE_DETAIL.userlist = {"alice": 1, "bob": 2}
        BATTLE_DETAIL.extra_useridlist = {}
        BATTLE_DETAIL.namenick = {"alice": "Alice", "bob": "Bob"}
        BATTLE_DETAIL.extra_namenick = {}
        battle = {
            "head": {
                "mapName": "排位赛",
                "acntCamp": 1,
                "userId": 1,
                "gameResult": True,
                "roleName": "Alice",
                "heroName": "赵云",
                "killCnt": 5,
                "deadCnt": 2,
                "assistCnt": 8,
                "gradeGame": 10.5,
            },
            "battle": {"dtEventTime": "2026-09-23 20:00"},
            "redTeam": {"acntCamp": 1},
            "redRoles": [
                {"basicInfo": {"userId": 1}, "battleStats": {"gradeGame": 10.5}},
                {"basicInfo": {"userId": 2}, "battleStats": {"gradeGame": 8.0}},
            ],
            "blueRoles": [],
        }
        writes = []
        images = []
        ZFUNC.fetch_battle = lambda gameseq, roleid=0: battle
        ZFUNC.check_btl_official_with_matching = lambda map_name: True
        ZFUNC.calculate_battle_contribution_factor = lambda result: 1.234
        ZFUNC.WebArtifacts.make_hash = staticmethod(lambda seed=None: "fixed")
        ZFUNC.WebArtifacts.history_route_link = staticmethod(
            lambda *args, **kwargs: "https://example/battle"
        )
        ZFILE.web_history_json_path = lambda key: "/tmp/fixed.json"
        ZFILE.battle_exhibit_image_path = lambda: "/tmp/exhibit.png"
        ZFILE.writerl = lambda path, payload: writes.append((path, payload))
        GEN_BATTLE.generate_battle_ui_image = (
            lambda source, target: images.append((source, target))
        )
        try:
            message, image_path, map_name = ZFUNC.btldetail_process(
                "1",
                "2",
                "3",
                "4",
                111,
                gen_image=True,
            )
        finally:
            BATTLE_DETAIL.userlist = originals["userlist"]
            BATTLE_DETAIL.extra_useridlist = originals["extra_useridlist"]
            BATTLE_DETAIL.namenick = originals["namenick"]
            BATTLE_DETAIL.extra_namenick = originals["extra_namenick"]
            ZFUNC.fetch_battle = originals["fetch"]
            ZFUNC.check_btl_official_with_matching = originals["check"]
            ZFUNC.calculate_battle_contribution_factor = originals["contribution"]
            ZFUNC.WebArtifacts.make_hash = originals["make_hash"]
            ZFUNC.WebArtifacts.history_route_link = originals["route_link"]
            ZFILE.web_history_json_path = originals["web_path"]
            ZFILE.battle_exhibit_image_path = originals["image_path"]
            ZFILE.writerl = originals["writer"]
            GEN_BATTLE.generate_battle_ui_image = originals["generator"]

        self.assertEqual(map_name, "排位赛")
        self.assertEqual(image_path, "/tmp/exhibit.png")
        self.assertIn("最后一局 🏆 贡献: 1.23", message)
        self.assertIn("With: Bob(8.0)", message)
        self.assertIn("https://example/battle", message)
        self.assertEqual(writes, [("/tmp/fixed.json", battle)])
        self.assertEqual(images, [("/tmp/fixed.json", "/tmp/exhibit.png")])


if __name__ == "__main__":
    unittest.main()

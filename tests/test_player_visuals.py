import sys
import types
import unittest

from local_debugger import import_hok_module


PLAYER_VISUALS = import_hok_module("business.player_visuals")
ZFILE = import_hok_module("zfile")
ZFUNC = import_hok_module("zfunc")


class FakeListener:
    instances = []

    def __init__(self, stream_url, *, save_path, roleid):
        self.stream_url = stream_url
        self.save_path = save_path
        self.roleid = roleid
        self.started = False
        self.captured = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def screenshot(self):
        self.captured = True

    def stop(self):
        self.stopped = True


class PlayerVisualTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "userlist": PLAYER_VISUALS.userlist,
            "roleidlist": PLAYER_VISUALS.roleidlist,
            "namenick": PLAYER_VISUALS.namenick,
        }
        PLAYER_VISUALS.userlist = {"alice": 11}
        PLAYER_VISUALS.roleidlist = {"alice": 111}
        PLAYER_VISUALS.namenick = {"alice": "Alice"}

    def tearDown(self):
        PLAYER_VISUALS.userlist = self.originals["userlist"]
        PLAYER_VISUALS.roleidlist = self.originals["roleidlist"]
        PLAYER_VISUALS.namenick = self.originals["namenick"]

    def test_grade_chart_uses_filtered_history_and_zfile_paths(self):
        originals = {
            "fetch": ZFUNC.fetch_history,
            "paths": ZFILE.grade_chart_output_paths,
        }
        module_name = "hok.tools.gen_grade_chart"
        original_module = sys.modules.get(module_name)
        grade_chart = types.ModuleType(module_name)
        calls = []
        ZFUNC.fetch_history = lambda **kwargs: ({"alice": [{"GameSeq": "1"}]}, 1)
        ZFILE.grade_chart_output_paths = lambda: (
            "/tmp/chart/grade_chart.png",
            "/tmp/chart",
        )
        grade_chart.gen_from_history = (
            lambda *args: calls.append(args) or "分析完成"
        )
        sys.modules[module_name] = grade_chart
        try:
            result = ZFUNC.gradeanalyze_process("alice")
        finally:
            ZFUNC.fetch_history = originals["fetch"]
            ZFILE.grade_chart_output_paths = originals["paths"]
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module

        self.assertEqual(result, ("/tmp/chart/grade_chart.png", "分析完成"))
        self.assertEqual(calls[0][0:2], (11, "Alice"))
        self.assertEqual(calls[0][2], [{"GameSeq": "1"}])
        self.assertEqual(calls[0][3], "/tmp/chart")

    def test_watchbattle_replaces_listener_and_takes_screenshot(self):
        originals = {
            "official": ZFUNC.wzry_get_official,
            "path": ZFILE.watch_battle_shot_path,
            "runtime_listener": PLAYER_VISUALS.dmc.RTMPListener,
            "stream": PLAYER_VISUALS.dmc.streamurl,
        }
        module_name = "hok.tools.gen_battle_shot"
        original_module = sys.modules.get(module_name)
        battle_shot = types.ModuleType(module_name)
        battle_shot.RTMPListener = FakeListener
        sys.modules[module_name] = battle_shot
        old_listener = FakeListener("old", save_path="/tmp/old.png", roleid=1)
        FakeListener.instances = []
        PLAYER_VISUALS.dmc.RTMPListener = old_listener
        PLAYER_VISUALS.dmc.streamurl = "rtmp://example/live"
        ZFUNC.wzry_get_official = lambda **kwargs: {
            "isGaming": True,
            "gaming": {
                "canBeWatch": True,
                "battleId": "battle",
                "mapName": "排位赛",
                "duration": 5,
            },
        }
        ZFILE.watch_battle_shot_path = lambda roleid: "/tmp/watch.png"
        try:
            result = ZFUNC.watchbattle_process("alice")
            new_listener = PLAYER_VISUALS.dmc.RTMPListener
        finally:
            ZFUNC.wzry_get_official = originals["official"]
            ZFILE.watch_battle_shot_path = originals["path"]
            PLAYER_VISUALS.dmc.RTMPListener = originals["runtime_listener"]
            PLAYER_VISUALS.dmc.streamurl = originals["stream"]
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module

        self.assertTrue(old_listener.stopped)
        self.assertTrue(new_listener.started)
        self.assertTrue(new_listener.captured)
        self.assertEqual(result, ("/tmp/watch.png", None))


if __name__ == "__main__":
    unittest.main()

import sys
import types
import unittest

from local_debugger import import_hok_module


BATTLE_VISIBILITY = import_hok_module("business.battle_visibility")
ZFUNC = import_hok_module("zfunc")


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, **kwargs):
        self.values[key] = value
        return True


class BattleVisibilityTests(unittest.TestCase):
    def test_resolve_visibility_qids_includes_aliases_and_deduplicates(self):
        target_qids, missing_names = BATTLE_VISIBILITY.resolve_visibility_qids(
            "alice-alt",
            {"alice": ["alice-alt", "alice-mobile"]},
            {
                "alice": "10001",
                "alice-alt": "10001",
                "alice-mobile": "10002",
            },
        )

        self.assertEqual(target_qids, ["10001", "10002"])
        self.assertEqual(missing_names, [])

    def test_resolve_visibility_qids_reports_missing_aliases(self):
        target_qids, missing_names = BATTLE_VISIBILITY.resolve_visibility_qids(
            "alice",
            {"alice": ["alice-alt"]},
            {"alice": "10001"},
        )

        self.assertEqual(target_qids, ["10001"])
        self.assertEqual(missing_names, ["alice-alt"])

    def test_invisible_adds_only_new_targets(self):
        updated, changed = BATTLE_VISIBILITY.update_disabled_qids(
            ["10001", "20001"],
            ["10001", "10002"],
            visible=False,
        )

        self.assertEqual(updated, ["10001", "20001", "10002"])
        self.assertEqual(changed, ["10002"])

    def test_visible_removes_all_related_targets(self):
        updated, changed = BATTLE_VISIBILITY.update_disabled_qids(
            ["10001", "10002", "20001"],
            ["10001", "10002"],
            visible=True,
        )

        self.assertEqual(updated, ["20001"])
        self.assertEqual(changed, ["10001", "10002"])

    def test_sync_keeps_redis_and_group_ban_side_effects_in_zfunc(self):
        originals = {
            "redis": ZFUNC.dmc.redis_deamon,
            "qid": ZFUNC.qid,
            "sameuser": ZFUNC.sameuser,
        }
        calls = []
        module_name = "hok.utils.message_sender"
        original_message_sender = sys.modules.get(module_name)
        message_sender = types.ModuleType(module_name)
        message_sender.BATTLE_INVISIBLE_MUTE_SECONDS = 60
        message_sender.add_group_ban_task = lambda user_qid, **kwargs: calls.append(
            (user_qid, kwargs)
        )
        sys.modules[module_name] = message_sender
        ZFUNC.dmc.redis_deamon = FakeRedis()
        ZFUNC.qid = {"alice": "10001", "alice-alt": "10002"}
        ZFUNC.sameuser = {"alice": ["alice-alt"]}
        try:
            changed = ZFUNC.sync_battle_visibility_state("alice", False)
            stored = ZFUNC.get_battle_invisible_disabled_qids()
        finally:
            ZFUNC.dmc.redis_deamon = originals["redis"]
            ZFUNC.qid = originals["qid"]
            ZFUNC.sameuser = originals["sameuser"]
            if original_message_sender is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_message_sender

        self.assertEqual(changed, ["10001", "10002"])
        self.assertEqual(stored, ["10001", "10002"])
        self.assertEqual([user_qid for user_qid, _ in calls], ["10001", "10002"])
        self.assertTrue(all(call[1]["duration"] > 0 for call in calls))
        self.assertTrue(
            all(
                call[1]["source"] == "battle_visibility:alice:invisible"
                for call in calls
            )
        )


if __name__ == "__main__":
    unittest.main()

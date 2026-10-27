"""Binding decisions retain verified identity and never guess between platforms."""
import unittest
from scripts.resolve_player_client import select_candidate


class BindingSelectionTests(unittest.TestCase):
    def setUp(self):
        self.android = dict(nickname="甲", uid=1, logic_world_id=10, platform=1, fake_description_id=0)
        self.ios = dict(nickname="甲", uid=2, logic_world_id=20, platform=2, fake_description_id=0)

    def test_new_binding_requires_one_full_nickname_match(self):
        self.assertEqual(select_candidate({"candidates": [self.ios]}, "甲")[0], self.ios)
        self.assertIsNone(select_candidate({"candidates": [self.android, self.ios]}, "甲")[0])
        self.assertIsNone(select_candidate({"candidates": [self.ios]}, "相似昵称")[0])

    def test_existing_reference_disambiguates_by_identity_without_replacement(self):
        self.assertEqual(select_candidate({"candidates": [self.android, self.ios]}, "甲", self.android)[0], self.android)
        self.assertIsNone(select_candidate({"candidates": [self.ios]}, "甲", self.android)[0])

    def test_fake_context_is_refreshed_from_returned_candidate(self):
        latest = {**self.android, "fake_description_id": 321}
        self.assertEqual(select_candidate({"candidates": [latest]}, "甲", self.android)[0]["fake_description_id"], 321)

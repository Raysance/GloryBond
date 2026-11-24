"""Bot and Web delegate to a reusable SDK client without owning wire protocols."""
import ast
import importlib
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from shared import camp


class CampBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.old = camp._client
        self.old_path = camp._client_path
        self.addCleanup(setattr, camp, "_client_path", self.old_path)
        camp._client = None
        self.addCleanup(setattr, camp, "_client", self.old)
        self.client = Mock()
        factory = patch.object(camp, "CampClient", return_value=self.client)
        self.factory = factory.start()
        self.addCleanup(factory.stop)

    def test_all_old_call_names_route_to_named_sdk_operations(self):
        mapping = {"btlist": "get_battle_list", "btlist_url": "get_battle_list",
                   "btldetail": "get_battle_detail", "profile": "get_player_profile",
                   "season": "get_current_season", "heropower": "get_hero_power",
                   "allhero": "get_heroes", "herostatistics": "get_hero_statistics",
                   "heroranklist": "get_hero_rankings", "honorranklist": "get_honor_rankings",
                   "watchbattle": "get_watch_battle_info"}
        for name, method in mapping.items():
            with self.subTest(name=name):
                getattr(self.client, method).return_value = {"result": name}
                self.assertEqual(camp.query("/private/camp.json", name, userid=1001, roleid=42), {"result": name})
        self.factory.assert_called_once_with(state_file=Path("/private/camp.json"), timeout=30, trust_env=False)
        self.assertEqual(self.client.reload_session.call_count, len(mapping)-1)

    def test_hot_reload_and_cursor_keep_same_instance(self):
        camp.query("/private/camp.json", "btlist", userid=1001, roleid=42, last_time="1700000000")
        camp.query("/private/camp.json", "btlist_url", userid=1001, roleid=42, last_time="1700000010")
        self.factory.assert_called_once()
        self.client.reload_session.assert_called_once_with()
        self.client.get_battle_list.assert_called_with(1001, 42, last_time="1700000010")

    def test_failure_is_not_retried_and_public_close_is_used(self):
        self.client.get_current_season.side_effect = TimeoutError("offline")
        with self.assertRaises(TimeoutError):
            camp.query("/private/camp.json", "season", roleid=42)
        self.client.get_current_season.assert_called_once_with(42)
        camp.close()
        self.client.close.assert_called_once()
        self.assertIsNone(camp._client)

    def test_wire_protocols_and_crypto_have_no_host_copies(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("hok/api_adapters/wzry.py", "web/utils.py", "shared/camp.py"):
            text = (root/name).read_text()
            for literal in ("kohcamp.qq.com", "kohsocialapp.qq.com", "encodeParam", "decrypt_game_data"):
                self.assertNotIn(literal, text, name)
        for name in ("hok/tools/endecoder.py", "web/tools/endecoder.py"):
            self.assertFalse((root/name).exists())
        source = (root/"login_console/providers.py").read_text()
        tree = ast.parse(source)
        provider = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Camp")
        segment = ast.get_source_segment(source, provider)
        for private in ("._post", "._qr", "._state", ".http", "export_session", "session_from_config", "HOK_CAMP_SESSION_JSON"):
            self.assertNotIn(private, segment)


if __name__ == "__main__":
    unittest.main()

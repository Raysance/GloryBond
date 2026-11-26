import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

spec = importlib.util.spec_from_file_location(
    "clash_watchdog", Path(__file__).resolve().parents[1] / "deployment/server_modules/clash_watchdog.py")
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"selector": "Main", "fallback": "Auto", "binary": "/clash"}
        self.current = {
            "secret": "local-controller-secret", "port": 7890,
            "external-ui": "/local/dashboard", "rules": ["MATCH,Main"],
            "dns": {"enable": True}, "unknown-key": {"preserve": True},
            "proxies": [{"name": "old", "type": "ss"}],
            "proxy-groups": [{"name": "Main", "type": "select", "proxies": ["old"]}],
        }
        self.remote = {
            "secret": "untrusted", "port": 1234, "rules": ["MATCH,DIRECT"],
            "proxies": [{"name": "日本 A", "type": "ss"}, {"name": "新加坡 A", "type": "ss"}],
            "proxy-groups": [{"name": "Main", "type": "select", "proxies": ["日本 A", "新加坡 A"]}],
        }

    def test_refresh_preserves_host_policy_and_prefers_regions(self):
        before = copy.deepcopy(self.current)
        result = watchdog.merge_subscription(self.current, self.remote, self.settings)
        self.assertEqual(before, self.current)
        for key in ("secret", "port", "rules", "external-ui", "dns", "unknown-key"):
            self.assertEqual(result[key], before[key])
        self.assertEqual(result["proxy-groups"][0]["proxies"][0], "Auto")
        self.assertEqual(result["proxy-groups"][-1]["proxies"], ["新加坡 A", "日本 A"])
        self.assertEqual(result["proxy-groups"][-1]["interval"], 300)
        self.assertEqual(watchdog.merge_subscription(result, self.remote, self.settings), result)

    def test_reject_empty_duplicate_and_dangling_members(self):
        for remote in ({"proxies": []}, {"proxies": [{"name": "a"}, {"name": "a"}]}):
            with self.assertRaises(ValueError):
                watchdog.merge_subscription(self.current, remote, self.settings)
        self.current["proxy-groups"].append({"name": "Custom", "proxies": ["old"]})
        with self.assertRaises(ValueError):
            watchdog.merge_subscription(self.current, self.remote, self.settings)

    def test_rejected_validation_does_not_touch_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(self.current))
            previous = path.read_bytes()
            with patch.object(watchdog.subprocess, "run", side_effect=RuntimeError("bad config")):
                with self.assertRaises(RuntimeError):
                    watchdog.install_candidate(path, self.remote, self.settings, Mock())
            self.assertEqual(path.read_bytes(), previous)
            self.assertFalse(list(path.parent.glob(".candidate-*")))

    def test_failed_activation_restores_disk_and_reloads_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(self.current))
            previous = path.read_bytes()
            controller = Mock()
            controller.reload.side_effect = [RuntimeError("reload failed"), None]
            with patch.object(watchdog.subprocess, "run"):
                with self.assertRaises(RuntimeError):
                    watchdog.install_candidate(path, self.remote, self.settings, controller)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(controller.reload.call_count, 2)
            self.assertEqual(len(list((path.parent / "backups").glob("*.yaml"))), 1)

    def test_cooldown_and_daily_refresh(self):
        state = {"last_refresh": 100000, "last_attempt": 100000}
        self.assertFalse(watchdog.refresh_due(state, 100100, False))
        self.assertTrue(watchdog.refresh_due(state, 103600, False))
        self.assertFalse(watchdog.refresh_due(state, 103600, True))
        self.assertTrue(watchdog.refresh_due(state, 186400, True))

    def test_subscription_env_is_parsed_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('export CLASH_URL="https://example.test/sub?token=private"\n')
            self.assertEqual(watchdog.read_subscription_url(path), "https://example.test/sub?token=private")
            path.write_text('export CLASH_URL="http://example.test/sub"\n')
            with self.assertRaises(ValueError):
                watchdog.read_subscription_url(path)


if __name__ == "__main__":
    unittest.main()

"""Withdrawal markers and the optional native bridge use stable, bounded state."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from glorybond.storage.chat_cancellations import normalize_key, record_recall, was_recalled
from deployment.scripts.sync_napcat_recall import sync


class CancellationStorageTests(unittest.TestCase):
    def test_markers_are_scope_bound_and_duplicate_notices_do_not_extend_expiry(self):
        key = ("300", "group", "200", "101", "-42")
        store = Mock()
        record_recall(key, store=store)
        marker = store.set.call_args.args[0]
        self.assertEqual(store.set.call_args.kwargs, {"ex": 86400, "nx": True})
        self.assertNotIn("300:group:200:101", marker)
        store.exists.return_value = 1
        self.assertTrue(was_recalled(list(key), store=store))
        self.assertEqual(store.exists.call_args.args[0], marker)
        was_recalled(("301", *key[1:]), store=store)
        self.assertNotEqual(store.exists.call_args.args[0], marker)
        self.assertIsNone(normalize_key(("300", "private", "200", "101", "42")))
        self.assertIsNone(normalize_key(("300", "group", "200", "101", "0")))


class NativeBridgeDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.native = self.root / "native"
        self.native.mkdir()
        (self.native / "napcat.mjs").write_text("// existing installation")
        self.plugin = self.native / "plugins/glorybond_recall.mjs"
        self.source = self.root / "src/glorybond/integrations/napcat_recall.mjs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("export function plugin_init() {}")
        (self.root / "config.yaml").write_text("QQAgent:\n  napcat_plugin_directory: " + str(self.plugin.parent) + "\n")

    def test_first_install_and_changed_source_restart_but_unchanged_deploy_does_not(self):
        with patch("deployment.scripts.sync_napcat_recall.subprocess.run") as run:
            self.assertTrue(sync(self.root, restart=True)["restarted"])
            self.assertEqual(self.plugin.resolve(), self.source.resolve())
            self.assertFalse(sync(self.root, restart=True)["restarted"])
            self.source.write_text("export function plugin_init() { return 1; }")
            self.assertTrue(sync(self.root, restart=True)["restarted"])
        self.assertEqual(sum(call.args[0][0] == "systemctl" for call in run.call_args_list), 2)

    def test_foreign_files_and_symlinks_are_never_replaced(self):
        self.plugin.parent.mkdir()
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                if foreign:
                    self.plugin.symlink_to(self.root / "missing-third-party-plugin.mjs")
                else:
                    self.plugin.write_text("unrelated")
                with patch("deployment.scripts.sync_napcat_recall.subprocess.run"), self.assertRaises(ValueError):
                    sync(self.root, restart=True)
                self.plugin.unlink()

    def test_unconfigured_hosts_do_not_touch_napcat(self):
        (self.root / "config.yaml").write_text("QQAgent: {}\n")
        with patch("deployment.scripts.sync_napcat_recall.subprocess.run") as run:
            self.assertFalse(sync(self.root, restart=True)["enabled"])
        run.assert_not_called()

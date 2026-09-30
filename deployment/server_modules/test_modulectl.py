"""Offline checks for private module exports and namespace-limited snapshots."""

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

import modulectl
import snapshot_hok


class ModuleControlTests(unittest.TestCase):
    def test_export_is_private_filtered_and_checksums_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = root / "personal-site"
            module.mkdir()
            manifest = {"name": "personal-site", "target": "personal-site.target", "members": ["site.service"], "shared_dependencies": ["nginx.service"]}
            (module / "module.json").write_text(json.dumps(manifest))
            for relative in ["apps/index.html", "config/private.env", "apps/.git/config", "apps/.venv/bin/python", "apps/site/node_modules/library.js", "apps/vendor/node_modules/runtime.js", "logs/live.log", "logs/nbot/errors/error.log", "backups/previous/old.dump", "apps/runtime-assets.tar.gz", "apps/runtime-assets.zip", "apps/__pycache__/cache.pyc"]:
                path = module / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture contents")
            (module / "current").symlink_to("apps/index.html")
            (module / "apps/log").symlink_to("../logs/nbot")
            os.link(module / "apps/index.html", module / "apps/index-copy.html")
            args = argparse.Namespace(output_dir=root / "exports", snapshot_python=None, pg_dump=None)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(modulectl.export_module(module, manifest, args), 0)
            bundle = next(args.output_dir.glob("*.tar.gz"))
            self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
            self.assertEqual(args.output_dir.stat().st_mode & 0o777, 0o700)
            expected_digest = bundle.with_name(bundle.name + ".sha256").read_text().split()[0]
            self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), expected_digest)
            with tarfile.open(bundle) as archive:
                names = archive.getnames()
                self.assertIn("personal-site/config/private.env", names)
                self.assertIn("personal-site/apps/index.html", names)
                self.assertIn("personal-site/apps/index-copy.html", names)
                self.assertIn("personal-site/apps/runtime-assets.tar.gz", names)
                self.assertIn("personal-site/apps/runtime-assets.zip", names)
                self.assertIn("personal-site/apps/vendor/node_modules/runtime.js", names)
                self.assertIn("personal-site/logs/nbot/errors", names)
                self.assertIn("personal-site/backups/previous", names)
                self.assertTrue(archive.getmember("personal-site/current").issym())
                self.assertTrue(archive.getmember("personal-site/apps/log").issym())
                for unwanted in [".git", ".venv", "apps/site/node_modules", "__pycache__", "old.dump", "live.log", "error.log"]:
                    self.assertFalse(any(unwanted in name for name in names), unwanted)
                metadata = json.load(archive.extractfile("personal-site/export-manifest.json"))
                self.assertEqual(metadata["capture_mode"], "live")
                self.assertEqual(metadata["entry_count"], len(names) - 1)
                for entry in metadata["entries"]:
                    if entry["type"] == "file":
                        self.assertEqual(hashlib.sha256(archive.extractfile(entry["path"]).read()).hexdigest(), entry["sha256"])

    def test_hok_keeps_napcat_bundled_node_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = root / "hok"
            relative = Path("apps/napcat/opt/QQ/resources/app/app_launcher/napcat/node_modules/vendor/node_modules/nested/runtime.js")
            asset = module / relative
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"bundled runtime dependency")
            inventory = []
            bundle = root / "fixture.tar"
            with tarfile.open(bundle, "w") as archive:
                modulectl.add_tree(archive, module, "hok", inventory)
            with tarfile.open(bundle) as archive:
                self.assertEqual(archive.extractfile(f"hok/{relative.as_posix()}").read(), b"bundled runtime dependency")
            self.assertTrue(any(entry["path"] == f"hok/{relative.as_posix()}" for entry in inventory))

    def test_vendor_subtree_preserves_names_that_are_usually_filtered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = root / "hok"
            vendor = Path("apps/napcat/opt/QQ/resources/app/app_launcher/napcat/node_modules")
            assets = ["log/index.js", "logs/index.js", "snapshots/current.json", "vendor/.git/metadata", "vendor/.venv/runtime.py", "vendor/__pycache__/runtime.pyc", "backups/index.js"]
            for relative in assets:
                path = module / vendor / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"required vendor contents")
            inventory = []
            bundle = root / "fixture.tar"
            with tarfile.open(bundle, "w") as archive:
                modulectl.add_tree(archive, module, "hok", inventory)
            with tarfile.open(bundle) as archive:
                for relative in assets:
                    with self.subTest(relative=relative):
                        self.assertEqual(archive.extractfile(f"hok/{vendor.as_posix()}/{relative}").read(), b"required vendor contents")

    def test_start_does_not_accept_active_target_with_failed_member(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service", "hok-cleanup.timer"], "shared_dependencies": ["redis.service"]}
        with patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl, "unit_state", side_effect=["active", "failed", "active", "active"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "terminal unit state"):
                modulectl.control("start", manifest)
            run.assert_called_once_with(["systemctl", "start", "hok.target"], check=True)

    def test_control_commands_wait_for_all_members_to_settle(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        for action in ("start", "stop", "restart"):
            with self.subTest(action=action):
                transition = "deactivating" if action == "stop" else "activating"
                final = "inactive" if action == "stop" else "active"
                states = [transition, transition, final, final, "active"]
                with patch.object(modulectl, "unit_state", side_effect=states), patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl.time, "sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(modulectl.control(action, manifest, wait_timeout=15), 0)
                    self.assertEqual(sleep.call_count, 1)
                    run.assert_called_once_with(["systemctl", action, "hok.target"], check=True)

    def test_status_does_not_wait_for_transitions(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        with patch.object(modulectl, "unit_state", side_effect=["active", "activating", "active"]), patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl, "wait_for_units") as wait, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(modulectl.control("status", manifest), 1)
            wait.assert_not_called()
            run.assert_not_called()

    def test_stop_does_not_accept_failed_member_as_stopped(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        with patch.object(modulectl, "unit_state", side_effect=["inactive", "failed"]), patch.object(modulectl.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Module stop did not reach inactive.*failed"):
                modulectl.control("stop", manifest)
            run.assert_called_once_with(["systemctl", "stop", "hok.target"], check=True)

    def test_rejects_world_readable_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "public"
            path.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                modulectl.private_directory(path)

    def test_quiesce_pauses_only_target_and_restores_after_export_failure(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        states = ["active", "active", "inactive", "inactive", "active", "active"]
        with patch.object(modulectl, "unit_state", side_effect=states), patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl, "export_module", side_effect=RuntimeError("fixture export failed")), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "fixture export failed"):
                modulectl.quiesced_export(Path("/fixture/hok"), manifest, argparse.Namespace())
            self.assertEqual([call.args[0] for call in run.call_args_list], [["systemctl", "stop", "hok.target"], ["systemctl", "start", "hok.target"]])

    def test_quiesce_keeps_previously_stopped_module_stopped(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        with patch.object(modulectl, "unit_state", return_value="inactive"), patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl, "export_module", return_value=0) as export:
            self.assertEqual(modulectl.quiesced_export(Path("/fixture/hok"), manifest, argparse.Namespace()), 0)
            run.assert_not_called()
            self.assertFalse(export.call_args.kwargs["capture"]["restore_active"])

    def test_quiesced_archive_records_capture_mode_and_initial_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = root / "personal-site"
            module.mkdir()
            manifest = {"name": "personal-site", "target": "personal-site.target", "members": ["site.service"], "shared_dependencies": ["nginx.service"]}
            (module / "module.json").write_text(json.dumps(manifest))
            args = argparse.Namespace(output_dir=root / "exports", snapshot_python=None, pg_dump=None)
            with patch.object(modulectl, "unit_state", return_value="inactive"), patch.object(modulectl.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(modulectl.quiesced_export(module, manifest, args), 0)
                run.assert_not_called()
            with tarfile.open(next(args.output_dir.glob("*.tar.gz"))) as archive:
                metadata = json.load(archive.extractfile("personal-site/export-manifest.json"))
                self.assertEqual(metadata["capture_mode"], "quiesced")
                self.assertEqual(metadata["quiesce"]["initial_states"], {"personal-site.target": "inactive", "site.service": "inactive"})
                self.assertFalse(metadata["quiesce"]["restore_active"])

    def test_quiesce_rejects_mixed_states_without_stopping_anything(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        with patch.object(modulectl, "unit_state", side_effect=["active", "inactive"]), patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl, "export_module") as export:
            with self.assertRaisesRegex(RuntimeError, "all target/member units"):
                modulectl.quiesced_export(Path("/fixture/hok"), manifest, argparse.Namespace())
            run.assert_not_called()
            export.assert_not_called()

    def test_quiesce_cancels_export_if_stop_fails_and_attempts_restoration(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        states = ["active", "active", "inactive", "failed", "active", "active"]
        with patch.object(modulectl, "unit_state", side_effect=states), patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl, "export_module") as export, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "did not become fully inactive"):
                modulectl.quiesced_export(Path("/fixture/hok"), manifest, argparse.Namespace())
            export.assert_not_called()
            self.assertEqual(run.call_args.args[0], ["systemctl", "start", "hok.target"])

    def test_quiesce_waits_for_child_stop_and_start_transitions(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        states = [
            "active", "active",  # initial
            "inactive", "deactivating", "inactive", "inactive",  # stop settles
            "active", "activating", "active", "active",  # start settles
        ]
        with patch.object(modulectl, "unit_state", side_effect=states), patch.object(modulectl.subprocess, "run") as run, patch.object(modulectl, "export_module", return_value=0), patch.object(modulectl.time, "sleep") as sleep, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(modulectl.quiesced_export(Path("/fixture/hok"), manifest, argparse.Namespace()), 0)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual([call.args[0] for call in run.call_args_list], [["systemctl", "stop", "hok.target"], ["systemctl", "start", "hok.target"]])

    def test_wait_timeout_reports_last_states(self):
        with patch.object(modulectl, "unit_state", side_effect=["inactive", "deactivating"]), patch.object(modulectl.time, "monotonic", side_effect=[10.0, 130.0]), patch.object(modulectl.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "timed out after 120s.*deactivating"):
                modulectl.wait_for_units(["hok.target", "hok-nbot.service"], "inactive", 120.0, "fixture timeout")
            sleep.assert_not_called()

    def test_quiesce_reports_failed_restoration(self):
        manifest = {"target": "hok.target", "members": ["hok-nbot.service"], "shared_dependencies": ["redis.service"]}
        states = ["active", "active", "inactive", "inactive", "active", "failed"]
        with patch.object(modulectl, "unit_state", side_effect=states), patch.object(modulectl.subprocess, "run"), patch.object(modulectl, "export_module", return_value=0), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "restart did not restore"):
                modulectl.quiesced_export(Path("/fixture/hok"), manifest, argparse.Namespace())


class SnapshotTests(unittest.TestCase):
    def test_postgres_credentials_are_not_command_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary)
            (module / "apps/NBot").mkdir(parents=True)
            (module / "apps/NBot/config.yaml").write_text("fixture")
            output = module / "output"
            output.mkdir()
            imported = {
                "yaml": types.SimpleNamespace(safe_load=lambda text: {"PostgreSQL": {"dsn": "REDACTED_CREDENTIAL"}}),
                "psycopg.conninfo": types.SimpleNamespace(conninfo_to_dict=lambda dsn: {"host": "127.0.0.1", "dbname": "hok", "user": "hok", "password": "REDACTED_CREDENTIAL"}),
            }
            with patch.dict(sys.modules, imported), patch.dict(os.environ, {}, clear=True), patch.object(snapshot_hok.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)) as run:
                snapshot_hok.dump_postgres(module, output, "/usr/bin/pg_dump")
            arguments = run.call_args.args[0]
            self.assertNotIn("REDACTED_CREDENTIAL", " ".join(arguments))
            self.assertNotIn("REDACTED_CREDENTIAL", " ".join(arguments))
            self.assertEqual(run.call_args.kwargs["env"]["PGPASSWORD"], "REDACTED_CREDENTIAL")
            self.assertEqual(run.call_args.kwargs["env"]["PGDATABASE"], "hok")
            self.assertEqual((output / "postgresql.dump").stat().st_mode & 0o777, 0o600)

    def test_rejects_nonzero_redis_database_without_connecting(self):
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary)
            (module / "apps/NBot").mkdir(parents=True)
            (module / "apps/NBot/config.yaml").write_text("Redis:\n  REDIS_DB: 9\n")
            with patch.dict(sys.modules, {"redis": types.SimpleNamespace()}), self.assertRaises(ValueError):
                snapshot_hok.dump_redis(module, module)

    def test_redis_snapshot_is_db0_namespace_only_and_preserves_expiry(self):
        calls = []

        class Pipeline:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def dump(self, key):
                self.key = key

            def pttl(self, key):
                assert key == self.key

            def time(self):
                pass

            def execute(self):
                if self.key == b"hok:gone":
                    return None, -2, (100, 123000)
                return b"serialized", 5000 if self.key == b"hok:expires" else -1, (100, 123000)

        class Redis:
            def __init__(self, **kwargs):
                calls.append(kwargs)

            def scan_iter(self, **kwargs):
                calls.append(kwargs)
                return iter([b"hok:expires", b"hok:permanent", b"hok:gone", b"hok:expires"])

            def pipeline(self, **kwargs):
                self.assert_transaction = kwargs["transaction"]
                return Pipeline()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary)
            (module / "apps/NBot").mkdir(parents=True)
            (module / "apps/NBot/config.yaml").write_text(
                "Redis:\n  REDIS_HOST: localhost\n  REDIS_PORT: 6379\n  REDIS_DB: 0\n"
            )
            output = module / "output"
            output.mkdir()
            with patch.dict(sys.modules, {"redis": types.SimpleNamespace(Redis=Redis)}):
                summary = snapshot_hok.dump_redis(module, output)
            rows = [json.loads(line) for line in (output / summary["file"]).read_text().splitlines()]
            self.assertEqual(calls[0]["db"], 0)
            self.assertEqual(calls[1]["match"], b"hok:*")
            self.assertEqual(summary["key_count"], 2)
            self.assertEqual(rows[1]["expires_at_ms"], 105123)
            self.assertIsNone(rows[2]["expires_at_ms"])
            self.assertEqual(base64.b64decode(rows[1]["key_b64"]), b"hok:expires")
            self.assertEqual((output / summary["file"]).stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

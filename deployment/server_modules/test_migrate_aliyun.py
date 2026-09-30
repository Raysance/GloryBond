"""Offline migration transaction and existing CI compatibility checks.

All paths and Git repositories are temporary; system commands are mocked except
Git commands operating on the throwaway repositories.
"""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import migrate_aliyun as migration


class MigrationTransactionTests(unittest.TestCase):
    def test_nested_child_parent_and_state_moves_roll_back_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "QQBot/Web"
            source.joinpath("html/raysance").mkdir(parents=True)
            source.joinpath("html/raysance/index.html").write_text("published")
            source.joinpath("raysance-site").mkdir()
            source.joinpath("raysance-site/source.txt").write_text("source")
            root = base / "modules"
            transaction = migration.Transaction(base / "journal")
            transaction.relocate(source / "raysance-site", root / "personal-site/apps/site")
            transaction.relocate(source / "html/raysance", root / "personal-site/public")
            transaction.relocate(source, root / "hok/apps/Web")
            transaction.relocate(root / "hok/apps/Web/html", root / "hok/public")
            self.assertEqual((source / "html/raysance/index.html").read_text(), "published")
            self.assertEqual((source / "raysance-site/source.txt").read_text(), "source")
            with patch.object(migration, "run", return_value=types.SimpleNamespace(returncode=0)), contextlib.redirect_stdout(io.StringIO()):
                migration.rollback(transaction.directory)
            self.assertFalse(source.is_symlink())
            self.assertFalse((source / "html").is_symlink())
            self.assertFalse((source / "html/raysance").is_symlink())
            self.assertFalse((source / "raysance-site").is_symlink())
            self.assertEqual((source / "html/raysance/index.html").read_text(), "published")
            self.assertEqual((source / "raysance-site/source.txt").read_text(), "source")

    def test_file_overwrite_then_relocation_rollback_restores_original_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = base / "original.env"
            old.write_text("UNCHANGED=original\n")
            old.chmod(0o640)
            new = base / "modules/config/common.env"
            transaction = migration.Transaction(base / "journal")
            transaction.relocate(old, new)
            transaction.write(new, "CHANGED=new\n", 0o600)
            with patch.object(migration, "run", return_value=types.SimpleNamespace(returncode=0)), contextlib.redirect_stdout(io.StringIO()):
                migration.rollback(transaction.directory)
            self.assertFalse(old.is_symlink())
            self.assertEqual(old.read_text(), "UNCHANGED=original\n")
            self.assertEqual(old.stat().st_mode & 0o777, 0o640)

    def test_target_lists_all_members_and_preserves_existing_dependencies(self):
        for owner, members in migration.MEMBERS.items():
            target = migration.target_text(owner)
            wants = next(line for line in target.splitlines() if line.startswith("Wants=")).split("=", 1)[1].split()
            self.assertTrue(set(members).issubset(wants))
            unit = "[Unit]\nAfter=network-online.target\n[Service]\nExecStart=/bin/true\n"
            result = migration.insert_partof(unit, owner + ".target")
            self.assertIn("PartOf=" + owner + ".target\n", result)
            self.assertIn("After=network-online.target\n", result)

    def test_nginx_split_preserves_routes_and_classifies_only_expected_hosts(self):
        text = '''events { worker_connections 1024; }
http {
    server {
        server_name  example_user_29.top;
        root html/raysance;
        location /auth { proxy_pass http://127.0.0.1:9105; }
        location /emoji_template/ { alias /QQBot/NBot/file_transfer/emoji_template/; }
    }
    server {
        server_name  hok.example_user_29.top;
        root html;
        location /file_transfer { alias /QQBot/NBot/file_transfer/; }
    }
    server {
        listen 80;
        server_name example_user_29.top;
        return 301 https://$host$request_uri;
    }
}
'''
        shared, blocks = migration.split_nginx(text)
        self.assertEqual(len(blocks["personal-site"]), 2)
        self.assertEqual(len(blocks["hok"]), 1)
        self.assertIn("include /srv/modules/hok/nginx/site.conf;", shared)
        self.assertIn("proxy_pass http://127.0.0.1:9105;", blocks["personal-site"][0])
        self.assertIn("root /srv/modules/personal-site/public;", blocks["personal-site"][0])
        self.assertIn("alias /srv/modules/hok/data/file_transfer/emoji_template/;", blocks["personal-site"][0])
        self.assertIn("return 301 https://$host$request_uri;", blocks["personal-site"][1])
        with self.assertRaises(RuntimeError):
            migration.split_nginx(text.replace("hok.example_user_29.top", "unexpected.example"))


class ExistingGitWorkflowProbes(unittest.TestCase):
    def test_git_restore_replaces_outward_link_for_tracked_data_directory(self):
        """Document why migrating the whole tracked data/ tree breaks this CI."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = base / "repo"
            repo.mkdir()

            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

            git("init", "--quiet")
            (repo / "data/honor").mkdir(parents=True)
            (repo / "data/history").mkdir()
            (repo / "data/honor/districts.json").write_text("{}")
            (repo / "data/history/BEGIN_TEMPLATE.json").write_text("[]")
            git("add", "data")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "Initial fixture")
            moved = base / "runtime-data"
            (repo / "data").rename(moved)
            (repo / "data").symlink_to(moved, target_is_directory=True)
            (moved / "history/runtime.json").write_text("runtime")
            git("restore", "--source=HEAD", "--worktree", "--", ".", ":(exclude)data/history")
            self.assertFalse((repo / "data").is_symlink())
            self.assertTrue((repo / "data/honor/districts.json").is_file())
            self.assertFalse((repo / "data/history/runtime.json").exists())
            self.assertEqual((moved / "history/runtime.json").read_text(), "runtime")


if __name__ == "__main__":
    unittest.main()

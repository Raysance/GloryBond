"""Exercise the copied-package to pinned-submodule migration on temporary repos."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[1]


class MigrationTests(unittest.TestCase):
    def test_old_sources_are_backed_up_and_history_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            dependency, parent = base / "core", base / "parent"
            dependency.mkdir()
            parent.mkdir()
            env = {**os.environ, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}

            def run(args, cwd=parent):
                return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()

            def git(*args, cwd=parent):
                return run(["git", *args], cwd)

            for repo in (parent, dependency):
                git("init", cwd=repo)
                git("config", "user.email", "test@example.invalid", cwd=repo)
                git("config", "user.name", "Test", cwd=repo)
            code = dependency / "src/agent_runtime"
            code.mkdir(parents=True)
            (code / "__init__.py").write_text('canonical = True\n')
            git("add", ".", cwd=dependency)
            git("commit", "-m", "Core", cwd=dependency)
            (parent / "agent_runtime").mkdir()
            (parent / "agent_runtime/old.py").write_text("legacy = True\n")
            history = parent / "data/history/record.json"
            history.parent.mkdir(parents=True)
            history.write_text("original")
            git("add", ".")
            git("commit", "-m", "Old")
            old = git("rev-parse", "HEAD")
            git("submodule", "add", str(dependency), "vendor/react-agent-runtime")
            git("rm", "-r", "agent_runtime")
            (parent / "agent_runtime").symlink_to("vendor/react-agent-runtime/src/agent_runtime")
            git("add", "agent_runtime")
            git("commit", "-m", "New")
            new = git("rev-parse", "HEAD")
            git("checkout", old)
            (parent / "agent_runtime/ignored.cache").write_text("cache")
            history.write_text("runtime archive")
            git("reset", "--mixed", new)
            git("restore", "--source=" + new, "--worktree", "--", ".", ":(exclude)data/history", ":(exclude)agent_runtime")
            run(["bash", str(ROOT / "deployment/scripts/sync_agent_runtime.sh"), ".", new])
            self.assertTrue((parent / "agent_runtime").is_symlink())
            self.assertIn("canonical", (parent / "agent_runtime/__init__.py").read_text())
            backups = list((parent / "log/deployment-backups").glob("*/agent_runtime"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "old.py").read_text(), "legacy = True\n")
            self.assertEqual((backups[0] / "ignored.cache").read_text(), "cache")
            self.assertEqual(history.read_text(), "runtime archive")
            # Re-running is harmless and retains the exact gitlink commit.
            run(["bash", str(ROOT / "deployment/scripts/sync_agent_runtime.sh"), ".", new])
            self.assertEqual(git("rev-parse", "HEAD", cwd=parent / "vendor/react-agent-runtime"), git("rev-parse", "HEAD", cwd=dependency))

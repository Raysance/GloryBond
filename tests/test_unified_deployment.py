"""Offline checks for cutover guards, service layout and environment relocation."""

from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from deployment.server_modules.unify_project import Migration
from deployment.scripts import verify_startup


ROOT = Path(__file__).parents[1]


class UnifiedDeploymentTests(unittest.TestCase):
    def test_existing_readonly_credential_moves_from_legacy_host_file(self):
        from dotenv import dotenv_values

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "apps/NBot").mkdir(parents=True)
            (base / "config").mkdir()
            target = base / "apps/NBot/.env"
            target.write_text("OTHER='preserve'\nHOK_CHAT_READONLY_DSN=''\n")
            (base / "config/nbot-host.env").write_text("HOK_CHAT_READONLY_DSN='reader-value'\n")
            migration = Migration(base)
            migration.consolidate_credentials()
            self.assertEqual(dotenv_values(target), {"OTHER": "preserve", "HOK_CHAT_READONLY_DSN": "reader-value"})
            (base / "config/nbot-host.env").write_text("HOK_CHAT_READONLY_DSN='stale-value'\n")
            migration.consolidate_credentials()
            self.assertEqual(dotenv_values(target)["HOK_CHAT_READONLY_DSN"], "reader-value")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_cutover_overrides_legacy_shell_paths_before_python_imports(self):
        migration = Migration("/srv/modules/hok")
        with patch.dict("os.environ", {"BOT_PATH": "/QQBot/NBot", "HOK_CONFIG_FILE": "/QQBot/NBot/config.yaml"}), \
             patch("deployment.server_modules.unify_project.subprocess.run", return_value=Mock(returncode=0, stdout=b"ok")) as run:
            migration.run("python", "-c", "import web.app", cwd=migration.project)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["BOT_PATH"], "/srv/modules/hok/apps/HOK_QQBot")
        self.assertEqual(env["HOK_CONFIG_FILE"], "/srv/modules/hok/apps/HOK_QQBot/config.yaml")

    def test_web_service_uses_root_environment_and_module_entry(self):
        migration = Migration("/srv/modules/hok")
        migration.project = ROOT
        text = migration.unit("hok-web.service")
        self.assertIn(f"WorkingDirectory={ROOT}\n", text)
        self.assertIn(f"ExecStart={ROOT}/.venv/bin/python -m web", text)
        self.assertIn(f"EnvironmentFile={ROOT}/.env", text)
        self.assertIn("PartOf=hok.target", text)
        self.assertNotIn("web/.venv", text)
        self.assertNotIn("@NBOT_ROOT@", text)

    def test_relocating_virtualenv_rewrites_scripts_but_never_follows_links(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            old, new = base / "NBot", base / "HOK_QQBot"
            bins = new / ".venv/bin"
            bins.mkdir(parents=True)
            script = bins / "pip"
            script.write_text(f"#!{old}/.venv/bin/python\nprint('ok')\n")
            script.chmod(0o755)
            binary = bins / "binary"
            binary.write_bytes(b"\x00" + str(old).encode())
            external = base / "python"
            external.write_text("unchanged")
            (bins / "python").symlink_to(external)
            Migration(base).rebase_environment(old, new)
            self.assertIn(str(new), script.read_text())
            self.assertEqual(script.stat().st_mode & 0o777, 0o755)
            self.assertEqual(binary.read_bytes(), b"\x00" + str(old).encode())
            self.assertEqual(external.read_text(), "unchanged")

    def test_preflight_preserves_runtime_credentials_and_rejects_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ("NBot", "Web"):
                repo = base / "apps" / name
                repo.mkdir(parents=True)
                (repo / "source.py").write_text("original")
                (repo / ".env").write_text("KEY=original")
                for args in (("init",), ("config", "user.email", "test@example.invalid"),
                             ("config", "user.name", "Test"), ("add", "."), ("commit", "-m", "Initial")):
                    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
            (base / "apps/NBot/.env").write_text("KEY=runtime")
            migration = Migration(base)
            self.assertEqual(migration.preflight()["project"], str((base / "apps/HOK_QQBot").resolve()))
            (base / "apps/Web/source.py").write_text("unmerged")
            with self.assertRaisesRegex(ValueError, "source changes"):
                migration.preflight()
            self.assertEqual((base / "apps/NBot/.env").read_text(), "KEY=runtime")

    def test_readiness_requires_both_services_and_web_health(self):
        opener = Mock()
        opener.open.return_value = BytesIO(b'{"status":"ok"}')
        with patch.object(verify_startup, "unit_property", side_effect=lambda unit, name:
                          "active" if name == "ActiveState" else "invocation"), \
             patch.object(verify_startup.subprocess, "check_output", return_value="Application startup complete."), \
             patch.object(verify_startup, "build_opener", return_value=opener):
            verify_startup.verify()
        opener.open.assert_called_once()

    def test_readiness_rejects_a_bot_restart(self):
        with patch.object(verify_startup, "unit_property", side_effect=["old", "new"]):
            with self.assertRaisesRegex(RuntimeError, "restarted"):
                verify_startup.verify()


if __name__ == "__main__":
    unittest.main()

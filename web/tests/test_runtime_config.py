import tempfile
import unittest
from pathlib import Path

from web.runtime_config import load_shared_config, resolve_runtime_paths


class RuntimeConfigTests(unittest.TestCase):
    def test_explicit_paths_are_resolved_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = {
                "HOK_STACK_ROOT": str(root / "stack"),
                "BOT_PATH": str(root / "code" / "nbot"),
                "WEB_PATH": str(root / "code" / "web"),
                "HOK_NAPCAT_ROOT": str(root / "runtime" / "napcat"),
                "HOK_ENV_FILE": str(root / "code" / "nbot" / ".env"),
                "HOK_CONFIG_FILE": str(root / "etc" / "config.yaml"),
                "HOK_DATA_DIR": str(root / "state" / "data"),
                "HOK_FILE_TRANSFER_DIR": str(root / "state" / "file_transfer"),
            }

            runtime = resolve_runtime_paths(env, root / "source" / "web")

            self.assertEqual(runtime.nbot_root, (root / "code" / "nbot").resolve())
            self.assertEqual(runtime.web_root, (root / "code" / "web").resolve())
            self.assertEqual(runtime.napcat_root, (root / "runtime" / "napcat").resolve())
            self.assertEqual(runtime.env_file, (root / "code" / "nbot" / ".env").resolve())
            self.assertEqual(runtime.config_file, (root / "etc" / "config.yaml").resolve())
            self.assertEqual(runtime.data_dir, (root / "state" / "data").resolve())
            self.assertEqual(
                runtime.file_transfer_dir,
                (root / "state" / "file_transfer").resolve(),
            )

    def test_web_uses_its_own_project_root_without_sibling_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stack_root = Path(temp_dir)
            app_root = stack_root / "web"
            (stack_root / "NBot").mkdir()
            app_root.mkdir()

            runtime = resolve_runtime_paths({}, app_root)

            self.assertEqual(runtime.nbot_root, stack_root.resolve())
            self.assertEqual(runtime.web_root, app_root.resolve())
            self.assertEqual(runtime.napcat_root, (stack_root / "napcat").resolve())
            self.assertEqual(runtime.env_file, (stack_root / ".env").resolve())

    def test_shared_config_reads_yaml_and_injects_env_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nbot_root = root
            web_root = root / "web"
            web_root.mkdir()
            (nbot_root / "config.yaml").write_text(
                "Redis:\n  REDIS_DB: 0\nWebService:\n  server_domain: example.test\n"
                "wzry:\n  roleid: '1'\n",
                encoding="utf-8",
            )
            runtime = resolve_runtime_paths({}, web_root)

            config = load_shared_config(runtime, {
                "HOK_WEB_SECRET_KEY": "web-secret",
                "HOK_WZRY_TOKEN": "wzry-secret",
                "HOK_DATABASE_DSN": "postgresql://private",
            })

            self.assertEqual(config["Redis"]["REDIS_DB"], 0)
            self.assertEqual(config["WebService"]["server_domain"], "example.test")
            self.assertEqual(config["WebService"]["secret_key"], "web-secret")
            self.assertEqual(config["wzry"], {"roleid": "1", "token": "wzry-secret"})
            self.assertEqual(config["PostgreSQL"]["dsn"], "postgresql://private")


if __name__ == "__main__":
    unittest.main()

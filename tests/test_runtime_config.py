import tempfile
import unittest
from pathlib import Path

from runtime_config import resolve_runtime_paths


class RuntimeConfigTests(unittest.TestCase):
    def test_explicit_paths_are_resolved_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = {
                "HOK_STACK_ROOT": str(root / "stack"),
                "BOT_PATH": str(root / "code" / "nbot"),
                "WEB_PATH": str(root / "code" / "web"),
                "HOK_ENV_FILE": str(root / "etc" / "common.env"),
                "HOK_CONFIG_FILE": str(root / "etc" / "config.yaml"),
                "HOK_STATIC_VARIABLES_FILE": str(root / "etc" / "variables_static.json"),
                "REDIS_CONF": str(root / "etc" / "redis.json"),
                "HOK_DATA_DIR": str(root / "state" / "data"),
                "HOK_FILE_TRANSFER_DIR": str(root / "state" / "file_transfer"),
            }

            runtime = resolve_runtime_paths(env, root / "source" / "web")

            self.assertEqual(runtime.nbot_root, (root / "code" / "nbot").resolve())
            self.assertEqual(runtime.web_root, (root / "code" / "web").resolve())
            self.assertEqual(runtime.config_file, (root / "etc" / "config.yaml").resolve())
            self.assertEqual(runtime.data_dir, (root / "state" / "data").resolve())
            self.assertEqual(
                runtime.file_transfer_dir,
                (root / "state" / "file_transfer").resolve(),
            )

    def test_legacy_uppercase_nbot_sibling_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stack_root = Path(temp_dir)
            app_root = stack_root / "Web"
            (stack_root / "NBot").mkdir()
            app_root.mkdir()

            runtime = resolve_runtime_paths({}, app_root)

            self.assertEqual(runtime.nbot_root, (stack_root / "NBot").resolve())
            self.assertEqual(runtime.web_root, app_root.resolve())


if __name__ == "__main__":
    unittest.main()

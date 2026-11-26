"""The new source layout keeps services, resources and SDKs independently loadable."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

from deployment.scripts.migrate_source_layout import rewrite_unit


ROOT = Path(__file__).resolve().parents[1]


class SourceLayoutTests(unittest.TestCase):
    def test_web_unit_migration_preserves_private_settings_and_is_idempotent(self):
        source = ("[Service]\nWorkingDirectory=/srv/app\nEnvironmentFile=/private/runtime.env\n"
                  "Environment=WEB_PATH=/srv/app/web\nEnvironment=HOK_WEB_PORT=8123\n"
                  "ExecStart=/srv/app/.venv/bin/python -m web\nUser=existing-user\n")
        result = rewrite_unit(source, Path("/srv/app"))
        expected = source.replace("WEB_PATH=/srv/app/web", "WEB_PATH=/srv/app/src/glorybond/apps/web")
        expected = expected.replace(" -m web\n", " -m glorybond.apps.web\n")
        self.assertEqual(result, expected)
        self.assertEqual(rewrite_unit(result, Path("/srv/app")), result)

    def test_source_packages_are_importable_without_starting_nonebot(self):
        code = ("import sys; import glorybond; import glorybond.apps.qq; import glorybond.apps.web; "
                "import glorybond.agent; import glorybond.accounts; "
                "assert 'nonebot' not in sys.modules; "
                "assert 'glorybond.apps.qq.plugin' not in sys.modules")
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, timeout=10)

    def test_sdk_imports_resolve_to_the_pinned_private_checkouts(self):
        for name, repo in [("agent_runtime", "react-agent-runtime"),
                           ("hok_research", "hok-player-client"), ("hok_camp_client", "hok-camp-client")]:
            with self.subTest(package=name):
                origin = Path(importlib.util.find_spec(name).origin).resolve()
                self.assertEqual(origin, (ROOT / "vendor" / repo / "src" / name / "__init__.py").resolve())


if __name__ == "__main__":
    unittest.main()

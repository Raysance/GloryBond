import ast
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from dotenv import load_dotenv


def load_environment_function():
    """Load only the environment helper, without importing private Bot config."""
    source_path = Path(__file__).resolve().parents[1] / "hok" / "zstatic.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_runtime_environment"
    )
    return compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec")


ENVIRONMENT_FUNCTION = load_environment_function()


class ChatEnvironmentTests(unittest.TestCase):
    def run_environment_loader(self, files, initial_environment=None):
        loaded = []

        def load_fixture(*, dotenv_path, override):
            loaded.append(dotenv_path)
            return load_dotenv(
                stream=io.StringIO(files[dotenv_path]),
                override=override,
                interpolate=False,
            )

        namespace = {"os": os, "load_dotenv": load_fixture}
        exec(ENVIRONMENT_FUNCTION, namespace)
        with patch.dict(os.environ, initial_environment or {}, clear=True), \
                patch.object(os, "getcwd", return_value="/fixture/launch"), \
                patch.object(os.path, "isfile", side_effect=lambda path: path in files):
            result = namespace["_load_runtime_environment"]()
            environment = dict(os.environ)
        return result, environment, loaded

    def test_local_env_uses_bot_path_loaded_from_base_dotenv(self):
        base = "/fixture/.env"
        private = "/fixture/bot/.env.local"
        result, environment, loaded = self.run_environment_loader({
            base: "BOT_PATH=/fixture/bot\n",
            private: "HOK_CHAT_API_KEY=fixture-local-key\n",
        })

        self.assertEqual(environment["BOT_PATH"], "/fixture/bot")
        self.assertEqual(environment["HOK_CHAT_API_KEY"], "fixture-local-key")
        self.assertEqual(loaded, [base, private])
        self.assertEqual(result, os.pathsep.join([base, private]))

    def test_explicit_env_file_does_not_load_local_env(self):
        explicit = "/fixture/private.env"
        result, environment, loaded = self.run_environment_loader({
            explicit: "BOT_PATH=/fixture/bot\nHOK_CHAT_API_KEY=fixture-explicit-key\n",
            "/fixture/.env": "HOK_CHAT_API_KEY=fixture-base-key\n",
            "/fixture/bot/.env.local": "HOK_CHAT_API_KEY=fixture-local-key\n",
        }, {"HOK_ENV_FILE": explicit})

        self.assertEqual(environment["HOK_CHAT_API_KEY"], "fixture-explicit-key")
        self.assertEqual(loaded, [explicit])
        self.assertEqual(result, explicit)

    def test_process_api_key_is_not_overridden_by_dotenv_files(self):
        base = "/fixture/.env"
        private = "/fixture/bot/.env.local"
        _, environment, loaded = self.run_environment_loader({
            base: "HOK_CHAT_API_KEY=fixture-base-key\n",
            private: "HOK_CHAT_API_KEY=fixture-local-key\n",
        }, {
            "BOT_PATH": "/fixture/bot",
            "HOK_CHAT_API_KEY": "fixture-process-key",
        })

        self.assertEqual(loaded, [base, private])
        self.assertEqual(environment["HOK_CHAT_API_KEY"], "fixture-process-key")


if __name__ == "__main__":
    unittest.main()

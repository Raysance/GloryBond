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


def load_chat_config_function():
    source_path = Path(__file__).resolve().parents[1] / "hok" / "zstatic.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_chat_api_config"
    )
    return compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec")


CHAT_CONFIG_FUNCTION = load_chat_config_function()


class ChatEnvironmentTests(unittest.TestCase):
    def build_chat_config(self, config, environment):
        from urllib.parse import urlparse

        namespace = {"urlparse": urlparse}
        exec(CHAT_CONFIG_FUNCTION, namespace)
        return namespace["_build_chat_api_config"](config, environment)

    def test_official_deepseek_reuses_legacy_key_and_allows_direct_connection(self):
        result = self.build_chat_config({
            "ChatAPI": {
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-flash",
                "proxy_url": "",
            },
            "QQBot": {"deepseek_key": "legacy-private-key"},
        }, {})

        self.assertEqual(result, {
            "base_url": "https://api.deepseek.com",
            "api_key": "legacy-private-key",
            "model": "deepseek-flash",
            "proxy_url": "",
        })

    def test_explicit_empty_proxy_overrides_configured_proxy(self):
        result = self.build_chat_config({
            "ChatAPI": {
                "base_url": "https://example.invalid/v1",
                "api_key": "configured-key",
                "model": "model",
                "proxy_url": "socks5h://127.0.0.1:1080",
            },
        }, {"HOK_CHAT_PROXY_URL": ""})

        self.assertEqual(result["proxy_url"], "")

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

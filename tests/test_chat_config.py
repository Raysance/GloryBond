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


def load_secret_config_function():
    source_path = Path(__file__).resolve().parents[1] / "hok" / "zstatic.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_secret_environment"
    )
    return compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec")


SECRET_CONFIG_FUNCTION = load_secret_config_function()


class ChatEnvironmentTests(unittest.TestCase):
    def build_chat_config(self, config, environment):
        from urllib.parse import urlparse

        namespace = {"urlparse": urlparse}
        exec(CHAT_CONFIG_FUNCTION, namespace)
        return namespace["_build_chat_api_config"](config, environment)

    def test_secret_environment_populates_runtime_sections(self):
        namespace = {}
        exec(SECRET_CONFIG_FUNCTION, namespace)
        config = {"QQBot": {"ark_responses_model": "model"}, "wzry": {"roleid": "1"}}

        result = namespace["_apply_secret_environment"](config, {
            "HOK_ARK_API_KEY": "ark-secret",
            "HOK_WZRY_TOKEN": "wzry-secret",
        })

        self.assertEqual(result["QQBot"]["ark_key"], "ark-secret")
        self.assertEqual(result["QQBot"]["ark_responses_model"], "model")
        self.assertEqual(result["wzry"], {"roleid": "1", "token": "wzry-secret"})

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

    def test_project_env_is_the_single_local_configuration_file(self):
        base = "/fixture/.env"
        result, environment, loaded = self.run_environment_loader({
            base: "BOT_PATH=/fixture/bot\nHOK_CHAT_API_KEY=fixture-key\n",
        })

        self.assertEqual(environment["BOT_PATH"], "/fixture/bot")
        self.assertEqual(environment["HOK_CHAT_API_KEY"], "fixture-key")
        self.assertEqual(loaded, [base])
        self.assertEqual(result, base)

    def test_explicit_env_file_does_not_load_local_env(self):
        explicit = "/fixture/private.env"
        result, environment, loaded = self.run_environment_loader({
            explicit: "BOT_PATH=/fixture/bot\nHOK_CHAT_API_KEY=fixture-explicit-key\n",
            "/fixture/.env": "HOK_CHAT_API_KEY=fixture-base-key\n",
        }, {"HOK_ENV_FILE": explicit})

        self.assertEqual(environment["HOK_CHAT_API_KEY"], "fixture-explicit-key")
        self.assertEqual(loaded, [explicit])
        self.assertEqual(result, explicit)

    def test_process_api_key_is_not_overridden_by_project_env(self):
        base = "/fixture/.env"
        _, environment, loaded = self.run_environment_loader({
            base: "HOK_CHAT_API_KEY=fixture-base-key\n",
        }, {
            "BOT_PATH": "/fixture/bot",
            "HOK_CHAT_API_KEY": "fixture-process-key",
        })

        self.assertEqual(loaded, [base])
        self.assertEqual(environment["HOK_CHAT_API_KEY"], "fixture-process-key")


if __name__ == "__main__":
    unittest.main()

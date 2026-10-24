"""An expired legacy game credential must not prevent the QQ plugin loading."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock
import logging

ROOT = Path(__file__).resolve().parents[1]


class StartupCacheTests(unittest.TestCase):
    def test_failed_legacy_fetch_does_not_abort_other_initializers(self):
        source = ast.parse((ROOT / "hok/zscheduler.py").read_text())
        node = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_initialize_business_cache_impl")
        namespace = {"__package__": "hok", "logging": logging,
                     "log_message": Mock(), "load_yesterday": Mock(), "init_fetch_news": Mock(),
                     "init_fetch_heroranklist": Mock(side_effect=RuntimeError("private credential text")),
                     "init_fetch_hero_tier": Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "startup-cache", "exec"), namespace)
        namespace["_initialize_business_cache_impl"]()
        namespace["load_yesterday"].assert_called_once_with(1)
        namespace["init_fetch_heroranklist"].assert_called_once()
        namespace["init_fetch_hero_tier"].assert_called_once()
        namespace["log_message"].assert_called_once()
        self.assertNotIn("private credential text", namespace["log_message"].call_args.args[0])

    def test_plugin_import_has_no_top_level_cache_fetch(self):
        module = ast.parse((ROOT / "hok/__init__.py").read_text())
        names = {node.value.func.id for node in module.body if isinstance(node, ast.Expr)
                 and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)}
        self.assertFalse(names & {"load_yesterday", "init_fetch_news", "init_fetch_heroranklist", "init_fetch_hero_tier"})


if __name__ == "__main__":
    unittest.main()

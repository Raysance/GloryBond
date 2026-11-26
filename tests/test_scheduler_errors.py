"""Only exhausted failures should generate public archive diagnostics."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.debugger import import_project_module


class ArchiveErrorsTests(unittest.TestCase):
    def run_archive(self, users, outcomes):
        facade = import_project_module("glorybond.features.facade")
        files = import_project_module("glorybond.storage.files")
        source = ast.parse(Path("src/glorybond/apps/qq/scheduler.py").read_text())
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "_dump_today_impl")
        scope = {"userlist": users, "dmc": SimpleNamespace(DumpTodayFailedList=[]),
                 "time": SimpleNamespace(sleep=Mock()), "log_message": Mock(), "report_exception": Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "archive", "exec"), scope)
        with patch.object(facade, "wzry_data", side_effect=outcomes) as fetch, \
             patch.object(files, "daily_history_path", return_value="archive.json"), \
             patch.object(files, "personal_history_path", return_value="personal.json"), \
             patch.object(files, "writerl") as write:
            scope["_dump_today_impl"]()
        return scope, fetch, write

    def test_recovered_failure_is_not_reported_or_duplicated_in_archive(self):
        scope, fetch, write = self.run_archive({"one": 1, "two": 2}, [TimeoutError(), {"key": "two"}, {"key": "one"}])
        scope["report_exception"].assert_not_called()
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(write.call_args.args[1], [{"key": "two"}, {"key": "one"}])
        self.assertEqual(scope["dmc"].DumpTodayFailedList, [])

    def test_exhausted_failure_reports_once_and_preserves_success(self):
        error = TimeoutError()
        scope, fetch, write = self.run_archive({"one": 1, "two": 2}, [error, {"key": "two"}, error, error])
        self.assertEqual(fetch.call_count, 4)
        scope["report_exception"].assert_called_once_with(error, operation="每日战绩归档", partial=True)
        self.assertEqual(write.call_args.args[1], [{"key": "two"}])

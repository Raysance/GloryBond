import os
import tempfile
import unittest

from local_debugger import import_hok_module, project_root


ZDB = import_hok_module("zdb")
ZFILE = import_hok_module("zfile")


class PostgresArchiveTests(unittest.TestCase):
    def test_classifies_supported_archives(self):
        root = str(project_root())
        cases = {
            os.path.join(root, "data", "history", "2026-09-22.json"): {
                "kind": "history",
                "date": "2026-09-22",
                "source_path": "data/history/2026-09-22.json",
            },
            os.path.join(root, "data", "history", "battles", "1782530763.json"): {
                "kind": "battle",
                "game_seq": "1782530763",
                "source_path": "data/history/battles/1782530763.json",
            },
            os.path.join(root, "data", "history", "battles", "-9223372036854775806.json"): {
                "kind": "battle",
                "game_seq": "-9223372036854775806",
                "source_path": "data/history/battles/-9223372036854775806.json",
            },
            os.path.join(root, "data", "history", "personal", "2026-09-22", "123.json"): {
                "kind": "personal",
                "date": "2026-09-22",
                "user_id": "123",
                "source_path": "data/history/personal/2026-09-22/123.json",
            },
            os.path.join(root, "data", "history", "power", "1782530763.json"): {
                "kind": "power",
                "game_seq": "1782530763",
                "source_path": "data/history/power/1782530763.json",
            },
            os.path.join(root, "data", "herotier", "2026-09-22.json"): {
                "kind": "hero_tier",
                "date": "2026-09-22",
                "source_path": "data/herotier/2026-09-22.json",
            },
            os.path.join(root, "data", "herorank", "2026-09-22.json"): {
                "kind": "hero_rank",
                "date": "2026-09-22",
                "source_path": "data/herorank/2026-09-22.json",
            },
        }
        for filepath, expected in cases.items():
            with self.subTest(filepath=filepath):
                self.assertEqual(ZFILE.classify_postgres_archive_path(filepath), expected)

    def test_history_reader_prefers_postgres(self):
        original_db_reader = ZDB.read_history_date
        original_json_reader = ZFILE.readerl
        try:
            ZDB.read_history_date = lambda target_date: [{"date": target_date, "source": "postgres"}]
            ZFILE.readerl = lambda filepath: self.fail(f"unexpected JSON read: {filepath}")
            self.assertEqual(
                ZFILE.read_history_date("2026-09-22"),
                [{"date": "2026-09-22", "source": "postgres"}],
            )
        finally:
            ZDB.read_history_date = original_db_reader
            ZFILE.readerl = original_json_reader

    def test_history_reader_falls_back_without_modifying_archive(self):
        original_db_reader = ZDB.read_history_date
        original_json_reader = ZFILE.readerl
        requested_paths = []
        try:
            def fail_database(_target_date):
                raise RuntimeError("database unavailable")

            def fake_json_reader(filepath):
                requested_paths.append(filepath)
                return [{"source": "json"}]

            ZDB.read_history_date = fail_database
            ZFILE.readerl = fake_json_reader
            self.assertEqual(ZFILE.read_history_date("2026-09-22"), [{"source": "json"}])
            self.assertEqual(
                requested_paths,
                [os.path.join(ZFILE.data_root, "history", "2026-09-22.json")],
            )
        finally:
            ZDB.read_history_date = original_db_reader
            ZFILE.readerl = original_json_reader

    def test_external_data_root_keeps_stable_archive_identifiers(self):
        original_data_root = ZFILE.data_root
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ZFILE.data_root = temp_dir
                target = os.path.join(temp_dir, "history", "2026-09-22.json")
                self.assertEqual(
                    ZFILE.classify_postgres_archive_path(target),
                    {
                        "kind": "history",
                        "date": "2026-09-22",
                        "source_path": "data/history/2026-09-22.json",
                    },
                )
                self.assertEqual(ZFILE.daily_history_path("2026-09-22"), target)
        finally:
            ZFILE.data_root = original_data_root

    def test_managed_archive_writes_only_postgres_when_enabled(self):
        original_classifier = ZFILE.classify_postgres_archive_path
        original_sync = ZFILE._sync_postgres_archive
        original_archive_setting = ZFILE.postgres_archive_json
        try:
            ZFILE.classify_postgres_archive_path = lambda _path: {
                "kind": "history",
                "date": "2099-01-01",
                "source_path": "data/history/2099-01-01.json",
            }
            ZFILE._sync_postgres_archive = lambda _path, _payload: {"players": 1}
            ZFILE.postgres_archive_json = False
            with tempfile.TemporaryDirectory() as temp_dir:
                target = os.path.join(temp_dir, "history.json")
                ZFILE.writerl(target, [{"key": "test"}])
                self.assertFalse(os.path.exists(target))
        finally:
            ZFILE.classify_postgres_archive_path = original_classifier
            ZFILE._sync_postgres_archive = original_sync
            ZFILE.postgres_archive_json = original_archive_setting

    def test_managed_archive_falls_back_to_json_when_postgres_write_fails(self):
        original_classifier = ZFILE.classify_postgres_archive_path
        original_sync = ZFILE._sync_postgres_archive
        original_archive_setting = ZFILE.postgres_archive_json
        try:
            ZFILE.classify_postgres_archive_path = lambda _path: {
                "kind": "history",
                "date": "2099-01-01",
                "source_path": "data/history/2099-01-01.json",
            }
            ZFILE._sync_postgres_archive = lambda _path, _payload: False
            ZFILE.postgres_archive_json = False
            with tempfile.TemporaryDirectory() as temp_dir:
                target = os.path.join(temp_dir, "history.json")
                payload = [{"key": "fallback"}]
                ZFILE.writerl(target, payload)
                self.assertEqual(ZFILE.readerl(target), payload)
        finally:
            ZFILE.classify_postgres_archive_path = original_classifier
            ZFILE._sync_postgres_archive = original_sync
            ZFILE.postgres_archive_json = original_archive_setting


if __name__ == "__main__":
    unittest.main()

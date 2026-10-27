"""Saved client windows survive a new game day without another game request."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_debugger import import_hok_module

ZDB = import_hok_module('zdb')
ZFILE = import_hok_module('zfile')


class ClientSnapshotRecoveryTests(unittest.TestCase):
    def test_database_lookup_is_scoped_to_exact_camp_account_role_and_date(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {'payload': {'saved': True}}
        with patch.object(ZDB, '_connect', return_value=connection):
            self.assertEqual(ZDB.read_latest_client_snapshot('2026-10-25', 1001, 42), {'saved': True})
        sql, parameters = cursor.execute.call_args.args
        self.assertEqual(parameters, (1001, 42, '2026-10-25'))
        self.assertIn('target_role_id = %s', sql)
        self.assertIn('snapshot_date <= %s', sql)
        self.assertIn('LIMIT 1', sql)

    def test_empty_database_result_does_not_read_an_emergency_copy(self):
        with patch.object(ZDB, 'read_latest_client_snapshot', return_value=None) as database, \
             patch.object(ZFILE, 'readerl') as archive:
            self.assertIsNone(ZFILE.read_latest_client_history('2026-10-25', 1001, 42))
        database.assert_called_once_with('2026-10-25', 1001, 42)
        archive.assert_not_called()

    def test_database_failure_uses_latest_eligible_archive_without_crossing_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            def save(date, role, *, client=True):
                path = Path(directory) / 'history' / 'personal' / date / '1001.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = {'profile': {'userId': 1001, 'targetRoleId': role},
                           'btlist': {'list': [{'clientOnly': client, 'gameSeq': date}]}}
                path.write_text(json.dumps(payload), encoding='utf-8')
                return payload

            expected = save('2026-10-23', 42)
            save('2026-10-24', 43)
            save('2026-10-25', 42, client=False)
            save('2026-10-26', 42)
            with patch.object(ZFILE, 'data_root', directory), \
                 patch.object(ZDB, 'read_latest_client_snapshot', side_effect=RuntimeError('unavailable')), \
                 patch.object(ZFILE, 'log_message'):
                self.assertEqual(ZFILE.read_latest_client_history('2026-10-25', 1001, 42), expected)


if __name__ == '__main__':
    unittest.main()

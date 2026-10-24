"""Legacy large snapshots download only display fields; cached views track file updates."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import app as web
import battle_list_data as lists


class BattleListLoadingTests(unittest.TestCase):
    def test_compaction_keeps_order_identifiers_profile_and_display_values_without_mutation(self):
        original = {'profile': {'targetRoleId': 42}, 'btlist': {'invisible': False, 'list': [
            {'gameSeq': '-9223372036854775806', 'gradeMissing': True, 'gradeGame': 0,
             'clientMatch': {'players': ['large native payload']}, 'clientPlayer': {'uid': 123}},
            {'gameSeq': 123, 'gradeGame': 10.5}]}}
        before = copy.deepcopy(original)
        result = lists.compact_battle_list(original)
        self.assertNotIn('clientMatch', result['btlist']['list'][0])
        self.assertNotIn('clientPlayer', result['btlist']['list'][0])
        self.assertEqual(result['btlist']['list'][0]['gameSeq'], '-9223372036854775806')
        self.assertEqual(result['btlist']['list'][1]['gradeGame'], 10.5)
        self.assertEqual(result['profile'], before['profile'])
        self.assertEqual(original, before)

    def test_compact_route_uses_existing_key_and_cache_invalidates_after_snapshot_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'temp_files').mkdir()
            path = root / 'temp_files' / 'saved.json'
            path.write_text(json.dumps({'btlist': {'list': [{'gameSeq': 1, 'clientMatch': {'large': 'data'}}]}}))
            with patch.object(lists, 'RUNTIME', SimpleNamespace(file_transfer_dir=root)), \
                 patch.object(web, 'key_to_filename', return_value=({}, 'file_transfer/temp_files/saved.json')), \
                 patch.object(web, 'should_track_request', return_value=False):
                client = TestClient(web.app)
                for route in ['/all', '/person', '/period', '/query']:
                    result = client.get(route, params={'key': 'saved', 'data': 'true'})
                    self.assertEqual(result.status_code, 200, route)
                    self.assertNotIn('clientMatch', result.text)
                    self.assertEqual(result.headers['cache-control'], 'no-store')
                first = lists.load_battle_list('file_transfer/temp_files/saved.json')
                self.assertIs(first, lists.load_battle_list('file_transfer/temp_files/saved.json'))
                path.write_text(json.dumps({'btlist': {'list': [{'gameSeq': 222}]}}))
                self.assertEqual(lists.load_battle_list('file_transfer/temp_files/saved.json')['btlist']['list'][0]['gameSeq'], 222)
                with self.assertRaises(ValueError):
                    lists.load_battle_list('file_transfer/temp_files/../private.json')
        lists._read_compact.cache_clear()

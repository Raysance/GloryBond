"""Legacy large snapshots download only display fields; cached views track file updates."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from glorybond.apps.web import app as web
from glorybond.apps.web import battle_list_data as lists
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

    def test_hidden_snapshot_exposes_only_selected_public_role_fields(self):
        selected = {'roleId': 9223372036854775806, 'roleName': '玩家', 'roleJobName': '钻石',
                    'roleIcon': 'https://example.com/avatar', 'gameLevel': 30, 'areaName': '安卓区',
                    'serverName': '一区', 'gameOpenId': 'private', 'battleId': 'hidden'}
        profile = {'targetRoleId': str(selected['roleId']), 'roleList': [{'roleId': 'other'}, selected],
                   'head': {'mods': [{'name': '胜率', 'content': '50%'}]}}
        original = {'profile': profile, 'btlist': {'invisible': True, 'invisDes': '已隐藏',
                    'list': [{'gameSeq': 'hidden'}], 'gaming': {'battleId': 'hidden'}}}
        result = lists.compact_battle_list(original)
        self.assertEqual(result['profile']['roleList'], [{k: selected[k] for k in
            ('roleName', 'roleJobName', 'roleIcon', 'gameLevel', 'areaName', 'serverName')}])
        self.assertEqual(result['btlist']['invisDes'], '已隐藏')
        self.assertNotIn('hidden', repr(result))
        self.assertEqual(lists.profile_only_battle_list({**profile, 'targetRoleId': 'missing'})['profile']['roleList'], [])

    def test_period_with_private_days_retains_only_available_information(self):
        day = {'visible': False, 'nickname': '玩家', 'rank_name': '钻石', 'details': [{'gameSeq': 'hidden'}]}
        hidden = lists.visible_period_data({'periods': [day]})
        self.assertTrue(hidden['btlist']['invisible'])
        self.assertEqual(hidden['profile']['roleList'][0]['roleName'], '玩家')
        self.assertNotIn('hidden', repr(hidden))
        self.assertEqual(lists.visible_period_data([day, {'visible': True}]), [{'visible': True}])

    def test_jump_person_keeps_public_profile_when_battle_request_fails(self):
        profile = {'roleList': [{'roleId': 1, 'roleName': '另一个角色'}, {'roleId': 2, 'roleName': '目标'}]}
        with patch.object(web, 'check_key_valid', return_value=True), patch.object(web, 'writerl') as save, \
             patch.object(web, 'should_track_request', return_value=False), \
             patch.object(web, 'wzry_get_official', side_effect=[profile, ValueError('network')]):
            response = TestClient(web.app).get('/jump-person', params={'userid': '3', 'roleid': '2', 'key': 'test'})
        self.assertEqual(response.status_code, 200)
        saved = save.call_args.args[1]
        self.assertFalse(saved['btlist']['invisible'])
        self.assertTrue(saved['btlist']['unavailable'])
        self.assertEqual(saved['profile']['roleList'], [{'roleName': '目标'}])

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

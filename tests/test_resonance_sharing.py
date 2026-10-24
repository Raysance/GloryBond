"""Saved entertainment games reach the share renderer without a game request."""
import ast
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from local_debugger import import_hok_module
from tests.test_player_client_integration import HISTORY, STATIC, PLAYER, match, client_result

ZFILE = import_hok_module('zfile')
ZFUNC = import_hok_module('zfunc')
DETAIL = import_hok_module('business.battle_detail')
GEN = import_hok_module('tools.gen_battle_res')


def detail_fixture():
    native = match()
    native['players'][1].update(score_raw=835, gold=10000, hero_damage=20000,
        damage_taken_from_enemies=30000, equipment=[{'dwEquipID': 1137, 'bCnt': 1}],
        selected_skill_ids=[5414800, 5455030, 5499700, 0])
    row = HISTORY.client_battles(client_result(native), PLAYER, STATIC.player_client_config)[0]
    return HISTORY.camp_battle_detail(row, PLAYER, roleid=42, userid=1001, identities={},
        hero_names=STATIC.HeroList, settings=STATIC.player_client_config, assets=ZFILE.player_client_battle_assets())


class ResonanceSharingTests(unittest.TestCase):
    def test_scores_include_zero_and_keep_sdk_rounding_and_missing_values(self):
        for raw, expected in [(0, (0, '0.0')), (835, (8.35, '8.4')), (-1, (0, '0.0'))]:
            self.assertEqual(HISTORY.client_score({'score_raw': raw}), expected)
        self.assertEqual(HISTORY.client_score({}), (None, None))
        native = match(); native['players'][1].update(score=8.35, score_display='8.4', score_raw=835)
        row = HISTORY.client_battles(client_result(native), PLAYER, STATIC.player_client_config)[0]
        self.assertFalse(row['gradeMissing'])
        self.assertEqual((row['gradeGame'], row['gradeDisplay']), (8.35, '8.4'))
        self.assertNotIn('评分', row['clientMissing'])

    def test_equipment_and_four_ordered_skills_use_explicit_catalogs(self):
        detail = detail_fixture()
        records = detail['redRoles'][0]['battleRecords']
        self.assertEqual(records['finalEquips'][0]['equipName'], '暗影战斧')
        self.assertTrue(records['finalEquips'][0]['equipIcon'].endswith('/1137.jpg'))
        skills = records['selectedSkills']
        self.assertEqual([row['skillId'] for row in skills], [5414800, 5455030, 5499700, 0])
        self.assertEqual([row['skillName'] for row in skills], ['姜子牙被动', '空空儿大招', '巨人之握被动', '—'])
        self.assertEqual(skills[0]['sourceHeroId'], 148)
        self.assertEqual(skills[0]['sourceHeroName'], '姜子牙')
        self.assertIsNone(skills[2]['sourceHeroId'])
        self.assertEqual(skills[2]['sourceHeroIcon'], '')
        self.assertIsNone(detail['blueRoles'][0]['battleStats']['gradeGame'])
        self.assertIsNone(detail['blueRoles'][0]['basicInfo']['userId'])

    def test_web_share_renders_saved_resonance_and_unknown_identities(self):
        detail = detail_fixture()
        with patch.object(ZFUNC, 'fetch_battle', return_value=detail), \
             patch.object(ZFUNC, 'wzry_get_official') as api, \
             patch.object(ZFILE, 'writerl') as write, \
             patch.object(ZFILE, 'web_history_json_path', return_value='/tmp/share.json'), \
             patch.object(ZFILE, 'battle_exhibit_image_path', return_value='/tmp/share.png'), \
             patch.object(ZFUNC.WebArtifacts, 'history_route_link', return_value='https://example.com/battle'), \
             patch.object(GEN, 'generate_battle_ui_image', return_value=True) as render:
            text, image, mode = DETAIL.btldetail_process('', '', '-123', 0, 42,
                gen_image=True, from_web=True, strict_filter=False)
        self.assertIn('共鸣之战', text)
        self.assertEqual((image, mode), ('/tmp/share.png', '共鸣之战'))
        self.assertEqual(write.call_args.args[1]['redRoles'][0]['battleRecords']['selectedSkills'][0]['sourceHeroId'], 148)
        api.assert_not_called(); render.assert_called_once()

    def test_share_consumer_disables_official_mode_filter_without_sending_a_message(self):
        source = ast.parse(Path('hok/zscheduler.py').read_text(encoding='utf-8-sig'))
        handler = next(node for node in source.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'run_web_shared_btls_processor')
        handler.decorator_list = []
        from types import SimpleNamespace
        params = dict(gameSvrId='', relaySvrId='', gameseq='-123', pvptype='0', roleid='42')
        async def to_thread(function, **kwargs):
            self.assertFalse(kwargs['strict_filter'])
            self.assertTrue(kwargs['from_web'])
            self.assertEqual(kwargs['gameseq'], '-123')
            return '分享', '/tmp/share.png', '共鸣之战'
        scope = dict(__name__='hok._share_test', __package__='hok',
            dmc=SimpleNamespace(redis_deamon_share_btl=SimpleNamespace(rpop=lambda key: json.dumps(params))),
            REDIS_KEY_BATTLE_SHARE_QUEUE='share', json=json, asyncio=SimpleNamespace(to_thread=to_thread),
            MessageSegment=SimpleNamespace(text=lambda value: value, image=lambda value: value),
            add_msg=Mock(), confs={'QQBot': {'group_qid': 1}})
        exec(compile(ast.Module(body=[handler], type_ignores=[]), '<share consumer>', 'exec'), scope)
        asyncio.run(scope[handler.name]())
        scope['add_msg'].assert_called_once()

    def test_image_contains_skill_rows_with_missing_scores_and_team_stats(self):
        detail = detail_fixture()
        requested = []
        def image_asset(url):
            requested.append(url)
            return Image.new('RGBA', (100, 100), '#4488bb')
        with tempfile.TemporaryDirectory() as tmp, patch.object(ZFILE, 'load_battle_report_image', side_effect=image_asset):
            source = Path(tmp) / 'battle.json'; target = Path(tmp) / 'battle.png'
            source.write_text(json.dumps(detail), encoding='utf-8')
            renderer = GEN.BattleUIGenerator()
            with patch.object(renderer, '_draw_selected_skills', wraps=renderer._draw_selected_skills) as skills:
                self.assertTrue(renderer.generate_battle_image(source, target))
            self.assertTrue(any(call.args[2] and call.args[2][0]['skillName'] == '姜子牙被动' for call in skills.call_args_list))
            with Image.open(target) as saved:
                self.assertEqual(saved.width, 1200)
            self.assertTrue(any(url.endswith('/1137.jpg') for url in requested))
            self.assertTrue(any('/148/148.jpg' in url for url in requested))
            self.assertEqual(renderer._grade_label({'gradeGame': None}), '—')
            self.assertEqual(renderer._percentages({}, {'money': None, 'damage': None, 'tanked': None})['money'], None)

    def test_public_image_cache_reuses_original_across_render_sizes_without_another_download(self):
        from io import BytesIO
        stream = BytesIO(); Image.new('RGB', (100, 100), '#4488bb').save(stream, format='PNG')
        api = import_hok_module('zapi')
        with tempfile.TemporaryDirectory() as tmp, patch.object(STATIC, 'battle_image_cache_path', tmp), \
             patch.object(api, 'wzry_battle_image_bytes', return_value=stream.getvalue()) as download:
            for size in [(20, 20), (35, 35)]:
                renderer = GEN.BattleUIGenerator()
                self.assertEqual(renderer._download_image('https://example.com/icon.png', size).size, size)
            download.assert_called_once()


if __name__ == '__main__':
    unittest.main()

import io
import os
import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image
from tools.debugger import import_project_module

REPORT = import_project_module('glorybond.features.game.daily_report')
DRAW = import_project_module('glorybond.rendering.gen_daily_report')
ZFILE = import_project_module('glorybond.storage.files')
ZAPI = import_project_module('glorybond.integrations.api')
STATIC = import_project_module('glorybond.config.settings')


class DailyReportTests(unittest.TestCase):
    def build(self, players, activity=None, failed=()):
        return REPORT.build_daily_report(players, [p['key'] for p in players], activity or {},
                                         report_date='2026-11-23', now=2000000000, failed=failed)

    def player(self, **kwargs):
        return {'key': 'alpha', 'nickname': 'Game Name', 'visible': True, 'today_num': 0,
                'star_up': 0, 'details': [], **kwargs}

    def test_peak_changes_all_modes_and_last_saved_time(self):
        details = [
            {'MapType': -1, 'PeakGradeBeforeGame': 1500, 'PeakGradeAfterGame': 1540, 'GameTime_Timestamp': 1999990000},
            {'MapType': -1, 'PeakGradeBeforeGame': 1540, 'PeakGradeAfterGame': 1520, 'GameTime_Timestamp': 1999995000},
            {'MapType': 0, 'GameTime_Timestamp': 1999998000},
            {'MapType': 1, 'GameTime_Timestamp': 2000000100},
        ]
        row = self.build([self.player(details=details, today_num=3, star_up=-2)],
                         {'alpha': {'last_game_epoch': 1999999000}})['rows'][0]
        self.assertEqual((row['peak'], row['stars'], row['games']), (20, -2, 3))
        self.assertEqual(row['last'], 1999999000)
        self.assertEqual(row['name'], 'Game Name')

    def test_hidden_missing_and_unavailable_fields_never_become_zero(self):
        hidden = self.build([self.player(visible=False, today_num=99, star_up=20)])['rows'][0]
        self.assertEqual(hidden['status'], '战绩隐藏')
        self.assertEqual([hidden[k] for k in ('peak', 'games', 'stars', 'last')], [None]*4)
        missing = self.build([self.player(profile_available=False, details=[{'MapType': -1}])])['rows'][0]
        self.assertIsNone(missing['peak'])
        self.assertIsNone(missing['stars'])
        failed = self.build([self.player(today_num=10)], failed=['alpha'])['rows'][0]
        self.assertIsNone(failed['games'])
        self.assertEqual(failed['status'], '查询失败')

    def test_no_games_keeps_zero_and_previous_activity(self):
        report = self.build([self.player()], {'alpha': {'last_game_epoch': 1900000000}})
        row = report['rows'][0]
        self.assertEqual((row['games'], row['peak'], row['stars']), (0, 0, 0))
        self.assertEqual(row['last'], 1900000000)

    def test_avatar_cache_needs_only_first_download(self):
        stream = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(stream, format='PNG')
        with tempfile.TemporaryDirectory() as cache, \
             patch.object(STATIC, 'battle_image_cache_path', cache), \
             patch.object(ZAPI, 'wzry_battle_image_bytes', return_value=stream.getvalue()) as download:
            REPORT._avatar('https://example.invalid/avatar/test')
            # Unknown hosts are never used as avatar download targets.
            download.assert_not_called()
            REPORT._avatar('https://thirdqq.qlogo.cn/avatar/test')
            REPORT._avatar('https://thirdqq.qlogo.cn/avatar/test')
            download.assert_called_once()

    def test_render_empty_hidden_long_names_and_aligned_days_without_platform_fonts(self):
        for players in ([], [self.player(visible=False)],
                        [self.player(nickname='◽一个足够长的游戏昵称用于验证列宽◽')]):
            report = self.build(players, {'alpha': {'last_game_epoch': 1000000000}})
            image = DRAW.render_daily_report(report, {'alpha': Image.new('RGB', (20, 20), 'red')})
            self.assertEqual(image.width, 1200)
            self.assertGreater(image.height, 500)
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        with tempfile.TemporaryDirectory() as root, patch.object(ZFILE, 'temp_path', root):
            first = ZFILE.save_daily_report_image(image)
            second = ZFILE.save_daily_report_image(image)
            self.assertNotEqual(first, second)
            self.assertTrue(Path(first).is_file())

    def test_expired_avatar_refresh_failure_keeps_cached_image(self):
        stream = io.BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(stream, format='PNG')
        url = 'https://thirdqq.qlogo.cn/avatar/test'
        with tempfile.TemporaryDirectory() as cache, patch.object(STATIC, 'battle_image_cache_path', cache):
            path = Path(cache) / (hashlib.sha256(url.encode()).hexdigest() + '.img')
            path.write_bytes(stream.getvalue())
            os.utime(path, (1, 1))
            with patch.object(ZAPI, 'wzry_battle_image_bytes', side_effect=RuntimeError('offline')) as download:
                image = REPORT._avatar(url)
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))
                download.assert_called_once()

    def test_corrupt_cache_is_replaced_with_valid_image(self):
        stream = io.BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(stream, format='PNG')
        url = 'https://thirdqq.qlogo.cn/avatar/test'
        with tempfile.TemporaryDirectory() as cache, patch.object(STATIC, 'battle_image_cache_path', cache), \
             patch.object(ZAPI, 'wzry_battle_image_bytes', return_value=stream.getvalue()) as download:
            path = Path(cache) / (hashlib.sha256(url.encode()).hexdigest() + '.img')
            path.write_bytes(b'incomplete')
            self.assertEqual(REPORT._avatar(url).size, (8, 8))
            self.assertEqual(REPORT._avatar(url).size, (8, 8))
            download.assert_called_once()


if __name__ == '__main__':
    unittest.main()

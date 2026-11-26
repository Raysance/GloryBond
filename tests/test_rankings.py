import unittest
from unittest.mock import patch

from tools.debugger import import_project_module


RANKINGS = import_project_module('glorybond.features.game.rankings')
REPORT = import_project_module('glorybond.features.game.daily_report')
ZFUNC = import_project_module('glorybond.features.facade')


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.report = None
        def render(report):
            self.report = report
            return '/tmp/report.png'
        patches = [
            patch.object(RANKINGS, 'userlist', {'alice': 11, 'bob': 22}),
            patch.object(RANKINGS, 'write_daily_history_export'),
            patch.object(RANKINGS.zfile, 'read_history_date', return_value=[]),
            patch.object(RANKINGS.zfile, 'read_latest_player_activity', return_value={}),
            patch.object(REPORT, 'render_daily_report_file', side_effect=render),
            patch.object(ZFUNC, 'ai_parser', side_effect=AssertionError('no AI for report images')),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.writer, self.history = self.mocks[1:3]

    def test_partial_player_failure_keeps_available_image_and_saved_history(self):
        old = {'key': 'bob', 'nickname': 'Saved Game Name', 'today_num': 9, 'visible': True, 'star_up': 20}
        self.history.return_value = [old]
        def collect(*, realname):
            if realname == 'bob':
                raise RuntimeError('unavailable')
            return {'key': 'alice', 'nickname': 'Game Name', 'star_up': 3, 'today_num': 2,
                    'visible': True, 'details': []}
        with patch.object(ZFUNC, 'wzry_data', side_effect=collect):
            result = ZFUNC.rnk_process('$', show_zero=False)
        self.assertEqual(result['text'], '')
        self.assertEqual(result['image_path'], '/tmp/report.png')
        self.assertIn('排行遍历异常汇总 count=1', result['error_report'])
        self.assertIn('rank.wzry_data', result['error_report'])
        self.assertIn(old, self.writer.call_args.args[1])
        self.assertEqual(self.report['rows'][1]['name'], 'Saved Game Name')
        self.assertEqual(self.report['rows'][1]['status'], '查询失败')
        self.assertIsNone(self.report['rows'][1]['games'])
        self.assertIsNone(self.report['rows'][1]['stars'])

    def test_all_failures_do_not_write_or_render(self):
        with patch.object(ZFUNC, 'wzry_data', side_effect=RuntimeError('offline')):
            result = ZFUNC.rnk_process('$')
        self.assertIn('暂无可用排行数据', result['text'])
        self.assertIsNone(result['image_path'])
        self.assertIn('count=2', result['error_report'])
        self.writer.assert_not_called()
        self.assertIsNone(self.report)

    def test_zero_games_still_produces_image_with_idle_players(self):
        def collect(*, realname):
            return {'key': realname, 'nickname': realname, 'visible': True,
                    'star_up': 0, 'today_num': 0, 'details': []}
        with patch.object(ZFUNC, 'wzry_data', side_effect=collect):
            result = ZFUNC.rnk_process('', show_zero=False, show_analyze=True)
        self.assertEqual(len(self.report['rows']), 2)
        self.assertEqual(result['image_path'], '/tmp/report.png')

    def test_traversal_error_report_compacts_large_parameters(self):
        error = ZFUNC._build_traversal_error('rank.test', 'alice', {'payload': 'x' * 400}, RuntimeError('offline'))
        report = ZFUNC.format_traversal_error_report('排行遍历', [error])
        self.assertIn('count=1', report)
        self.assertIn("RuntimeError('offline')", report)
        self.assertLess(len(report), 520)


if __name__ == '__main__':
    unittest.main()

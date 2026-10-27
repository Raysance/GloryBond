"""Detailed card facts stay scoped, and the shared identity panel stays readable."""
import copy
import unittest
from unittest.mock import Mock, patch

from PIL import ImageDraw
from hok_research import PlayerRef, Profile
from hok_research.player_pages import battle_display
from local_debugger import import_hok_module
from tests.test_hero_history_cards import history_report
from tests.test_player_client_pages import battle_row
from tests.test_player_client_summary import profile_result

ADAPTER = import_hok_module('api_adapters.player_client')
CARDS = import_hok_module('business.player_client')
MODELS = import_hok_module('business.player_client_profile')
RENDER = import_hok_module('tools.gen_player_summary')
STATIC = import_hok_module('zstatic')
ZFILE = import_hok_module('zfile')


def sections(report):
    return {row['title']: row for row in report['detail_sections']}


def items(section):
    return {label: value for label, value, _ in section['items']}


class DetailModelTests(unittest.TestCase):
    def test_branch_statistics_reuse_the_same_profile_scope_mode_and_native_weighting(self):
        rows = [battle_row(10 + i, 7000 + 100 * i) for i in range(5)]
        for i, row in enumerate(rows):
            row['dwWinNum'] = i
        target = PlayerRef(7, 8, 9)
        profile = Profile(target, {'szAcntName': b'Player', 'stStatistic': {'stRadarDetail': {
            'stCurYear': {'stLadder': battle_row(999, 1), 'astBranchLadder': rows}}}})
        adapter = ADAPTER.PlayerClientAdapter.__new__(ADAPTER.PlayerClientAdapter)
        adapter.settings = {'timeout_seconds': 1}
        adapter.client, adapter.gate, adapter.on_error = Mock(), Mock(), Mock()
        adapter.client.profile.return_value = profile
        result = adapter.query('game_statistics', player=vars(target), scope='year', mode='ranked')
        report = MODELS.statistics_report('配置昵称', result)
        adapter.client.profile.assert_called_once_with(target, timeout=1)
        self.assertEqual(len(adapter.client.method_calls), 1)
        self.assertEqual(adapter.gate.call_count, 1)
        self.assertEqual(report['values']['games'], 60)
        self.assertEqual(items(sections(report)['胜负与表现'])['负场'], 50)
        table = sections(report)['各分路表现']['rows']
        self.assertEqual([row[0] for row in table], ['对抗路', '中路', '发育路', '打野', '游走'])
        for values, raw in zip(table, rows):
            native = battle_display([raw])
            self.assertEqual(values[1:], [native['games'], native['win_rate_percent'], native['composite_score']])
        result = adapter.query('game_statistics', player=vars(target), scope='year', mode='ranked', branch='mid')
        self.assertEqual(result['branch_statistics'], [])
        self.assertEqual(result['display']['games'], 11)
        adapter.client.profile.assert_called_once()

    def test_details_use_unclipped_ability_values_and_do_not_mix_raw_summary_totals(self):
        display = battle_display([battle_row()])
        display['radar']['values']['output'] = 1.24
        display['radar']['plot_ratios']['output'] = 1.0
        report = MODELS.statistics_report('配置昵称', {'display': display, 'games': 999,
            'wins': 900, 'losses': 99, 'raw': {'private': 'PRIVATE_SENTINEL'}})
        projected = sections(report)
        self.assertEqual(items(projected['胜负与表现'])['胜场'], 53)
        self.assertEqual(items(projected['胜负与表现'])['负场'], 51)
        self.assertAlmostEqual(items(projected['胜负与表现'])['败方最佳占比'], 8/51*100)
        self.assertEqual(items(projected['五维能力值'])['输出指数'], 1.24)
        self.assertEqual(report['values']['radar']['output'], 1.0)
        self.assertNotIn('PRIVATE_SENTINEL', repr(report))
        zero = copy.deepcopy(display)
        zero.update(games=0, wins=0, mvp=0, losing_mvp=0)
        projected = sections(MODELS.statistics_report('', {'display': zero}))
        self.assertEqual(items(projected['胜负与表现'])['负场'], 0)
        self.assertIsNone(items(projected['胜负与表现'])['全场最佳占比'])
        self.assertEqual(MODELS.statistics_report('', {})['detail_sections'], [])

    def test_hero_details_include_averages_titles_named_badges_and_labels_without_private_data(self):
        source = {'hero_id': 106, 'player_name': '真实昵称', 'games': 10, 'wins': 6, 'losses': 4,
            'mvp': 0, 'fight_value': 0, 'raw': {'uid': 'PRIVATE_SENTINEL'},
            'statistic_records': [dict(dwKill=20, dwDead=0, dwAssist=40, dwGPM=6000,
                dwHurtPM=20000, ullTotalBeHurt=100000), dict(dwKill=10, dwDead=10, dwAssist=20,
                dwGPM=3000, dwHurtPM=10000, ullTotalBeHurt=50000)],
            'historical_badges': [{'title_type': 5, 'count': 2, 'least_rank': 3, 'raw': {'dwAdCode': 110101}}],
            'badges_named': [{'id': 987654321, 'name': '掌控全场', 'stage': 2, 'done_value': 70}, {'name': None}],
            'year_labels': {'labels': [{'name': '团战发动机', 'level': 3, 'in_use': True}, {'name': None}]}}
        report = MODELS.hero_summary_report(source, STATIC.HeroList, district_names={110101: '北京市东城区'})
        projected = sections(report)
        self.assertEqual(items(projected['详细对局表现']), {'场均击杀': 3, '场均死亡': 1, '场均助攻': 6,
            '每分钟经济': 900, '每分钟输出': 3000, '场均承伤': 15000})
        self.assertEqual(items(projected['当前战力']), {'英雄战力': 0})
        self.assertEqual(projected['历史称号记录']['rows'], [['北京市东城区', 3, 2]])
        self.assertEqual(projected['生涯徽章']['rows'], [['掌控全场', 2, 70]])
        self.assertEqual(projected['赛年标签详情']['rows'], [['团战发动机', 3, '使用中']])
        self.assertNotIn('PRIVATE_SENTINEL', repr(report))
        self.assertNotIn('987654321', repr(report))
        source['statistic_records'][1].pop('dwGPM')
        source['historical_badges'][0]['raw']['dwAdCode'] = True
        projected = sections(MODELS.hero_summary_report(source, STATIC.HeroList, district_names={1: '错误地区'}))
        self.assertIsNone(items(projected['详细对局表现'])['每分钟经济'])
        self.assertIsNone(projected['历史称号记录']['rows'][0][0])

    def test_hero_list_details_keep_the_same_ten_selected_heroes_and_all_branch_scores(self):
        source = {'heroes': [{'hero_id': 106+i, 'name': f'英雄{i}', 'highest_fight_value': 5000-i,
            'wins': i, 'losses': 0, 'proficiency': 1000+i, 'unlocked_badge_count': 2} for i in range(12)],
            'branches': {'branches': [{'name': '中路', 'level': 19, 'score': 14000}]}}
        projected = sections(CARDS.hero_report('', source, STATIC.player_client_config, {}))
        self.assertEqual(len(projected['英雄详细数据']['rows']), 10)
        self.assertEqual(projected['英雄详细数据']['rows'][0], ['英雄0', 0, 0, 1000, 2])
        self.assertEqual(projected['分路战力']['rows'], [['中路', 19, 14000]])

    def test_historical_details_keep_the_existing_grade_denominator(self):
        projected = sections(history_report())
        overall = items(projected['整体对局表现'])
        self.assertEqual((overall['胜场'], overall['负场'], overall['场均击杀']), (4, 4, 2))
        self.assertEqual(overall['平均评分'], (10+8+7+0+12)/5)
        self.assertEqual(projected['英雄表现明细']['rows'][2], ['海月', 2, 0, None, 0])


class SharedHeaderAndLayoutTests(unittest.TestCase):
    def test_name_branch_scope_and_mode_share_size_weight_color_and_a_single_panel(self):
        report = MODELS.statistics_report('', {'player_name': '这是较长的真实游戏昵称' * 3,
            'scope': 'year', 'branch': 'mid', 'mode': 'ranked', 'display': battle_display([battle_row()])})
        fields, lines, heights, body_y, _ = RENDER._header_plan(report, ZFILE.player_client_report_font, {})
        self.assertEqual(''.join(lines[0]), report['label'])
        self.assertGreater(len(lines[0]), 1)
        drawn, original = [], ImageDraw.ImageDraw.text
        def track(draw, xy, text, *args, **kwargs):
            if 128 <= xy[1] < body_y - 20:
                drawn.append((xy, str(text), kwargs['font'].size, kwargs['fill']))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, 'text', track):
            RENDER.render_summary(report, ZFILE.player_client_report_font)
        for index, (_, value) in enumerate(fields):
            x = 88 + index % 2 * 504
            y = 158 + (heights[0] if index // 2 else 0)
            for i, line in enumerate(lines[index]):
                self.assertIn(((x, y + 40*i), line, 32, RENDER.INK), drawn)
        self.assertLess(158 + 40*(len(lines[0])-1) + 40, 128 + heights[0])

    def test_long_region_table_wraps_and_grows_without_clipping_or_section_overlap(self):
        report = MODELS.statistics_report('', {'player_name': '真实昵称', 'scope': 'season'})
        report['detail_sections'] = [{'title': '历史称号记录', 'headers': ['地区', '最好名次', '获得次数'],
            'rows': [['很长的地区名称' * 9, 3, 2]], 'formats': ['text', 'integer', 'integer']},
            {'title': '当前战力', 'items': [('英雄战力', 4300, 'integer')]}]
        drawn, original = [], ImageDraw.ImageDraw.text
        def track(draw, xy, text, *args, **kwargs):
            box = draw.textbbox(xy, text, font=kwargs['font'], anchor=kwargs['anchor'])
            self.assertGreaterEqual(box[0], 24, text)
            self.assertLessEqual(box[2], 1096, text)
            self.assertLess(box[3], draw._image.height-24, text)
            drawn.append((str(text), box))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, 'text', track):
            image = RENDER.render_summary(report, ZFILE.player_client_report_font)
        table_top = next(box[1] for text, box in drawn if text == '历史称号记录')
        next_top = next(box[1] for text, box in drawn if text == '当前战力')
        table_text = [(text, box) for text, box in drawn if table_top < box[1] < next_top and box[0] == 64]
        self.assertEqual(''.join(text for text, _ in table_text if text != '地区'), '很长的地区名称'*9)
        self.assertGreater(next_top - table_top, 300)
        self.assertLess(image.width * image.height, 8_000_000)


if __name__ == '__main__':
    unittest.main()

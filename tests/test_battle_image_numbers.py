"""Camp strings and native numeric statistics render together without losing missing values."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from local_debugger import import_hok_module

GEN = import_hok_module('tools.gen_battle_res')


class BattleImageNumberTests(unittest.TestCase):
    def stats(self):
        return {'money': '1200', 'totalHeroHurtCnt': '6000', 'totalBeheroHurtCnt': '1000'}

    def team(self):
        return [{'battleStats': self.stats()}, {'battleStats': {
            'money': 800, 'totalHeroHurtCnt': '2000', 'totalBeheroHurtCnt': 3000}}]

    def test_mixed_camp_strings_and_native_numbers_have_correct_totals_and_shares(self):
        totals = GEN.BattleUIGenerator._team_totals(self.team())
        self.assertEqual(totals, {'money': 2000, 'damage': 8000, 'tanked': 4000})
        self.assertEqual(GEN.BattleUIGenerator._percentages(self.stats(), totals),
                         {'money': 60, 'damage': 75, 'tanked': 25})

    def test_zero_is_valid_and_unknown_statistics_stay_unknown(self):
        for unknown in (None, '', '—', 'NaN', float('inf'), True):
            with self.subTest(value=unknown):
                team = self.team(); team[1]['battleStats']['money'] = unknown
                totals = GEN.BattleUIGenerator._team_totals(team)
                self.assertIsNone(totals['money'])
                shares = GEN.BattleUIGenerator._percentages(self.stats(), totals)
                self.assertIsNone(shares['money'])
                self.assertEqual(shares['damage'], 75)
                self.assertEqual(GEN.BattleUIGenerator._percent_label(shares['money']), '—')
        zeros = {'money': '0', 'totalHeroHurtCnt': 0, 'totalBeheroHurtCnt': '0.0'}
        totals = GEN.BattleUIGenerator._team_totals([{'battleStats': zeros}])
        self.assertEqual(GEN.BattleUIGenerator._percentages(zeros, totals), {'money': 0, 'damage': 0, 'tanked': 0})

    def test_complete_image_renders_string_statistics_in_header_and_player_cards(self):
        roles = self.team()
        for index, role in enumerate(roles):
            role.update(basicInfo={'roleId': str(42 + index), 'roleName': '玩家', 'acntCamp': 1},
                        battleRecords={'usedHero': {'heroName': '小乔'}, 'finalEquips': []})
            role['battleStats'].update(killCnt='3', deadCnt='2', assistCnt=5, gradeGame='8.5')
        data = {'head': {'roleId': '42', 'roleName': '玩家', 'gameResult': True},
                'battle': {'mapName': '匹配赛', 'usedTime': 600},
                'redRoles': roles, 'redTeam': {'gameResult': True}, 'blueRoles': [], 'blueTeam': {}}
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'battle.json', Path(tmp) / 'battle.png'
            source.write_text(json.dumps(data), encoding='utf-8')
            renderer = GEN.BattleUIGenerator()
            with patch.object(renderer, '_calculate_team_percentages', wraps=renderer._calculate_team_percentages) as header, \
                 patch.object(renderer, '_draw_player_card', wraps=renderer._draw_player_card) as cards:
                self.assertTrue(renderer.generate_battle_image(source, target))
            header.assert_called_once(); self.assertEqual(cards.call_count, 2)
            with Image.open(target) as image:
                self.assertEqual(image.format, 'PNG')
                self.assertEqual(image.width, 1200)


if __name__ == '__main__':
    unittest.main()

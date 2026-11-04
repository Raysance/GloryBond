"""Extra accounts keep their own identity, perspective and archive coverage."""

import datetime
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from sqlglot import parse_one

from agent_console import remote_worker as worker
from agent_console.tools import sql_validation as validation
from agent_console.tools.reference_data import ReferenceData


ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / 'shared/agent/hok_sql/catalog.json').read_text())
DEFINITIONS = json.loads((ROOT / 'shared/agent/hok_sql/views.json').read_text())
MANIFEST = json.loads((ROOT / 'shared/agent/reference_data/manifest.json').read_text())
RECORDED_COLUMNS = {
    'snapshot_date': 'text', 'player_key': 'text', 'player_index': 'integer',
    'detail_index': 'integer', 'user_id': 'bigint', 'role_id': 'bigint',
    'game_seq': 'bigint', 'game_time_label': 'text', 'game_time_epoch': 'bigint',
    'hero_name': 'text', 'map_name': 'text', 'map_type': 'integer',
    'star_after_game': 'integer', 'peak_grade_after': 'integer', 'peak_grade_before': 'integer',
    'kill_count': 'integer', 'death_count': 'integer', 'assist_count': 'integer',
    'result': 'text', 'game_grade': 'numeric', 'duration_seconds': 'integer',
    'params': 'jsonb', 'others': 'jsonb', 'record_payload': 'jsonb', 'record_source': 'text',
    'is_official': 'boolean', 'participant_index': 'integer', 'player_camp': 'text',
    'player_hero_id': 'bigint', 'player_gold': 'integer', 'participant_payload': 'jsonb',
    'game_type': 'integer', 'battle_payload': 'jsonb',
}


def references():
    return ReferenceData(MANIFEST, {
        'userlist': {'main': 1001, 'main_b': 1002},
        'roleidlist': {'main': 101, 'main_b': 102},
        'extra_namenick': {'extra': '额外成员'},
        'extra_useridlist': {'extra': 1003, 'opponent': 1004, 'user_only': 1005, 'conflict': 1006,
                            'shared_a': 2000, 'shared_b': 2000},
        'extra_roleidlist': {'extra': 103, 'opponent': 104, 'conflict': 106,
                            'shared_a': 201, 'shared_b': 202},
        'sameuser': {'main': ['extra']},
    }, source='fixture')


class ExtraPlayerSQLTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS hok")
        self.db.execute('CREATE TABLE hok.recorded (' + ','.join(
            name + ' ' + kind for name, kind in RECORDED_COLUMNS.items()) + ')')
        self.db.execute('CREATE VIEW hok.battle_records AS SELECT *, record_payload AS payload FROM recorded')
        self.db.execute('CREATE TABLE hok.battle_details (game_seq bigint, game_type integer, payload jsonb)')
        self.db.execute('''CREATE TABLE hok.battle_participants (
            game_seq bigint, participant_index integer, camp text, role_id bigint, user_id bigint,
            role_name text, hero_id bigint, hero_name text, kill_count integer, death_count integer,
            assist_count integer, game_grade numeric, gold integer, payload jsonb)''')
        self.bindings = references().game_identity_rows()
        definitions = {**DEFINITIONS, 'chat_recorded_battle_source': 'SELECT * FROM hok.recorded'}
        context = {'definitions': definitions, 'catalogs': {'hok_sql': CATALOG},
                   'validation': validation.__dict__}
        patcher = patch.dict(worker.CONTEXT, context, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.epoch = int(datetime.datetime.fromisoformat('2026-01-01T12:00:00+08:00').timestamp())
        self.add_record('main', 1, 101, 0)
        self.add_record('main_b', 1, 102, 1)
        for index, role, user, camp in [(0, 101, 1001, '1'), (1, 102, 1002, '1'),
                (2, 103, 1003, '1'), (3, 104, 1004, '2'), (4, None, 1005, '2'),
                (5, 999, 1006, '1'), (6, None, 2000, '1'), (7, 999, 9999, '1')]:
            self.add_participant(1, index, role, user, camp)
        # The account's own archived row wins over a projected participant row.
        self.add_record('extra', 2, 103, 2, result='失败', game_grade=7, star_after_game=55)
        self.add_participant(2, 2, 103, 1003, '1')
        self.add_record('main', 3, 101, 0, game_time_epoch=self.epoch + 86400)
        self.add_participant(3, 2, 103, 1003, None)
        self.add_participant(4, 2, 103, 1003, '1')  # No dated match anchor.
        self.add_record('main', 5, 101, 0, is_official=False, map_name='大乱斗')
        self.add_participant(5, 2, 103, 1003, '1')

    def add_record(self, key, game, role, index, **changes):
        row = dict.fromkeys(RECORDED_COLUMNS)
        row.update(snapshot_date='2025-12-31', player_key=key, game_seq=game, role_id=role,
                   player_index=index, detail_index=game, participant_index=index,
                   game_time_epoch=self.epoch, hero_name='主成员英雄', map_name='排位赛',
                   map_type=1, result='胜利', game_grade=8, kill_count=10, death_count=1,
                   assist_count=10, star_after_game=99, duration_seconds=1200,
                   record_source='battle_record', is_official=True, player_camp='1',
                   participant_payload='{}', battle_payload='{}')
        row.update(changes)
        self.db.execute('INSERT INTO hok.recorded VALUES (' + ','.join('?' for _ in row) + ')', list(row.values()))

    def add_participant(self, game, index, role, user, camp):
        payload = {'battleStats': {'mvp': False, 'totalHeroHurtCnt': 1234},
                   'battleRecords': {'finalEquips': [{'equipName': '本人装备'}]}}
        self.db.execute('INSERT INTO hok.battle_participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (game, index, camp, role, user, '不用于身份匹配', 11, '额外成员英雄', 2, 9, 4, 3, 5000, json.dumps(payload)))

    def query(self, sql, scope=None):
        normalized = validation.validate_readonly_sql(sql, allowed_tables=CATALOG['tables'], schema_name='hok')
        compiled = worker.expand_semantic_views(normalized, validation.normalize_game_scope(scope or {}), self.bindings)
        return [dict(row) for row in self.db.execute(parse_one(compiled, read='postgres').sql(dialect='sqlite'))]

    def test_exact_extra_identity_owns_stats_and_matches_are_not_multiplied(self):
        rows = self.query("SELECT player_key,game_seq,hero_name,kill_count,death_count,assist_count,"
                          "game_grade,result,star_after_game,is_mvp,record_source "
                          "FROM hok.chat_player_battles WHERE player_key='extra' ORDER BY game_seq")
        self.assertEqual([row['game_seq'] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0], {'player_key': 'extra', 'game_seq': 1, 'hero_name': '额外成员英雄',
            'kill_count': 2, 'death_count': 9, 'assist_count': 4, 'game_grade': 3, 'result': '胜利',
            'star_after_game': None, 'is_mvp': 0, 'record_source': 'battle_participant'})
        self.assertEqual((rows[1]['game_grade'], rows[1]['star_after_game'], rows[1]['record_source']), (7, 55, 'battle_record'))
        self.assertIsNone(rows[2]['result'])
        rows = self.query("SELECT player_key,result FROM hok.chat_player_battles WHERE game_seq=1 ORDER BY player_key")
        self.assertEqual([(row['player_key'], row['result']) for row in rows],
                         [('extra', '胜利'), ('main', '胜利'), ('main_b', '胜利'), ('opponent', '失败'), ('user_only', '失败')])

    def test_scoped_counts_and_roster_use_extra_account_perspective(self):
        scope = {'start_at': '2026-01-01T00:00:00+08:00', 'end_at': '2026-01-02T00:00:00+08:00'}
        sql = "SELECT COUNT(*) AS games FROM hok.chat_player_battles WHERE player_key='extra'"
        self.assertEqual(self.query(sql, scope), [{'games': 2}])
        self.assertEqual(self.query(sql, {**scope, 'mode': 'all'}), [{'games': 3}])
        rows = self.query("SELECT relation,participant_player_key,game_grade FROM hok.chat_player_battle_roster "
                          "WHERE player_key='opponent' AND game_seq=1 ORDER BY participant_index", scope)
        self.assertEqual(len(rows), 8)
        self.assertEqual((rows[2]['relation'], rows[2]['participant_player_key']), ('opponent', 'extra'))
        self.assertEqual((rows[3]['relation'], rows[3]['participant_player_key']), ('self', 'opponent'))
        self.assertEqual((rows[4]['relation'], rows[4]['participant_player_key']), ('teammate', 'user_only'))
        self.assertIsNone(rows[5]['participant_player_key'])
        self.assertIsNone(rows[6]['participant_player_key'])

    def test_known_match_result_is_preferred_over_an_unknown_perspective(self):
        self.add_record('a_unknown_result', 1, 901, 8, result=None)
        self.assertEqual(self.query("SELECT result FROM hok.chat_player_battles WHERE player_key='extra' AND game_seq=1"),
                         [{'result': '胜利'}])

    def test_configuration_literals_are_escaped_and_private_relations_stay_private(self):
        key = "member'; SELECT 1; --"
        self.bindings.append({'player_key': key, 'user_id': 1003, 'role_id': 103})
        rows = self.query('SELECT player_key FROM hok.chat_player_battles WHERE game_seq=1')
        self.assertIn({'player_key': key}, rows)
        for table in ('chat_configured_players', 'chat_configured_users', 'chat_configured_battle_participants',
                      'chat_battle_record_keys', 'chat_player_battle_facts',
                      'chat_player_battle_source', 'chat_recorded_battle_source', 'battle_participants'):
            with self.subTest(table=table), self.assertRaises(validation.ChatSQLValidationError):
                self.query(f'SELECT player_key FROM hok.{table}')
        self.bindings = []
        self.assertEqual(self.query("SELECT COUNT(*) AS games FROM hok.chat_player_battles WHERE game_seq=1"), [{'games': 2}])

    def test_extra_personal_snapshots_and_power_do_not_require_daily_history(self):
        self.db.execute('CREATE TABLE hok.history_players (snapshot_date text, user_id bigint, player_key text, player_index integer)')
        self.db.execute('''CREATE TABLE hok.personal_snapshots (snapshot_date text, user_id bigint,
            target_role_id bigint, invisible boolean, is_gaming boolean, battle_count integer, payload jsonb, updated_at text)''')
        self.db.executemany('INSERT INTO hok.personal_snapshots VALUES (?,?,?,?,?,?,?,?)', [
            ('2026-01-01', 1003, 103, False, False, 5, '{}', None),
            ('2026-01-01', 2000, None, False, False, 8, '{}', None)])
        self.assertEqual(self.query("SELECT player_key,battle_count FROM hok.chat_personal_snapshots WHERE player_key='extra'"),
                         [{'player_key': 'extra', 'battle_count': 5}])
        self.assertEqual(self.query('SELECT battle_count FROM hok.chat_personal_snapshots WHERE player_key IS NULL'), [{'battle_count': 8}])
        self.db.execute('''CREATE TABLE hok.battle_power (game_seq bigint, map_name text, evaluated_at text,
            my_side_level numeric, opponent_side_level numeric, my_side_tier numeric, opponent_side_tier numeric, game_result text)''')
        self.db.execute('''CREATE TABLE hok.battle_power_players (game_seq bigint, participant_index integer,
            role_id bigint, user_id bigint, nickname text, side text, hero_name text, hero_power integer,
            hero_win_rate numeric, hero_average_score numeric, single_level numeric, payload jsonb)''')
        self.db.execute("INSERT INTO hok.battle_power VALUES (99,'排位赛','2026-01-01',10,20,1,2,'胜利')")
        self.db.execute("INSERT INTO hok.battle_power_players VALUES (99,0,103,1003,'游戏昵称','op','英雄',100,0.5,8,15,'{}')")
        self.assertEqual(self.query("SELECT player_key,participant_result,participant_side_level FROM hok.chat_battle_power_players"),
                         [{'player_key': 'extra', 'participant_result': '失败', 'participant_side_level': 20}])
        # Power's own evaluation clock must not inherit battle time/mode filters,
        # including for old archived accounts absent from today's configuration.
        self.add_record('archived_only', 99, 999, 9, is_official=False, map_name='大乱斗')
        self.db.execute("INSERT INTO hok.battle_power_players VALUES (99,9,999,9999,'旧账号','my','英雄',100,0.5,8,15,'{}')")
        self.assertEqual(self.query("SELECT player_key FROM hok.chat_battle_power_players WHERE participant_index=9",
                                   {'start_at': '2027-01-01T00:00:00+08:00'}), [{'player_key': 'archived_only'}])

    def test_analysis_refreshes_mapping_once_per_validated_batch(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.description = []
        cursor.fetchmany.return_value = []
        args = {'domain': 'game', 'principal': {}, 'scope': {}, 'queries': [
            {'sql': 'SELECT COUNT(*) FROM hok.chat_player_battles'},
            {'sql': 'SELECT COUNT(*) FROM hok.chat_player_battle_roster'}]}
        first = references()
        second = ReferenceData(MANIFEST, {'extra_useridlist': {'new_member': 9001}}, source='fixture')
        with patch.dict(worker.CONTEXT, {'cfg': {}}), patch.object(worker, 'db_connection', return_value=conn), \
             patch.object(worker, 'reference_data', side_effect=[first, second]) as read:
            self.assertEqual(worker.analyze(args)['reference_version'], first.version)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(worker.analyze(args)['reference_version'], second.version)
            self.assertEqual(read.call_count, 2)
        self.assertIn('new_member', cursor.execute.call_args.args[0])
        self.assertNotIn("CAST('extra'", cursor.execute.call_args.args[0])


if __name__ == '__main__':
    unittest.main()

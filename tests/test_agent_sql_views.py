"""Semantic queries retain identity/cardinality across query shapes and hosts."""

import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from sqlglot import parse_one

from agent_console import remote_worker as worker


DEFINITIONS = json.loads((Path(__file__).parents[1] / 'shared/agent/hok_sql/views.json').read_text())


class SemanticCompilerTests(unittest.TestCase):
    def test_qualified_columns_and_explicit_aliases_keep_resolving_after_expansion(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for sql in ('SELECT items.id FROM hok.items', 'SELECT hok.items.id FROM hok.items',
                    'SELECT chosen.id FROM hok.items AS chosen'):
            with self.subTest(sql=sql), patch.dict(worker.CONTEXT, {'definitions': {'items': 'SELECT 7 AS id'}}, clear=True):
                compiled = worker.expand_semantic_views(sql)
                self.assertEqual(db.execute(parse_one(compiled, read='postgres').sql(dialect='sqlite')).fetchall(), [(7,)])

    def test_definition_version_does_not_depend_on_installed_views_or_user_cte_names(self):
        definitions = {'items': 'SELECT id FROM hok.storage'}
        sql = ('WITH __agent_view_items AS (SELECT 99 AS id), items AS (SELECT 88 AS id) '
               'SELECT items.id FROM hok.items JOIN __agent_view_items AS other ON items.id=other.id')
        results = []
        for installed in (set(), {'items'}):
            with patch.dict(worker.CONTEXT, {'definitions': definitions, 'views': installed}, clear=True):
                results.append(worker.expand_semantic_views(sql))
        self.assertEqual(results[0], results[1])
        tree = parse_one(results[0], read='postgres')
        names = [cte.alias for cte in tree.args['with_'].expressions]
        self.assertEqual(len(names), len(set(names)))
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute("ATTACH DATABASE ':memory:' AS hok")
        db.execute('CREATE TABLE hok.storage (id INTEGER)')
        db.execute('INSERT INTO hok.storage VALUES (99)')
        self.assertEqual(db.execute(tree.sql(dialect='sqlite')).fetchall(), [(99,)])


class RosterSemanticsTests(unittest.TestCase):
    def test_boolean_mvp_flags_are_typed_and_unknown_values_stay_unknown(self):
        catalog = json.loads((Path(__file__).parents[1] / 'shared/agent/hok_sql/catalog.json').read_text())
        columns = [name for name in catalog['tables']['chat_player_battles']['columns'] if name != 'is_mvp']
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute("ATTACH DATABASE ':memory:' AS hok")
        db.execute('CREATE TABLE hok.chat_player_battle_source (' + ','.join(name+' TEXT' for name in columns) + ')')
        for value in (True, False, 1, 0, 'true', 'false', None, 'unknown'):
            row = {name: None for name in columns}
            row['participant_payload'] = json.dumps({'battleStats': {'mvp': value}})
            db.execute('INSERT INTO hok.chat_player_battle_source VALUES (' + ','.join('?' for _ in columns) + ')',
                       [row[name] for name in columns])
        sql = parse_one(DEFINITIONS['chat_player_battles'], read='postgres').sql(dialect='sqlite')
        rows = db.execute('SELECT is_mvp FROM ('+sql+')').fetchall()
        self.assertEqual([row[0] for row in rows], [1, 0, 1, 0, 1, 0, None, None])

    def test_multiple_perspectives_aliases_unknown_roles_and_null_camps_keep_their_meaning(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.execute("ATTACH DATABASE ':memory:' AS hok")
        db.execute('''CREATE TABLE hok.chat_player_battle_source (
            snapshot_date TEXT, player_key TEXT, game_seq INTEGER, game_time_epoch INTEGER,
            hero_name TEXT, map_name TEXT, map_type INTEGER, is_official BOOLEAN,
            result TEXT, game_grade NUMERIC, player_camp TEXT, role_id INTEGER,
            participant_index INTEGER, record_source TEXT)''')
        db.execute('''CREATE TABLE hok.battle_participants (
            game_seq INTEGER, role_id INTEGER, camp TEXT, participant_index INTEGER,
            role_name TEXT, hero_id INTEGER, hero_name TEXT, kill_count INTEGER,
            death_count INTEGER, assist_count INTEGER, game_grade NUMERIC, gold INTEGER, payload TEXT)''')
        # Two tracked names share a role; insertion order must not pick its identity.
        perspectives = [('z_alias', 10, 'blue'), ('a_alias', 10, 'blue'),
                        ('red_player', 20, 'red'), ('unknown_role', None, None)]
        participants = [(10, 'blue'), (20, 'red'), (30, 'blue'), (None, None)]
        for game in range(1, 5):
            for name, role, camp in perspectives:
                index = next((i for i, (r, _) in enumerate(participants) if r == role), None) if role is not None else None
                db.execute('INSERT INTO hok.chat_player_battle_source VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           ('2026-01-01', name, game, game, '本人英雄', '排位', 1, True, '胜利', 8, camp, role, index, 'battle_record'))
            for index, (role, camp) in enumerate(participants):
                db.execute('INSERT INTO hok.battle_participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (game, role, camp, index, '参赛者', index, '英雄', 1, 1, 1, 8, 100, '{}'))
        sql = parse_one(DEFINITIONS['chat_player_battle_roster'], read='postgres').sql(dialect='sqlite')
        rows = db.execute(sql).fetchall()
        self.assertEqual(len(rows), 4 * len(perspectives) * len(participants))
        for row in rows:
            role, camp = participants[row['participant_index']]
            viewer_role, viewer_camp = next((r, c) for name, r, c in perspectives if name == row['player_key'])
            expected = 'self' if role is not None and role == viewer_role else 'teammate' if camp == viewer_camp else 'opponent'
            self.assertEqual(row['relation'], expected)
            self.assertEqual(row['participant_player_key'], {10: 'a_alias', 20: 'red_player'}.get(role))
            self.assertEqual((row['player_result'], row['player_game_grade']), ('胜利', 8))


if __name__ == '__main__':
    unittest.main()

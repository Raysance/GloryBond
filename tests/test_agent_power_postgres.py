"""Synthetic SELECT-only PostgreSQL checks; opt in with HOK_TEST_POSTGRES_DSN."""

import datetime
import json
import os
import unittest
from unittest.mock import patch

from sqlglot import exp
from glorybond.agent import remote_worker as worker
from glorybond.agent.tools import sql_validation as validation
from tests.test_agent_power_sql import CATALOG, GAME_CATALOG, DEFINITIONS, validate


def literal(value, kind):
    return exp.cast(exp.convert(json.dumps(value, ensure_ascii=False) if kind == 'jsonb' else value), kind).sql(dialect='postgres')


def fixture_relation(rows, columns):
    return ' UNION ALL '.join('SELECT ' + ', '.join(
        literal(value, kind) + ' AS ' + name for (name, kind), value in zip(columns, row)) for row in rows)


def fixture_cases():
    epoch = int(datetime.datetime.fromisoformat('2026-11-02T00:10:00+08:00').timestamp())
    players = [dict(roleId=11+i, userId=21+i, nickname=f'player{i}', side=side, isAuth=True,
        heroName='hero', heroPower=1000+i, heroWinRate=.6, heroAvgScore=8, singleLevel=10+i,
        recentWinRate=.7, customMetric=42+i, requestErrors=['private-diagnostic'],
        playerAvatarUrl='private-avatar', heroAvatarUrl='private-hero')
        for i, side in enumerate(('my', 'op', 'op', None))]
    powers, participants = [], []
    for game in range(101, 105):
        mode = '排位赛' if game != 104 else '大乱斗'
        payload = dict(GameSeq=str(game), gameTime='source-label', gameResult='胜利',
            gameSvrId='private-server', relaySvrId='private-relay', roleid='private-role',
            mySide={'level':50,'tier':2,'authCnt':1,'requestErrors':['private-error']},
            opSide={'level':60,'tier':3,'authCnt':2,'requestErrors':[]}, players=players,
            matchup={'winRate':.6,'error':'private-matchup'}, aiAnalysis='saved-analysis',
            customBusiness={'newMetric':99})
        if game == 102:
            payload['matchup'] = None
        powers.append((game, mode, '2026-11-05', 50, 60, 2, 3, '胜利', payload))
        participants.extend((game,i,11+i,21+i,p['nickname'],p['side'],'hero',1000+i,.6,8,10+i,p)
                            for i,p in enumerate(players))
    for game, size, authorizations, level in [
        (105,5,[False]*5,0), (106,5,[True,False,False,False,False],0),
        (107,4,[False]*4,0), (108,5,[None,False,False,False,False],0),
        (109,5,[False]*5,60), (110,5,[False]*5,None), (111,5,[True]*5,60),
    ]:
        team = [dict(players[0])]
        for i in range(size):
            item = dict(roleId=100+i,userId=200+i,nickname='unknown',side='op',singleLevel=0)
            if authorizations[i] is not None:
                item['isAuth'] = authorizations[i]
            team.append(item)
        payload = dict(GameSeq=str(game),mySide={'level':50},opSide={'level':level},players=team)
        powers.append((game,'排位赛','2026-11-05',50,level,2,3,'胜利',payload))
        participants.extend((game,i,p['roleId'],p['userId'],p['nickname'],p['side'],'hero',1000,.6,8,p['singleLevel'],p)
                            for i,p in enumerate(team))
    definitions = {**DEFINITIONS,
        'battle_power': fixture_relation(powers, [('game_seq','bigint'),('map_name','text'),('evaluated_at','text'),
            ('my_side_level','numeric'),('opponent_side_level','numeric'),('my_side_tier','numeric'),
            ('opponent_side_tier','numeric'),('game_result','text'),('payload','jsonb')]),
        'battle_power_players': fixture_relation(participants, [('game_seq','bigint'),('participant_index','integer'),
            ('role_id','bigint'),('user_id','bigint'),('nickname','text'),('side','text'),('hero_name','text'),
            ('hero_power','integer'),('hero_win_rate','numeric'),('hero_average_score','numeric'),('single_level','numeric'),('payload','jsonb')]),
        'chat_recorded_battle_source': 'SELECT 101::bigint AS game_seq, 11::bigint AS role_id, \'main\'::text AS player_key',
        # The immediately preceding match has no power assessment and lies
        # outside the requested day. It must still define the activity gap.
        'chat_player_battle_facts': fixture_relation([
            ('main',90,epoch-30*86400,'battle_record'), ('main',100,epoch-3600,'battle_record'),
            ('main',101,epoch,'battle_record'), ('main',103,epoch+86400,'battle_record'),
            ('extra',50,epoch-8*86400,'battle_participant'), ('extra',101,epoch,'battle_participant')],
            [('player_key','text'),('game_seq','bigint'),('game_time_epoch','bigint'),('record_source','text')]),
        'chat_battle_record_keys': fixture_relation([(101,'2026-11-01',epoch),(101,'2026-11-01',epoch),
            (103,'2026-11-02',epoch+86400),(104,'2026-11-01',epoch)],
            [('game_seq','bigint'),('snapshot_date','date'),('game_time_epoch','bigint')]),
    }
    bindings = [{'player_key':'main','role_id':11,'user_id':21}, {'player_key':'extra','role_id':12,'user_id':22}]
    scope = {'start_at':'2026-11-02T00:00:00+08:00','end_at':'2026-11-03T00:00:00+08:00'}
    specifications = [
        ('full_business_json', "SELECT game_seq, jsonb_array_length(payload->'players') AS players, payload->'customBusiness' AS custom, payload->'mySide'->>'requestErrorCount' AS errors, payload->>'aiAnalysis' AS analysis, payload::text LIKE '%private-%' AS leaked FROM hok.chat_battle_power WHERE player_keys @> ARRAY['main']", scope,
         [{'game_seq':101,'players':4,'custom':{'newMetric':99},'errors':'1','analysis':'saved-analysis','leaked':False}]),
        ('cohort_before_aggregation', 'SELECT COUNT(*) AS games FROM hok.chat_battle_power', scope, [{'games':1}]),
        ('mode_all', 'SELECT COUNT(*) AS games FROM hok.chat_battle_power', {**scope,'mode':'all'}, [{'games':2}]),
        ('opponent_and_unknown', "SELECT other.player_key, other.participant_payload->>'customMetric' AS metric FROM hok.chat_battle_power_players me JOIN hok.chat_battle_power_players other ON me.game_seq=other.game_seq WHERE me.player_key='main' AND me.side='my' AND other.side='op' ORDER BY other.participant_index",scope,
         [{'player_key':'extra','metric':'43'},{'player_key':None,'metric':'44'}]),
        ('perspective', "SELECT participant_result, participant_side_level::int AS own FROM hok.chat_battle_power_players WHERE player_key='extra'", scope,[{'participant_result':'失败','own':60}]),
        ('unknown_side', "SELECT participant_result FROM hok.chat_battle_power_players WHERE participant_index=3",scope,[{'participant_result':None}]),
        ('undated_json', "SELECT game_seq, payload->'matchup' AS matchup FROM hok.chat_battle_power WHERE game_seq=102",{},[{'game_seq':102,'matchup':None}]),
        ('undated_excluded', 'SELECT game_seq FROM hok.chat_battle_power WHERE game_seq=102',scope,[]),
        ('json_expand', "SELECT p->>'playerKey' AS player, p->>'customMetric' AS metric FROM hok.chat_battle_power CROSS JOIN LATERAL jsonb_array_elements(payload->'players') p WHERE p->>'playerKey' = 'extra'",scope,[{'player':'extra','metric':'43'}]),
        ('end_boundary', 'SELECT game_seq FROM hok.chat_battle_power',{'start_at':'2026-11-02T00:00:00+08:00','end_at':'2026-11-02T00:10:00+08:00'},[]),
        ('complete_history_gap', "SELECT gap_since_previous_game_seconds, previous_game_record_source, match_average_level::int AS power FROM hok.chat_battle_power_players WHERE game_seq=101 AND player_key='main'",scope,
         [{'gap_since_previous_game_seconds':3600,'previous_game_record_source':'battle_record','power':55}]),
        ('extra_history_gap', "SELECT gap_since_previous_game_seconds, activity_record_source FROM hok.chat_battle_power_players WHERE game_seq=101 AND player_key='extra'",scope,
         [{'gap_since_previous_game_seconds':8*86400,'activity_record_source':'battle_participant'}]),
        ('bot_team_rule', "SELECT game_seq, rival_side_is_bot, match_average_level::int AS power FROM hok.chat_battle_power_players WHERE player_key='main' AND game_seq>=105 ORDER BY game_seq",{},
         [{'game_seq':g,'rival_side_is_bot':flag,'power':p} for g,flag,p in
          [(105,True,None),(106,False,None),(107,None,None),(108,None,None),(109,False,55),(110,True,None),(111,False,55)]]),
        ('full_json_bot_flags', 'SELECT game_seq, opponent_side_is_bot FROM hok.chat_battle_power WHERE game_seq>=105 ORDER BY game_seq',{},
         [{'game_seq':g,'opponent_side_is_bot':flag} for g,flag in
          [(105,True),(106,False),(107,None),(108,None),(109,False),(110,True),(111,False)]]),
    ]
    cases = []
    with patch.dict(worker.CONTEXT, {'definitions': definitions, 'catalogs': {'hok_sql':GAME_CATALOG,'power_sql':CATALOG},'validation':validation.__dict__}, clear=True):
        for name, sql, bounds, expected in specifications:
            scoped = validation.normalize_game_scope(bounds)
            scoped['as_of'] = '2026-11-04T00:00:00+08:00'
            cases.append({'name':name,'sql':worker.expand_semantic_views(validate(sql),scoped,bindings),'expected':expected})
    return cases


@unittest.skipUnless(os.environ.get('HOK_TEST_POSTGRES_DSN'), 'requires an explicitly configured PostgreSQL test connection')
class PowerPostgresTests(unittest.TestCase):
    def test_synthetic_json_and_account_queries(self):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ['HOK_TEST_POSTGRES_DSN'], row_factory=dict_row,
                options='-c default_transaction_read_only=on -c statement_timeout=10000') as conn:
            for case in fixture_cases():
                with self.subTest(case=case['name']):
                    self.assertEqual(conn.execute(case['sql']).fetchall(), case['expected'])


if __name__ == '__main__':
    unittest.main()

"""Dual-source deduplication, bounded persistence and native-layout projections."""
import copy
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

from local_debugger import import_hok_module

HISTORY = import_hok_module('business.player_client_history')
DATA = import_hok_module('business.player_data')
PRESENT = import_hok_module('business.player_client_screens')
HANDLER = import_hok_module('event_handlers.player_client')
ADAPTER = import_hok_module('api_adapters.player_client')
ZFUNC = import_hok_module('zfunc')
STATIC = import_hok_module('zstatic')
ZTIME = import_hok_module('ztime')
ZFILE = import_hok_module('zfile')
METRICS = import_hok_module('business.battle_metrics')
ZDB = import_hok_module('zdb')

PLAYER = dict(uid=2**61+3, logic_world_id=8, fake_description_id=9)
START = ZTIME.parse_chat_time_bound('2026-10-23 12:00:00')


def match(sequence=123, hero=106, start=START):
    return dict(desk_id=42, desk_sequence=sequence, start_time=start, duration_seconds=600,
        winning_camp=2, mode='resonance', mode_name='共鸣之战', map_id=5466,
        players=[dict(uid=999, logic_world_id=8, hero_id=hero, camp=1),
                 dict(**PLAYER, hero_id=hero, camp=2, kills=3, deaths=4, assists=5,
                      selected_skill_ids=[1, 2, 3, 4], premade_size=3)])


def client_result(*rows):
    return dict(matches=list(rows or [match()]), collection=dict(ordinary_complete=True,
        entertainment_received=True, entertainment_complete=False))


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.settings = {**STATIC.player_client_config, 'players': {'alice': PLAYER}}

    def converted(self, *rows):
        return HISTORY.client_battles(client_result(*rows), PLAYER, self.settings)

    def test_exact_full_uid_world_and_unknown_values_never_guess_another_players_view(self):
        row = self.converted()[0]
        self.assertEqual((row['killcnt'], row['deadcnt'], row['assistcnt'], row['gameresult']), (3,4,5,1))
        self.assertEqual(row['selectedSkillIds'], [1,2,3,4])
        self.assertTrue(row['gradeMissing'])
        self.assertEqual(row['gradeGame'], 0)  # Explicit legacy placeholder, not a rating.
        self.assertIn('评分', row['clientMissing'])
        self.assertLess(row['gameSeq'], 0)
        self.assertGreater(row['gameSeq'], -(2**63))
        self.assertEqual(row['gameSeq'], self.converted()[0]['gameSeq'])
        wrong = match(); wrong['players'][1]['logic_world_id'] = 9
        self.assertEqual(self.converted(wrong), [])
        wrong['players'][1]['logic_world_id'] = 8
        wrong['players'].append(dict(wrong['players'][1]))
        self.assertEqual(self.converted(wrong), [])

    def test_dedup_strong_sequence_preserves_all_original_camp_fields(self):
        client = self.converted()[0]
        camp = {**client, 'gameSeq': 123, 'gradeGame': 12.5, 'clientOnly': False, 'detailUrl': 'real-camp-link'}
        before = copy.deepcopy(camp)
        rows, count = HISTORY.merge_battles([camp], [client], tolerance_seconds=90)
        self.assertEqual(count, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['gradeGame'], 12.5)
        self.assertEqual(rows[0]['detailUrl'], 'real-camp-link')
        self.assertEqual(camp, before)

    def test_time_hero_kda_duration_fallback_is_unique_and_does_not_merge_nearby_distinct_games(self):
        client = self.converted()[0]
        camp = {**client, 'gameSeq': 555, 'clientOnly': False, 'dtEventTime': str(START+620)}
        rows,count = HISTORY.merge_battles([camp], [client], tolerance_seconds=90)
        self.assertEqual((len(rows), count), (1,0))
        for field,value in [('heroId',112), ('killcnt',10), ('usedTime',900), ('dtEventTime',str(START+2000))]:
            with self.subTest(field=field):
                rows,count = HISTORY.merge_battles([{**camp,field:value}], [client], tolerance_seconds=90)
                self.assertEqual((len(rows), count), (2,1))
        duplicate = match(); duplicate['source']='entertainment'
        self.assertEqual(len(self.converted(match(),duplicate)), 1)
        rows,count = HISTORY.merge_battles([{**camp,'dtEventTime':str(START)}], [client], tolerance_seconds=90)
        self.assertEqual((len(rows), count), (2,1))  # Previous game's end is this game's start.

    def collect(self, camp, client, saved=None):
        with patch.object(ZFUNC,'player_client_config',self.settings), \
             patch.object(ZFUNC,'userlist',{'alice':1001}), patch.object(ZFUNC,'roleidlist',{'alice':42}), \
             patch.object(DATA,'_battle_list_for_date',side_effect=camp), \
             patch.object(ZFUNC,'player_client_query',side_effect=client), \
             patch.object(DATA.zfile,'read_personal_history',return_value=saved), patch.object(ZFUNC,'log_message'):
            return DATA._combined_battle_list('alice',1001,42,ZTIME.str_to_time('2026-10-23').date())

    def test_providers_start_in_parallel_then_merge(self):
        barrier=threading.Barrier(2,timeout=2)
        def camp(*args):
            barrier.wait(); return dict(list=[],invisible=False,isGaming=False,gaming={})
        def client(*args,**kwargs):
            barrier.wait(); return client_result()
        value=self.collect(camp,client)
        self.assertEqual(len(value['list']),1)
        self.assertEqual(value['clientAdded'],1)
        self.assertEqual(value['sourceWarnings'],[])

    def test_failed_provider_retains_the_other_and_saved_client_rows(self):
        saved={'btlist':{'list':self.converted()}}
        value=self.collect(lambda *a: dict(list=[],invisible=False), lambda *a,**k: (_ for _ in ()).throw(TimeoutError()),saved)
        self.assertEqual(len(value['list']),1)
        self.assertEqual(value['sourceWarnings'],[])
        self.assertEqual(value['sourceErrors'],[{'source':'客户端','error_type':'TimeoutError'}])
        value=self.collect(lambda *a: (_ for _ in ()).throw(RuntimeError('paging incomplete')),lambda *a,**k:client_result())
        self.assertEqual(len(value['list']),1)
        self.assertFalse(value['invisible'])
        value=self.collect(lambda *a: dict(list=[],invisible=True),lambda *a,**k:client_result())
        self.assertTrue(value['campInvisible'])
        self.assertFalse(value['invisible'])
        with self.assertRaisesRegex(RuntimeError,'均未取得'):
            self.collect(lambda *a: (_ for _ in ()).throw(TimeoutError()),lambda *a,**k: (_ for _ in ()).throw(TimeoutError()))

    def test_saved_client_record_is_replaced_by_new_camp_record_without_double_counting(self):
        converted=self.converted()[0]
        saved={'btlist':{'list':[converted]}}
        camp={**converted,'gameSeq':123,'clientOnly':False,'gradeGame':12,'gradeMissing':False}
        value=self.collect(lambda *a:dict(list=[camp],invisible=False),lambda *a,**k:client_result(),saved)
        self.assertEqual(len(value['list']),1)
        self.assertEqual(value['list'][0]['gameSeq'],123)
        self.assertEqual(value['list'][0]['gradeGame'],12)

    def test_wrong_explicit_role_does_not_query_a_players_other_account(self):
        with patch.object(ZFUNC,'player_client_config',self.settings), patch.object(ZFUNC,'userlist',{'alice':1001}), \
             patch.object(ZFUNC,'roleidlist',{'alice':42}), patch.object(DATA,'_battle_list_for_date',return_value={}), \
             patch.object(ZFUNC,'player_client_query') as query:
            DATA._combined_battle_list('alice',1001,43,ZTIME.str_to_time('2026-10-23').date())
            query.assert_not_called()

    def test_client_only_daily_rows_reach_saved_payload_and_details_but_not_camp_detail_endpoint(self):
        # Exercises the real daily exporter rather than only testing a projected list.
        row=self.converted()[0]
        older=self.converted(match(sequence=124,start=START-86400))[0]
        btlist=dict(list=[row,older],invisible=False,isGaming=False,gaming={},sourceWarnings=['本次返回范围'])
        profile={'roleList':[{'roleId':42,'roleName':'甲'}], 'head':{'mods':[{
            'modId':701,'name':'最强王者','param1':'{"rankingStar":12}'}]}}
        with patch.object(ZFUNC,'userlist',{'alice':1001}), patch.object(ZFUNC,'roleidlist',{'alice':42}), \
             patch.object(DATA,'_combined_battle_list',return_value=btlist), \
             patch.object(ZFUNC,'wzry_get_official',return_value=profile) as camp, \
             patch.object(ZFUNC,'log_message'), patch.object(DATA.zdb,'latest_rank_star_before',return_value=50), \
             patch.object(ZFILE,'read_battle_detail',return_value=None), patch.object(ZFILE,'writerl') as save:
            result=DATA.wzry_data('alice','out.json',target_date='2026-10-23')
        self.assertEqual(result['today_num'],1)
        self.assertEqual(result['details'][0]['Source'],'player_client')
        self.assertTrue(result['details'][0]['GradeMissing'])
        self.assertNotIn('clientMatch',save.call_args.args[1]['btlist']['list'][0])
        self.assertNotIn('clientPlayer',save.call_args.args[1]['btlist']['list'][0])
        archive=[call.args[1] for call in save.call_args_list
                 if call.args[0]==ZFILE.personal_history_path('2026-10-23',1001)]
        self.assertEqual(len(archive),1)
        self.assertEqual(archive[0]['profile']['targetRoleId'],42)
        self.assertEqual(archive[0]['profile']['userId'],1001)
        self.assertEqual(archive[0]['btlist']['list'][0]['clientMatch']['map_id'],5466)
        details=[call.args[0] for call in save.call_args_list if call.args[0] in
                 [ZFILE.battle_detail_path(row['gameSeq']),ZFILE.battle_detail_path(older['gameSeq'])]]
        self.assertEqual(len(details),2)
        self.assertEqual([call.kwargs['reqtype'] for call in camp.call_args_list],['profile'])
        self.assertEqual(METRICS.calculate_official_battle_average([
            dict(MapName='排位赛',GameGrade=0,GradeMissing=True),dict(MapName='排位赛',GameGrade=10)]),10)

    def test_database_columns_do_not_store_placeholder_zeroes_as_real_ratings_or_rank_changes(self):
        connection=MagicMock()
        connection.__enter__.return_value=connection
        cursor=connection.cursor.return_value.__enter__.return_value
        detail=dict(Source='player_client',GradeMissing=True,GameGrade=0,StarAfterGame=-1,
                    PeakGradeBeforeGame=-1,PeakGradeAfterGame=-1,KillCnt=0,DeadCnt=0,AssistCnt=0,
                    DataMissing=['击杀','死亡','助攻'])
        player=dict(id=1001,key='alice',profile_available=False,rank_star=0,star=0,star_up=0,details=[detail])
        with patch.object(ZDB,'_connect',return_value=connection):
            ZDB.replace_history_date('2026-10-23',[player])
        player_args=cursor.execute.call_args_list[1].args[1]
        battle_args=cursor.execute.call_args_list[2].args[1]
        self.assertEqual(player_args[7:10],(None,None,None))
        self.assertEqual(battle_args[12:18],(None,None,None,None,None,None))
        self.assertIsNone(battle_args[19])

    def test_missing_camp_profile_does_not_drop_client_matches_or_claim_camp_visibility(self):
        btlist=dict(list=self.converted(),invisible=False,isGaming=False,gaming={},
                    sourceWarnings=['营地战绩未取得'],campAvailable=False)
        with patch.object(ZFUNC,'userlist',{'alice':1001}), patch.object(ZFUNC,'roleidlist',{'alice':42}), \
             patch.object(DATA,'_combined_battle_list',return_value=btlist), \
             patch.object(ZFUNC,'wzry_get_official',side_effect=TimeoutError()), \
             patch.object(ZFUNC,'sync_battle_visibility_state') as visibility, patch.object(ZFUNC,'log_message'), \
             patch.object(DATA.zdb,'latest_rank_star_before',return_value=50), \
             patch.object(ZFILE,'read_battle_detail',return_value=None), \
             patch.object(ZFILE,'read_personal_history',return_value=None), patch.object(ZFILE,'writerl'):
            result=DATA.wzry_data('alice','out.json',target_date='2026-10-23',sync_battle_visibility=True)
        self.assertEqual(result['today_num'],1)
        self.assertFalse(result['profile_available'])
        visibility.assert_not_called()


class StatisticsTests(unittest.TestCase):
    def test_data_filters_preserve_scope_mode_and_branch_independently(self):
        settings={'players':{'alice':PLAYER}}
        examples=[('#甲的数据',('season','all',None)),
                  ('#甲的数据 当前赛年 中路',('year','all','mid')),
                  ('＃甲当前塞年打野的数据',('year','all','jungle')),
                  ('#甲的数据全部比赛 所有游戏 全部分路',('all','all',None)),
                  ('#甲的数据 当前赛季 排位 对抗路',('season','ranked','top'))]
        for text,wanted in examples:
            with self.subTest(text=text):
                tokens=HANDLER.parse_client_shortcut(text,settings=settings,nicknames={'alice':'甲'},
                    player_aliases={},hero_names={},hero_aliases={})
                _,params,_=HANDLER.query_parameters(tokens,user_id='1',settings=settings,qids={},nicknames={'alice':'甲'})
                self.assertEqual(tuple(params[k] for k in ('scope','mode','branch')),wanted)
        with self.assertRaises(ValueError):HANDLER.statistics_options('当前赛季 当前赛年')
        with self.assertRaises(ValueError):HANDLER.statistics_options('猜测一种分路')

    def test_structured_api_uses_server_scope_and_branch_not_recent_matches(self):
        from hok_research.profile_data import GameData
        row=dict(dwCount=104,dwWinNum=53,dwLoseNum=51,dwTotal=7370,dwGoldMedal=6,
                 dwHurtHero=8000,dwKDA=6000,dwGrow=7000,dwBattle=8500,dwSurvive=6500,
                 dwColorMedal=0,dwSliverMedal=14,dwCopperMedal=3,dwMvp=10,dwLoseSoul=8,
                 dwTripleKill=1,dwUltraKill=0,dwRampage=0,dwGodLike=4)
        fake=Mock(); fake.game.return_value=GameData({'stStatistic':{'stRadarDetail':{'stCurSeason':{
            'stTotal':row,'astBranchTotal':[{},row,{}, {}, {}]}}}})
        adapter=object.__new__(ADAPTER.PlayerClientAdapter)
        adapter.client=fake; adapter.settings={'timeout_seconds':1}; adapter.gate=Mock();adapter.on_error=Mock()
        data=adapter.query('game_statistics',player=PLAYER,scope='season',mode='all',branch='mid')
        self.assertEqual(data['games'],104)
        self.assertEqual(data['branch'],'mid')
        self.assertEqual(data['score_raw'],7370)
        self.assertAlmostEqual(data['display']['composite_score'],73.7,places=4)
        fake.matches.assert_not_called()
        fake.game.assert_called_once()

    def test_missing_units_and_unknown_fields_are_excluded_from_visible_reports(self):
        data=dict(scope='season',games=104,win_rate_percent=51,score_raw=7370,
                  radar_raw={'output':100000},raw={'secret':'not for display'},medals={'gold':0})
        report=PRESENT.screen_report('game','甲',data,{})
        self.assertIsNone(report['values']['score'])
        self.assertEqual(report['values']['medals']['gold'],0)
        self.assertNotIn('secret',repr(report))
        self.assertIn('雷达图',report['notice'])
        self.assertIn('综合得分',report['notice'])

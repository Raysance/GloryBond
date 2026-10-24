"""Client matches use the existing detail archive/SQL contract with exact identities."""
import copy
import unittest
from unittest.mock import MagicMock, patch

from tests.test_player_client_integration import HISTORY, DATA, ZFUNC, ZFILE, ZDB, STATIC, PLAYER, match, client_result


class ClientDetailTests(unittest.TestCase):
    def row(self):
        value=match()
        value['players'][1].update(name='甲',gold=12345,hero_damage=40000,
            damage_taken_from_enemies=50000,equipment=[dict(dwEquipID=1234,bCnt=1)],score_raw=910)
        return HISTORY.client_battles(client_result(value),PLAYER,STATIC.player_client_config)[0]

    def detail(self,row):
        return HISTORY.camp_battle_detail(row,PLAYER,roleid=42,userid=1001,identities={},
            hero_names=STATIC.HeroList,settings=STATIC.player_client_config)

    def test_complete_participant_projection_preserves_values_and_never_forges_camp_ids(self):
        detail=self.detail(self.row())
        self.assertEqual(detail['source'],'player_client')
        self.assertEqual(detail['head']['roleId'],'42')
        self.assertEqual(detail['head']['userId'],'1001')
        self.assertTrue(detail['head']['gameResult'])
        self.assertEqual(len(detail['redRoles'])+len(detail['blueRoles']),2)
        own=detail['redRoles'][0]
        self.assertEqual(own['basicInfo']['clientUid'],str(PLAYER['uid']))
        self.assertEqual(own['battleStats']['money'],12345)
        self.assertEqual(own['battleStats']['totalHeroHurtCnt'],40000)
        self.assertEqual(own['battleStats']['gradeGame'],9.1)
        self.assertEqual(own['battleStats']['gradeDisplay'],'9.1')
        self.assertEqual(own['battleRecords']['finalEquips'][0]['equipId'],1234)
        self.assertEqual(own['battleRecords']['selectedSkillIds'],[1,2,3,4])
        self.assertIsNone(detail['blueRoles'][0]['basicInfo']['roleId'])
        self.assertIsNone(detail['blueRoles'][0]['basicInfo']['userId'])
        self.assertEqual(detail['battle']['usedTime'],600)

    def test_wrong_or_ambiguous_target_is_rejected(self):
        row=self.row();row['clientMatch']['players'][1]['logic_world_id']=9
        with self.assertRaises(ValueError):self.detail(row)
        row=self.row();row['clientMatch']['players'].append(copy.deepcopy(row['clientMatch']['players'][1]))
        with self.assertRaises(ValueError):self.detail(row)

    def test_export_reaches_sql_details_and_participants_without_external_request(self):
        row=self.row();connection=MagicMock();connection.__enter__.return_value=connection
        cursor=connection.cursor.return_value.__enter__.return_value
        with patch.object(ZDB,'_connect',return_value=connection),patch.object(ZFILE,'postgres_archive_json',False), \
             patch.object(ZFUNC,'wzry_get_official') as api:
            failed=DATA.export_battle_details([dict(GameSeq=str(row['gameSeq']),Source='player_client')],42,
                client_rows=[row],userid=1001)
        self.assertEqual(failed,[]);api.assert_not_called()
        sql_calls=cursor.execute.call_args_list
        self.assertIn('INSERT INTO hok.battle_details',sql_calls[0].args[0])
        self.assertEqual(sql_calls[0].args[1][0],row['gameSeq'])
        participants=[call.args[1]for call in sql_calls if 'INSERT INTO hok.battle_participants'in call.args[0]]
        self.assertEqual(len(participants),2)
        self.assertEqual(participants[0][0],row['gameSeq'])
        self.assertEqual(participants[0][11],9.1)
        self.assertIn(12345,[p[12]for p in participants])

    def test_saved_snapshots_backfill_is_offline_and_idempotent_by_game_sequence(self):
        row=self.row();snapshot=dict(target_role_id=42,user_id=1001,payload={'btlist':{'list':[row]}})
        writes={}
        def save(path,payload):writes[payload['gameSeq']]=payload
        for apply in (False,True,True):
            with patch.object(ZFILE,'iter_client_battle_snapshots',return_value=iter([snapshot])), \
                 patch.object(ZFILE,'iter_cached_client_battle_snapshots',return_value=iter([snapshot,snapshot])), \
                 patch.object(ZFILE,'writerl',side_effect=save),patch.object(ZFUNC,'wzry_get_official') as api:
                result=DATA.backfill_client_battle_details(apply=apply)
            self.assertEqual(result['battles'],1);self.assertEqual(result['failed'],0)
            api.assert_not_called()
            self.assertEqual(len(writes),int(apply))

    def test_legacy_web_cache_backfill_honors_game_day_without_external_requests(self):
        row=self.row();snapshot=dict(target_role_id=42,user_id=1001,payload={'btlist':{'list':[row]}})
        for start,end,count in [('2026-10-23','2026-10-23',1),('2026-10-24',None,0),(None,'2026-10-22',0)]:
            with patch.object(ZFILE,'iter_client_battle_snapshots',return_value=iter([])), \
                 patch.object(ZFILE,'iter_cached_client_battle_snapshots',return_value=iter([snapshot])), \
                 patch.object(ZFILE,'writerl') as save,patch.object(ZFUNC,'wzry_get_official') as api:
                result=DATA.backfill_client_battle_details(start_date=start,end_date=end,apply=True)
            self.assertEqual(result['battles'],count);self.assertEqual(result['failed'],0)
            self.assertEqual(save.call_count,count);api.assert_not_called()

    def test_web_cache_reader_ignores_compact_public_lists_and_preserves_legacy_identity(self):
        row=self.row()
        native={'profile':{'targetRoleId':42,'userId':1001},'btlist':{'list':[row]}}
        compact=DATA.battle_list_web_payload(native)
        with patch.object(ZFILE,'get_file_list',return_value=['old.json','new.json']), \
             patch.object(ZFILE,'readerl',side_effect=[native,compact]):
            snapshots=list(ZFILE.iter_cached_client_battle_snapshots())
        self.assertEqual(len(snapshots),1)
        self.assertEqual(snapshots[0]['target_role_id'],42)
        self.assertEqual(snapshots[0]['user_id'],1001)

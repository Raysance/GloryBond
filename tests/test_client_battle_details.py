"""Follow an exact client-only battle ID from browser JSON through the existing detail route."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

os.environ.setdefault('BOT_PATH',str(Path(__file__).resolve().parents[2]/'HOK_QQBot'))
from fastapi.testclient import TestClient
from fastapi.responses import HTMLResponse
import app as web
import utils

SEQ='-9223372036854775806'


def payload():
    return dict(source='player_client',gameSeq=SEQ,
        head=dict(roleId='42',userId='1001',gameResult=True),
        battle=dict(mapName='共鸣之战',usedTime=600),
        redTeam=dict(acntCamp=2,gameResult=True),blueTeam=dict(acntCamp=1,gameResult=False),
        blueRoles=[dict(basicInfo=dict(roleId=None,userId=None))],
        redRoles=[dict(basicInfo=dict(roleId='42',userId='1001',roleName='甲',acntCamp=2),
            battleRecords=dict(usedHero=dict(heroName='小乔')),
            battleStats=dict(killCnt=3,deadCnt=4,assistCnt=5,gradeGame=None))])


class ClientBattleRoutes(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(web.app)
        # These legacy routes use the Starlette 0.x template calling convention deployed by Web.
        def render(name,context,**kwargs):
            return HTMLResponse(web.templates.get_template(name).render(context),status_code=kwargs.get('status_code',200))
        replacement=patch.object(web.templates,'TemplateResponse',side_effect=render)
        replacement.start();self.addCleanup(replacement.stop)
        analytics=patch.object(web,'should_track_request',return_value=False)
        analytics.start();self.addCleanup(analytics.stop)

    def browser(self,code):
        helpers=(Path(__file__).parents[1]/'templates/CommonPages/battle_helpers.js').read_text()
        result=subprocess.run(['node','-e',helpers+'\n'+code],check=True,text=True,capture_output=True)
        return json.loads(result.stdout)

    def test_legacy_int64_json_survives_browser_and_click_opens_saved_detail(self):
        raw='{"GameSeq":'+SEQ+',"Source":"player_client","name":"literal 9223372036854775806"}'
        url=self.browser('const game=parseBattlePayload('+json.dumps(raw)+');console.log(JSON.stringify(battleDetailUrl({roleid:42},game,"valid")));')
        self.assertIn('gameSeq='+SEQ,url)
        with patch.object(web,'check_key_valid',return_value=True), \
             patch.object(web,'check_battle_local_exist',return_value=True),patch.object(web,'wzry_get_official') as camp:
            page=self.client.get(url)
        self.assertEqual(page.status_code,200)
        self.assertIn('/battle-data/'+SEQ+'?roleid=42',page.text)
        camp.assert_not_called()
        with patch.object(utils,'postgres_fetch_battle',return_value=copy.deepcopy(payload())):
            data=self.client.get('/battle-data/'+SEQ,params={'roleid':'42'})
        self.assertEqual(data.status_code,200)
        self.assertEqual(data.json()['head']['roleName'],'甲')
        self.assertIsNone(data.json()['head']['gradeGame'])

    def test_missing_client_detail_never_calls_camp_and_invalid_ids_never_reach_storage(self):
        with patch.object(web,'check_key_valid',return_value=True), \
             patch.object(web,'check_battle_local_exist',return_value=False),patch.object(web,'wzry_get_official') as api:
            result=self.client.get('/jump-battle',params=dict(gameSvr='',relaySvr='',battleType='0',
                gameSeq=SEQ,targetRoleId='42',key='valid'))
        self.assertEqual(result.status_code,404);api.assert_not_called()
        with patch.object(web,'fetch_battle') as read:
            for identifier in ['--123','0x12','9223372036854775808','-9223372036854775809','１２']:
                self.assertEqual(self.client.get('/battle-data/'+identifier).status_code,400)
        read.assert_not_called()

    def test_missing_scores_show_a_dash_and_are_excluded_from_averages(self):
        result=self.browser('console.log(JSON.stringify([battleGradeLabel({gradeMissing:true,gradeGame:0}),'+
            'battleGradeLabel({gradeGame:null}),battleAverageGrade([{gradeGame:10},{gradeMissing:true,gradeGame:0}])]))')
        self.assertEqual(result,['—','—','10.0'])

    def test_camp_links_keep_server_parameters_and_missing_parameters_are_not_invented(self):
        url=self.browser('console.log(JSON.stringify(battleDetailUrl({roleid:42},{GameSeq:123,Params:{gameSvrId:1,relaySvrId:2,pvptype:4}},"valid")))')
        self.assertIn('gameSvr=1',url);self.assertIn('relaySvr=2',url)
        self.assertEqual(self.browser('console.log(JSON.stringify(battleDetailUrl({roleid:42},{GameSeq:123},"valid")))'),'')

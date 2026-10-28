"""Consume SDK page views with synthetic data and no private research fixtures."""
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
from hok_research import Profile, PlayerRef, HeroExtraStatistics, HeroTitles
from hok_research.player_pages import battle_display
from local_debugger import import_hok_module

ADAPTER=import_hok_module('api_adapters.player_client')
SCREENS=import_hok_module('business.player_client_screens')
CARDS=import_hok_module('business.player_client')
RENDER=import_hok_module('tools.gen_player_client')
ZFILE=import_hok_module('zfile')
STATIC=import_hok_module('zstatic')
ZFUNC=import_hok_module('zfunc')
SUMMARY_RENDER=import_hok_module('tools.gen_player_summary')


def battle_row(count=104,score=7370):
    return dict(dwCount=count,dwWinNum=53,dwLoseNum=51,dwTotal=score,
        dwHurtHero=8000,dwKDA=6000,dwGrow=7000,dwBattle=8500,dwSurvive=6500,
        dwColorMedal=0,dwGoldMedal=6,dwSliverMedal=14,dwCopperMedal=3,
        dwMvp=10,dwLoseSoul=8,dwTripleKill=1,dwUltraKill=0,dwRampage=0,dwGodLike=4)


class PlayerPageTests(unittest.TestCase):
    def sources(self):
        player=PlayerRef(7,8,9)
        stats=dict(bGameType=4,bMapAcntNum=10,dwWinNum=139,dwLoseNum=135,
                     dwMvpGameNum=274,dwAbilityGameCnt=274,dwMvpScore=1033*274,
                     dwHurtHero=8500*274,dwKDA=6000*274,dwGrow=7000*274,
                     dwBattle=8000*274,dwSurvive=5500*274,
                     dwColorMedalCnt=0,dwGoldMedalCnt=24,dwSilverMedalCnt=28,dwCopperMedalCnt=12,
                     dwMvp=46,dwLoseSoul=8)
        hero=dict(dwHeroID=106,dwSkinID=0,dwFightValue=3900,dwTopFightValueOfHistory=4300,
                  dwGameWinNum=139,dwGameLoseNum=135,
                  stStatisticDetail=dict(dwNum=1,astTypeDetail=[stats]))
        raw=dict(szAcntName=b'test-player',stMostUsedHero=dict(dwHeroNum=1,astHeroInfoList=[hero]),
                 stStatistic=dict(stRadarDetail=dict(stCurSeason=dict(stTotal=battle_row(),astBranchTotal=[battle_row()]))),
                 stPosFightValue=dict(astBranchScore=[dict(dwPosFightValueScore=v)for v in (0,14000,0,0,3000)]))
        profile=Profile(player,raw)
        label_raw=dict(ullUid=player.uid,dwLogicWorldID=player.logic_world_id,stResultInfo=dict(iResultId=0),
            stHeroStatisticExtraInfo=dict(astHeroInfoList=[dict(dwHeroID=106,
                stHeroLabel=dict(bNum=3,bUseHeroLabelNum=3,astHeroLabelInfo=[
                    dict(bHeroLableID=i,bHeroLableLevel=2,bUseFlag=1)for i in (102,103,110)]))]))
        titles=HeroTitles(player,dict(ullUid=player.uid,dwLogicWorldID=player.logic_world_id,
            stResultInfo=dict(iResultId=0),stHistoryHeroLbsTitleInfo=dict(dwHeroCnt=1,
            astHeroLbsTitleData=[dict(dwHeroID=106,dwTitleTypeCnt=2,astOneTitleTypeData=[
                dict(dwTitleType=1,dwLeastRankNo=50,dwTitleGetCnt=7,dwAdCode=340803),
                dict(dwTitleType=5,dwLeastRankNo=3,dwTitleGetCnt=2,dwAdCode=110101)])])))
        brief=dict(stHeroRoadBriefInfo=dict(astHeroRoadBriefData=[dict(dwHeroID=106,dwUnLockBadgeNum=23,
            stShowTitle=dict(dwShowTitleID=2,dwShowBigType=2,iStyleLvl=0))]))
        detail=dict(stDetailHeroExtraInfo=dict(astDetailHeroExtraData=[]))
        return profile,HeroExtraStatistics(player,label_raw),titles,brief,detail

    def adapter(self):
        profile,labels,titles,brief,detail=self.sources()
        fake=Mock()
        fake.profile.return_value=profile
        fake.hero_extra_statistics.return_value=labels
        fake.hero_titles.return_value=titles
        fake.hero_road_brief.return_value=brief
        fake.hero_detail.return_value=detail
        adapter=object.__new__(ADAPTER.PlayerClientAdapter)
        adapter.client=fake
        adapter.gate=Mock()
        adapter.on_error=Mock()
        adapter.settings={'timeout_seconds':1,'rate_limit':{'privacy_codes':[32002]}}
        return adapter,fake,profile.player

    def test_paced_hero_honors_reads_only_needed_sources_and_native_display(self):
        adapter,fake,player=self.adapter()
        result=adapter.query('hero_honors',player=vars(player),hero_id=106)
        self.assertEqual(adapter.gate.call_count,5)
        self.assertEqual([call[0] for call in fake.method_calls],
                         ['profile','hero_titles','hero_extra_statistics','hero_road_brief','hero_detail'])
        fake.homepage.assert_not_called()
        model=SCREENS.screen_report('hero','甲',result,STATIC.HeroList)
        self.assertEqual(model['values']['score'],result['display']['composite_score'])
        self.assertIsNotNone(model['values']['radar'])
        self.assertEqual(model['historical_badges'],[7,0,0,2,0])
        self.assertEqual(model['rank_badge']['text'],'第3名')
        self.assertEqual(len(model['year_labels']),3)
        self.assertNotIn(None,model['year_labels'])
        self.assertEqual(model['notice'],'')
        self.assertNotIn('raw',repr(model))

    def test_cards_include_named_style_rank_and_native_branch_levels(self):
        adapter,fake,player=self.adapter()
        result=adapter.query('heroes',player=vars(player),scope='all')
        self.assertEqual(adapter.gate.call_count,4)
        fake.hero_detail.assert_not_called()
        model=CARDS.hero_report('甲',result,STATIC.player_client_config,STATIC.HeroList)
        self.assertEqual(model['rows'][0]['fight_style'],'均衡发展的峡谷财神')
        self.assertEqual(model['rows'][0]['rank_badge']['rank'],3)
        self.assertEqual([row['text']for row in model['branches']],['中路19段','游走7段'])
        self.assertNotIn('暂缺',model['hint'])
        self.assertNotIn('raw',repr(model))

    def test_historical_title_region_survives_sdk_projection_and_both_image_facades(self):
        adapter,fake,player=self.adapter()
        # The title belongs to Beijing even when the current profile location differs.
        fake.profile.return_value.raw['stAcntLocation']={'dwAdCode':440300}
        cards=adapter.query('heroes',player=vars(player),scope='all')
        honors=adapter.query('hero_honors',player=vars(player),hero_id=106)
        self.assertEqual(honors['rank_badge']['raw']['dwAdCode'],110101)
        with patch.object(ZFUNC,'player_client_hero_avatars',return_value={}), \
             patch.object(SUMMARY_RENDER,'render_summary') as render, \
             patch.object(ZFILE,'save_player_client_report',return_value='card.png'):
            ZFUNC.player_client_hero_report('甲',cards)
            ZFUNC.player_client_screen_report('hero','甲',honors)
        reports=[call.args[0] for call in render.call_args_list]
        badges=[reports[0]['rows'][0]['rank_badge'],reports[1]['rank_badge']]
        for badge in badges:
            self.assertEqual(badge['region'],'北京市东城区')
            self.assertEqual(badge['text'],'北京市东城区 第3名')
        self.assertIn('历史称号北京市东城区 第3名',reports[0]['text'])
        self.assertIn('历史称号 北京市东城区 第3名',reports[1]['text'])
        self.assertEqual(adapter.gate.call_count,5)

    def test_unknown_or_missing_title_regions_do_not_guess_a_location(self):
        regions={110101:'北京市东城区',156:'全国'}
        for adcode in (None,0,999999,True,'110101'):
            with self.subTest(adcode=adcode):
                rank=SCREENS.rank_model({'ranked':True,'rank':3,'raw':{'dwAdCode':adcode}},regions)
                self.assertIsNone(rank['region'])
                self.assertEqual(rank['text'],'第3名')
        rank=SCREENS.rank_model({'ranked':True,'rank':1,'raw':{'dwAdCode':156}},regions)
        self.assertEqual(rank['text'],'全国 第1名')
        with patch.object(ZFILE,'read_honor_districts',side_effect=OSError('missing catalog')):
            self.assertEqual(ZFUNC._player_client_title_regions(),{})

    def test_hero_list_single_hero_and_game_share_the_same_profile_sources(self):
        adapter,fake,player=self.adapter()
        fake.profile.return_value.raw['szAcntName']='LYG.未央'.encode()
        cards=adapter.query('heroes',player=vars(player),scope='all')
        honors=adapter.query('hero_honors',player=vars(player),hero_id=106,scope='all')
        game=adapter.query('game_statistics',player=vars(player),scope='season')
        self.assertTrue(cards['heroes'])
        self.assertEqual(honors['hero_id'],106)
        self.assertEqual(game['scope'],'season')
        models=import_hok_module('business.player_client_profile')
        self.assertEqual(CARDS.hero_report('配置昵称',cards,STATIC.player_client_config,STATIC.HeroList)['label'],'LYG.未央')
        self.assertEqual(models.hero_summary_report(honors,STATIC.HeroList)['label'],'LYG.未央')
        self.assertEqual(models.statistics_report('配置昵称',game)['label'],'LYG.未央')
        fake.profile.assert_called_once()
        fake.hero_titles.assert_called_once()
        fake.hero_extra_statistics.assert_called_once()
        fake.hero_road_brief.assert_called_once()
        fake.hero_detail.assert_called_once()
        fake.game.assert_not_called()
        self.assertEqual(adapter.gate.call_count,5)

    def test_game_display_uses_weighted_branch_rows_instead_of_raw_summary(self):
        # Raw summary is deliberately inconsistent with the native display source.
        result=dict(scope='season',mode='ranked',games=999,win_rate_percent=1,
            mvp=999,score_raw=99999,display=battle_display([battle_row()]))
        model=SCREENS.screen_report('game','甲',result,{})
        self.assertEqual(model['values']['games'],104)
        self.assertEqual(model['values']['mvp'],10)
        self.assertAlmostEqual(model['values']['score'],73.7,places=4)
        self.assertAlmostEqual(model['values']['radar']['output'],.8,places=5)
        self.assertEqual(model['notice'],'')

    def test_zero_empty_and_unread_history_sources_remain_distinct(self):
        adapter,fake,player=self.adapter()
        titles=fake.hero_titles.return_value
        titles.raw['stHistoryHeroLbsTitleInfo'].update(dwHeroCnt=0,astHeroLbsTitleData=[])
        result=adapter.query('hero_honors',player=vars(player),hero_id=106)
        model=SCREENS.screen_report('hero','甲',result,STATIC.HeroList)
        self.assertEqual(model['historical_badges'],[0]*5)
        self.assertEqual(model['rank_badge']['text'],'暂无排名')
        result['historical_badges']=None;result['rank_badge']=None
        unknown=SCREENS.screen_report('hero','甲',result,STATIC.HeroList)
        self.assertEqual(unknown['historical_badges'],[None]*5)
        self.assertIsNone(unknown['rank_badge'])
        self.assertIn('历史徽章',unknown['notice'])

    def test_optional_pacing_keeps_received_sources_and_stops_further_requests(self):
        adapter,fake,player=self.adapter()
        adapter.gate.side_effect=[None,None,ADAPTER.PlayerClientRateLimited(20)]
        result=adapter.query('hero_honors',player=vars(player),hero_id=106)
        self.assertIsNotNone(result['display'])
        self.assertEqual(result['historical_badges'][0]['count'],7)
        fake.hero_extra_statistics.assert_not_called()
        fake.hero_road_brief.assert_not_called()
        fake.hero_detail.assert_not_called()
        self.assertEqual(adapter.gate.call_count,3)

    def test_rendered_radar_labels_counts_and_styles_replace_placeholders(self):
        adapter,_,player=self.adapter()
        honors=SCREENS.screen_report('hero','甲',adapter.query('hero_honors',player=vars(player),hero_id=106),STATIC.HeroList)
        cards=CARDS.hero_report('甲',adapter.query('heroes',player=vars(player)),STATIC.player_client_config,STATIC.HeroList)
        drawn=[]
        original=ImageDraw.ImageDraw.text
        def track(draw,xy,text,*args,**kwargs):
            drawn.append(str(text));return original(draw,xy,text,*args,**kwargs)
        with patch.object(RENDER,'player_client_reference_image',
                          side_effect=lambda kind: Image.new('RGB',(2048,952),(36,63,102))), \
             patch.object(ImageDraw.ImageDraw,'text',track):
            hero_image=RENDER.render_screen(honors,ZFILE.player_client_report_font,
                win_rate_bands=STATIC.player_client_config['win_rate_bands'])
            cards_image=RENDER.render_hero_report(cards,ZFILE.player_client_report_font,
                win_rate_bands=STATIC.player_client_config['win_rate_bands'])
        for label in [*honors['year_labels'],'第3名','均衡发展的峡谷财神','中路19段','游走7段']:
            self.assertIn(label,drawn)
        self.assertFalse(any(word in text for text in drawn for word in ('缺失','暂缺','待补齐','说明')))
        # The cyan fill is actual source ratios, not an empty polygon or a constant default.
        cx,cy=1017,607
        self.assertNotEqual(hero_image.getpixel((cx,cy)),(36,63,102))
        self.assertEqual(cards_image.size,(2048,952))

    def test_report_faces_are_original_application_fonts(self):
        regular=ZFILE.player_client_report_font(28,400)
        bold=ZFILE.player_client_report_font(28,650)
        self.assertEqual(regular.getname()[0],'FZLanTingHeiS-R-GB')
        self.assertEqual(bold.getname()[0],'FZZhengHeiS-DB-GB')
        for face in (regular,bold):
            self.assertGreater(face.getlength('小乔 73.7% 中路19段'),0)

"""Battle-power and co-player analysis workflows."""

import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import zdynamic as dmc
from .. import zdb, zfile, ztime
from ..zstatic import *
def _runtime():
    from .. import zfunc

    return zfunc


def coplayer_process(gameSvrId, relaySvrId, gameseq, pvptype,roleid,spoiler_info,from_web=False,return_power_data=False,official_priority="normal",save_power_history=False,with_ai_analysis=False):
    from ..tools.gen_coplayer_analyses import CoPlayerProcess

    runtime = _runtime()
    wzry_get_official = runtime.wzry_get_official
    fetch_battle = runtime.fetch_battle
    battle_lineup_ai_process = runtime.battle_lineup_ai_process
    hero_matchup_process = runtime.hero_matchup_process
    check_btl_official = runtime.check_btl_official
    log_message = runtime.log_message

    def sigmoid(x):
        return 1/(1+math.exp(-x))

    def fetch_player_data(player):
        roleid = player["basicInfo"]["roleId"]
        userid = player["basicInfo"]["userId"]
        is_auth = player["basicInfo"]["isGameAuth"]
        result = {
            'player': player,
            'profile_res': None,
            'heropower_res': None,
            'recentbtl_res': None,
            'errors': []
        }
        if not is_auth:
            return result
        try:
            result['profile_res'] = wzry_get_official(reqtype="profile", roleid=roleid, userid=userid, priority=official_priority)
        except Exception as e:
            result['errors'].append(str(e))
        try:
            result['heropower_res'] = wzry_get_official(reqtype="heropower", roleid=roleid, userid=userid, priority=official_priority)
        except Exception as e:
            result['errors'].append(str(e))
        try:
            result['recentbtl_res'] = wzry_get_official(reqtype="btlist_url", roleid=roleid, userid=userid, priority=official_priority)
        except Exception as e:
            result['errors'].append(str(e))
        return result
    def get_hero_tier(detail_list):
        total_tier = 0
        found_cnt = 0
        for player in detail_list:
            heroName = player["battleRecords"]["usedHero"]["heroName"]
            tier_dict = getattr(dmc, 'herotier', {})
            if heroName in tier_dict:
                tier = tier_dict[heroName]
                total_tier += tier
                found_cnt += 1
        if (found_cnt):
            total_tier = total_tier * (5 / found_cnt)
        avg_tier = total_tier / 5
        return avg_tier

    def get_player_power(detail_list, is_my_side, player_data_cache):
        auth_cnt=0      # 授权人数统计
        ret_level=0     # 返回值
        req_error=[]
        player_power_data=[]
        for player in detail_list:
            # 对于该队伍中的一个玩家
            winNum=10        # 当前英雄输局数
            loseNum=10       # 当前英雄胜局数
            avgScore=8      # 当前英雄平均评分
            winRate=0.5     # 当前英雄胜率
            starNum=50      # 总星数
            peakScore=1200  # 巅峰分数
            PowerNum=70000  # 总战斗力
            TotalCnt=1000   # 总场次
            MVPCnt=100      # 总MVP场次
            MVPRate=0.1
            heroPower=1000
            rankName="未知段位"
            rankStar=0
            RecentWinRate=0.55
            RecentAvgScore=8
            BetterHeroPowerList=[]
            BetterHeroPower=1
            heroTag=""
            MaxHeroPower=-1
            MaxHeroTag=""

            is_auth=player["basicInfo"]["isGameAuth"] # 营地授权与否
            roleid=player["basicInfo"]["roleId"]
            userid=player["basicInfo"]["userId"]
            nickname=player["basicInfo"]["roleName"]
            heroBehavior=player["heroBehavior"]
            heroName=player["battleRecords"]["usedHero"]["heroName"]
            heroAvatar=player["battleRecords"]["usedHero"]["heroIcon"]
            player_avatar_url=""
            if (is_auth):
                auth_cnt+=1
                winNum=heroBehavior["winNum"]
                loseNum=heroBehavior["loseNum"]
                avgScore=float(heroBehavior["avgScore"])
                winRate=float(heroBehavior["winRate"].strip('%')) / 100
                heroPower=player["battleStats"]["fightPower"]

                # 从缓存中获取预先并行获取的数据
                player_key = (roleid, userid)
                cached_data = player_data_cache.get(player_key, {})
                profile_res = cached_data.get('profile_res')
                heropower_res = cached_data.get('heropower_res')
                recentbtl_res = cached_data.get('recentbtl_res')
                req_error.extend(cached_data.get('errors', []))

                if not profile_res:
                    continue

                RoleInfo = (roles[0] if (roles := [role for role in profile_res["roleList"] if role["roleId"] == roleid]) else None)
                rankInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 701]) else None)
                peakInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 702]) else None)
                Powerinfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 304]) else None)
                TotalNumInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 401]) else None)
                MVPInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 408]) else None)
                if (RoleInfo):
                    player_avatar_url=RoleInfo.get("roleIcon","")
                if (rankInfo):
                    rankName=rankInfo["name"]
                    rankStar=int(json.loads(rankInfo["param1"])["rankingStar"])
                    starNum=(ranklist[rankName] if rankName in ranklist else fin) + rankStar
                if (peakInfo): peakScore=int(peakInfo["content"]) or 1200
                if (Powerinfo): PowerNum=int(Powerinfo["content"])
                if (TotalNumInfo): TotalCnt=int(TotalNumInfo["content"])
                if (MVPInfo): MVPCnt=int(MVPInfo["content"])
                if (TotalNumInfo and MVPInfo): MVPRate=MVPCnt/TotalCnt
                else: MVPRate=0.25
                if (heropower_res):
                    for hero in heropower_res['heroList']:
                        try:
                            if (hero['basicInfo']['title']==heroName):
                                region_name=hero['honorTitle']['desc']['full'].split("第")[0]
                                metal_name=hero['honorTitle']['desc']['abbr'].split("第")[0]
                                heroTag=f"{region_name}\n No.{hero['honorTitle']['rank']} \n"
                        except Exception as e:
                            pass
                        if (hero['basicInfo']['heroFightPower']>=heroPower):
                            BetterHeroPowerList.append(hero['basicInfo']['heroFightPower'])
                        if (hero['basicInfo']['heroFightPower']>MaxHeroPower):
                            if ('honorTitle' in hero and hero['honorTitle']):
                                MaxHeroPower=hero['basicInfo']['heroFightPower']
                                region_name=hero['honorTitle']['desc']['full'].split("第")[0]
                                metal_name=hero['honorTitle']['desc']['abbr'].split("第")[0]
                                MaxHeroTag=f"Top {MaxHeroPower}\n{region_name}第{hero['honorTitle']['rank']}{hero['basicInfo']['title']}"
                if (recentbtl_res and recentbtl_res["list"]):
                    official_btls=[]
                    for btl in recentbtl_res["list"]:
                        if (check_btl_official(btl["mapName"])):
                            official_btls.append({"result":btl["gameresult"]==1,"grade":float(btl["gradeGame"])})
                    if (official_btls):
                        if (len(official_btls)>=10):
                            RecentWinRate=sum(1 for btl in official_btls if (btl["result"]))/len(official_btls)
                        RecentAvgScore=sum(btl["grade"] for btl in official_btls)/len(official_btls)
            BetterHeroPower=heroPower
            if (BetterHeroPowerList):
                BetterHeroPowerList=BetterHeroPowerList[:3]
                BetterHeroPower=sum(BetterHeroPowerList)/len(BetterHeroPowerList)
            HeroShowCnt=loseNum+winNum                      # 该玩家此英雄的出场局数
            equiv_star=(starNum-25)+(peakScore-1200)/15.0   # 巅峰分与星数折算成一个综合星级
            if (equiv_star<=0): equiv_star=1                # 星级下界
            single_level = (
                1
                * pow(equiv_star, 0.3)                                          # equiv_star        星级和巅峰分计算得的等价星级                                0.3
                * pow(sigmoid(MVPRate), 4)                                      # MVPRate           MVP率                                                       4
                * pow((PowerNum / 10000), 0.85)                                 # PowerNum          战斗力                                                      0.85
                * pow((8.0 + RecentAvgScore) / 2, 1)                       # avgScore          该英雄历史场次平均评分 + 近期场次平均评分                       1
                * pow(sigmoid(HeroShowCnt / 10), 1.3)                           # HeroShowCnt       该英雄历史场次数                                            1.3
                * pow(sigmoid((heroPower + BetterHeroPower) / 2 / 10000), 2)    # heroPower         该英雄当前战力 + 更高战力英雄的战力平均值(最多取更高的3个)          2
                * pow(max(RecentWinRate / 0.5, 1), 2)
            )
            # 指标1.5倍的等价条件
            # 王者0星 巅峰1200分 -> 王者50星 巅峰1600分
            # MVP率 30% -> 56%
            # 战斗力 50000 -> 80000
            # 本局使用英雄与近期场次的平均评分 8分 -> 12分
            # 本局使用英雄的总场次 10场 -> 300场
            # 本局使用英雄与高战力英雄的战力 1000 -> 6000 -> 13000

            # 高战力英雄的取法： 比该局所选英雄战力高的英雄中 取前3名

            # 生成图表中
            # 卡片右上角红色角标：营地未授权
            # 玩家卡片背景色：红色，低于所有玩家历史平均水平；绿色，高于所有玩家历史平均水平；颜色越深，差值越大
            # 底蕴值：以该局最高玩家为100%计算
            if (is_auth): ret_level+=single_level
            player_power_data.append({
                "side": "my" if is_my_side else "op",
                "roleId": roleid,
                "userId": userid,
                "nickname": nickname,
                "isAuth": is_auth,
                "heroName": heroName,
                "position": player.get("battleRecords", {}).get("position"),
                "playerAvatarUrl": player_avatar_url,
                "heroAvatarUrl": heroAvatar,
                "heroPower": heroPower,
                "heroTag": heroTag,
                "maxHeroTag": MaxHeroTag,
                "winNum": winNum,
                "loseNum": loseNum,
                "heroShowCnt": HeroShowCnt,
                "heroAvgScore": avgScore,
                "heroWinRate": winRate,
                "rankName": rankName,
                "rankStar": rankStar,
                "starNum": starNum,
                "peakScore": peakScore,
                "equivStar": equiv_star,
                "powerNum": PowerNum,
                "totalCnt": TotalCnt,
                "mvpCnt": MVPCnt,
                "mvpRate": MVPRate,
                "recentWinRate": RecentWinRate,
                "recentAvgScore": RecentAvgScore,
                "betterHeroPower": BetterHeroPower,
                "maxHeroPower": MaxHeroPower,
                "singleLevel": single_level if is_auth else 0,
                "requestErrors": cached_data.get('errors', []) if is_auth else [],
            })
            gen_inst.add_player(
                nickname=nickname,
                is_auth=is_auth,
                is_my_side=is_my_side,
                winNum=winNum,
                loseNum=loseNum,
                avgScore=avgScore,
                winRate=winRate,
                avatarUrl=player_avatar_url,
                starNum=starNum,
                peakScore=peakScore,
                PowerNum=PowerNum,
                TotalCnt=TotalCnt,
                MVPCnt=TotalCnt*MVPRate,
                rankName=rankName,
                rankStar=rankStar,
                single_level=single_level,
                HeroAvatar=heroAvatar,
                HeroPower=heroPower,
                HeroTag=heroTag,
                MaxHeroTag=MaxHeroTag,
            )
        ret_level=ret_level*(5/auth_cnt) if (auth_cnt) else 0
        return ret_level,auth_cnt,req_error,player_power_data

    gen_inst=CoPlayerProcess()
    is_spoiler=1 if spoiler_info else 0
    if (is_spoiler):
        res=spoiler_info
    else:
        res = fetch_battle(gameseq,roleid)
        if not res:
            res=wzry_get_official(reqtype="btldetail",gameseq=gameseq,gameSvrId=gameSvrId,relaySvrId=relaySvrId,roleid=roleid,pvptype=pvptype,priority=official_priority)
    if ('head' not in res): return None
    gameres=res['head']['gameResult']
    my_side_detail=res['redRoles'] if (res['redTeam']['acntCamp']==res['head']['acntCamp']) else res['blueRoles']
    op_side_detail=res['redRoles'] if (res['redTeam']['acntCamp']!=res['head']['acntCamp']) else res['blueRoles']
    lineup_ai_future = None
    lineup_ai_executor = None
    if with_ai_analysis and not is_spoiler:
        lineup_ai_executor = ThreadPoolExecutor(max_workers=1)
        lineup_ai_future = lineup_ai_executor.submit(
            battle_lineup_ai_process,
            _battle_lineup_items(my_side_detail),
            _battle_lineup_items(op_side_detail),
        )
    # my_side_detail=my_side_detail[0:1]
    # op_side_detail=op_side_detail[0:1]
    # 并行获取所有玩家的数据
    all_players = my_side_detail + op_side_detail
    player_data_cache = {}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future_to_player = {executor.submit(fetch_player_data, player): player for player in all_players}
        for future in as_completed(future_to_player):
            try:
                result = future.result()
                player = result['player']
                roleid = player["basicInfo"]["roleId"]
                userid = player["basicInfo"]["userId"]
                player_key = (roleid, userid)
                player_data_cache[player_key] = {
                    'profile_res': result['profile_res'],
                    'recentbtl_res': result['recentbtl_res'],
                    'heropower_res': result['heropower_res'],
                    'errors': result['errors']
                }
            except Exception as e:
                pass

    my_side_total_level,my_side_auth_cnt,my_side_req_error,my_side_power_data=get_player_power(my_side_detail,1,player_data_cache)
    op_side_total_level,op_side_auth_cnt,op_side_req_error,op_side_power_data=get_player_power(op_side_detail,0,player_data_cache)

    my_side_total_tier = get_hero_tier(my_side_detail)
    op_side_total_tier = get_hero_tier(op_side_detail)
    matchup = hero_matchup_process(my_side_detail, op_side_detail)
    ai_analysis = ""
    if lineup_ai_future:
        try:
            ai_analysis = lineup_ai_future.result()
        except Exception as error:
            _runtime().log_message(f"BATTLE_LINEUP_AI_FUTURE_ERROR: {repr(error)}")
        finally:
            lineup_ai_executor.shutdown(wait=False)

    delta_level=my_side_total_level-op_side_total_level

    if (op_side_total_level and my_side_total_level):
        record = {
            'created_at': ztime.current_datetime_text(),
            'game_res': gameres,
            'my_side_total_level': my_side_total_level,
            'op_side_total_level': op_side_total_level,
            'gameSvrId': gameSvrId,
            'relaySvrId': relaySvrId,
            'gameseq': gameseq,
            'pvptype': pvptype,
            'roleid': roleid,
        }
        runtime.record_battle_evaluator(record)

    snd_msg=(
        f"实力天平倾斜度：{round(delta_level,2) if op_side_total_level else "unknown"}\n"
        f"我方底蕴：{round(my_side_total_level,2) if my_side_total_level else "unknown"}\n"
        f"我方英雄梯度：{round(my_side_total_tier,2)}\n"
        f"对方底蕴：{round(op_side_total_level,2) if op_side_total_level else "unknown"}\n"
        f"对方英雄梯度：{round(op_side_total_tier,2)}\n"
        + (
            f"英雄对位胜率：{round(matchup['winRate'] * 100, 1)}%（近30天，{matchup['sampleMatches']}局）\n"
            if matchup.get("winRate") is not None
            else "英雄对位胜率：暂无有效样本\n"
        )
    )
    save_path=zfile.battle_power_image_path()

    pic_title="对局预言" if is_spoiler else "对局底蕴"
    matchup_subtitle = (
        f"英雄对位胜率 {matchup['winRate'] * 100:.1f}% · 近30天 {matchup['sampleMatches']} 局"
        if matchup.get("winRate") is not None
        else "英雄对位胜率 · 暂无有效样本"
    )
    out_path, ok = gen_inst.gen(save_path,title=pic_title,subtitle=matchup_subtitle)

    stats = {
        "my_side_level": my_side_total_level,
        "op_side_level": op_side_total_level,
        "my_side_tier": my_side_total_tier,
        "op_side_tier": op_side_total_tier,
        "matchup": matchup,
    }

    if (return_power_data):
        power_data = {
            "GameSeq": str(gameseq),
            "gameSvrId": gameSvrId,
            "relaySvrId": relaySvrId,
            "pvptype": pvptype,
            "roleid": roleid,
            "mapName": res.get("head", {}).get("mapName") or res.get("battle", {}).get("mapName", ""),
            "gameTime": res.get("head", {}).get("dtEventTime") or res.get("battle", {}).get("dtEventTime", ""),
            "gameResult": gameres,
            "mySide": {
                "level": my_side_total_level,
                "tier": my_side_total_tier,
                "authCnt": my_side_auth_cnt,
                "requestErrors": my_side_req_error,
            },
            "opSide": {
                "level": op_side_total_level,
                "tier": op_side_total_tier,
                "authCnt": op_side_auth_cnt,
                "requestErrors": op_side_req_error,
            },
            "players": my_side_power_data + op_side_power_data,
            "matchup": matchup,
            "aiAnalysis": ai_analysis,
        }
        if (save_power_history and not is_spoiler):
            power_data["evaluatedAt"] = ztime.current_datetime_text()
            BattlePowerHistory.save(power_data)
        return snd_msg,save_path,stats,power_data

    return snd_msg,save_path,stats

class BattlePowerHistory:
    @staticmethod
    def path(gameseq):
        return zfile.battle_power_history_path(gameseq)

    @staticmethod
    def failed_path(gameseq):
        return zfile.battle_power_failed_path(gameseq)

    @staticmethod
    def side(power_data, side_key):
        return power_data.get(side_key, {}) if isinstance(power_data, dict) else {}

    @staticmethod
    def display_value(value):
        return round(value, 2) if value else "unknown"

    @staticmethod
    def message(power_data):
        my_side = BattlePowerHistory.side(power_data, "mySide")
        op_side = BattlePowerHistory.side(power_data, "opSide")
        my_side_level = my_side.get("level") or 0
        op_side_level = op_side.get("level") or 0
        my_side_tier = my_side.get("tier") or 0
        op_side_tier = op_side.get("tier") or 0
        delta_level = my_side_level - op_side_level
        matchup = power_data.get("matchup") or {}
        return (
            f"实力天平倾斜度：{BattlePowerHistory.display_value(delta_level) if op_side_level else "unknown"}\n"
            f"我方底蕴：{BattlePowerHistory.display_value(my_side_level)}\n"
            f"我方英雄梯度：{round(my_side_tier,2)}\n"
            f"对方底蕴：{BattlePowerHistory.display_value(op_side_level)}\n"
            f"对方英雄梯度：{round(op_side_tier,2)}\n"
            + (
                f"英雄对位胜率：{round(matchup['winRate'] * 100, 1)}%（近30天，{matchup.get('sampleMatches', 0)}局）\n"
                if matchup.get("winRate") is not None
                else "英雄对位胜率：暂无有效样本\n"
            )
        )

    @staticmethod
    def stats(power_data):
        my_side = BattlePowerHistory.side(power_data, "mySide")
        op_side = BattlePowerHistory.side(power_data, "opSide")
        return {
            "my_side_level": my_side.get("level") or 0,
            "op_side_level": op_side.get("level") or 0,
            "my_side_tier": my_side.get("tier") or 0,
            "op_side_tier": op_side.get("tier") or 0,
            "matchup": power_data.get("matchup") or {},
        }

    @staticmethod
    def add_player_to_image(gen_inst, player):
        hero_show_cnt = int(player.get("heroShowCnt") or 0)
        win_rate = float(player.get("heroWinRate") or 0)
        win_num = player.get("winNum")
        lose_num = player.get("loseNum")
        if win_num is None or lose_num is None:
            win_num = int(round(hero_show_cnt * win_rate))
            lose_num = max(hero_show_cnt - win_num, 0)
        gen_inst.add_player(
            nickname=player.get("nickname", "未知玩家"),
            is_auth=bool(player.get("isAuth")),
            is_my_side=player.get("side") == "my",
            winNum=int(win_num or 0),
            loseNum=int(lose_num or 0),
            avgScore=float(player.get("heroAvgScore") or 0),
            winRate=win_rate,
            avatarUrl=player.get("playerAvatarUrl", ""),
            starNum=player.get("starNum"),
            peakScore=player.get("peakScore"),
            PowerNum=player.get("powerNum"),
            TotalCnt=player.get("totalCnt"),
            MVPCnt=player.get("mvpCnt"),
            rankName=player.get("rankName"),
            rankStar=player.get("rankStar"),
            single_level=player.get("singleLevel"),
            HeroAvatar=player.get("heroAvatarUrl", ""),
            HeroPower=player.get("heroPower"),
            HeroTag=player.get("heroTag", ""),
            MaxHeroTag=player.get("maxHeroTag", ""),
        )

    @staticmethod
    def image(power_data):
        from ..tools.gen_coplayer_analyses import CoPlayerProcess

        gen_inst = CoPlayerProcess()
        for player in power_data.get("players", []):
            BattlePowerHistory.add_player_to_image(gen_inst, player)
        save_path=zfile.battle_power_image_path()
        matchup = power_data.get("matchup") or {}
        subtitle = (
            f"英雄对位胜率 {matchup['winRate'] * 100:.1f}% · 近30天 {matchup.get('sampleMatches', 0)} 局"
            if matchup.get("winRate") is not None
            else "英雄对位胜率 · 暂无有效样本"
        )
        gen_inst.gen(save_path,title="对局底蕴",subtitle=subtitle)
        return save_path

    @staticmethod
    def rounded(data):
        if isinstance(data, float):
            return round(data, 3)
        if isinstance(data, list):
            return [BattlePowerHistory.rounded(item) for item in data]
        if isinstance(data, dict):
            return {key: BattlePowerHistory.rounded(value) for key, value in data.items()}
        return data

    @staticmethod
    def load(gameseq):
        if not gameseq:
            return None
        try:
            database_payload = zdb.read_battle_power(gameseq)
            if isinstance(database_payload, dict):
                return database_payload
        except Exception as exc:
            _runtime().log_message(f"POSTGRES_POWER_READ_FALLBACK: GameSeq={gameseq} error={repr(exc)}", logging.WARNING)
        if not zfile.file_exist(BattlePowerHistory.path(gameseq)):
            return None
        saved_power_data = zfile.readerl(BattlePowerHistory.path(gameseq))
        if isinstance(saved_power_data, dict):
            return saved_power_data
        raise Exception(f"load_battle_power_history_error: invalid saved data GameSeq={gameseq}")

    @staticmethod
    def exists(gameseq):
        if not gameseq:
            return False
        try:
            if zdb.battle_power_exists(gameseq):
                return True
        except Exception as exc:
            _runtime().log_message(f"POSTGRES_POWER_EXISTS_FALLBACK: GameSeq={gameseq} error={repr(exc)}", logging.WARNING)
        return zfile.file_exist(BattlePowerHistory.path(gameseq))

    @staticmethod
    def save(power_data):
        gameseq = power_data.get("GameSeq")
        if not gameseq:
            raise Exception("save_battle_power_history_error: missing GameSeq")
        map_name = power_data.get("mapName", "")
        if not _runtime().check_btl_official(map_name):
            _runtime().log_message(f"SKIP_SAVE_BATTLE_POWER_NON_OFFICIAL: GameSeq={gameseq} mapName={map_name}")
            return None
        power_data = BattlePowerHistory.rounded(power_data)
        zfile.writerl(BattlePowerHistory.path(gameseq), power_data)
        if not BattlePowerHistory.exists(gameseq):
            raise Exception(f"save_battle_power_history_error: write failed GameSeq={gameseq}")
        return BattlePowerHistory.path(gameseq)

    @staticmethod
    def failed_exists(gameseq):
        return bool(gameseq and zfile.file_exist(BattlePowerHistory.failed_path(gameseq)))

    @staticmethod
    def mark_failed(gameseq, reason, candidate=None):
        if not gameseq:
            raise Exception("mark_battle_power_failed_error: missing GameSeq")
        zfile.ensure_dir(zfile.battle_power_failed_dir())
        failed_data = {
            "GameSeq": str(gameseq),
            "failedAt": ztime.current_datetime_text(),
            "reason": str(reason),
            "candidate": candidate or {},
        }
        zfile.writerl(BattlePowerHistory.failed_path(gameseq), failed_data)
        return BattlePowerHistory.failed_path(gameseq)

    @staticmethod
    def normalize_params(game_params):
        params = dict(game_params)
        if "gameseq" not in params and "GameSeq" in params:
            params["gameseq"] = params["GameSeq"]
        return params

    @staticmethod
    def saved_response(power_data, gen_image, with_ai_analysis=False):
        if with_ai_analysis and not power_data.get("aiAnalysis"):
            my_lineup = [player for player in power_data.get("players", []) if player.get("side") == "my"]
            op_lineup = [player for player in power_data.get("players", []) if player.get("side") == "op"]
            power_data["aiAnalysis"] = _runtime().battle_lineup_ai_process(my_lineup, op_lineup)
        stats = BattlePowerHistory.stats(power_data)
        pic_path = BattlePowerHistory.image(power_data) if gen_image else ""
        return BattlePowerHistory.message(power_data),pic_path,stats,power_data

    @staticmethod
    def parse_game_time(detail, gameseq):
        game_time = detail.get("GameTime_Timestamp")
        if not game_time:
            return None
        try:
            return ztime.stamp_to_time(int(game_time))
        except Exception as e:
            _runtime().log_message(f"HISTORY_POWER_TIME_PARSE_ERROR: {gameseq} {str(e)}")
            return None

    @staticmethod
    def should_skip_candidate(gameseq, excluded_gameseqs):
        if not gameseq or gameseq in excluded_gameseqs:
            return True
        if BattlePowerHistory.exists(gameseq):
            return True
        if BattlePowerHistory.failed_exists(gameseq):
            return True
        return False

    @staticmethod
    def begin_in_progress(gameseq):
        gameseq = str(gameseq)
        with dmc.BattlePowerInProgressLock:
            progress = dmc.BattlePowerInProgress.get(gameseq)
            if progress:
                return progress, False
            progress = {
                "event": threading.Event(),
                "error": "",
            }
            dmc.BattlePowerInProgress[gameseq] = progress
            return progress, True

    @staticmethod
    def finish_in_progress(gameseq, progress, error=None):
        gameseq = str(gameseq)
        if error:
            progress["error"] = str(error)
        with dmc.BattlePowerInProgressLock:
            current_progress = dmc.BattlePowerInProgress.get(gameseq)
            if current_progress is progress:
                dmc.BattlePowerInProgress.pop(gameseq, None)
        progress["event"].set()

    @staticmethod
    def wait_in_progress(gameseq, progress, gen_image, with_ai_analysis=False):
        gameseq = str(gameseq)
        _runtime().log_message(f"BATTLE_POWER_WAIT_IN_PROGRESS: GameSeq={gameseq}")
        progress["event"].wait()
        saved_power_data = BattlePowerHistory.load(gameseq)
        if saved_power_data:
            return BattlePowerHistory.saved_response(saved_power_data, gen_image, with_ai_analysis)
        if progress.get("error"):
            raise Exception(f"battle_power_process_wait_failed: GameSeq={gameseq} {progress['error']}")
        if BattlePowerHistory.failed_exists(gameseq):
            raise Exception(f"battle_power_process_wait_skipped_failed: GameSeq={gameseq}")
        raise Exception(f"battle_power_process_wait_missing_result: GameSeq={gameseq}")
def mark_battle_power_failed(gameseq, reason, candidate=None):
    return BattlePowerHistory.mark_failed(gameseq, reason, candidate)

def battle_power_process(gameSvrId, relaySvrId, gameseq, pvptype, roleid, spoiler_info=None, from_web=False, official_priority="normal", save_power_history=True, gen_image=True, with_ai_analysis=False):

    spoiler_info = spoiler_info or {}
    progress = None
    is_owner = False
    if (not spoiler_info):
        saved_power_data = BattlePowerHistory.load(gameseq)
        if saved_power_data:
            return BattlePowerHistory.saved_response(saved_power_data, gen_image, with_ai_analysis)
        if BattlePowerHistory.failed_exists(gameseq):
            raise Exception(f"battle_power_process_skipped_failed: GameSeq={gameseq}")
        if save_power_history:
            progress, is_owner = BattlePowerHistory.begin_in_progress(gameseq)
            if not is_owner:
                return BattlePowerHistory.wait_in_progress(gameseq, progress, gen_image, with_ai_analysis)
    try:
        ret = _runtime().coplayer_process(
            gameSvrId,
            relaySvrId,
            gameseq,
            pvptype,
            roleid,
            spoiler_info=spoiler_info,
            from_web=from_web,
            return_power_data=True,
            official_priority=official_priority,
            save_power_history=save_power_history,
            with_ai_analysis=with_ai_analysis,
        )
        snd_msg,pic_path,stats,power_data = ret
        if (save_power_history and not spoiler_info and not power_data.get("evaluatedAt")):
            power_data["evaluatedAt"] = ztime.current_datetime_text()
            BattlePowerHistory.save(power_data)
        return snd_msg,pic_path,stats,power_data
    except Exception as e:
        if progress and is_owner:
            progress["error"] = repr(e)
        raise
    finally:
        if progress and is_owner:
            BattlePowerHistory.finish_in_progress(gameseq, progress)

def evaluate_battle_power_history(game_params, roleid, official_priority="low"):

    params = BattlePowerHistory.normalize_params(game_params)
    gameseq = params.get("gameseq")
    saved_power_data = BattlePowerHistory.load(gameseq)
    if saved_power_data:
        return saved_power_data
    if BattlePowerHistory.failed_exists(gameseq):
        raise Exception(f"evaluate_battle_power_history_skipped_failed: GameSeq={gameseq}")
    _, _, _, power_data = _runtime().battle_power_process(
        params.get("gameSvrId"),
        params.get("relaySvrId"),
        params.get("gameseq"),
        params.get("pvptype"),
        roleid,
        spoiler_info={},
        official_priority=official_priority,
        save_power_history=True,
    )
    if not power_data.get("evaluatedAt"):
        power_data["evaluatedAt"] = ztime.current_datetime_text()
        BattlePowerHistory.save(power_data)
    return power_data

def find_pending_battle_power_candidate(days=7, excluded_gameseqs=None, start_date_str=None):

    end_date = ztime.time_r()
    if start_date_str:
        start_date = ztime.str_to_time(start_date_str)
    else:
        start_date = ztime.time_delta(end_date, -days)
    history_data, _ = _runtime().fetch_history(start_date=start_date, end_date=end_date, filter_official=True)
    candidates = []
    seen = set()
    excluded_gameseqs = {str(item) for item in (excluded_gameseqs or set())}
    for realname, details in history_data.items():
        roleid = roleidlist.get(realname)
        if not roleid:
            continue
        for detail in details:
            gameseq = str(detail.get("GameSeq") or "")
            if not gameseq or gameseq in seen:
                continue
            seen.add(gameseq)
            if BattlePowerHistory.should_skip_candidate(gameseq, excluded_gameseqs):
                continue
            game_time = detail.get("GameTime_Timestamp")
            game_time_obj = BattlePowerHistory.parse_game_time(detail, gameseq)
            if not game_time_obj:
                continue
            if game_time_obj < start_date or game_time_obj > end_date:
                continue
            params = detail.get("Params") or {}
            if not params:
                continue
            candidates.append({
                "realname": realname,
                "roleid": roleid,
                "GameSeq": gameseq,
                "GameTime": game_time,
                "Params": params,
            })
    candidates.sort(key=lambda item: item.get("GameTime") or 0, reverse=True)
    return candidates[0] if candidates else None

def recent_power_process(realname, days=7):

    roleid = roleidlist.get(realname)
    if not roleid:
        return "未找到该玩家的 roleid"
    end_date = ztime.time_r()
    start_date = ztime.time_delta(end_date, -days)
    history_data, _ = _runtime().fetch_history(userid=userlist.get(realname), start_date=start_date, end_date=end_date, filter_official=True)
    details = history_data.get(realname, [])
    valid_details = [detail for detail in details if _runtime().check_btl_official(detail.get("MapName", ""))]
    rows = []
    missing = 0
    for detail in valid_details:
        gameseq = detail.get("GameSeq")
        if not gameseq or not BattlePowerHistory.exists(gameseq):
            missing += 1
            continue
        power_data = BattlePowerHistory.load(gameseq)
        if not isinstance(power_data, dict):
            missing += 1
            continue
        player_record = None
        for player in power_data.get("players", []):
            if str(player.get("roleId")) == str(roleid):
                player_record = player
                break
        if not player_record:
            missing += 1
            continue
        own_key = "mySide" if player_record.get("side") == "my" else "opSide"
        rival_key = "opSide" if own_key == "mySide" else "mySide"
        own_side = power_data.get(own_key, {})
        rival_side = power_data.get(rival_key, {})
        own_level = float(own_side.get("level") or 0)
        rival_level = float(rival_side.get("level") or 0)
        single_level = float(player_record.get("singleLevel") or 0)
        battle_player_levels = [
            float(player.get("singleLevel") or 0)
            for player in power_data.get("players", [])
            if float(player.get("singleLevel") or 0) > 0
        ]
        battle_player_avg_level = sum(battle_player_levels) / len(battle_player_levels) if battle_player_levels else 0
        rows.append({
            "GameSeq": gameseq,
            "HeroName": detail.get("HeroName"),
            "Result": detail.get("Result"),
            "GameGrade": detail.get("GameGrade"),
            "MapName": detail.get("MapName"),
            "ownLevel": own_level,
            "rivalLevel": rival_level,
            "battlePlayerAvgLevel": battle_player_avg_level,
            "singleLevelPercent": single_level / battle_player_avg_level * 100 if battle_player_avg_level else 0,
            "levelDiff": own_level - rival_level,
            "ownTier": float(own_side.get("tier") or 0),
            "rivalTier": float(rival_side.get("tier") or 0),
            "ownAuthCnt": int(own_side.get("authCnt") or 0),
            "rivalAuthCnt": int(rival_side.get("authCnt") or 0),
            "singleLevel": single_level,
        })
    if not rows:
        return f"最近{days}天没有可用的底蕴历史数据（官方对局{len(valid_details)}局，待后台评估{missing}局）"

    count = len(rows)
    avg_own = sum(row["ownLevel"] for row in rows) / count
    avg_rival = sum(row["rivalLevel"] for row in rows) / count
    avg_diff = sum(row["levelDiff"] for row in rows) / count
    avg_own_tier = sum(row["ownTier"] for row in rows) / count
    avg_rival_tier = sum(row["rivalTier"] for row in rows) / count
    avg_single = sum(row["singleLevel"] for row in rows) / count
    avg_single_percent = sum(row["singleLevelPercent"] for row in rows) / count
    win_count = sum(1 for row in rows if row["Result"] == "胜利")
    display_name = namenick.get(realname, realname)
    lines = [
        f"【{display_name}】最近{days}天对局底蕴统计",
    ]
    if missing:
        lines.append(f"已评估/官方对局：{count}/{len(valid_details)}（待评估{missing}）")
    lines.extend([
        f"胜率：{round(win_count / count * 100, 1)}%（{win_count}胜{count - win_count}负）",
        f"我方底蕴：{round(avg_own, 2)}",
        f"对方底蕴：{round(avg_rival, 2)}",
        f"底蕴差：{round(avg_diff, 2)}",
        f"个人底蕴/队友对手底蕴：{round(avg_single_percent, 1)}%",
        f"个人单人底蕴：{round(avg_single, 2)}",
        f"我方/对方英雄梯度：{round(avg_own_tier, 2)} / {round(avg_rival_tier, 2)}",
    ])
    return "\n".join(lines)

def power_rank_process(days=7):
    from ..tools import gen_power_rank_table

    end_date = ztime.time_r()
    start_date = ztime.time_delta(end_date, -days)
    history_data, _ = _runtime().fetch_history(start_date=start_date, end_date=end_date, filter_official=True)

    rows = []
    columns = ["总局数", "我方底蕴", "对方底蕴", "个人底蕴/队友对手底蕴", "个人单人底蕴", "我方英雄梯度", "对方英雄梯度"]
    metric_keys = ["平均底蕴", "我方底蕴", "对方底蕴", "个人底蕴/队友对手底蕴", "个人单人底蕴", "我方英雄梯度", "对方英雄梯度"]
    for realname, details in history_data.items():
        roleid = roleidlist.get(realname)
        if not roleid:
            continue
        accum = {key: 0.0 for key in metric_keys}
        count = 0
        for detail in details:
            gameseq = detail.get("GameSeq")
            if not gameseq or not BattlePowerHistory.exists(gameseq):
                continue
            power_data = BattlePowerHistory.load(gameseq)
            if not isinstance(power_data, dict):
                continue
            player_record = None
            for player in power_data.get("players", []):
                if str(player.get("roleId")) == str(roleid):
                    player_record = player
                    break
            if not player_record:
                continue
            own_key = "mySide" if player_record.get("side") == "my" else "opSide"
            rival_key = "opSide" if own_key == "mySide" else "mySide"
            own_side = power_data.get(own_key, {})
            rival_side = power_data.get(rival_key, {})
            own_level = float(own_side.get("level") or 0)
            rival_level = float(rival_side.get("level") or 0)
            own_tier = float(own_side.get("tier") or 0)
            rival_tier = float(rival_side.get("tier") or 0)
            single_level = float(player_record.get("singleLevel") or 0)
            battle_player_levels = [
                float(player.get("singleLevel") or 0)
                for player in power_data.get("players", [])
                if float(player.get("singleLevel") or 0) > 0
            ]
            battle_player_avg_level = sum(battle_player_levels) / len(battle_player_levels) if battle_player_levels else 0
            accum["平均底蕴"] += (own_level + rival_level) / 2
            accum["我方底蕴"] += own_level
            accum["对方底蕴"] += rival_level
            accum["个人底蕴/队友对手底蕴"] += single_level / battle_player_avg_level * 100 if battle_player_avg_level else 0
            accum["个人单人底蕴"] += single_level
            accum["我方英雄梯度"] += own_tier
            accum["对方英雄梯度"] += rival_tier
            count += 1
        if not count:
            continue
        games = {key: accum[key] / count for key in accum}
        games["总局数"] = count
        rows.append({
            "realname": realname,
            "player": namenick.get(realname, realname),
            "total": games["平均底蕴"],
            "games": games,
            "rank_value": games["平均底蕴"],
            "subs": [],
        })

    if not rows:
        return f"最近{days}天没有可用的底蕴排行数据", ""
    rows.sort(key=lambda item: float(item.get("rank_value") or 0), reverse=True)

    ts = str(ztime.current_epoch_microseconds())
    filename_hashed = _runtime().WebArtifacts.make_hash(ts)
    pic_path = zfile.battle_power_rank_image_path(filename_hashed)
    gen_power_rank_table.gen(rows, columns, pic_path, title=f"最近{days}天底蕴排行（排位、巅峰、战队赛）")
    return "", pic_path

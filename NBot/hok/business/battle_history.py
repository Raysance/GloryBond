"""Battle-detail loading and structured history analyses."""

import math

from .. import zfile, ztime
from ..zstatic import (
    analyze_time_gap,
    benefit_history_gap,
    benefit_prior_max_games,
    benefit_prior_min_games,
)


def _runtime():
    from .. import zfunc

    return zfunc


def fetch_battle(gameseq,roleid=0): # 读取单局战绩具体内容
    res=zfile.read_battle_detail(gameseq)
    if (res and roleid):
        # 找到对应的玩家信息并更新head
        target_role = None
        for role in res.get('redRoles', []) + res.get('blueRoles', []):
            if int(role['basicInfo']['roleId']) == int(roleid):
                target_role = role
                break

        if target_role:
            # 更新head信息以适应当前的查询目标
            res['head'] = {
                'userId': target_role['basicInfo']['userId'],
                'roleId': target_role['basicInfo']['roleId'],
                'roleName': target_role['basicInfo']['roleName'],
                'heroName': target_role['battleRecords']['usedHero']['heroName'],
                'acntCamp': target_role['basicInfo']['acntCamp'],
                'gameResult': (res['redTeam']['gameResult'] == 1 if target_role['basicInfo']['acntCamp'] == res['redTeam']['acntCamp'] else res['blueTeam']['gameResult'] == 1),
                'killCnt': target_role['battleStats']['killCnt'],
                'deadCnt': target_role['battleStats']['deadCnt'],
                'assistCnt': target_role['battleStats']['assistCnt'],
                'gradeGame': target_role['battleStats']['gradeGame'],
                'mapName': res.get('battle', {}).get('mapName', 'Unknown'),
                'dtEventTime': res.get('battle', {}).get('dtEventTime', '')
            }
    return res
class Analyses:
    @staticmethod
    def analyze_history(userid=None,start_date=None,end_date=None): # 返回排位巅峰战队赛
        all_history,duration=_runtime().fetch_history(userid=userid,start_date=start_date,end_date=end_date)
        analyzed_infos={}
        for k,v in all_history.items():
            history_kept=v
            if (len(history_kept)==0): continue
            analyzed_info={}
            win_tourna_cnt=sum(1 for detail in history_kept if detail["Result"]=="胜利")
            total_tourna_cnt=sum(1 for detail in history_kept)
            win_rate_tourna=-1 if total_tourna_cnt==0 else float(win_tourna_cnt)/total_tourna_cnt
            hero_info={}
            for detail in history_kept:
                if (detail["HeroName"] not in hero_info): hero_info[detail["HeroName"]]=[0,1,[],0,0]
                else: hero_info[detail["HeroName"]][1]+=1
                if (detail["Result"]=="胜利"): hero_info[detail["HeroName"]][0]+=1
                hero_info[detail["HeroName"]][2].append(float(detail["GameGrade"]))
            for hero in hero_info:
                hero_info[hero][3]=float(hero_info[hero][0])/hero_info[hero][1] # 英雄胜率
                hero_info[hero][4]=float(sum(hero_info[hero][2]))/len(hero_info[hero][2]) # 英雄平均评分
            analyzed_info={"win_tourna_cnt":win_tourna_cnt,"total_tourna_cnt":total_tourna_cnt,"win_rate_tourna":win_rate_tourna,"hero_info":{k:v for k,v in hero_info.items()},"duration":duration}
            analyzed_infos[k]=analyzed_info
        # print(analyzed_infos)
        return analyzed_infos

    @staticmethod
    def summarize_player_benefit_infos(analyzed_infos):
        summary={}
        for k,v in analyzed_infos.items():
            if (len(v["hero_info"])==0): continue
            count=sum(heroinfo[1] for heroname,heroinfo in v["hero_info"].items())
            if (count==0): continue
            wins=sum(heroinfo[0] for heroname,heroinfo in v["hero_info"].items())
            grade_sum=sum(sum(heroinfo[2]) for heroname,heroinfo in v["hero_info"].items())
            summary[k]={"count":count,"wins":wins,"grade_sum":grade_sum,"win_rate":float(wins)/count,"avg_grade":float(grade_sum)/count}
        return summary

    @staticmethod
    def build_benefit_shrinkage_rows(userid=None,time_gap=analyze_time_gap):

        end_date=ztime.time_r()
        start_date=ztime.time_r_delta(time_gap)
        prior_end_date=ztime.time_delta(start_date,-1)
        prior_start_date=ztime.time_r_delta(time_gap+benefit_history_gap)
        analyzed_infos=Analyses.analyze_history(userid=userid,start_date=start_date,end_date=end_date)
        prior_analyzed_infos=Analyses.analyze_history(userid=userid,start_date=prior_start_date,end_date=prior_end_date)
        recent_summary=Analyses.summarize_player_benefit_infos(analyzed_infos)
        prior_summary=Analyses.summarize_player_benefit_infos(prior_analyzed_infos)
        rows=[]
        for k,v in recent_summary.items():
            recent_win_rate=v["win_rate"]
            recent_avg_grade=v["avg_grade"]
            posterior_win_rate=recent_win_rate
            posterior_avg_grade=recent_avg_grade
            prior_info=prior_summary.get(k)
            prior_weight=0
            if (prior_info):
                prior_weight=min(prior_info["count"],max(benefit_prior_min_games,v["count"]),benefit_prior_max_games)
                posterior_win_rate=(v["wins"]+prior_info["win_rate"]*prior_weight)/(v["count"]+prior_weight)
                posterior_avg_grade=(v["grade_sum"]+prior_info["avg_grade"]*prior_weight)/(v["count"]+prior_weight)
            posterior_metric=pow(posterior_avg_grade,2)/(math.exp(posterior_win_rate))
            recent_metric=pow(recent_avg_grade,2)/(math.exp(recent_win_rate))
            rows.append({
                "player": k,
                "nickname": _runtime().namenick.get(k,k),
                "recent_count": v["count"],
                "recent_wins": v["wins"],
                "recent_win_rate": recent_win_rate,
                "recent_avg_grade": recent_avg_grade,
                "recent_metric": recent_metric,
                "prior_count": prior_info["count"] if prior_info else 0,
                "prior_wins": prior_info["wins"] if prior_info else 0,
                "prior_win_rate": prior_info["win_rate"] if prior_info else None,
                "prior_avg_grade": prior_info["avg_grade"] if prior_info else None,
                "prior_weight": prior_weight,
                "posterior_win_rate": posterior_win_rate,
                "posterior_avg_grade": posterior_avg_grade,
                "posterior_metric": posterior_metric,
                "metric_delta": posterior_metric-recent_metric,
            })
        rows=sorted(rows,key=lambda item:item["posterior_metric"])
        meta={
            "time_gap": time_gap,
            "benefit_history_gap": benefit_history_gap,
            "benefit_prior_min_games": benefit_prior_min_games,
            "benefit_prior_max_games": benefit_prior_max_games,
            "recent_start": ztime.time_to_str(start_date,"%Y-%m-%d"),
            "recent_end": ztime.time_to_str(end_date,"%Y-%m-%d"),
            "prior_start": ztime.time_to_str(prior_start_date,"%Y-%m-%d"),
            "prior_end": ztime.time_to_str(prior_end_date,"%Y-%m-%d"),
            "formula": "posterior_avg_grade^2 / exp(posterior_win_rate)",
        }
        return rows,meta

    @staticmethod
    def get_benefit_debug_payload(userid=None,time_gap=analyze_time_gap):

        rows,meta=Analyses.build_benefit_shrinkage_rows(userid=userid,time_gap=time_gap)
        meta["generated_at"]=ztime.time_to_str(ztime.time_r())
        return {"meta":meta,"rows":rows}

    @staticmethod
    def get_benefit_data(userid=None,time_gap=analyze_time_gap): # 评分^2/exp(胜率)： exp防止胜率0附近斜率过大 # 值越大越受害 值越小越受益
        rows,meta=Analyses.build_benefit_shrinkage_rows(userid=userid,time_gap=time_gap)
        # print(analyzed_infos)

        user_low_grade_winrate_ratio="" # 评分胜率比最低
        user_high_grade_winrate_ratio="" # 评分胜率比最高
        low_grade_winrate_ratio=10000
        high_grade_winrate_ratio=0
        player_benefit={}
        for item in rows: # 为了评判机制受益程度，或许评分与上星比值更为合理（评分：实力，上星：受益），胜率与上星无必然关联
            k=item["player"]
            win_rate=item["posterior_win_rate"]
            aver_grade=item["posterior_avg_grade"]
            grade_winrate_ratio=item["posterior_metric"]
            # grade_winrate_ratio=math.exp((math.log(aver_grade)-math.log(2))/(math.log(14)-math.log(2)))/(math.exp(win_rate))
            # grade_winrate_ratio=math.exp((aver_grade-2)/(14-2))/(math.exp(win_rate))
            player_benefit[k]=[grade_winrate_ratio,win_rate,aver_grade]
            # print("benefit",k,win_rate,aver_grade,grade_winrate_ratio)
            if (grade_winrate_ratio<low_grade_winrate_ratio):
                user_low_grade_winrate_ratio=k
                low_grade_winrate_ratio=grade_winrate_ratio
            if (grade_winrate_ratio>high_grade_winrate_ratio):
                user_high_grade_winrate_ratio=k
                high_grade_winrate_ratio=grade_winrate_ratio
        player_benefit = dict(sorted(player_benefit.items(), key=lambda item: item[1][0]))
        # print([user_low_grade_winrate_ratio,user_high_grade_winrate_ratio,round(low_grade_winrate_ratio,3),round(high_grade_winrate_ratio,3)],player_benefit)
        return [user_low_grade_winrate_ratio,user_high_grade_winrate_ratio,round(low_grade_winrate_ratio,3),round(high_grade_winrate_ratio,3),player_benefit]

    @staticmethod
    def get_hero_benefit_data(time_gap=analyze_time_gap):
        """按英雄聚合分析（与 get_benefit_data 对玩家的分析类似）
        - time_gap: 向前统计天数
        返回格式：[hero_min_metric, hero_max_metric, round(min_val,3), round(max_val,3), hero_stats]
        hero_stats 为 dict: {hero: [metric, win_rate, avg_grade, total_count]}
        metric 计算方式与玩家端一致： avg_grade^2 / exp(win_rate)
        值越大表示该英雄在统计期内总体上“受害”（评分高但胜率偏低），值越小表示更“受益”。
        """

        end_date = ztime.time_r()
        start_date = ztime.time_r_delta(time_gap)
        analyzed_infos = Analyses.analyze_history(userid=None, start_date=start_date, end_date=end_date)

        hero_acc = {}  # hero -> {'count':, 'wins':, 'grades':[]}
        for player, info in analyzed_infos.items():
            for hero, hinfo in info.get('hero_info', {}).items():
                cnt = hinfo[1]
                wins = hinfo[0]
                grades = hinfo[2]
                entry = hero_acc.setdefault(hero, {'count': 0, 'wins': 0, 'grades': []})
                entry['count'] += cnt
                entry['wins'] += wins
                entry['grades'].extend(grades)

        # 只统计出场超过 3 场的英雄
        hero_acc = {h: acc for h, acc in hero_acc.items() if acc['count'] > 3}
        if not hero_acc:
            return ["", "", 0, 0, {}]

        hero_stats = {}
        min_metric = float('inf')
        max_metric = float('-inf')
        hero_min = ""
        hero_max = ""

        for hero, acc in hero_acc.items():
            total = acc['count']
            win_rate = (acc['wins'] / total) if total else 0
            all_grades = acc['grades']
            avg_grade = (sum(all_grades) / len(all_grades)) if all_grades else 0
            metric = pow(avg_grade, 2) / math.exp(win_rate) if total else 0
            hero_stats[hero] = [metric, win_rate, avg_grade, total]
            if metric < min_metric:
                min_metric = metric
                hero_min = hero
            if metric > max_metric:
                max_metric = metric
                hero_max = hero

        # 按 metric 排序（升序）
        hero_stats = dict(sorted(hero_stats.items(), key=lambda item: item[1][0]))
        return [hero_min, hero_max, round(min_metric, 3), round(max_metric, 3), hero_stats]

    @staticmethod
    def get_expert_hero(userid=None,time_gap=analyze_time_gap):

        end_date=ztime.time_r()
        start_date=ztime.time_r_delta(time_gap)
        analyzed_infos=Analyses.analyze_history(userid=userid,start_date=start_date,end_date=end_date)
        exported={}
        for k,v in analyzed_infos.items(): # 英雄胜率*英雄评分*f(英雄场次)
            if (len(v["hero_info"])==0): continue
            max_factor_hero=""
            max_factor=0
            for heroname,heroinfo in v["hero_info"].items():
                factor=math.pow(heroinfo[3],0.5)*(heroinfo[4])*((math.tanh((heroinfo[1]-5)/3)+1)/2)
                if (factor>max_factor):
                    max_factor=factor
                    max_factor_hero=heroname
            exported[k]=[{max_factor_hero:round(max_factor,3)}]
        # print(exported)
        return exported

    @staticmethod
    def get_extreme_data(time_gap=analyze_time_gap):

        end_date=ztime.time_r()
        start_date=ztime.time_r_delta(time_gap)
        history_info,_=_runtime().fetch_history(userid=None,start_date=start_date,end_date=end_date)

        lowest_grade=16
        highest_grade=0
        lowest_player=""
        highest_player=""
        lowest_hero=""
        highest_hero=""

        for playerid,details in history_info.items():
            for detail in details:
                if (_runtime().check_btl_official_with_matching(detail['MapName'])):
                    detail['GameGrade']=float(detail['GameGrade'])
                    if (detail['GameGrade']<lowest_grade):
                        lowest_grade=detail['GameGrade']
                        lowest_player=playerid
                        lowest_hero=detail['HeroName']
                    if (detail['GameGrade']>highest_grade):
                        highest_grade=detail['GameGrade']
                        highest_player=playerid
                        highest_hero=detail['HeroName']
        # print([lowest_grade,highest_grade,lowest_player,highest_player,lowest_hero,highest_hero])
        return [round(lowest_grade,1),round(highest_grade,1),lowest_player,highest_player,lowest_hero,highest_hero]

    @staticmethod
    def get_intersection_data(time_gap=analyze_time_gap):

        end_date=ztime.time_r()
        start_date=ztime.time_r_delta(time_gap)
        history_info,_=_runtime().fetch_history(userid=None,start_date=start_date,end_date=end_date)

        player_intersection={}
        for playerid_a,details_a in history_info.items():
            for playerid_b,details_b in history_info.items():
                if (playerid_a==playerid_b): continue
                for detail_a in details_a:
                    for detail_b in details_b:
                        if (detail_a['GameSeq']==detail_b['GameSeq']):
                            player_set=frozenset({playerid_a,playerid_b})
                            if (player_set not in player_intersection): player_intersection[player_set]=1/2
                            else: player_intersection[player_set]+=1/2

        player_intersection = dict(sorted(player_intersection.items(), key=lambda item: item[1]))
        # print(player_intersection)
        return player_intersection

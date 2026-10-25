"""Structured single- and multi-player hero statistics."""

import collections

from .. import zdynamic as dmc
from ..zstatic import *


def _zfunc_call(name, *args, **kwargs):
    from .. import zfunc

    return getattr(zfunc, name)(*args, **kwargs)


def fetch_history(*args, **kwargs):
    return _zfunc_call("fetch_history", *args, **kwargs)


def wzry_get_official(*args, **kwargs):
    return _zfunc_call("wzry_get_official", *args, **kwargs)

def single_player_single_hero_process(username,heroid,heroname,this_season=True):
    from ..ztime import time_r, time_delta,str_to_time

    userid=(extra_useridlist | userlist)[username]
    roleid=(extra_roleidlist | roleidlist)[username]
    player_name = namenick.get(username, extra_namenick.get(username, username))

    res = wzry_get_official(reqtype="herostatistics", userid=userid, roleid=roleid, heroid=heroid)

    # 提取核心数据
    hero_info = res.get("heroInfo", {})
    tier_dict = getattr(dmc, "herotier", {})
    herotier = tier_dict.get(heroname, "未知")
    winNum = int(hero_info.get("winNum") or 0)
    failNum = int(hero_info.get("failNum") or 0)
    total_cnt = winNum + failNum
    win_rate = (winNum / total_cnt) if total_cnt else 0

    power_data = res.get("powerData") or []
    heropower = power_data[-1]["value"] if power_data else 0
    month_heropower_incre = (power_data[-1]["value"] - power_data[0]["value"]) if len(power_data) > 1 else 0

    month_mvp = int(hero_info.get("mvpCount") or 0)
    month_medal = int(hero_info.get("goldCount") or 0) + int(hero_info.get("silverCount") or 0) + int(hero_info.get("bestCount") or 0)

    # 获取本地历史数据（用于详细统计）
    end_date = time_r()
    if(this_season):
        start_date = str_to_time(this_season_start_date)
        TimeLim=f"本赛季({this_season_start_date.replace('-','')}-now)"
    else:
        start_date = time_delta(end_date, -30)
        TimeLim="近30日"
    history, duration = fetch_history(userid=userid, start_date=start_date, end_date=end_date)
    games = history.get(username, []) if history else []
    hero_games = [g for g in games if g.get('HeroName') == heroname]

    # 组装简洁输出
    lines = []
    lines.append(f"【统计信息】 {player_name}的{heroname} (梯度{herotier})")
    lines.append(line_delim)
    lines.append(f"战力  {heropower}  ({month_heropower_incre:+d})")
    lines.append(f"总战绩  {winNum}胜{failNum}负  胜率{round(win_rate*100,1)}%")

    if hero_games:
        total_games_h = len(hero_games)
        wins_h = sum(1 for g in hero_games if g.get('Result') == '胜利')
        win_rate_h = (wins_h / total_games_h) if total_games_h else 0
        scored_games = [g for g in hero_games if not g.get('GradeMissing')]
        avg_grade_h = round(sum(float(g.get('GameGrade', 0) or 0) for g in scored_games) / len(scored_games), 1) if scored_games else '—'
        mvp_h = sum(1 for g in hero_games if 'MVP' in (g.get('Others') or ''))
        avg_kill_h = sum(int(g.get('KillCnt', 0) or 0) for g in hero_games) / total_games_h if total_games_h else 0
        avg_dead_h = sum(int(g.get('DeadCnt', 0) or 0) for g in hero_games) / total_games_h if total_games_h else 0
        avg_assist_h = sum(int(g.get('AssistCnt', 0) or 0) for g in hero_games) / total_games_h if total_games_h else 0

        lines.append(line_delim)
        lines.append(f"{TimeLim}表现")
        lines.append(f"{total_games_h}场  胜率{round(win_rate_h*100,1)}%  均分{avg_grade_h}")
        lines.append(f"MVP×{mvp_h}  牌子×{month_medal}  KDA {round(avg_kill_h,1)}/{round(avg_dead_h,1)}/{round(avg_assist_h,1)}")
    else:
        lines.append(line_delim)
        lines.append(f"{TimeLim}无对局记录")

    # 添加成就牌（如果有特殊成就才显示）
    medal_list = res.get("medalList") or []
    if medal_list and len(medal_list) > 0:
        lines.append(line_delim)
        lines.append("成就")
        for medal_info in medal_list[:3]:  # 最多显示3个
            info = medal_info.get("UserMedalInfo") if isinstance(medal_info, dict) else str(medal_info)
            if info:
                lines.append(f"  · {info}")

    return "\n".join(lines)
# 单一玩家、所有英雄
def single_player_mult_hero_process(username, days=30, top_n=3, min_games=2, this_season=False, *, as_report=False):
    """Return the existing summary, or its structured facts for the two-image reply."""
    from ..ztime import time_r, time_delta, str_to_time

    userid = (extra_useridlist | userlist)[username]
    player_name = namenick.get(username, extra_namenick.get(username, username))

    end_date = time_r()
    if(this_season):
        start_date = str_to_time(this_season_start_date)
        TimeLim=f"本赛季({this_season_start_date.replace('-','')}-now)"
    else:
        start_date = time_delta(end_date, -days)
        TimeLim=f"近{days}日"
    history, duration = fetch_history(userid=userid, start_date=start_date, end_date=end_date)
    games = history.get(username, []) if history else []
    total_games = len(games)

    # 聚合每个英雄的统计
    hero_stats = {}
    tier_dict = getattr(dmc, "herotier", {})
    total_tier_val = 0
    tier_counted_games = 0
    for g in games:
        hn = g.get('HeroName', '未知')
        if hn in tier_dict:
            try:
                total_tier_val += float(tier_dict[hn])
                tier_counted_games += 1
            except:
                pass
        s = hero_stats.setdefault(hn, {'count': 0, 'wins': 0, 'grades': [], 'kills': 0, 'deads': 0, 'assists': 0, 'mvp': 0})
        s['count'] += 1
        if g.get('Result') == '胜利':
            s['wins'] += 1
        try:
            if not g.get('GradeMissing'):
                s['grades'].append(float(g.get('GameGrade') or 0))
        except:
            pass
        s['kills'] += int(g.get('KillCnt') or 0)
        s['deads'] += int(g.get('DeadCnt') or 0)
        s['assists'] += int(g.get('AssistCnt') or 0)
        if 'MVP' in (g.get('Others') or ''):
            s['mvp'] += 1

    # 计算指标
    metrics = {}
    hero_ids = {name: str(hero_id) for hero_id, name in HeroList.items()}
    for hn, s in hero_stats.items():
        cnt = s['count']
        wins = s['wins']
        win_rate = (wins / cnt) if cnt else 0
        avg_grade = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
        avg_k = s['kills'] / cnt if cnt else 0
        avg_d = s['deads'] / cnt if cnt else 0
        avg_a = s['assists'] / cnt if cnt else 0
        play_rate = cnt / total_games
        metrics[hn] = {
            'hero': hn,
            'hero_id': hero_ids.get(hn, ''),
            'tier': tier_dict.get(hn),
            'count': cnt,
            'play_rate': play_rate,
            'win_rate': win_rate,
            'avg_grade': avg_grade,
            'grade_available': bool(s['grades']),
            'kda': [round(avg_k, 2), round(avg_d, 2), round(avg_a, 2)],
            'mvp': s['mvp']
        }

    # 排名列表
    top_by_play = sorted(metrics.values(), key=lambda x: x['play_rate'], reverse=True)[:top_n]
    eligible = [m for m in metrics.values() if m['count'] >= max(1, min_games)]
    top_by_win = sorted(eligible, key=lambda x: x['win_rate'], reverse=True)[:top_n]
    top_by_grade = sorted(eligible, key=lambda x: x['avg_grade'], reverse=True)[:top_n]

    if as_report:
        from .player_client_details import metrics as detail_metrics, present, table
        report = {'kind': 'hero_history', 'label': '—', 'scope': '本赛季' if this_season else TimeLim,
                  'total': total_games, 'hero_count': len(metrics),
                  'average_tier': round(total_tier_val / tier_counted_games, 2) if tier_counted_games else None,
                  'sections': []}
        for title, minimum, rows in (('出场率 TOP', None, top_by_play),
                                     ('胜率 TOP', max(1, min_games), top_by_win),
                                     ('评分 TOP', max(1, min_games), top_by_grade)):
            report['sections'].append({'title': title, 'minimum_games': minimum, 'rows': [
                {**row, 'avg_grade': row['avg_grade'] if row['grade_available'] else None}
                for row in rows]})
        wins = sum(row['wins'] for row in hero_stats.values())
        grades = [grade for row in hero_stats.values() for grade in row['grades']]
        report['detail_sections'] = present([
            detail_metrics('整体对局表现', [('胜场', wins, 'integer'), ('负场', total_games-wins, 'integer'),
                ('平均评分', sum(grades)/len(grades) if grades else None, 'decimal'),
                ('全场最佳', sum(row['mvp'] for row in hero_stats.values()), 'integer'),
                *[(label, sum(row[field] for row in hero_stats.values()) / total_games if total_games else None, 'decimal')
                  for field, label in (('kills', '场均击杀'), ('deads', '场均死亡'), ('assists', '场均助攻'))]]),
            table('英雄表现明细', ['英雄', '场次', '胜率', '均分', 'MVP'], [
                [row['hero'], row['count'], row['win_rate']*100,
                 row['avg_grade'] if row['grade_available'] else None, row['mvp']]
                for row in sorted(metrics.values(), key=lambda row: -row['count'])[:10]],
                ['text', 'integer', 'percent', 'decimal', 'integer'])])
        return report

    if total_games == 0:
        return f"{player_name} 在{TimeLim}内没有对局记录。"

    # 可读摘要
    lines = []
    avg_tier = round(total_tier_val / tier_counted_games, 2) if tier_counted_games > 0 else "N/A"
    lines.append(f"【统计信息】 {player_name}的英雄汇总 \n（{TimeLim}，共 {total_games} 场，均梯: {avg_tier}）")
    lines.append(line_delim)
    lines.append("出场率 TOP:")
    for it in top_by_play:
        th = it['hero']
        tier_info = f" (梯 {tier_dict[th]})" if th in tier_dict else ""
        lines.append(f"  【{th}】{tier_info}: 出场 {it['count']} 场 ({round(it['play_rate']*100,1)}%)\n  胜率 {round(it['win_rate']*100,1)}%  均分 {round(it['avg_grade'],1)}\n  KDA {it['kda'][0]}/{it['kda'][1]}/{it['kda'][2]}")
    lines.append(line_delim)
    lines.append("胜率 TOP (至少 %d 场)：" % max(1, min_games
                ))
    if top_by_win:
        for it in top_by_win:
            th = it['hero']
            tier_info = f" (梯 {tier_dict[th]})" if th in tier_dict else ""
            lines.append(f"  【{th}】{tier_info}: 胜率 {round(it['win_rate']*100,1)}% ({it['count']} 场)\n  均分 {round(it['avg_grade'],1)}")
    else:
        lines.append("  无满足最小出场次数的英雄")
    lines.append(line_delim)
    lines.append("评分 TOP：")
    if top_by_grade:
        for it in top_by_grade:
            th = it['hero']
            tier_info = f" (梯 {tier_dict[th]})" if th in tier_dict else ""
            lines.append(f"  【{th}】{tier_info}: 均分 {round(it['avg_grade'],1)} ({it['count']} 场)\n  胜率 {round(it['win_rate']*100,1)}%")
    else:
        lines.append("  无满足最小出场次数的英雄")

    return "\n".join(lines)


def hero_history_text(report):
    """Readable fallback for the same facts used by the history leaderboard card."""
    tier = report['average_tier'] if report['average_tier'] is not None else '—'
    lines = [f"{report['label']} · {report['scope']}英雄汇总",
             f"共 {report['total']} 场 · {report['hero_count']} 位英雄 · 平均梯度 {tier}"]
    for section in report['sections']:
        minimum = section['minimum_games']
        lines.append(section['title'] + (f"（至少{minimum}场）" if minimum else ''))
        for row in section['rows']:
            grade = '—' if row['avg_grade'] is None else f"{row['avg_grade']:.1f}"
            tier = f" · 梯度{row['tier']}" if row['tier'] is not None else ''
            kda = '/'.join(str(value) for value in row['kda'])
            lines.append(f"{row['hero']}{tier} · {row['count']}场 · 出场率{row['play_rate']*100:.1f}% · "
                         f"胜率{row['win_rate']*100:.1f}% · 均分{grade} · KDA {kda}")
        if not section['rows']:
            lines.append('—')
    return '\n'.join(lines)


# 所有玩家、所有英雄
def mult_player_mult_hero_process(days=30, top_n=5, min_games=5, this_season=False):
    """统计所有玩家在最近若干天内的英雄总体表现，返回人类可读摘要字符串。
    - days: 向前统计天数
    - top_n: 每个榜单返回的条目数
    - min_games: 计算胜率/评分榜时的最小出场次数阈值（按英雄总出场次数）
    """
    from ..ztime import time_r, time_delta, str_to_time

    end_date = time_r()
    if(this_season):
        start_date = str_to_time(this_season_start_date)
        TimeLim=f"本赛季({this_season_start_date.replace('-','')}-now)"
    else:
        start_date = time_delta(end_date, -days)
        TimeLim=f"近{days}日"

    hero_stats = {}
    total_games_all = 0

    for realname, uid in userlist.items():
        try:
            history, duration = fetch_history(userid=uid, start_date=start_date, end_date=end_date)
        except Exception:
            continue
        games = history.get(realname, []) if history else []
        total_games_all += len(games)
        for g in games:
            hn = g.get('HeroName', '未知')
            s = hero_stats.setdefault(hn, {'count': 0, 'wins': 0, 'grades': []})
            s['count'] += 1
            if g.get('Result') == '胜利':
                s['wins'] += 1
            try:
                if not g.get('GradeMissing'):
                    s['grades'].append(float(g.get('GameGrade') or 0))
            except:
                pass

    if total_games_all == 0:
        return f"{TimeLim}内所有用户没有对局数据。"

    metrics = {}
    for hn, s in hero_stats.items():
        cnt = s['count']
        wins = s['wins']
        win_rate = (wins / cnt) if cnt else 0
        avg_grade = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
        play_rate = cnt / total_games_all
        metrics[hn] = {'hero': hn, 'count': cnt, 'play_rate': play_rate, 'win_rate': win_rate, 'avg_grade': avg_grade}

    top_by_play = sorted(metrics.values(), key=lambda x: x['play_rate'], reverse=True)[:top_n]
    eligible = [m for m in metrics.values() if m['count'] >= max(1, min_games)]
    top_by_win = sorted(eligible, key=lambda x: x['win_rate'], reverse=True)[:top_n]
    top_by_grade = sorted(eligible, key=lambda x: x['avg_grade'], reverse=True)[:top_n]

    lines = []
    lines.append(f"【统计信息】 群u的英雄汇总\n（{TimeLim}，共 {total_games_all} 场）")
    lines.append(line_delim)
    lines.append("出场率 TOP:")
    for it in top_by_play:
        lines.append(f"  {it['hero']}: 出场 {it['count']} 场 ({round(it['play_rate']*100,1)}%)  胜率 {round(it['win_rate']*100,1)}%  均分 {round(it['avg_grade'],1)}")
    lines.append(line_delim)
    lines.append(f"胜率 TOP（至少 {max(1,min_games)} 场）：")
    if top_by_win:
        for it in top_by_win:
            lines.append(f"  {it['hero']}: 胜率 {round(it['win_rate']*100,1)}% ({it['count']} 场)  均分 {round(it['avg_grade'],1)}")
    else:
        lines.append("  无满足最小出场次数的英雄")
    lines.append(line_delim)
    lines.append("评分 TOP：")
    if top_by_grade:
        for it in top_by_grade:
            lines.append(f"  {it['hero']}: 均分 {round(it['avg_grade'],1)} ({it['count']} 场)  胜率 {round(it['win_rate']*100,1)}%")
    else:
        lines.append("  无满足最小出场次数的英雄")

    return "\n".join(lines)
# 所有玩家、单一英雄
def mult_player_single_hero_process(hero_id,hero_name, days=30, min_games=3, top_n=5, this_season=False):
    """针对指定英雄聚合全服数据，返回人类可读摘要。
    - hero_name: 英雄名称（精确匹配 `HeroName` 字段）
    - days: 向前统计天数
    - min_games: 列入胜率/评分榜的最小出场次数阈值（按单个玩家）
    - top_n: 每个榜单返回条目数
    返回字符串，包含：总体场次、参战玩家数、总体胜率、均分、KDA、地图分布、玩家榜单等
    """
    from ..ztime import time_r, time_delta, str_to_time

    end_date = time_r()
    if(this_season):
        start_date = str_to_time(this_season_start_date)
        TimeLim=f"本赛季({this_season_start_date.replace('-','')}-now)"
    else:
        start_date = time_delta(end_date, -days)
        TimeLim=f"近{days}日"

    per_player = {}  # player -> stats
    map_counter = collections.Counter()
    total_games = 0

    for realname, uid in userlist.items():
        try:
            history, duration = fetch_history(userid=uid, start_date=start_date, end_date=end_date)
        except Exception:
            continue
        games = history.get(realname, []) if history else []
        hero_games = [g for g in games if g.get('HeroName') == hero_name]
        if not hero_games:
            continue
        stats = {'count': 0, 'wins': 0, 'grades': [], 'kills': 0, 'deads': 0, 'assists': 0, 'mvp': 0, 'maps': collections.Counter()}
        for g in hero_games:
            stats['count'] += 1
            total_games += 1
            if g.get('Result') == '胜利':
                stats['wins'] += 1
            try:
                if not g.get('GradeMissing'):
                    stats['grades'].append(float(g.get('GameGrade') or 0))
            except:
                pass
            stats['kills'] += int(g.get('KillCnt') or 0)
            stats['deads'] += int(g.get('DeadCnt') or 0)
            stats['assists'] += int(g.get('AssistCnt') or 0)
            if 'MVP' in (g.get('Others') or ''):
                stats['mvp'] += 1
            mapname = g.get('MapName') or '未知'
            stats['maps'][mapname] += 1
            map_counter[mapname] += 1
        per_player[realname] = stats

    if total_games == 0:
        return f"在{TimeLim}内未发现任何玩家使用 {hero_name} 的对局。"

    # 汇总总体指标
    total_wins = sum(s['wins'] for s in per_player.values())
    all_grades = [g for s in per_player.values() for g in s['grades']]
    overall_winrate = total_wins / total_games if total_games else 0
    overall_avg_grade = (sum(all_grades) / len(all_grades)) if all_grades else 0
    overall_k = sum(s['kills'] for s in per_player.values()) / total_games
    overall_d = sum(s['deads'] for s in per_player.values()) / total_games
    overall_a = sum(s['assists'] for s in per_player.values()) / total_games

    # 玩家榜单
    players_by_count = sorted(per_player.items(), key=lambda x: x[1]['count'], reverse=True)[:top_n]
    eligible = [(p, s) for p, s in per_player.items() if s['count'] >= max(1, min_games)]
    players_by_win = sorted(eligible, key=lambda x: (x[1]['wins'] / x[1]['count']) if x[1]['count'] else 0, reverse=True)[:top_n]
    players_by_grade = sorted(eligible, key=lambda x: (sum(x[1]['grades']) / len(x[1]['grades'])) if x[1]['grades'] else 0, reverse=True)[:top_n]

    # 地图分布前几
    top_maps = map_counter.most_common(8)

    # 组装输出
    lines = []
    lines.append(f"【统计信息】 群u的{hero_name}\n（{TimeLim}）")
    lines.append(line_delim)
    lines.append(f"总场次：{total_games}    参战玩家数：{len(per_player)}")
    lines.append(f"总胜率：{round(overall_winrate*100,1)}%    均分：{round(overall_avg_grade,2)}\n K/D/A：{round(overall_k,2)}/{round(overall_d,2)}/{round(overall_a,2)}")
    lines.append(line_delim)
    lines.append("地图分布（Top）：")
    for m, c in top_maps:
        lines.append(f"  【{m}】: {c} 场 ({round(c/total_games*100,1)}%)")
    lines.append(line_delim)
    lines.append(f"出场最多的玩家（Top {top_n}）：")
    for p, s in players_by_count:
        winr = (s['wins'] / s['count']) if s['count'] else 0
        avgg = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
        lines.append(f"  【{namenick.get(p,p)}】: {s['count']} 场  胜率 {round(winr*100,1)}%  均分 {round(avgg,2)}  KDA {round(s['kills']/s['count'],2)}/{round(s['deads']/s['count'],2)}/{round(s['assists']/s['count'],2)}")
    lines.append(line_delim)
    lines.append(f"胜率最高（至少 {max(1,min_games)} 场）Top {top_n}: ")
    if players_by_win:
        for p, s in players_by_win:
            winr = (s['wins'] / s['count']) if s['count'] else 0
            lines.append(f"  【{namenick.get(p,p)}】: 胜率 {round(winr*100,1)}% ({s['count']} 场)  均分 {round((sum(s['grades'])/len(s['grades'])) if s['grades'] else 0,2)}")
    else:
        lines.append("  无满足最小出场次数的玩家")
    lines.append(line_delim)
    lines.append(f"评分最高（至少 {max(1,min_games)} 场）Top {top_n}: ")
    if players_by_grade:
        for p, s in players_by_grade:
            avgg = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
            lines.append(f"  【{namenick.get(p,p)}】: 均分 {round(avgg,2)} ({s['count']} 场)  胜率 {round((s['wins']/s['count'])*100,1)}%")
    else:
        lines.append("  无满足最小出场次数的玩家")

    return "\n".join(lines)

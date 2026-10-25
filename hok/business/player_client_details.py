"""Readable detail sections from already returned client facts; no extra queries."""
from .player_client import _number, _text


def metrics(title, items):
    return {"title": title, "items": items} if any(value is not None for _, value, _ in items) else None


def table(title, headers, rows, formats):
    return {"title": title, "headers": headers, "rows": rows, "formats": formats} if rows else None


def present(sections):
    return [section for section in sections if section is not None]


def _ratio(value, total):
    return value / total * 100 if value is not None and total and value <= total else None


def statistics_details(values, result):
    games, wins = values['games'], values['wins']
    # The display's weighted games/wins are the same scope used by the overview.
    losses = games - wins if games is not None and wins is not None and wins <= games else values['losses']
    ability = (result.get('display') or {}).get('radar') or {}
    ability = ability.get('values') or {}
    branches = []
    for row in result.get('branch_statistics') or []:
        display = row.get('display') or {}
        names = {'top': '对抗路', 'mid': '中路', 'bot': '发育路', 'jungle': '打野', 'assist': '游走'}
        if row.get('branch') in names:
            branches.append([names[row['branch']], _number(display.get('games')),
                _number(display.get('win_rate_percent')), _number(display.get('composite_score'))])
    return present([
        metrics('胜负与表现', [('胜场', wins, 'integer'), ('负场', losses, 'integer'),
            ('全场最佳占比', _ratio(values['mvp'], games), 'percent'),
            ('败方最佳占比', _ratio(values['losing_mvp'], losses), 'percent')]),
        metrics('五维能力值', [(label, _number(ability.get(key)), 'fixed2') for key, label in (
            ('output', '输出指数'), ('kda', 'KDA指数'), ('development', '发育指数'),
            ('teamfight', '团战指数'), ('survival', '生存指数'))]),
        table('各分路表现', ['分路', '场次', '胜率', '综合得分'], branches,
              ['text', 'integer', 'percent', 'decimal'])])


def hero_details(values, result, district_names):
    sections = statistics_details(values, result)
    records = result.get('statistic_records') or []
    count = values['games']
    def average(field):
        parts = [_number(row.get(field)) for row in records]
        return sum(parts) / count if parts and count and all(value is not None for value in parts) else None
    sections += present([metrics('详细对局表现', [(label, average(field), 'decimal') for field, label in (
        ('dwKill', '场均击杀'), ('dwDead', '场均死亡'), ('dwAssist', '场均助攻'),
        ('dwGPM', '每分钟经济'), ('dwHurtPM', '每分钟输出'), ('ullTotalBeHurt', '场均承伤'))])])
    titles = []
    for row in result.get('historical_badges') or []:
        raw = row.get('raw') or {}
        if raw or _number(row.get('count')):
            adcode = raw.get('dwAdCode')
            region = (district_names or {}).get(adcode) if type(adcode) is int and adcode > 0 else None
            titles.append([region,
                _number(row.get('least_rank')), _number(row.get('count'))])
    badges = [[_text(row.get('name')), _number(row.get('stage')), _number(row.get('done_value'))]
              for row in result.get('badges_named') or [] if _text(row.get('name'))][:12]
    labels = [[_text(row.get('name')), _number(row.get('level')),
               '使用中' if row.get('in_use') is True else '未使用' if row.get('in_use') is False else None]
              for row in (result.get('year_labels') or {}).get('labels') or [] if _text(row.get('name'))][:12]
    sections += present([
        metrics('当前战力', [('英雄战力', _number(result.get('fight_value')), 'integer')]),
        table('历史称号记录', ['地区', '最好名次', '获得次数'], titles, ['text', 'integer', 'integer']),
        table('生涯徽章', ['徽章', '阶段', '进度'], badges, ['text', 'integer', 'integer']),
        table('赛年标签详情', ['标签', '等级', '状态'], labels, ['text', 'integer', 'text'])])
    return sections

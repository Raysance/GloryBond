"""Approved light daily-report table. Pure Pillow drawing, no network or writes."""
from PIL import Image, ImageDraw, ImageOps

from ..zfile import daily_report_font

INK = '#2C3535'
MUTED = '#929C9B'
GREEN = '#16876D'
RED = '#CC5C57'
GOLD = '#B58A38'
BG = '#FFFFFF'


def render_daily_report(data, avatars=None):
    avatars = avatars or {}
    scale = 2
    rows = sorted(data['rows'], key=lambda r: (r['games'] is None, -(r['games'] or 0), r['name']))
    row_h = 68
    start = 418
    table_end = start + len(rows) * row_h
    height = table_end + 124
    image = Image.new('RGB', (1200 * scale, height * scale), BG)
    draw = ImageDraw.Draw(image)
    fonts = {}

    def font(size, weight=400):
        key = (size, weight)
        if key not in fonts:
            f = daily_report_font(int(size * scale), weight)
            fonts[key] = f
        return fonts[key]

    def text(x, y, value, size=26, color=INK, weight=400, anchor='lt', max_width=None):
        value = str(value)
        if max_width:
            while draw.textlength(value, font=font(size, weight)) > max_width * scale and size > 17:
                size -= 1
            while draw.textlength(value, font=font(size, weight)) > max_width * scale:
                value = value[:-2] + '…'
        # Draw this standard nickname symbol explicitly: the bundled CJK face lacks it.
        if '◽' in value:
            left = x * scale
            top = y * scale - (size * scale / 2 if anchor.endswith('m') else 0)
            for char in value:
                if char == '◽':
                    side = size * scale * .32
                    cy = top + size * scale / 2
                    draw.rectangle((left + 2, cy - side / 2, left + 2 + side, cy + side / 2), outline=color, width=scale)
                    left += size * scale * .48
                else:
                    draw.text((left, top), char, font=font(size, weight), fill=color, anchor='lt')
                    left += draw.textlength(char, font=font(size, weight))
        else:
            draw.text((x * scale, y * scale), value, font=font(size, weight), fill=color, anchor=anchor)

    def box(coords, fill, radius=0, outline=None):
        coords = tuple(int(v * scale) for v in coords)
        if radius:
            draw.rounded_rectangle(coords, radius * scale, fill=fill, outline=outline, width=scale)
        else:
            draw.rectangle(coords, fill=fill, outline=outline, width=scale)

    def line(x1, y1, x2, y2, fill):
        draw.line((x1*scale, y1*scale, x2*scale, y2*scale), fill=fill, width=scale)

    def signed(value):
        return '—' if value is None else f'{int(value):+d}' if value else '0'

    def value_color(value):
        return MUTED if not value else GREEN if value > 0 else RED

    def total(field):
        values = [r[field] for r in rows if r[field] is not None]
        return sum(values) if values else None

    text(56, 54, '每日战报', 48, INK, 700)
    text(1144, 67, data['date'].replace('-', ' / '), 29, MUTED, 450, 'rt')
    line(56, 139, 1144, 139, '#DCE5E1')

    stats = [
        ('巅峰上分', signed(total('peak')), '分', value_color(sum(r['peak'] or 0 for r in rows))),
        ('排位上星', signed(total('stars')), '星', value_color(sum(r['stars'] or 0 for r in rows))),
        ('当日把数', '—' if total('games') is None else total('games'), '把', INK),
    ]
    for index, (label, value, unit, color) in enumerate(stats):
        x = 56 + index * 374
        text(x, 180, label, 25, MUTED)
        text(x, 222, value, 54, color, 650)
        text(x + 192, 255, unit, 24, MUTED, anchor='lm')
        if index < 2:
            line(x + 328, 184, x + 328, 281, '#E8EDEB')

    box((48, 351, 1152, 407), '#F0F5F2', 8)
    for x, label, anchor in [(72, '游戏昵称', 'lt'), (490, '巅峰分', 'mt'), (638, '排位星', 'mt'),
                             (780, '把数', 'mt'), (1018, '多久没打了', 'mt')]:
        text(x, 366, label, 24, '#61756B', 500, anchor)

    start = 418
    for i, row in enumerate(rows):
        y = start + i * row_h
        if i % 2:
            box((48, y, 1152, y + row_h), '#F8FAF9')
        source = avatars.get(row.get('key'))
        if source is not None:
            avatar = ImageOps.fit(source.convert('RGB'), (48 * scale, 48 * scale), method=Image.Resampling.LANCZOS)
            mask = Image.new('L', avatar.size)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, 48 * scale - 1, 48 * scale - 1), 9 * scale, fill=255)
            image.paste(avatar, (70 * scale, (y + 9) * scale), mask)
        else:
            box((70, y + 9, 118, y + 57), '#E8EEEB', 9)
            text(94, y + 33, '—', 23, MUTED, anchor='mm')
        text(134, y + 33, row['name'], 27, INK, 500, 'lm', max_width=282)
        text(490, y + 33, signed(row['peak']), 29, value_color(row['peak']), 600, 'mm')
        text(638, y + 33, signed(row['stars']), 29, value_color(row['stars']), 600, 'mm')
        text(780, y + 33, '—' if row['games'] is None else row['games'], 29, INK if row['games'] else MUTED, 550, 'mm')
        if row.get('status'):
            text(995, y + 33, row['status'], 24, MUTED, anchor='mm')
        elif row['last']:
            days, remainder = divmod(max(0, int(data['asof'] - row['last'])), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            age_color = GOLD if days >= 7 else '#72847A'
            for x, value, unit in zip((838, 916, 994, 1072), (days, hours, minutes, seconds), '天时分秒'):
                text(x + 35, y + 33, f'{value:02d}', 25 if value < 100 else 21 if value < 1000 else 16, age_color, 500, 'rm')
                text(x + 50, y + 33, unit, 19, MUTED, 400, 'mm')
        else:
            text(995, y + 33, '暂无记录', 24, MUTED, anchor='mm')
    y = start + len(rows) * row_h + 28
    line(56, y, 1144, y, '#DCE5E1')
    text(56, y + 24, '未打间隔按最近收录对局计算，缺档不代表没有游玩；— 为未取得。', 20, MUTED)
    text(56, y + 59, '间隔计算至 ' + data['asof_text'] + '；汇总仅计已取得数据，把数按玩家累计。', 20, MUTED)
    return image.resize((1200, height), Image.Resampling.LANCZOS)

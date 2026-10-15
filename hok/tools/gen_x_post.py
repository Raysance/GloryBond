"""Quiet, modern X cards with bilingual type, original media and sampled replies."""

import re
from html import unescape

from PIL import Image, ImageDraw, ImageFont

from ..zfile import x_card_font_path
from ..zstatic import x_subscription_config
from ..ztime import parse_chat_time_bound, epoch_to_text


def render_x_post_images(bundle, media_images=(), reply_media_images=None):
    config = x_subscription_config
    reply_media_images = reply_media_images or {}
    width = max(640, min(1800, int(config['image_width'])))
    scale = width / 1080
    px = lambda value: max(1, round(value * scale))
    margin, pad, gap = px(40), px(40), px(20)
    panel_width = width - 2 * margin
    text_width = panel_width - 2 * pad
    max_height = int(config['max_image_height'])
    font_path = x_card_font_path()
    if not font_path:
        raise ValueError('X 卡片缺少中文字体，请配置 XSubscriptions.font_paths')

    def font(size, weight=400):
        face = ImageFont.truetype(font_path, px(size))
        try:
            axes = face.get_variation_axes()
            face.set_variation_by_axes([weight if axis['name'] == b'Weight' else axis['default'] for axis in axes])
        except (OSError, AttributeError):
            pass
        return face

    body, original = font(34), font(27)
    reply_body, reply_original = font(29), font(24)
    author, reply_author = font(40, 600), font(25, 600)
    meta, caption = font(22), font(20)
    heading, monogram = font(27, 600), font(30, 500)
    ink, muted, faint, green = '#192D2A', '#697B76', '#8C9B96', '#328C76'
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))

    def wrapped(text, face, available=text_width):
        text = str(text or '').strip()
        lines = []
        for paragraph in text.split('\n'):
            line = ''
            for token in re.findall(r'[A-Za-z0-9_]+|\s+|.', paragraph):
                pieces = list(token) if measure.textlength(token, font=face) > available else [token]
                for part in pieces:
                    if line and measure.textlength(line + part, font=face) > available:
                        if part in '，。！？；：、）》】,.!?;:)]' and len(line) > 1:
                            lines.append(line[:-1].rstrip())
                            line = line[-1]
                        else:
                            lines.append(line.rstrip())
                            line = ''
                    if line or not part.isspace():
                        line += part
            lines.append(line)
        return lines

    def text_rows(text, face, color=ink, leading=1.65):
        return [{'kind':'text', 'text':line, 'font':face, 'color':color,
                 'height':round(face.size * (leading if line else .85))}
                for line in wrapped(text, face)]

    def space(value):
        return {'kind':'space', 'height':px(value)}

    def clean_text(value, post):
        text = unescape(str(value or ''))
        if (post.get('id') == bundle['post'].get('id') and media_images) or reply_media_images.get(post.get('id')):
            for url in post.get('media_short_urls', []):
                text = text.replace(url, '')
        if post.get('id') != bundle['post'].get('id') and bundle['post'].get('username'):
            text = re.sub(r'^@' + re.escape(bundle['post']['username']) + r'\s+', '', text, count=1, flags=re.I)
        return text.strip()

    def bilingual_rows(post, main_font, source_font, label=False):
        source = clean_text(post.get('text'), post)
        translated = clean_text(post.get('translation'), post)
        if translated:
            return ((text_rows('译文', caption, green, 1.4) + [space(10)] if label else [])
                    + text_rows(translated, main_font) + [space(24)]
                    + text_rows(source, source_font, muted, 1.6))
        return text_rows(source, main_font)

    post = bundle['post']
    stamp = epoch_to_text(parse_chat_time_bound(post['created_at']), '%Y.%m.%d  %H:%M') if post.get('created_at') else ''
    rows = [{'kind':'author', 'name':post.get('name') or post.get('username') or '',
             'username':post.get('username') or '', 'stamp':stamp, 'main':True, 'height':px(94)}]
    rows += [space(32)] + bilingual_rows(post, body, original, label=True)
    for media in media_images:
        image = media.copy().convert('RGB')
        # Fit the entire image. Portrait attachments retain their content.
        image.thumbnail((text_width, min(px(1500), max_height - 2 * margin - 2 * pad)), Image.Resampling.LANCZOS)
        rows += [space(28), {'kind':'image', 'image':image, 'height':image.height}]
    if bundle.get('media_unavailable'):
        rows += [space(18)] + text_rows('部分配图未加载', caption, faint)
    panels = [{'rows':rows, 'padding':pad, 'card':True}]

    replies = bundle.get('replies') or []
    if replies:
        sample = int(bundle.get('sample_size') or len(replies))
        panels.append({'rows':[{'kind':'reply_heading', 'count':sample, 'height':px(54)}],
                       'padding':0, 'card':False})
        for reply in replies:
            rows = [{'kind':'author', 'name':reply.get('name') or reply.get('username') or '',
                     'username':reply.get('username') or '', 'likes':int(reply.get('likes') or 0),
                     'main':False, 'height':px(64)}]
            rows += [space(16)] + bilingual_rows(reply, reply_body, reply_original)
            for media in reply_media_images.get(reply.get('id'), []):
                image = media.copy().convert('RGB')
                image.thumbnail((text_width, px(600)), Image.Resampling.LANCZOS)
                rows += [space(24), {'kind':'image','image':image,'height':image.height}]
            panels.append({'rows':rows, 'padding':pad, 'card':True})
    elif bundle.get('replies_available') is False:
        panels.append({'rows':text_rows('回复暂不可用', caption, faint), 'padding':px(12), 'card':False})

    # Keep ordinary cards together; split long cards at text line boundaries.
    pages, page, used = [], [], margin
    capacity = max_height - 2 * margin
    for panel in panels:
        padding = panel['padding']
        pending = list(panel['rows'])
        total = sum(row['height'] for row in pending) + 2 * padding
        if total <= capacity and page and used + gap + total > max_height - margin:
            pages.append((page, used + margin))
            page, used = [], margin
        while pending:
            room = max_height - margin - used - 2 * padding - (gap if page else 0)
            selected, consumed = [], 0
            while pending and consumed + pending[0]['height'] <= room:
                row = pending.pop(0)
                selected.append(row)
                consumed += row['height']
            if not selected:
                if not page:
                    raise ValueError('X 单个内容块超过图片高度预算')
                pages.append((page, used + margin))
                page, used = [], margin
                continue
            if page:
                used += gap
            part = dict(panel, rows=selected, y=used, height=consumed + 2 * padding)
            page.append(part)
            used += part['height']
            if pending:
                pages.append((page, used + margin))
                page, used = [], margin
    if page:
        pages.append((page, used + margin))

    def ellipsis(text, face, available):
        text = str(text)
        while text and measure.textlength(text, font=face) > available:
            text = text[:-2] + '…' if len(text) > 1 else ''
        return text

    def display_name(value, face):
        missing = face.getmask('\U0010ffff')
        missing_shape = (missing.size, bytes(missing))
        chars = []
        for char in str(value or ''):
            mask = face.getmask(char)
            if (mask.size, bytes(mask)) != missing_shape:
                chars.append(char)
        return ''.join(chars).strip()

    def rounded_media(canvas, image, x, y):
        mask = Image.new('L', image.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width, image.height), radius=px(18), fill=255)
        canvas.paste(image, (x, y), mask)

    images = []
    for page, height in pages:
        canvas = Image.new('RGB', (width, height), '#F1F7F4')
        draw = ImageDraw.Draw(canvas)
        for panel in page:
            y, padding = panel['y'], panel['padding']
            if panel['card']:
                box = (margin, y, width - margin, y + panel['height'])
                draw.rounded_rectangle(box, radius=px(28), fill='#FFFFFF', outline='#E2ECE7', width=1)
            x, y = margin + padding, y + padding
            for row in panel['rows']:
                kind = row['kind']
                if kind == 'text':
                    draw.text((x, y), row['text'], font=row['font'], fill=row['color'])
                elif kind == 'image':
                    rounded_media(canvas, row['image'], x + (text_width - row['image'].width) // 2, y)
                elif kind == 'reply_heading':
                    draw.text((margin + px(4), y + px(9)), '回复', font=heading, fill=ink)
                    label = f"按赞排序 · 采样 {row['count']} 条"
                    label_width = draw.textlength(label, font=caption)
                    draw.text((width - margin - label_width - px(4), y + px(14)), label, font=caption, fill=faint)
                elif kind == 'author':
                    main = row['main']
                    face = author if main else reply_author
                    name = display_name(row['name'], face) or row['username']
                    size = px(64 if main else 44)
                    draw.rounded_rectangle((x, y + px(4), x + size, y + size + px(4)), radius=size // 2, fill='#E5F3EC')
                    initial = (name or 'X')[0].upper()
                    initial_font = monogram if main else meta
                    draw.text((x + size / 2, y + px(4) + size / 2), initial, font=initial_font, fill=green, anchor='mm')
                    tx = x + size + px(18)
                    reserve = px(245 if main else 120)
                    name = ellipsis(name, face, text_width - size - px(18) - reserve)
                    draw.text((tx, y - px(5) if main else y - px(2)), name, font=face, fill=ink)
                    draw.text((tx, y + px(49 if main else 33)), '@' + row['username'], font=meta if main else caption, fill=muted)
                    if main and row['stamp']:
                        label = row['stamp']
                        draw.text((width - margin - padding - draw.textlength(label, font=caption), y + px(9)), label, font=caption, fill=faint)
                    elif not main:
                        label = f"赞 {row['likes']}"
                        draw.text((width - margin - padding - draw.textlength(label, font=caption), y + px(5)), label, font=caption, fill=green)
                y += row['height']
        images.append(canvas)
    return images

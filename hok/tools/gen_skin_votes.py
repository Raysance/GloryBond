"""Source-inspired light card, unsmoothed vote trends and ranking table."""

from PIL import Image, ImageDraw, ImageOps
import math

from ..zfile import pil_image_from_bytes, skin_votes_font


COLORS = ("#8b5cf6", "#3b82f6", "#f97316", "#111827", "#10b981",
          "#ef4444", "#06b6d4", "#eab308", "#ec4899", "#6366f1")


def render_skin_votes_image(data, rows, icons=None):
    icons = icons or {}
    chart_rows = rows[:10]
    width, margin, row_h = 1600, 40, 90
    table_top = 900
    height = table_top + 120 + len(rows) * row_h + 115
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title, heading = skin_votes_font(44, 700), skin_votes_font(29, 600)
    body, small, tiny = skin_votes_font(26), skin_votes_font(23), skin_votes_font(21)
    ink, muted, border = "#111827", "#6b7280", "#e5e7eb"

    def text(x, y, value, face=body, color=ink, right=False):
        value = str(value)
        if right:
            x -= draw.textlength(value, font=face)
        draw.text((x, y), value, font=face, fill=color)

    def fitted(x, y, value, max_width, face=body, color=ink):
        value = str(value)
        if draw.textlength(value, font=face) > max_width:
            while value and draw.textlength(value + "…", font=face) > max_width:
                value = value[:-1]
            value += "…"
        text(x, y, value, face, color)

    def wan(value, signed=False):
        return "—" if value is None else f"{value / 10000:{'+' if signed else ''}.2f}万"

    text(margin, 30, "皮肤返场投票趋势", title)
    text(margin, 100, "累计票数走势与当前排行", small, muted)
    draw.rounded_rectangle((margin, 155, margin + 98, 202), radius=10,
                           fill="#f4f4f5", outline=border)
    text(margin + 22, 162, "票数", small)
    period = f"近{data['hours']}小时" if data["hours"] else "全部"
    text(margin + 125, 164, f"{period} · 趋势前{len(chart_rows)}名", small, muted)
    text(width - margin, 166, f"更新时间：{data['updated']}  北京时间", small, muted, right=True)

    # Match the page's thin, colored lines and light dotted grid. Use real timestamps.
    draw.rounded_rectangle((margin, 225, width - margin, 865), radius=18,
                           outline=border, width=2)
    left, top, right, bottom = 150, 275, 1300, 785
    epochs = data["times"]
    values = [v for row in chart_rows for v in row["history"] if v is not None]
    maximum = max(values, default=1) or 1
    # Nice 1/2/5 tick spacing without changing any observations.
    base = 10 ** math.floor(math.log10(maximum / 6))
    step = max(value * base for value in (1, 2, 5, 10) if value * base <= maximum / 6)
    ceiling = max(step, math.ceil(maximum / step) * step)
    for index in range(int(ceiling / step) + 1):
        value = index * step
        y = bottom - value / ceiling * (bottom - top)
        for x in range(left, right, 10):
            draw.line((x, y, min(x + 5, right), y), fill=border)
        text(left - 16, y - 14, f"{value / 10000:g}万", tiny, muted, right=True)
    if epochs:
        start, end = epochs[0], epochs[-1]
        span = max(1, end - start)
        points_x = [left + (stamp - start) / span * (right - left) for stamp in epochs]
        labels = sorted({round(i * (len(epochs) - 1) / 4) for i in range(5)})
        for index in labels:
            x = points_x[index]
            for y in range(top, bottom, 10):
                draw.line((x, y, x, min(y + 5, bottom)), fill=border)
            label = data["time_labels"][index]
            text(max(left, min(x - 70, right - 140)), bottom + 20, label, tiny, muted)
        for index, row in enumerate(chart_rows):
            color = COLORS[index] if index < 10 else "#a1a1aa"
            points = []
            for x, value in zip(points_x, row["history"]):
                if value is None:
                    if len(points) > 1:
                        draw.line(points, fill=color, width=3)
                    elif points:
                        px, py = points[0]
                        draw.ellipse((px-3, py-3, px+3, py+3), fill=color)
                    points = []
                    continue
                points.append((x, bottom - value / ceiling * (bottom - top)))
            if len(points) > 1:
                draw.line(points, fill=color, width=4 if index < 3 else 3)
            elif points:
                px, py = points[0]
                draw.ellipse((px-3, py-3, px+3, py+3), fill=color)
            if points:
                px, py = points[-1]
                draw.ellipse((px-4, py-4, px+4, py+4), fill=color)
    # Keep labels in a separate rail: leader lines can look like declining votes.
    draw.rounded_rectangle((right+20, top-18, width-margin-16, bottom+5),
                           radius=10, fill="#fafafa", outline=border)
    text(right+32, top-5, "最新票数", tiny, muted)
    for index, row in enumerate(chart_rows):
        y = top + 57 + index * 46
        color = COLORS[index]
        label = f"{row['rank'] or '?'}  {wan(row['votes'])}"
        label_w = draw.textlength(label, font=tiny) + 16
        draw.rounded_rectangle((right+30, y-15, right+30+label_w, y+18), radius=6, fill=color)
        text(right+38, y-13, label, tiny, "white")
    if not values:
        text(560, 510, "暂无可绘制的趋势记录", heading, muted)

    table_bottom = table_top + 120 + len(rows) * row_h
    draw.rounded_rectangle((margin, table_top, width-margin, table_bottom), radius=16,
                           outline=border, width=2)
    text(65, table_top+18, "当前榜单", heading)
    text(width-margin-24, table_top+24,
         f"显示前{len(rows)}名 / 共{len(data['rows'])}款皮肤", small, muted, right=True)
    headers_y = table_top + 76
    text(65, headers_y, "#", small, muted)
    text(235, headers_y, "皮肤 / 英雄", small, muted)
    for x, label in ((870, "累计票数"), (1100, "区间增长"), (1285, "分均票数"), (1510, "与上一名差")):
        text(x, headers_y, label, small, muted, right=True)
    loaded_icons = 0
    for index, row in enumerate(rows):
        y = table_top + 120 + index * row_h
        draw.line((margin, y, width-margin, y), fill=border)
        color = COLORS[index] if index < 10 else "#a1a1aa"
        draw.rounded_rectangle((65, y+26, 111, y+66), radius=8, fill=color)
        rank = str(row["rank"]) if row["rank"] is not None else "?"
        text(88 - draw.textlength(rank, font=small)/2, y+28, rank, small, "white")
        avatar = None
        if icons.get(row["skin_id"]):
            try:
                avatar = ImageOps.fit(pil_image_from_bytes(icons[row["skin_id"]], max_pixels=4000000)
                                      .convert("RGB"), (62, 62))
            except Exception:
                pass
        if avatar is not None:
            image.paste(avatar, (145, y+14))
            loaded_icons += 1
        else:
            draw.rounded_rectangle((145, y+14, 207, y+76), radius=8, fill="#f4f4f5")
            text(162, y+28, row["hero"][:1], small, muted)
        fitted(230, y+12, row["skin"], 390, heading)
        fitted(230, y+50, row["hero"], 390, small, muted)
        text(870, y+29, wan(row["votes"]), body, right=True)
        text(1100, y+29, wan(row["growth"], signed=True), body, "#059669", right=True)
        text(1285, y+29, "—" if row["speed"] is None else f"{row['speed']:,.0f}", body, right=True)
        text(1510, y+29, wan(row["gap"]), body, right=True)

    footer = table_bottom + 25
    text(margin, footer, "票数约有百票精度误差；分均为估算值。", small, muted)
    text(margin, footer+37, "区间增长以各皮肤首个有效观测为起点，缺失观测保留空白。", tiny, muted)
    if loaded_icons < len(rows):
        text(width-margin, footer+37, "部分缩略图未加载", tiny, muted, right=True)
    return image

"""Render compact hero statistics; persistence and fonts use zfile boundaries."""

from PIL import Image, ImageDraw


def render_hero_report(report, font):
    rows = report["rows"]
    width, height = 1120, 310 + 116 * len(rows)
    image = Image.new("RGB", (width, height), "#edf2f8")
    draw = ImageDraw.Draw(image)
    title, subtitle = font(38, 700), font(21)
    name_font, value_font, small = font(27, 650), font(27, 600), font(18)
    compact_value_font = font(18, 600)
    ink, muted = "#172c48", "#65758b"

    def fit(text, face, max_width):
        text = str(text).replace("\n", " ")
        if draw.textlength(text, font=face) <= max_width:
            return text
        while text and draw.textlength(text + "…", font=face) > max_width:
            text = text[:-1]
        return text + "…"

    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=24, fill="white")
    draw.rounded_rectangle((24, 24, width - 24, 164), radius=24, fill="#172c48")
    draw.rectangle((24, 135, width - 24, 164), fill="#172c48")
    draw.text((54, 43), f"{report['scope']}常用英雄", font=title, fill="white")
    draw.text((55, 102), fit(report["label"], subtitle, 500), font=subtitle, fill="#d2def0")
    draw.text((width - 355, 105), f"5v5 · 按场次降序 · 前 {len(rows)} 名", font=small, fill="#d2def0")
    columns = ((54, "英雄"), (390, "场次"), (575, "胜率"), (760, "当前战力"), (950, "历史最高"))
    for x, heading in columns:
        draw.text((x, 186), heading, font=small, fill=muted)
    for index, row in enumerate(rows):
        top = 226 + index * 116
        if index % 2 == 0:
            draw.rounded_rectangle((42, top - 6, width - 42, top + 98), radius=12, fill="#f3f6fa")
        draw.rounded_rectangle((54, top + 12, 94, top + 53), radius=10,
                               fill="#d9ebff" if index == 0 else "#e5ebf2")
        draw.text((66, top + 18), str(index + 1), font=small, fill="#2466a2")
        draw.text((111, top + 12), fit(row["name"], name_font, 252), font=name_font, fill=ink)
        draw.text((112, top + 57), f"ID {row['hero_id']}", font=small, fill=muted)
        for x, key in ((390, "games"), (760, "fight_value"), (950, "highest_fight_value")):
            value = "—" if row[key] is None else f"{row[key]:,.0f}"
            face = value_font if draw.textlength(value, font=value_font) <= 142 else compact_value_font
            draw.text((x, top + 13), value, font=face, fill=ink)
        wins = "—" if row["wins"] is None else f"{row['wins']:.0f}"
        losses = "—" if row["losses"] is None else f"{row['losses']:.0f}"
        draw.text((390, top + 57), f"{wins}胜 / {losses}负", font=small, fill=muted)
        rate = row["win_rate_percent"]
        draw.text((575, top + 13), "—" if rate is None else f"{rate:.1f}%", font=value_font, fill=ink)
        draw.rounded_rectangle((575, top + 64, 710, top + 72), radius=4, fill="#e0e8ef")
        if rate:
            draw.rounded_rectangle((575, top + 64, 575 + 135 * rate / 100, top + 72), radius=4, fill="#3baf91")
    footer_y = 234 + len(rows) * 116
    draw.text((54, footer_y), f"接口返回 {report['total']} 个英雄 · 本图展示 {len(rows)} 个 · — 表示无可用数据",
              font=small, fill=muted)
    return image

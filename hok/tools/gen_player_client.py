"""Render compact hero statistics; persistence and fonts use zfile boundaries."""

from PIL import Image, ImageDraw, ImageOps

from ..zfile import pil_image_from_bytes


def win_rate_color(rate, bands):
    if rate is None:
        return "#65758b"
    for band in sorted(bands, key=lambda value: value["min_percent"], reverse=True):
        if rate >= band["min_percent"]:
            return band["color"]
    return "#65758b"


def render_hero_report(report, font, *, avatar_bytes=None, win_rate_bands):
    rows = report["rows"]
    avatar_bytes = avatar_bytes or {}
    width, height = 1120, 340 + 116 * len(rows)
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
        draw.rounded_rectangle((54, top + 23, 94, top + 64), radius=10,
                               fill="#d9ebff" if index == 0 else "#e5ebf2")
        draw.text((66, top + 29), str(index + 1), font=small, fill="#2466a2")
        avatar = None
        content = avatar_bytes.get(row["hero_id"])
        if content:
            try:
                avatar = ImageOps.fit(pil_image_from_bytes(content, max_pixels=1_000_000).convert("RGB"),
                                      (72, 72), method=Image.Resampling.LANCZOS)
            except (OSError, ValueError):
                pass
        if avatar is not None:
            mask = Image.new("L", (72, 72))
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, 71, 71), radius=14, fill=255)
            image.paste(avatar, (110, top + 6), mask)
        else:
            draw.rounded_rectangle((110, top + 6, 182, top + 78), radius=14, fill="#dfe9f3")
            draw.text((132, top + 25), row["name"][:1], font=name_font, fill=muted)
        draw.text((196, top + 25), fit(row["name"], name_font, 177), font=name_font, fill=ink)
        for x, key in ((390, "games"), (760, "fight_value"), (950, "highest_fight_value")):
            value = "—" if row[key] is None else f"{row[key]:,.0f}"
            face = value_font if draw.textlength(value, font=value_font) <= 142 else compact_value_font
            draw.text((x, top + 13), value, font=face, fill=ink)
        wins = "—" if row["wins"] is None else f"{row['wins']:.0f}"
        losses = "—" if row["losses"] is None else f"{row['losses']:.0f}"
        draw.text((390, top + 57), f"{wins}胜 / {losses}负", font=small, fill=muted)
        rate = row["win_rate_percent"]
        rate_color = win_rate_color(rate, win_rate_bands)
        draw.text((575, top + 13), "—" if rate is None else f"{rate:.1f}%", font=value_font, fill=rate_color)
        draw.rounded_rectangle((575, top + 64, 710, top + 72), radius=4, fill="#e0e8ef")
        if rate:
            draw.rounded_rectangle((575, top + 64, 575 + 135 * rate / 100, top + 72), radius=4, fill=rate_color)
    footer_y = 234 + len(rows) * 116
    draw.text((54, footer_y), f"接口返回 {report['total']} 个英雄 · 本图展示 {len(rows)} 个 · — 表示无可用数据",
              font=small, fill=muted)
    x = 54
    for band in sorted(win_rate_bands, key=lambda value: value["min_percent"]):
        legend = "胜率 " + band["label"]
        draw.text((x, footer_y + 30), legend, font=small, fill=band["color"])
        x += draw.textlength(legend, font=small) + 36
    return image

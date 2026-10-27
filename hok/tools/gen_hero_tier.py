from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..zfile import pil_image_from_bytes, save_pil_image


TIER_RULES = (("T0", 70), ("T0.5", 60), ("T1", 45), ("T2", 30), ("T3", 15), ("T4", 0))
TIER_NAMES = tuple(tier for tier, _ in TIER_RULES)
TIER_STYLES = {
    "T0": {"panel": (255, 247, 237), "label": (249, 115, 22), "text": (255, 255, 255)},
    "T0.5": {"panel": (255, 251, 235), "label": (245, 158, 11), "text": (255, 255, 255)},
    "T1": {"panel": (254, 252, 232), "label": (250, 204, 21), "text": (49, 46, 39)},
    "T2": {"panel": (247, 254, 231), "label": (132, 204, 22), "text": (255, 255, 255)},
    "T3": {"panel": (240, 253, 244), "label": (34, 197, 94), "text": (255, 255, 255)},
    "T4": {"panel": (240, 249, 255), "label": (14, 165, 233), "text": (255, 255, 255)},
}


def _font(size):
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/chinese/simhei.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size, index=0)
        except Exception:
            continue
    return ImageFont.load_default()


def _rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _tier_for_score(score):
    score = float(score or 0)
    for index, (tier, minimum) in enumerate(TIER_RULES):
        if score >= minimum:
            return tier, index
    return "T4", len(TIER_RULES) - 1


def _group_by_web_tier(heroes):
    groups = {tier: {"upper": [], "core": [], "lower": []} for tier in TIER_NAMES}
    ordered = sorted(
        heroes,
        key=lambda item: (
            -float(item.get("finalNormalizedTierScore") or 0),
            -float(item.get("trueHeroPowerInRole") or 0),
        ),
    )
    for hero in ordered:
        score = float(hero.get("finalNormalizedTierScore") or 0)
        tier, index = _tier_for_score(score)
        if index > 0 and TIER_RULES[index - 1][1] - 1 <= score < TIER_RULES[index - 1][1]:
            groups[tier]["upper"].append(hero)
        elif index < len(TIER_RULES) - 1 and TIER_RULES[index][1] <= score <= TIER_RULES[index][1] + 1:
            groups[tier]["lower"].append(hero)
        else:
            groups[tier]["core"].append(hero)
    return groups


def _avatar_image(content, size):
    if not content:
        return None
    try:
        image = pil_image_from_bytes(content).convert("RGB")
        return ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
    except Exception:
        return None


def _section_height(hero_count, columns, card_height, row_gap, heading=False):
    if not hero_count:
        return 0
    rows = (hero_count + columns - 1) // columns
    return (38 if heading else 0) + rows * card_height + max(0, rows - 1) * row_gap


def generate_hero_tier_image(tier_data, output_path, avatar_bytes=None):
    heroes = [item for item in tier_data.get("tiers", []) if isinstance(item, dict)]
    if not heroes:
        raise ValueError("hero_tier_image_error: empty tiers")
    avatar_bytes = avatar_bytes or {}
    groups = _group_by_web_tier(heroes)

    width = 1800
    margin = 48
    header_h = 178
    footer_h = 72
    tier_gap = 22
    panel_pad = 18
    tier_label_w = 126
    columns = 10
    card_w = 138
    card_h = 174
    card_gap = 10
    row_gap = 16

    tier_heights = {}
    for tier in TIER_NAMES:
        content_h = 0
        for key in ("upper", "core", "lower"):
            items = groups[tier][key]
            content_h += _section_height(len(items), columns, card_h, row_gap, heading=(key != "core"))
            if items:
                content_h += 10
        tier_heights[tier] = max(210, content_h + panel_pad * 2 - 10)

    height = margin + header_h + sum(tier_heights.values()) + tier_gap * (len(TIER_NAMES) - 1) + footer_h + margin
    image = Image.new("RGB", (width, height), (243, 245, 249))
    draw = ImageDraw.Draw(image)
    title_font = _font(52)
    sub_font = _font(23)
    tier_font = _font(36)
    hero_font = _font(21)
    score_font = _font(18)
    role_font = _font(17)
    note_font = _font(18)

    _rounded(draw, (margin, margin, width - margin, height - margin), 28, (255, 255, 255), (224, 229, 238), 2)
    draw.text((margin + 36, margin + 26), "英雄梯度榜", font=title_font, fill=(31, 37, 51))
    query_date = tier_data.get("queryDate") or heroes[0].get("date") or "最新"
    draw.text((margin + 38, margin + 96), f"天元之弈 · {query_date} · 全部分路", font=sub_font, fill=(102, 111, 130))

    legend_x = width - margin - 520
    legend_y = margin + 92
    draw.rectangle((legend_x, legend_y, legend_x + 22, legend_y + 22), outline=(239, 68, 68), width=3)
    draw.text((legend_x + 32, legend_y - 2), "高禁用率", font=note_font, fill=(105, 113, 130))
    legend_x += 180
    draw.rectangle((legend_x, legend_y, legend_x + 22, legend_y + 22), outline=(14, 165, 233), width=3)
    draw.text((legend_x + 32, legend_y - 2), "低出场率", font=note_font, fill=(105, 113, 130))
    draw.text((width - margin - 200, legend_y - 2), f"共 {len(heroes)} 项", font=note_font, fill=(105, 113, 130))

    current_y = margin + header_h
    for tier_index, tier in enumerate(TIER_NAMES):
        style = TIER_STYLES[tier]
        panel_h = tier_heights[tier]
        panel = (margin + 18, current_y, width - margin - 18, current_y + panel_h)
        _rounded(draw, panel, 20, style["panel"], style["label"], 4)
        label_box = (panel[0] + 16, panel[1] + 16, panel[0] + tier_label_w, panel[3] - 16)
        _rounded(draw, label_box, 16, style["label"])
        tier_bbox = draw.textbbox((0, 0), tier, font=tier_font)
        draw.text(
            (label_box[0] + (label_box[2] - label_box[0] - (tier_bbox[2] - tier_bbox[0])) // 2, label_box[1] + 24),
            tier,
            font=tier_font,
            fill=style["text"],
        )
        minimum = TIER_RULES[tier_index][1]
        draw.text((label_box[0] + 18, label_box[1] + 78), f"≥ {minimum} 分", font=note_font, fill=style["text"])

        grid_x = panel[0] + tier_label_w + 28
        section_y = panel[1] + panel_pad
        for section_key in ("upper", "core", "lower"):
            items = groups[tier][section_key]
            if not items:
                continue
            if section_key != "core":
                adjacent = TIER_NAMES[tier_index - 1] if section_key == "upper" else (
                    TIER_NAMES[tier_index + 1] if tier_index + 1 < len(TIER_NAMES) else ""
                )
                label = f"与 {adjacent} 临界"
                label_fill = (123, 104, 64) if section_key == "upper" else (70, 125, 151)
                draw.text((grid_x, section_y), label, font=note_font, fill=label_fill)
                dash_y = section_y + 15
                for dash_x in range(grid_x + 140, panel[2] - 24, 18):
                    draw.line((dash_x, dash_y, dash_x + 9, dash_y), fill=(191, 197, 207), width=2)
                section_y += 38

            for item_index, hero in enumerate(items):
                row = item_index // columns
                column = item_index % columns
                card_x = grid_x + column * (card_w + card_gap)
                card_y = section_y + row * (card_h + row_gap)
                avatar_size = 112
                avatar_x = card_x + (card_w - avatar_size) // 2
                avatar_y = card_y
                outline = (239, 68, 68) if hero.get("highBan") else ((14, 165, 233) if hero.get("lowPick") else (222, 226, 234))
                draw.rectangle((avatar_x - 3, avatar_y - 3, avatar_x + avatar_size + 3, avatar_y + avatar_size + 3), fill=outline)
                avatar = _avatar_image(avatar_bytes.get(str(hero.get("heroId"))), avatar_size)
                if avatar is not None:
                    image.paste(avatar, (avatar_x, avatar_y))
                else:
                    draw.rectangle((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), fill=(226, 230, 238))
                    initial = str(hero.get("heroName") or "?")[:1]
                    initial_box = draw.textbbox((0, 0), initial, font=tier_font)
                    draw.text((avatar_x + (avatar_size - (initial_box[2] - initial_box[0])) // 2, avatar_y + 28), initial, font=tier_font, fill=(112, 120, 138))

                overlay_top = avatar_y + avatar_size - 30
                draw.rectangle((avatar_x, overlay_top, avatar_x + avatar_size, avatar_y + avatar_size), fill=(30, 32, 38))
                score_text = f"{float(hero.get('finalNormalizedTierScore') or 0):.1f}"
                score_box = draw.textbbox((0, 0), score_text, font=score_font)
                draw.text((avatar_x + (avatar_size - (score_box[2] - score_box[0])) // 2, overlay_top + 4), score_text, font=score_font, fill=(255, 255, 255))

                hero_name = str(hero.get("heroName") or "未知英雄")
                name_box = draw.textbbox((0, 0), hero_name, font=hero_font)
                draw.text((card_x + (card_w - (name_box[2] - name_box[0])) // 2, avatar_y + avatar_size + 7), hero_name, font=hero_font, fill=(39, 44, 58))
                role = str(hero.get("role") or "-")
                role_box = draw.textbbox((0, 0), role, font=role_font)
                draw.text((card_x + (card_w - (role_box[2] - role_box[0])) // 2, avatar_y + avatar_size + 36), role, font=role_font, fill=(105, 113, 130))

            rows = (len(items) + columns - 1) // columns
            section_y += rows * card_h + max(0, rows - 1) * row_gap + 10
        current_y += panel_h + tier_gap

    footer = "头像底部为梯度分 · 英雄下方为最佳分路 · 数据仅供参考"
    footer_box = draw.textbbox((0, 0), footer, font=sub_font)
    draw.text(((width - (footer_box[2] - footer_box[0])) // 2, height - margin - 44), footer, font=sub_font, fill=(111, 119, 137))
    save_pil_image(image, output_path, format="PNG", optimize=True)
    return output_path


__all__ = ["generate_hero_tier_image"]

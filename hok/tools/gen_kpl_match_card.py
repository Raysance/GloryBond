"""Render a polished broadcast-style KPL series report."""

from __future__ import annotations


def _duration(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _number(value):
    value = int(value or 0)
    return f"{value / 10000:.1f}万" if abs(value) >= 10000 else str(value)


def _metric_text(entries):
    labels = {
        "伤害占比": "▲",
        "承伤占比": "◆",
        "经济占比": "¥",
        "伤害转化": "▲/¥",
        "承伤转化": "◆/¥",
    }
    return "  ".join(
        f"{labels.get(item.get('name'), item.get('name'))} {item.get('value')}{'%' if item.get('type') == 'rate' else ''}"
        for item in entries or []
    )


def gen(match_detail: dict, save_path: str, title: str = "KPL 对局详情"):
    """Generate a long PNG containing the series score and every game field."""
    from PIL import Image, ImageDraw, ImageFont

    from ..zfile import first_existing_path, pil_image_from_bytes, save_pil_image
    from ..zkpl import load_match_asset_bytes

    font_path = first_existing_path(
        [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "C:/Windows/Fonts/msyh.ttc",
        ]
    )

    def font(size, bold=False):
        if font_path:
            try:
                return ImageFont.truetype(font_path, size + (2 if bold else 0))
            except (OSError, ValueError):
                pass
        return ImageFont.load_default()

    width = 1800
    margin = 54
    games = match_detail.get("games") or []
    overall = match_detail.get("overall_ratings") or []
    overall_height = max(300, 148 + max((len(team.get("players") or []) for team in overall), default=0) * 44)
    game_heights = []
    for game in games:
        player_count = max((len(team.get("players") or []) for team in game.get("teams") or []), default=0)
        game_heights.append(285 + player_count * 126)
    empty_games_height = 170 if not games else 0
    height = 350 + overall_height + sum(game_heights) + 38 * len(games) + empty_games_height + margin

    image = Image.new("RGB", (width, max(height, 700)), "#F4F7FB")
    draw = ImageDraw.Draw(image)
    for py in range(image.height):
        ratio = py / max(image.height - 1, 1)
        draw.line((0, py, width, py), fill=(249 - int(9 * ratio), 251 - int(8 * ratio), 255 - int(5 * ratio)))
    f_title = font(30, True)
    f_score = font(76, True)
    f_h1 = font(31, True)
    f_h2 = font(26, True)
    f_text = font(21)
    f_small = font(17)
    asset_cache = {}

    def asset(url, size):
        if not url:
            return None
        key = (url, size)
        if key not in asset_cache:
            try:
                icon = pil_image_from_bytes(load_match_asset_bytes(url)).convert("RGBA")
                icon.thumbnail((size, size))
                asset_cache[key] = icon
            except Exception:
                asset_cache[key] = None
        return asset_cache[key]

    def icon_row(x, y_pos, urls, size=24, limit=None):
        used = list(urls or [])[:limit]
        for offset, url in enumerate(used):
            icon = asset(url, size)
            if icon is not None:
                image.paste(icon, (x + offset * (size + 4), y_pos), icon)

    def text_width(value, target_font):
        box = draw.textbbox((0, 0), str(value), font=target_font)
        return box[2] - box[0]

    def stat_icon(x, y_pos, kind, size=22):
        if kind == "gold":
            draw.ellipse((x, y_pos, x + size, y_pos + size), fill="#F4C75B", outline="#D9A92F", width=2)
            draw.text((x + 6, y_pos + 1), "¥", fill="#795719", font=f_small)
        elif kind == "damage":
            draw.polygon(
                [(x + 12, y_pos), (x + 4, y_pos + 12), (x + 11, y_pos + 12), (x + 7, y_pos + size), (x + size, y_pos + 8), (x + 14, y_pos + 8)],
                fill="#F06B4F",
            )
        elif kind == "taken":
            draw.polygon(
                [(x + size // 2, y_pos), (x + size, y_pos + 5), (x + size - 3, y_pos + 16), (x + size // 2, y_pos + size), (x + 3, y_pos + 16), (x, y_pos + 5)],
                fill="#5B9FDD",
            )
        elif kind == "tower":
            draw.rectangle((x + 4, y_pos + 7, x + size - 4, y_pos + size), fill="#7D8CA2")
            draw.rectangle((x + 2, y_pos + 3, x + 7, y_pos + 9), fill="#7D8CA2")
            draw.rectangle((x + size - 7, y_pos + 3, x + size - 2, y_pos + 9), fill="#7D8CA2")

    def inline_stat(x, y_pos, kind, value):
        stat_icon(x, y_pos + 1, kind)
        text = str(value)
        draw.text((x + 29, y_pos), text, fill="#425168", font=f_text)
        return x + 29 + text_width(text, f_text) + 24

    home = match_detail.get("home_team") or {}
    away = match_detail.get("away_team") or {}
    score = match_detail.get("score") or {}
    home_accent = "#1598C9"
    away_accent = "#E25572"

    def accent_for(team, fallback_side=0):
        if team.get("id") == home.get("id"):
            return home_accent
        if team.get("id") == away.get("id"):
            return away_accent
        return home_accent if fallback_side == 0 else away_accent

    draw.rounded_rectangle((margin + 8, 28, width - margin + 8, 310), 28, fill="#D8E0EB")
    draw.rounded_rectangle((margin, 20, width - margin, 302), 28, fill="#FFFFFF", outline="#D7E0EC", width=2)
    draw.rectangle((margin, 20, width // 2, 24), fill="#45BFEA")
    draw.rectangle((width // 2, 20, width - margin, 24), fill="#F07A92")
    draw.text((margin + 30, 42), title.upper(), fill="#25334A", font=f_title)
    draw.text((width - margin - 210, 47), "MATCH REPORT", fill="#91A0B5", font=f_small)

    score_text = f"{score.get('home', '-')}  :  {score.get('away', '-')}"
    box = draw.textbbox((0, 0), score_text, font=f_score)
    draw.text(((width - (box[2] - box[0])) / 2, 105), score_text, fill="#172033", font=f_score)
    center_x = width // 2
    home_name = home.get("name") or "-"
    away_name = away.get("name") or "-"
    home_box = draw.textbbox((0, 0), home_name, font=f_h1)
    away_box = draw.textbbox((0, 0), away_name, font=f_h1)
    draw.text((center_x - 220 - (home_box[2] - home_box[0]), 132), home_name, fill=home_accent, font=f_h1)
    draw.text((center_x + 220, 132), away_name, fill=away_accent, font=f_h1)
    home_logo = asset(home.get("logo"), 96)
    away_logo = asset(away.get("logo"), 96)
    if home_logo is not None:
        image.paste(home_logo, (margin + 70, 102), home_logo)
    if away_logo is not None:
        image.paste(away_logo, (width - margin - 166, 102), away_logo)
    meta = "  |  ".join(filter(None, [match_detail.get("game_stage"), match_detail.get("start_time_text"), match_detail.get("end_time_text")]))
    meta_box = draw.textbbox((0, 0), meta, font=f_text)
    draw.text(((width - (meta_box[2] - meta_box[0])) / 2, 248), meta, fill="#718096", font=f_text)

    y = 340
    draw.rounded_rectangle((margin + 7, y + 8, width - margin + 7, y + overall_height + 8), 24, fill="#D8E0EB")
    draw.rounded_rectangle((margin, y, width - margin, y + overall_height), 24, fill="#FFFFFF", outline="#D7E0EC", width=2)
    draw.text((margin + 28, y + 20), "RATING", fill="#8B9AAF", font=f_small)
    draw.text((margin + 28, y + 47), "总评", fill="#25334A", font=f_h1)
    col_width = (width - margin * 2 - 72) // 2
    for side, team in enumerate(overall[:2]):
        x = margin + 24 + side * (col_width + 24)
        accent = accent_for(team, side)
        panel_x = x
        panel_y = y + 94
        draw.rounded_rectangle((panel_x, panel_y, panel_x + col_width, y + overall_height - 18), 16, fill="#F5F8FC")
        draw.rectangle((panel_x, panel_y, panel_x + 5, y + overall_height - 18), fill=accent)
        draw.text((x + 20, y + 108), team.get("name") or "", fill=accent, font=f_h2)
        py = y + 148
        for player in team.get("players") or []:
            line = f"{player.get('position') or '-'}  {player.get('name') or '-'}   ★ {player.get('rating') or '-'}   N {player.get('rating_users') or 0}"
            draw.text((x + 20, py), line, fill="#45546A", font=f_text)
            py += 42
    y += overall_height + 38

    if not games:
        section_h = empty_games_height
        draw.rounded_rectangle((margin + 7, y + 8, width - margin + 7, y + section_h + 8), 24, fill="#D8E0EB")
        draw.rounded_rectangle((margin, y, width - margin, y + section_h), 24, fill="#FFFFFF", outline="#D7E0EC", width=2)
        draw.text((margin + 28, y + 24), "GAME DETAIL", fill="#8B9AAF", font=f_small)
        draw.text((margin + 28, y + 54), "小局数据未返回", fill="#25334A", font=f_h1)
        warning = "Bilibili match/info.detail 为空，当前只能展示总比分与评分数据。"
        warnings = match_detail.get("data_warnings") or []
        if warnings:
            warning = warnings[0]
        draw.text((margin + 28, y + 104), warning, fill="#7B899E", font=f_text)
        y += section_h + 38

    for game, section_h in zip(games, game_heights):
        draw.rounded_rectangle((margin + 7, y + 8, width - margin + 7, y + section_h + 8), 24, fill="#D8E0EB")
        draw.rounded_rectangle((margin, y, width - margin, y + section_h), 24, fill="#FFFFFF", outline="#D7E0EC", width=2)
        winner_id = game.get("winner_team_id")
        draw.rounded_rectangle((margin + 24, y + 20, margin + 180, y + 68), 13, fill="#EAF0F8")
        draw.text((margin + 45, y + 26), f"GAME {game.get('game_number')}", fill="#33445C", font=f_h2)
        game_meta = [f"时长 {_duration(game.get('duration_seconds'))}"]
        if game.get("game_map"):
            game_meta.append(f"地图 {game.get('game_map')}")
        if game.get("game_type"):
            game_meta.append(f"类型 {game.get('game_type')}")
        draw.text(
            (margin + 210, y + 31),
            "   ".join(game_meta),
            fill="#8492A6",
            font=f_text,
        )
        draw.line((margin + 24, y + 82, width - margin - 24, y + 82), fill="#E0E7F0", width=2)
        teams = game.get("teams") or []
        for side, team in enumerate(teams[:2]):
            x = margin + 24 + side * (col_width + 24)
            accent = accent_for(team, side)
            panel_top = y + 100
            draw.rounded_rectangle((x, panel_top, x + col_width, y + section_h - 24), 18, fill="#F7F9FC", outline="#DCE4EE", width=2)
            draw.rectangle((x, panel_top, x + col_width, panel_top + 5), fill=accent)
            ty = y + 120
            won = team.get("id") == winner_id
            draw.text((x + 20, ty), team.get("name") or "-", fill=accent, font=f_h2)
            if won:
                draw.rounded_rectangle((x + col_width - 100, ty - 4, x + col_width - 20, ty + 30), 10, fill="#DDF5E8")
                draw.text((x + col_width - 80, ty), "WIN", fill="#24875B", font=f_small)
            ty += 43
            summary = f"K/D/A {team.get('kills', 0)}/{team.get('deaths', 0)}/{team.get('assists', 0)}"
            sx = x + 20
            draw.text((sx, ty), summary, fill="#425168", font=f_text)
            sx += text_width(summary, f_text) + 30
            sx = inline_stat(sx, ty, "gold", _number(team.get("gold")))
            sx = inline_stat(sx, ty, "tower", team.get("towers", 0))
            inline_stat(sx, ty, "damage", _number(team.get("hero_damage")))
            ty += 42
            icon_row(x + 20, ty - 3, team.get("bans"), 22, 5)
            draw.line((x + 167, ty - 3, x + 167, ty + 21), fill="#CBD5E1", width=2)
            icon_row(x + 182, ty - 3, team.get("picks"), 22, 5)
            ty += 31
            objectives = []
            for objective in team.get("objectives") or []:
                count = sum(item.get("count") or 0 for item in objective.get("values") or [])
                objectives.append(f"{objective.get('name')} {count}")
            draw.text((x + 20, ty), "OBJ  " + ("  ".join(objectives) or "-"), fill="#7D8CA2", font=f_small)
            ty += 36
            for player in team.get("players") or []:
                mvp = " MVP" if player.get("is_mvp") else ""
                base = f"{player.get('name') or '-'}{mvp}  KDA {player.get('kills')}/{player.get('deaths')}/{player.get('assists')}"
                draw.line((x + 20, ty - 8, x + col_width - 20, ty - 8), fill="#E1E7EF", width=1)
                hero_icon = asset(player.get("hero_image"), 32)
                if hero_icon is not None:
                    image.paste(hero_icon, (x + 20, ty - 3), hero_icon)
                draw.text((x + 60, ty), base, fill="#26364D", font=f_text)
                stat_x = x + 60 + text_width(base, f_text) + 22
                stat_x = inline_stat(stat_x, ty, "gold", _number(player.get("gold")))
                stat_x = inline_stat(stat_x, ty, "damage", _number(player.get("hero_damage")))
                inline_stat(stat_x, ty, "taken", _number(player.get("damage_taken")))
                draw.text((x + 60, ty + 29), _metric_text(player.get("metrics")) or "-", fill="#7B899E", font=f_small)
                icon_row(x + 60, ty + 54, player.get("items"), 22, 6)
                resource_urls = []
                for entry in player.get("resources") or []:
                    resource_urls.extend(item.get("image") for item in entry.get("values") or [] if item.get("image"))
                draw.line((x + 230, ty + 54, x + 230, ty + 77), fill="#CBD5E1", width=2)
                icon_row(x + 244, ty + 54, resource_urls, 22, 5)
                ty += 126
        y += section_h + 38

    return save_pil_image(image, save_path, format="PNG", optimize=True)

def merge_gametime_rows(rows, sameuser, namenick=None):
    """Merge per-account gametime rows into main accounts by sameuser mapping.

    rows: [{"realname": str, "total": float, "games": {game: hours}}]
    sameuser: {main: [alias1, alias2, ...]}
    namenick: optional nickname dict for display

    Returns: [{"player": str, "subs": [str], "total": float, "games": {game: hours}}]
    """
    namenick = namenick or {}

    alias_to_main = {}
    main_to_aliases = {}
    if isinstance(sameuser, dict):
        for main, aliases in sameuser.items():
            if not isinstance(aliases, list):
                continue
            main_to_aliases[main] = list(aliases)
            for a in aliases:
                alias_to_main[a] = main

    merged = {}
    main_sub_totals = {}
    for row in rows:
        realname = row.get("realname")
        if not realname:
            continue
        main = alias_to_main.get(realname, realname)
        if main not in merged:
            merged[main] = {"main": main, "total": 0.0, "games": {}}
            main_sub_totals[main] = {}
        merged[main]["total"] += float(row.get("total") or 0)
        main_sub_totals[main][realname] = main_sub_totals[main].get(realname, 0.0) + float(row.get("total") or 0)
        games = row.get("games") or {}
        for g, v in games.items():
            merged[main]["games"][g] = merged[main]["games"].get(g, 0.0) + float(v or 0)

    out = []
    for main, item in merged.items():
        aliases = main_to_aliases.get(main, [])
        subs = []
        for a in aliases:
            if a == main:
                continue
            if a not in alias_to_main:
                continue
            h = main_sub_totals.get(main, {}).get(a, 0.0)
            subs.append(f"({namenick.get(a, a)} {round(h, 1)}h)")
        out.append(
            {
                "player": namenick.get(main, main),
                "subs": subs,
                "total": item.get("total", 0.0),
                "games": item.get("games") or {},
            }
        )
    out.sort(key=lambda x: x.get("total", 0), reverse=True)
    return out


def gen(rows, games, save_path: str, title: str = "游戏时长排行"):
    """Generate neon glow gametime matrix image.

    rows: [{player,total,games:{game:hours}, subs:[...]}]
    """
    import os
    import math
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    try:
        from .emoji_renderer import draw_text_with_emoji
    except Exception as e:
        import importlib.util
        import pathlib

        this_dir = pathlib.Path(__file__).resolve().parent
        mod_path = this_dir / "emoji_renderer.py"
        spec = importlib.util.spec_from_file_location("emoji_renderer", str(mod_path))
        if spec is None or spec.loader is None:
            raise Exception(f"emoji_renderer_load_failed: {str(mod_path)} {repr(e)}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        draw_text_with_emoji = getattr(mod, "draw_text_with_emoji")

    def load_font(size: int, bold: bool = False):
        candidates = [
            "/usr/share/fonts/chinese/simhei.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    return ImageFont.truetype(path, size + (2 if bold else 0))
            except Exception:
                continue
        return ImageFont.load_default()

    def measure(draw: ImageDraw.ImageDraw, font, text: str):
        bbox = draw.textbbox((0, 0), str(text), font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def clamp01(x: float):
        return 0.0 if x < 0 else (1.0 if x > 1 else x)

    def pick_color(v: float, avg: float, max_above: float, max_below: float):
        if v >= avg:
            denom = max_above if max_above > 0 else 1.0
            strength = clamp01((v - avg) / denom)
            return (46, 204, 113), math.sqrt(strength)
        denom = max_below if max_below > 0 else 1.0
        strength = clamp01((avg - v) / denom)
        return (231, 76, 60), math.sqrt(strength)

    def luma(rgb):
        r, g, b = rgb
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def best_text_color(rgb):
        return "#FFFFFF" if luma(rgb) < 140 else "#0B0F1A"

    def render_glow_tile(w: int, h: int, color_rgb, strength: float):
        strength = clamp01(strength)
        radius = max(10, int(min(w, h) * 0.24))
        inner_alpha = int(18 + 55 * strength)
        edge_alpha = int(85 + 170 * strength)
        blur_r = 10 + int(10 * strength)

        mask_edge = Image.new("L", (w, h), 0)
        d_edge = ImageDraw.Draw(mask_edge)
        d_edge.rounded_rectangle([12, 10, w - 12, h - 10], radius=radius, outline=edge_alpha, width=6)
        mask_edge = mask_edge.filter(ImageFilter.GaussianBlur(radius=blur_r))
        glow = Image.new("RGBA", (w, h), (*color_rgb, 0))
        glow.putalpha(mask_edge)

        mask_fill = Image.new("L", (w, h), 0)
        d_fill = ImageDraw.Draw(mask_fill)
        d_fill.rounded_rectangle([12, 10, w - 12, h - 10], radius=radius, fill=inner_alpha)
        fill_layer = Image.new("RGBA", (w, h), (*color_rgb, 0))
        fill_layer.putalpha(mask_fill)

        return Image.alpha_composite(glow, fill_layer)

    def estimate_width(text: str, font, emoji_size: int):
        w = 0.0
        for ch in str(text):
            if ord(ch) > 0xFFFF:
                w += emoji_size
            else:
                try:
                    w += font.getlength(ch)
                except Exception:
                    tmp = Image.new("RGB", (10, 10), (255, 255, 255))
                    dtmp = ImageDraw.Draw(tmp)
                    w += dtmp.textlength(ch, font=font)
        return w

    def wrap_label(text: str, max_width: float, font, emoji_size: int):
        raw = str(text).strip()
        if not raw:
            return [""]
        parts = raw.split(" ")
        lines = []
        cur = ""
        for part in parts:
            cand = part if not cur else (cur + " " + part)
            if estimate_width(cand, font, emoji_size) <= max_width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = ""
            if estimate_width(part, font, emoji_size) <= max_width:
                cur = part
                continue
            tmp = ""
            for ch in part:
                cand2 = tmp + ch
                if estimate_width(cand2, font, emoji_size) <= max_width:
                    tmp = cand2
                else:
                    if tmp:
                        lines.append(tmp)
                    tmp = ch
            if tmp:
                cur = tmp
        if cur:
            lines.append(cur)
        return lines

    scale = 2

    def S(x: int):
        return int(x * scale)

    font_title = load_font(S(52), bold=True)
    font_header = load_font(S(30), bold=True)
    font_axis = load_font(S(32), bold=True)
    font_axis_sub = load_font(S(26), bold=False)
    font_total = load_font(S(30), bold=True)
    font_cell = load_font(S(30), bold=False)

    emoji_cache_dir = os.path.join("resources","wzry_images", "tmp", "twemoji")

    labels = []
    totals = []
    for r in rows:
        main = str(r.get("player") or "")
        subs = [str(x) for x in (r.get("subs") or [])]
        labels.append([main] + subs)
        totals.append(float(r.get("total") or 0))

    matrix = []
    cols = len(games)
    for r in rows:
        gmap = r.get("games") or {}
        matrix.append([float(gmap.get(g, 0) or 0) for g in games])

    rows_n = len(labels)
    col_stats = []
    for j in range(cols):
        col_vals = [matrix[i][j] for i in range(rows_n) if matrix[i][j] > 0]
        active_n = len(col_vals)
        avg = sum(col_vals) / active_n if active_n else 0.0
        max_v = max(col_vals) if col_vals else 0.0
        min_v = min(col_vals) if col_vals else 0.0
        col_stats.append(
            {"avg": avg, "max_above": max(0.0, max_v - avg), "max_below": max(0.0, avg - min_v)}
        )

    line_h_main = S(38)
    line_h_sub = S(32)
    max_lines = max((len(x) for x in labels), default=1)
    text_h = line_h_main + max(0, max_lines - 1) * line_h_sub

    cell_h = max(S(110), text_h + S(26))
    cell_w = S(240)
    total_w = S(190)
    gap_x = S(16)
    gap_y = S(16)

    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d0 = ImageDraw.Draw(dummy)

    left_w = 0
    for lines in labels + [["玩家"]]:
        for idx, line in enumerate(lines):
            f = font_axis if idx == 0 else font_axis_sub
            w, _ = measure(d0, f, line)
            left_w = max(left_w, w + (S(18) if idx > 0 else 0))
    left_w = max(left_w + S(28), S(220))

    top_h = S(150)
    header_h = S(110)

    grid_w = cols * cell_w + max(0, cols - 1) * gap_x
    grid_h = rows_n * cell_h + max(0, rows_n - 1) * gap_y

    total_x = left_w + S(54)
    x0 = total_x + total_w + S(22)
    y0 = top_h + header_h

    canvas_w = x0 + grid_w + S(54)
    canvas_h = y0 + grid_h + S(64)

    img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    tw, th = measure(draw, font_title, title)
    draw.text(((canvas_w - tw) // 2, S(34)), str(title), fill="#000000", font=font_title)

    band_dark = (245, 247, 250)
    band_light = (255, 255, 255)
    for i in range(rows_n):
        by = y0 + i * (cell_h + gap_y) - gap_y // 2
        bh = cell_h + gap_y
        band = band_dark if (i % 2 == 1) else band_light
        draw.rectangle([total_x - S(10), by, x0 + grid_w + S(10), by + bh], fill=band)

    for i, lines in enumerate(labels):
        row_y = y0 + i * (cell_h + gap_y)
        needed_h = line_h_main + max(0, len(lines) - 1) * line_h_sub
        y_start = row_y + (cell_h - needed_h) // 2

        for idx, line in enumerate(lines):
            if idx == 0:
                draw_text_with_emoji(img, (S(54), y_start), line, font_axis, "#000000", S(32), emoji_cache_dir)
                y_start += line_h_main
            else:
                draw_text_with_emoji(img, (S(72), y_start), line, font_axis_sub, "#000000", S(28), emoji_cache_dir)
                y_start += line_h_sub

    total_label = "总时长"
    gw, gh = measure(draw, font_total, total_label)
    draw.text((total_x + (total_w - gw) / 2, top_h + (header_h - gh) / 2), total_label, fill="#000000", font=font_total)
    for i, total in enumerate(totals):
        py = y0 + i * (cell_h + gap_y)
        txt = f"{round(total, 1)}h"
        ttw, tth = measure(draw, font_total, txt)
        draw.text((total_x + (total_w - ttw) / 2, py + (cell_h - tth) / 2), txt, fill="#000000", font=font_total)

    for j, g in enumerate(games):
        gx = x0 + j * (cell_w + gap_x)
        label = str(g)
        max_w = cell_w - S(20)
        lines = wrap_label(label, max_w, font_header, S(34))
        line_h = S(34)
        total_h = len(lines) * line_h
        y_start = top_h + (header_h - total_h) / 2
        for idx, line in enumerate(lines):
            gw, _ = measure(draw, font_header, line)
            draw_text_with_emoji(
                img,
                (gx + (cell_w - gw) / 2, y_start + idx * line_h),
                line,
                font_header,
                "#000000",
                S(34),
                emoji_cache_dir,
            )

    for i in range(rows_n):
        for j in range(cols):
            v = matrix[i][j]
            if v <= 0:
                continue
            stats = col_stats[j]
            color_rgb, strength = pick_color(v, stats["avg"], stats["max_above"], stats["max_below"])
            tile = render_glow_tile(cell_w, cell_h, color_rgb, strength)
            px = x0 + j * (cell_w + gap_x)
            py = y0 + i * (cell_h + gap_y)
            img.paste(tile, (int(px), int(py)), tile)

            txt = f"{round(v, 1)}h"
            ttw, tth = measure(draw, font_cell, txt)
            draw.text((px + (cell_w - ttw) / 2, py + (cell_h - tth) / 2), txt, fill=best_text_color(color_rgb), font=font_cell)

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    img.save(save_path)
    return save_path

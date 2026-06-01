def gen(rows, games, save_path: str, title: str = "游戏时长排行"):
    """Generate neon glow gametime matrix image.

    rows: [{player,total,games:{game:hours}}]
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
        bbox = draw.textbbox((0, 0), text, font=font)
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

    font_title = load_font(52, bold=True)
    font_header = load_font(30, bold=True)
    font_axis = load_font(30, bold=True)
    font_total = load_font(30, bold=True)
    font_cell = load_font(30, bold=False)

    players = [str(r.get("player") or "") for r in rows]
    totals = [float(r.get("total") or 0) for r in rows]

    matrix = []
    cols = len(games)
    for r in rows:
        gmap = r.get("games") or {}
        matrix.append([float(gmap.get(g, 0) or 0) for g in games])

    rows_n = len(players)
    col_stats = []
    for j in range(cols):
        col_vals = [matrix[i][j] for i in range(rows_n)]
        avg = sum(col_vals) / rows_n if rows_n else 0.0
        max_v = max(col_vals) if col_vals else 0.0
        min_v = min(col_vals) if col_vals else 0.0
        col_stats.append(
            {"avg": avg, "max_above": max(0.0, max_v - avg), "max_below": max(0.0, avg - min_v)}
        )

    cell_h = 98
    cell_w = 240
    total_w = 190
    gap_x = 16
    gap_y = 16

    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d0 = ImageDraw.Draw(dummy)

    left_w = 0
    for p in players + ["玩家"]:
        w, _ = measure(d0, font_axis, p)
        left_w = max(left_w, w)
    left_w = max(left_w + 28, 220)

    top_h = 150
    header_h = 110

    grid_w = cols * cell_w + max(0, cols - 1) * gap_x
    grid_h = rows_n * cell_h + max(0, rows_n - 1) * gap_y

    total_x = left_w + 54
    x0 = total_x + total_w + 22
    y0 = top_h + header_h

    canvas_w = x0 + grid_w + 54
    canvas_h = y0 + grid_h + 64

    img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    title = str(title)
    tw, th = measure(draw, font_title, title)
    draw.text(((canvas_w - tw) // 2, 34), title, fill="#000000", font=font_title)

    emoji_cache_dir = os.path.join("wzry_images", "tmp", "twemoji")

    band_dark = (245, 247, 250)
    band_light = (255, 255, 255)
    for i in range(rows_n):
        by = y0 + i * (cell_h + gap_y) - gap_y // 2
        bh = cell_h + gap_y
        band = band_dark if (i % 2 == 1) else band_light
        draw.rectangle([total_x - 10, by, x0 + grid_w + 10, by + bh], fill=band)

    for i, p in enumerate(players):
        py = y0 + i * (cell_h + gap_y) + (cell_h - 32) // 2
        draw_text_with_emoji(img, (54, py), p, font_axis, "#000000", emoji_size=32, cache_dir=emoji_cache_dir)

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
        gw, gh = measure(draw, font_header, label)
        draw_text_with_emoji(
            img,
            (gx + (cell_w - gw) / 2, top_h + (header_h - gh) / 2),
            label,
            font_header,
            "#000000",
            emoji_size=34,
            cache_dir=emoji_cache_dir,
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

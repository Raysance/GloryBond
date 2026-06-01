def gen(rows, games, save_path: str, title: str = "游戏时长排行"):
    """Generate neon glow gametime matrix image. rows: [{player,total,games:{game:hours}}]."""
    import os
    import math
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

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
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dg = ImageDraw.Draw(glow)

        inner_alpha = int(10 + 35 * strength)
        edge_alpha = int(55 + 165 * strength)
        blur_r = 9 + int(10 * strength)

        dg.rounded_rectangle([12, 10, w - 12, h - 10], radius=radius, outline=(*color_rgb, edge_alpha), width=6)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=blur_r))
        tile = Image.alpha_composite(tile, glow)

        fill_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        df = ImageDraw.Draw(fill_layer)
        df.rounded_rectangle([12, 10, w - 12, h - 10], radius=radius, fill=(*color_rgb, inner_alpha))
        tile = Image.alpha_composite(tile, fill_layer)
        return tile

    font_title = load_font(26, bold=True)
    font_header = load_font(14, bold=True)
    font_axis = load_font(14, bold=True)
    font_cell = load_font(14, bold=False)

    players = [str(r.get("player") or "") for r in rows]
    matrix = []
    col_stats = []
    for r in rows:
        gmap = r.get("games") or {}
        row_vals = []
        for g in games:
            v = float(gmap.get(g, 0) or 0)
            row_vals.append(v)
        matrix.append(row_vals)

    cols = len(games)
    rows_n = len(players)
    for j in range(cols):
        col_vals = [matrix[i][j] for i in range(rows_n)]
        avg = sum(col_vals) / rows_n if rows_n else 0.0
        max_v = max(col_vals) if col_vals else 0.0
        min_v = min(col_vals) if col_vals else 0.0
        col_stats.append(
            {
                "avg": avg,
                "max_above": max(0.0, max_v - avg),
                "max_below": max(0.0, avg - min_v),
            }
        )

    cell_h = 56
    cell_w = 150
    gap_x = 14
    gap_y = 14

    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d0 = ImageDraw.Draw(dummy)

    left_w = 0
    for p in players + ["玩家"]:
        w, _ = measure(d0, font_axis, p)
        left_w = max(left_w, w)
    left_w = max(left_w + 24, 170)

    top_h = 92
    header_h = 62

    grid_w = cols * cell_w + max(0, cols - 1) * gap_x
    grid_h = rows_n * cell_h + max(0, rows_n - 1) * gap_y

    canvas_w = left_w + 46 + grid_w + 46
    canvas_h = top_h + header_h + grid_h + 56

    bg = (255, 255, 255)
    img = Image.new("RGB", (canvas_w, canvas_h), bg)
    draw = ImageDraw.Draw(img)

    tw, th = measure(draw, font_title, title)
    draw.text(((canvas_w - tw) // 2, 28), title, fill="#000000", font=font_title)

    x0 = left_w + 46
    y0 = top_h + header_h

    for i, p in enumerate(players):
        py = y0 + i * (cell_h + gap_y) + (cell_h - 18) // 2
        draw.text((46, py), p, fill="#000000", font=font_axis)

    for j, g in enumerate(games):
        gx = x0 + j * (cell_w + gap_x)
        label = str(g)
        gw, gh = measure(draw, font_header, label)
        draw.text((gx + (cell_w - gw) / 2, top_h + (header_h - gh) / 2), label, fill="#000000", font=font_header)

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

"""Clean player/hero cards; no template assets, network or file IO."""

from math import cos, sin, pi

from PIL import Image, ImageDraw, ImageOps

from .gen_player_client import win_rate_color
from ..zfile import pil_image_from_bytes

BG, PAPER, INK, MUTED = "#eff4f5", "#ffffff", "#243746", "#788a96"
LINE, ACCENT, TINT = "#e7edef", "#24897d", "#edf7f4"


class Card:
    def __init__(self, font, height):
        self.image = Image.new("RGB", (1120, height), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.font, self.faces = font, {}
        self.draw.rounded_rectangle((24, 24, 1096, height - 24), radius=30, fill=PAPER)

    def text(self, x, y, value, size=24, color=INK, *, bold=False, width=None, anchor="lt"):
        key = (size, bold)
        if key not in self.faces:
            self.faces[key] = self.font(size, 650 if bold else 400)
        face, value = self.faces[key], str(value)
        if width and self.draw.textlength(value, font=face) > width:
            while value and self.draw.textlength(value + "…", font=face) > width:
                value = value[:-1]
            value += "…"
        self.draw.text((x, y), value, font=face, fill=color, anchor=anchor)

    def rule(self, y):
        self.draw.line((64, y, 1056, y), fill=LINE, width=2)

    def metric(self, x, y, label, value, *, color=INK, size=40, width=290):
        self.text(x, y, label, 22, MUTED, width=width)
        self.text(x, y + 36, value, size, color, bold=True, width=width)

    def avatar(self, content, x, y, size=72):
        box = (x, y, x + size, y + size)
        self.draw.rounded_rectangle(box, radius=16, fill=TINT)
        if not content:
            return
        try:
            source = pil_image_from_bytes(content, max_pixels=8_000_000).convert("RGB")
            photo = ImageOps.fit(source, (size, size), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            return
        mask = Image.new("L", (size, size))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=16, fill=255)
        self.image.paste(photo, (x, y), mask)


def number(value, *, percent=False):
    if value is None:
        return "—"
    if percent:
        return f"{value:.1f}%"
    return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"


def profile_card(report, font, bands):
    c, values = Card(font, 1080), report["values"]
    c.text(64, 62, "个人资料", 24, ACCENT, bold=True)
    c.text(64, 109, report["name"], 46, bold=True, width=790)
    c.text(1056, 124, "Lv. " + number(values["level"]), 27, MUTED, anchor="rt")
    c.rule(190)
    for index, (key, title) in enumerate((("heroes", "英雄"), ("skins", "皮肤"), ("credit", "信誉积分"),
                                          ("king_marks", "王者印记"), ("achievement", "成就积分"), ("popularity", "人气"))):
        c.metric(64 + index % 3 * 338, 220 + index // 3 * 108, title, number(values[key]))
    c.rule(437)
    c.text(64, 468, "本赛季", 25, bold=True)
    stats = report["statistics"]
    for index, (key, title) in enumerate((("games", "场次"), ("win_rate_percent", "胜率"), ("score", "综合得分"))):
        color = win_rate_color(stats[key], bands) if key == "win_rate_percent" else INK
        c.metric(64 + index * 338, 516, title, number(stats[key], percent=key == "win_rate_percent"), color=color)
    c.rule(624)
    c.text(64, 655, "巅峰赛", 25, bold=True)
    for index, title in enumerate(("当前积分", "本赛季最高", "历史最高")):
        c.metric(64 + index * 338, 701, title, number(values["peak"][index]), size=36)
    c.rule(803)
    c.text(64, 834, "我的分路", 25, bold=True)
    for index, branch in enumerate(report["branches"]):
        x = 64 + index * 202
        c.draw.rounded_rectangle((x, 880, x + 184, 972), radius=14, fill=TINT)
        c.text(x + 92, 898, branch["name"], 23, MUTED, anchor="mt")
        level = "—" if branch["level"] is None else number(branch["level"]) + "段"
        c.text(x + 92, 933, level, 26, ACCENT, bold=True, anchor="mt")
    if report["signature"]:
        c.text(64, 1006, report["signature"], 22, MUTED, width=992)
    return c.image


def _radar(c, ratios):
    cx, cy, radius = 300, 555, 108
    names = (("output", "输出"), ("kda", "KDA"), ("development", "发育"),
             ("teamfight", "团战"), ("survival", "生存"))
    vertices = [(cos(-pi / 2 + index * 2 * pi / 5), sin(-pi / 2 + index * 2 * pi / 5)) for index in range(5)]
    for scale in (.25, .5, .75, 1):
        points = [(cx + radius * scale * x, cy + radius * scale * y) for x, y in vertices]
        c.draw.line(points + [points[0]], fill=LINE, width=2)
    for x, y in vertices:
        c.draw.line((cx, cy, cx + radius * x, cy + radius * y), fill=LINE, width=2)
    if ratios:
        points = [(cx + radius * ratios[key] * x, cy + radius * ratios[key] * y)
                  for (key, _), (x, y) in zip(names, vertices)]
        c.draw.polygon(points, fill="#d5eee7")
        c.draw.line(points + [points[0]], fill=ACCENT, width=3)
        for x, y in points:
            c.draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=ACCENT)
    for (_, title), (x, y) in zip(names, vertices):
        c.text(cx + 135 * x, cy + 135 * y, title, 23, MUTED, anchor="mm")


def statistics_card(report, font, bands, avatar_bytes):
    hero = report["kind"] == "hero"
    c, values = Card(font, 1080 if hero else 920), report["values"]
    c.text(64, 62, "英雄表现" if hero else "对战数据", 24, ACCENT, bold=True)
    if hero:
        c.avatar(avatar_bytes.get(report["hero_id"]), 64, 110)
    left = 156 if hero else 64
    c.text(left, 109, report["label"], 38 if hero else 42, bold=True, width=790 - left)
    c.text(1056, 124, report["branch_label"], 27, ACCENT, anchor="rt", width=240)
    subtitle = report["scope"] if hero else report["scope"] + "  ·  " + report["mode"]
    c.text(left, 170, subtitle, 24, MUTED, width=1056 - left)
    for index, (key, title) in enumerate((("games", "场次"), ("win_rate_percent", "胜率"), ("score", "综合得分"))):
        color = win_rate_color(values[key], bands) if key == "win_rate_percent" else INK
        c.metric(64 + index * 338, 232, title, number(values[key], percent=key == "win_rate_percent"), size=52, color=color)
    c.rule(345)
    c.text(64, 375, "能力表现", 25, bold=True)
    _radar(c, values["radar"])
    c.text(636, 375, "对局荣誉", 25, bold=True)
    for index, (key, title) in enumerate((("top", "顶级"), ("gold", "金牌"), ("silver", "银牌"), ("bronze", "铜牌"))):
        y = 434 + index * 60
        c.text(636, y, title, 25, MUTED)
        c.text(1056, y, number(values["medals"][key]), 30, bold=True, anchor="rt", width=300)
        if index < 3:
            c.draw.line((636, y + 42, 1056, y + 42), fill=LINE, width=1)
    c.rule(712)
    if hero:
        for index, (key, title) in enumerate((("highest_fight_value", "最高战力"), ("mvp", "全场最佳"), ("losing_mvp", "败方最佳"))):
            c.metric(64 + index * 338, 748, title, number(values[key]), size=36)
        c.rule(854)
        c.text(64, 888, "赛年标签", 25, bold=True)
        for index, text in enumerate((report["year_labels"] or [None] * 3)[:3]):
            x = 64 + index * 338
            c.draw.rounded_rectangle((x, 932, x + 316, 982), radius=12, fill=TINT)
            c.text(x + 158, 957, text or "—", 23, ACCENT, anchor="mm", width=288)
        c.text(64, 1016, "历史称号", 23, MUTED)
        rank = (report["rank_badge"] or {}).get("text") or "—"
        count = report["honor_count"]
        c.text(1056, 1016, rank + "  ·  " + number(count) + "次", 24, ACCENT, anchor="rt", width=760)
        return c.image
    honors = (("mvp", "全场最佳"), ("losing_mvp", "败方最佳"), ("triple_kills", "三连决胜"),
              ("quadra_kills", "四连超凡"), ("penta_kills", "五连绝世"), ("legendary", "超神"))
    for index, (key, title) in enumerate(honors):
        x = 64 + index % 3 * 338
        y = 750 + index // 3 * 68
        c.text(x, y, title, 20, MUTED)
        c.text(x + 285, y - 3, number(values[key]), 29, bold=True, anchor="rt", width=160)
    return c.image


def heroes_card(report, font, bands, avatar_bytes):
    c = Card(font, 340 + len(report["rows"]) * 132)
    c.text(64, 62, "英雄统计", 24, ACCENT, bold=True)
    c.text(64, 109, report["label"], 42, bold=True, width=730)
    c.text(1056, 124, report["scope"], 27, ACCENT, anchor="rt", width=240)
    c.text(64, 170, f"5v5  ·  最高战力  ·  {len(report['rows'])}/{report['total']}", 24, MUTED)
    c.rule(210)
    c.text(64, 240, "英雄", 21, MUTED)
    for x, title in ((480, "场次"), (660, "胜率"), (850, "当前战力"), (1056, "最高战力")):
        c.text(x, 240, title, 21, MUTED, anchor="rt")
    for index, row in enumerate(report["rows"]):
        y = 280 + index * 132
        c.avatar(avatar_bytes.get(row["hero_id"]), 64, y)
        c.text(156, y + 4, row["name"], 28, bold=True, width=210)
        rank = (row["rank_badge"] or {}).get("text")
        if row["fight_style"]:
            c.text(156, y + 48, row["fight_style"], 18, MUTED, width=264)
        if rank:
            c.text(156, y + 78, "历史称号  " + rank, 18, MUTED, width=900)
        for x, key in ((480, "games"), (660, "win_rate_percent"), (850, "fight_value"), (1056, "highest_fight_value")):
            rate = key == "win_rate_percent"
            color = win_rate_color(row[key], bands) if rate else INK
            c.text(x, y + 18, number(row[key], percent=rate), 30, color, bold=True, anchor="rt", width=100 if key == "games" else 155)
        c.rule(y + 107)
    branches = [row["text"] for row in report["branches"] or [] if row.get("text")]
    if branches:
        c.text(64, c.image.height - 60, "我的分路  ·  " + "  ·  ".join(branches), 23, ACCENT, width=992)
    return c.image


def history_heroes_card(report, font, bands, avatar_bytes):
    sections = report["sections"]
    height = 280 + sum(104 + max(1, len(section["rows"])) * 112 for section in sections)
    c = Card(font, height if report["total"] else 420)
    c.text(64, 62, "英雄表现汇总", 24, ACCENT, bold=True)
    c.text(64, 109, report["label"], 42, bold=True, width=730)
    c.text(1056, 124, report["scope"], 27, ACCENT, anchor="rt", width=240)
    tier = "—" if report["average_tier"] is None else str(report["average_tier"])
    c.text(64, 170, f"共 {report['total']} 场  ·  使用 {report['hero_count']} 位英雄  ·  平均梯度 {tier}", 24, MUTED, width=992)
    c.rule(210)
    if not report["total"]:
        c.text(64, 258, "暂无对局记录", 27, MUTED)
        return c.image
    y = 240
    for section in sections:
        c.text(64, y, section["title"], 25, ACCENT, bold=True)
        if section["minimum_games"]:
            c.text(1056, y + 4, f"至少 {section['minimum_games']} 场", 21, MUTED, anchor="rt")
        c.text(64, y + 46, "英雄", 21, MUTED)
        for x, title in ((480, "场次"), (660, "出场率"), (850, "胜率"), (1056, "均分")):
            c.text(x, y + 46, title, 21, MUTED, anchor="rt")
        for index, row in enumerate(section["rows"]):
            top = y + 80 + index * 112
            c.avatar(avatar_bytes.get(row["hero_id"]), 64, top)
            c.text(156, top + 4, row["hero"], 28, bold=True, width=210)
            if row["tier"] is not None:
                c.text(156, top + 44, "梯度 " + str(row["tier"]), 18, MUTED, width=210)
            c.text(156, top + 74, "KDA  " + " / ".join(str(value) for value in row["kda"]), 18, MUTED, width=900)
            for x, value, percent in ((480, row["count"], False), (660, row["play_rate"] * 100, True),
                                      (850, row["win_rate"] * 100, True), (1056, row["avg_grade"], False)):
                color = win_rate_color(value, bands) if x == 850 else INK
                c.text(x, top + 18, number(value, percent=percent), 30, color, bold=True,
                       anchor="rt", width=100 if x == 480 else 155)
            c.rule(top + 103)
        if not section["rows"]:
            c.text(64, y + 80, "—", 27, MUTED)
        y += 104 + max(1, len(section["rows"])) * 112
    return c.image


def render_summary(report, font, *, win_rate_bands=(), avatar_bytes=None):
    if report["kind"] == "profile":
        return profile_card(report, font, win_rate_bands)
    renderer = {"heroes": heroes_card, "hero_history": history_heroes_card}.get(report["kind"], statistics_card)
    return renderer(report, font, win_rate_bands, avatar_bytes or {})

"""Clean profile/statistics cards; no template assets, network or file IO."""

from math import cos, sin, pi

from PIL import Image, ImageDraw

from .gen_player_client import win_rate_color

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


def statistics_card(report, font, bands):
    c, values = Card(font, 920), report["values"]
    c.text(64, 62, "对战数据", 24, ACCENT, bold=True)
    c.text(64, 109, report["label"], 42, bold=True, width=730)
    c.text(1056, 124, report["branch_label"], 27, ACCENT, anchor="rt", width=240)
    c.text(64, 170, report["scope"] + "  ·  " + report["mode"], 24, MUTED, width=992)
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
    honors = (("mvp", "全场最佳"), ("losing_mvp", "败方最佳"), ("triple_kills", "三连决胜"),
              ("quadra_kills", "四连超凡"), ("penta_kills", "五连绝世"), ("legendary", "超神"))
    for index, (key, title) in enumerate(honors):
        x = 64 + index % 3 * 338
        y = 750 + index // 3 * 68
        c.text(x, y, title, 20, MUTED)
        c.text(x + 285, y - 3, number(values[key]), 29, bold=True, anchor="rt", width=160)
    return c.image


def render_summary(report, font, *, win_rate_bands=()):
    renderer = profile_card if report["kind"] == "profile" else statistics_card
    return renderer(report, font, win_rate_bands)

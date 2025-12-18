from __future__ import annotations

import os
import math
from dataclasses import dataclass
import io
import urllib.request
from datetime import datetime
from typing import List, Optional, Tuple, Iterable, cast
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps  # type: ignore
except Exception as e:  # pragma: no cover - handled at runtime
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore
    ImageOps = None  # type: ignore


@dataclass
class PlayerInfo:
    # 基础身份信息
    name: str
    level: Optional[int] = None
    rank: Optional[str] = None
    role: Optional[str] = None
    avatar_path: Optional[str] = None
    hero_avatar_url: Optional[str] = None  # 英雄头像 URL/本地路径
    hero_power: Optional[int] = None       # 当前英雄战力
    hero_tag: Optional[str] = None         # 当前英雄标（文本）
    max_hero_tag: Optional[str] = None     # 最大/突出英雄标（用于在头像上方显示）

    # 关键对战指标（与官方数据字段对齐）
    win_rate: Optional[float] = None  # 0~1 或 0~100（heroBehavior.winRate）
    matches: Optional[int] = None     # 若未提供，将回退到 total_cnt/wins+losses
    wins: Optional[int] = None        # heroBehavior.winNum
    losses: Optional[int] = None      # heroBehavior.loseNum
    avg_score: Optional[float] = None # heroBehavior.avgScore（本局评分均值）
    kda: Optional[float] = None       # 若业务侧有 KDA 可填，否则留空
    total_cnt: Optional[int] = None   # mods 401 TotalCnt（总场次）
    mvp_cnt: Optional[int] = None     # mods 408 MVPCnt（总 MVP 场次）
    power: Optional[int] = None       # mods 304 PowerNum（总战斗力）
    peak_score: Optional[int] = None  # mods 702 巅峰分数
    star: Optional[int] = None        # 由段位与星数折算后的总星数
    auth: Optional[bool] = None       # basicInfo.isGameAuth（营地授权）
    side: Optional[str] = None        # 'my' 我方 / 'op' 对方

    # 评分（优先使用 single_level 作为“底蕴/实力评分”）
    single_level: Optional[float] = None
    score: Optional[float] = None

    def normalized_win_rate(self) -> Optional[float]:
        if self.win_rate is None:
            return None
        # 支持传入 0~1 或 0~100
        return self.win_rate if 0 <= self.win_rate <= 1 else max(0.0, min(1.0, self.win_rate / 100.0))

    def derived_matches(self) -> Optional[int]:
        if self.wins is not None and self.losses is not None:
            return int(self.wins) + int(self.losses)
        return None

    def derived_mvp_rate(self) -> Optional[float]:
        if self.mvp_cnt is None:
            return None
        total = self.total_cnt if self.total_cnt is not None else self.derived_matches()
        if not total or total <= 0:
            return None
        return max(0.0, min(1.0, float(self.mvp_cnt) / float(total)))


class CoPlayerProcess:
    """简单的采集器：外部可多次添加玩家，最后调用生成函数绘图。"""

    def __init__(self) -> None:
        self._players: List[PlayerInfo] = []

    def extend(self, players: Iterable[PlayerInfo]) -> None:
        for p in players:
            if isinstance(p, PlayerInfo):
                self._players.append(p)
            else:
                # 尝试从 dict 构造
                self._players.append(PlayerInfo(**p))  # type: ignore[arg-type]

    # 与 ori.py 字段保持一致的添加接口（命名、类型尽量对齐）
    def add_player(
        self,
        *,
        nickname: str,
        is_auth: bool,
        is_my_side: bool,
        winNum: int,
        loseNum: int,
        avgScore: float,
        winRate,  # 可为 0~1/0~100 的 float，或形如 "58.2%" 的字符串
        avatarUrl: Optional[str] = None,
        HeroAvatar: Optional[str] = None,
        HeroPower: Optional[int] = None,
        HeroTag: Optional[str] = None,
        MaxHeroTag: Optional[str] = None,
        starNum: Optional[int] = None,
        peakScore: Optional[int] = None,
        PowerNum: Optional[int] = None,
        TotalCnt: Optional[int] = None,
        MVPCnt: Optional[int] = None,
        rankName: Optional[str] = None,
        rankStar: Optional[int] = None,  # 仅用于业务侧计算 starNum，这里不再重复计算
        single_level: Optional[float] = None,
    ) -> None:
        # 规范化胜率
        norm_wr: Optional[float]
        if isinstance(winRate, str):
            s = winRate.strip().replace('%', '')
            try:
                val = float(s)
                norm_wr = val / 100.0
            except Exception:
                norm_wr = None
        else:
            try:
                val = float(winRate)
                norm_wr = val if 0 <= val <= 1 else max(0.0, min(1.0, val / 100.0))
            except Exception:
                norm_wr = None

        # 衍生场次：优先使用 TotalCnt，否则用 win+lose
        derived_total = TotalCnt if TotalCnt is not None else (int(winNum) + int(loseNum))

        self._players.append(
            PlayerInfo(
                name=nickname,
                rank=rankName,
                win_rate=norm_wr,
                matches=derived_total,  # 作为总场次使用
                wins=int(winNum),
                losses=int(loseNum),
                avg_score=float(avgScore),
                total_cnt=TotalCnt,
                mvp_cnt=MVPCnt,
                power=PowerNum,
                peak_score=peakScore,
                star=rankStar,
                auth=bool(is_auth),
                single_level=single_level,
                avatar_path=avatarUrl,
                hero_avatar_url=HeroAvatar,
                hero_power=HeroPower,
                hero_tag=HeroTag,
                max_hero_tag=MaxHeroTag,
                side='my' if is_my_side else 'op',
            )
        )

    def clear(self) -> None:
        self._players.clear()

    def players(self) -> List[PlayerInfo]:
        return list(self._players)

    # 便捷实例方法：基于当前实例内的玩家列表直接生成图片
    def gen(self, output_path: str, *, title: str = "COMPARISON") -> Tuple[str, bool]:
        return generate_player_strength_image(output_path, players=self.players(), title=title)


# 提供一个默认的全局收集器，满足“我会在 coplayer_process 中创建并多次加入玩家信息”的使用习惯
coplayer_process = CoPlayerProcess()


# 主题配色
BG = (245, 247, 250)
PANEL = (255, 255, 255)
TEXT_PRIMARY = (34, 34, 34)
TEXT_SECONDARY = (102, 115, 132)
ACCENT = (88, 101, 242)  # 蓝紫
ACCENT_GREEN = (0, 163, 108)
ACCENT_RED = (235, 87, 87)
BORDER = (229, 234, 242)
MUTED = (210, 215, 223)


def _ensure_pillow():
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("需要安装 pillow 库：pip install pillow")


def _try_load_font(size: int, bold: bool = False):
    """尽量加载系统中文/西文字体，失败则回退默认字体。"""
    _ensure_pillow()
    assert ImageFont is not None
    candidates = [
        '/usr/share/fonts/chinese/simhei.ttf'
    ]

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # 回退
    return ImageFont.load_default()


def _blend_with_white(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    """将颜色与白色按比例混合，factor 取值 0..1，越大越接近原色（更浓）。"""
    factor = max(0.0, min(1.0, factor))
    r, g, b = color
    return (
        int(255 - (255 - r) * factor),
        int(255 - (255 - g) * factor),
        int(255 - (255 - b) * factor),
    )


def _rounded_rectangle(draw, xy, radius: int, fill=None, outline=None, width: int = 1):
    # Pillow 新版支持 rounded_rectangle；若旧版则退化为普通 rectangle
    if hasattr(draw, "rounded_rectangle"):
        try:
            draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
            return
        except Exception:
            pass
    draw.rectangle(xy, fill=fill, outline=outline, width=width)


def _circle_crop(im, diameter: int):
    _ensure_pillow()
    assert Image is not None and ImageOps is not None and ImageDraw is not None
    im = im.convert("RGBA")
    im = ImageOps.fit(im, (diameter, diameter), method=Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, diameter, diameter), fill=255)
    im.putalpha(mask)
    return im


def _load_avatar_to_circle(src: Optional[str], diameter: int):
    """从本地路径或 URL 加载头像并裁剪为圆形，失败则返回 None。"""
    if not src:
        return None
    _ensure_pillow()
    assert Image is not None
    try:
        if src.startswith("http://") or src.startswith("https://"):
            with urllib.request.urlopen(src, timeout=3) as resp:
                data = resp.read()
            with Image.open(io.BytesIO(data)) as im:
                return _circle_crop(im, diameter)
        # 本地文件
        if os.path.exists(src):
            with Image.open(src) as im:
                return _circle_crop(im, diameter)
    except Exception:
        return None
    return None


def _batch_load_avatars(sources: List[Tuple[int, Optional[str]]], diameter: int) -> dict:
    """并行批量加载头像，返回 {index: image} 字典。
    
    Args:
        sources: [(index, url_or_path), ...] 列表
        diameter: 圆形头像直径
    
    Returns:
        {index: PIL.Image} 字典，加载失败的条目不包含在结果中
    """
    results = {}
    
    def load_single(idx, src):
        img = _load_avatar_to_circle(src, diameter)
        if img is not None:
            return (idx, img)
        return None
    
    # 过滤掉空源
    valid_sources = [(idx, src) for idx, src in sources if src]
    
    if not valid_sources:
        return results
    
    # 使用线程池并行加载
    with ThreadPoolExecutor(max_workers=min(10, len(valid_sources))) as executor:
        futures = {executor.submit(load_single, idx, src): (idx, src) for idx, src in valid_sources}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    idx, img = result
                    results[idx] = img
            except Exception:
                pass
    
    return results


def _load_hero_icon(url_or_path: Optional[str], size: Tuple[int, int]):
    """加载英雄头像图标，优先按自定义本地路径规则读取；失败则按常规 URL/本地读取。
    返回 RGBA 图像或 None。
    """
    if not url_or_path:
        return None
    _ensure_pillow()
    assert Image is not None
    try:
        # 优先按自定义本地规则
        url = url_or_path
        if 'custom_wzry_E1' in url:
            img_id = url.split('/')[-1].split('.')[0]
            local_path = f"wzry_images/custom_wzry_E1/{img_id}.jpg"
            if os.path.exists(local_path):
                with Image.open(local_path) as im2:
                    im2 = im2.convert('RGBA')
                    im2 = im2.resize(size, Image.LANCZOS)
                    return im2
        # 其次尝试本地原路径
        if os.path.exists(url_or_path):
            with Image.open(url_or_path) as im2:
                im2 = im2.convert('RGBA')
                im2 = im2.resize(size, Image.LANCZOS)
                return im2
        # 再尝试网络 URL
        if url_or_path.startswith('http://') or url_or_path.startswith('https://'):
            with urllib.request.urlopen(url_or_path, timeout=3) as resp:
                data = resp.read()
            with Image.open(io.BytesIO(data)) as im2:
                im2 = im2.convert('RGBA')
                im2 = im2.resize(size, Image.LANCZOS)
                return im2
    except Exception:
        return None
    return None


def _batch_load_hero_icons(sources: List[Tuple[int, Optional[str]]], size: Tuple[int, int]) -> dict:
    """并行批量加载英雄头像，返回 {index: image} 字典。
    
    Args:
        sources: [(index, url_or_path), ...] 列表
        size: 图标尺寸 (width, height)
    
    Returns:
        {index: PIL.Image} 字典，加载失败的条目不包含在结果中
    """
    results = {}
    
    def load_single(idx, src):
        img = _load_hero_icon(src, size)
        if img is not None:
            return (idx, img)
        return None
    
    # 过滤掉空源
    valid_sources = [(idx, src) for idx, src in sources if src]
    
    if not valid_sources:
        return results
    
    # 使用线程池并行加载
    with ThreadPoolExecutor(max_workers=min(10, len(valid_sources))) as executor:
        futures = {executor.submit(load_single, idx, src): (idx, src) for idx, src in valid_sources}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    idx, img = result
                    results[idx] = img
            except Exception:
                pass
    
    return results


def _rounded_rect_crop_rgba(im, size: Tuple[int, int], radius: int):
    """将 RGBA 图像裁剪为指定尺寸的圆角矩形。"""
    _ensure_pillow()
    assert Image is not None and ImageDraw is not None and ImageOps is not None
    im = im.convert('RGBA')
    im = ImageOps.fit(im, size, method=Image.LANCZOS)
    mask = Image.new('L', size, 0)
    md = ImageDraw.Draw(mask)
    if hasattr(md, 'rounded_rectangle'):
        md.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    else:
        md.rectangle((0, 0, size[0], size[1]), fill=255)
    im.putalpha(mask)
    return im


def _calc_display_score(p: PlayerInfo) -> int:
    # 优先使用 single_level（来自你在业务侧计算的“底蕴”）
    if p.single_level is not None:
        try:
            return int(round(float(p.single_level)))
        except Exception:
            pass
    # 其次使用外部传入的 score
    if p.score is not None:
        try:
            return int(round(float(p.score)))
        except Exception:
            pass
    win = cast(float, p.normalized_win_rate() if p.normalized_win_rate() is not None else 0.5)
    matches = cast(int, p.derived_matches() or 0)
    kda = cast(float, p.kda or 1.0)
    # 简单经验公式：胜率为主，场次开根号，KDA 加权
    base = 100.0 * float(win) + 5.0 * math.sqrt(max(0, int(matches))) + 20.0 * math.log(max(1.0, float(kda)), 2)
    return int(round(base))


def _format_percent(x: Optional[float]) -> str:
    if x is None:
        return "-"
    val = x if 0 <= x <= 1 else x / 100.0
    return f"{val*100:.1f}%"


def _safe_text(draw, xy, text: str, font, fill):
    try:
        draw.text(xy, text, font=font, fill=fill)
    except Exception:
        # 某些字体/字符渲染异常时，进行替代
        draw.text(xy, text.encode("utf-8", "ignore").decode("utf-8"), font=font, fill=fill)


def generate_player_strength_image(
    output_path: str,
    players: Optional[List[PlayerInfo]] = None,
    *,
    title: str = "Comparison",
) -> Tuple[str, bool]:
    """
    生成玩家实力信息图片。

    参数：
      - output_path: 输出图片路径（会自动创建父目录）
      - players: 可选，若为空则使用全局 coplayer_process 中的玩家列表
      - title: 图片标题

    返回：(输出路径, 是否生成成功)
    """
    _ensure_pillow()

    data = players if players is not None else coplayer_process.players()
    my_list = [p for p in data if p.side == 'my']
    op_list = [p for p in data if p.side == 'op']
    other_list = [p for p in data if p.side not in ('my', 'op')]

    # 画布尺寸根据玩家数量自适应（分组：我方/对方）
    width = 1600
    margin = 48
    header_h = 128
    footer_h = 28
    section_title_h = 48
    card_h = 260  # 提高单卡高度，给信息与条形更多空间
    gap = 20
    right_col_w = 300  # 右侧指标列宽，用于预留空间

    # 列布局（左右并排）
    content_w = width - 2 * margin
    col_gap = 32
    use_two_cols = (len(my_list) > 0 or len(op_list) > 0)
    if use_two_cols:
        col_w = (content_w - col_gap) // 2
        left_col_x = margin
        right_col_x = margin + col_w + col_gap
        rows = max(len(my_list), len(op_list))
    else:
        # 兼容无 side 的场景：单列
        col_w = content_w
        left_col_x = margin
        right_col_x = margin + col_w + col_gap  # 不使用，仅为静态检查避免 None
        rows = len(other_list)

    inner_h = header_h + section_title_h + (rows * (card_h + gap) - (gap if rows > 0 else 0)) + footer_h + margin
    height = inner_h + margin

    # 背景
    assert Image is not None and ImageDraw is not None
    im = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(im)

    # 主面板
    panel_xy = (margin, margin, width - margin, height - margin)
    _rounded_rectangle(draw, panel_xy, radius=24, fill=PANEL, outline=BORDER, width=2)

    # 标题区
    title_font = _try_load_font(44, bold=True)
    sub_font = _try_load_font(22)
    _safe_text(draw, (margin + 32, margin + 28), title, title_font, TEXT_PRIMARY)

    # 顶部右侧徽标/点缀
    dot_x = width - margin - 32
    dot_y = margin + 32
    draw.ellipse((dot_x - 8, dot_y - 8, dot_x + 8, dot_y + 8), fill=ACCENT)

    # 无数据占位
    if len(data) == 0:
        empty_font = _try_load_font(28)
        _safe_text(
            draw,
            (margin + 32, margin + header_h + 16),
            "暂无玩家数据，可通过 coplayer_process.add_player(...) 添加",
            empty_font,
            TEXT_SECONDARY,
        )
    else:
        # 统计最大分/平均分/最大偏差/最大场次，用于着色与对比
        scores = [_calc_display_score(p) for p in data]
        max_score = max(scores) if scores else 1
        max_score = max(max_score, 1)
        totals = [p.derived_matches() or 0 for p in data]
        max_total_matches = max(totals) if totals else 1
        if max_total_matches <= 0:
            max_total_matches = 1
        avg_score_all = (sum(scores) / len(scores)) if scores else 0.0
        max_abs_dev = max((abs(s - avg_score_all) for s in scores), default=1.0)
        if max_abs_dev <= 0:
            max_abs_dev = 1.0
        # single_level 最大值用于归一化百分比条
        sl_vals = [float(p.single_level) for p in data if p.single_level is not None]
        max_single_level = max(sl_vals) if sl_vals else 0.0
        # 英雄战力最大值用于归一化右侧“英雄战力”竖条
        hp_vals = [int(p.hero_power) for p in data if (hasattr(p, 'hero_power') and p.hero_power is not None)]
        max_hero_power = max(hp_vals) if hp_vals else 0
        if max_hero_power <= 0:
            max_hero_power = 1

        # 列标题
        title_font2 = _try_load_font(26, bold=True)
        base_y = margin + header_h
        if use_two_cols:
            _safe_text(draw, (left_col_x + 28, base_y + 8), "我方", title_font2, ACCENT)
            _safe_text(draw, (right_col_x + 28, base_y + 8), "对方", title_font2, ACCENT_RED)
        else:
            _safe_text(draw, (left_col_x + 28, base_y + 8), "玩家", title_font2, ACCENT)

        start_y = base_y + section_title_h

        # 简单按宽度换行
        def _wrap_text_local(text: str, font, max_width: int) -> List[str]:
            if not text:
                return []
            lines: List[str] = []
            cur = ""
            for ch in text:
                test = cur + ch
                bbox = draw.textbbox((0, 0), test, font=font)
                w = bbox[2] - bbox[0]
                if w <= max_width:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = ch
            if cur:
                lines.append(cur)
            return lines

        def render_column(col_x: int, players_list: List[PlayerInfo]):
            # 预加载所有头像和英雄图标（并行）
            avatar_d = 88
            small_d = 28
            
            # 收集所有需要加载的资源
            hero_sources = [(idx, p.hero_avatar_url) for idx, p in enumerate(players_list)]
            avatar_sources = [(idx, p.avatar_path if p.auth is not False else None) for idx, p in enumerate(players_list)]
            
            # 并行加载
            hero_images = _batch_load_hero_icons(hero_sources, (avatar_d, avatar_d))
            avatar_images = _batch_load_avatars(avatar_sources, small_d)
            
            for idx, p in enumerate(players_list):
                card_top = start_y + idx * (card_h + gap)
                card_left = col_x + 24
                card_right = col_x + col_w - 24
                card_xy = (card_left, card_top, card_right, card_top + card_h)

                # 计算评分与卡片背景着色（降低色彩强度，更加简洁）
                # 未授权检查
                unauthorized = (p.auth is False)
                
                if unauthorized:
                    # 未授权：使用灰色背景
                    fill_color = (240, 243, 248)
                else:
                    # 授权：根据评分着色
                    score = _calc_display_score(p)
                    dev = score - avg_score_all
                    t = abs(dev) / max_abs_dev
                    tint_factor = 0.08 + 0.16 * t  # 0.08..0.24 更克制
                    base_color = ACCENT_GREEN if dev >= 0 else ACCENT_RED
                    fill_color = _blend_with_white(base_color, tint_factor)
                
                _rounded_rectangle(draw, card_xy, radius=18, fill=fill_color, outline=BORDER, width=1)
                # 未授权：右上角三角角标（无文字）
                if unauthorized:
                    rx = card_xy[2]
                    ty = card_xy[1]
                    sz = 32
                    draw.polygon([(rx, ty), (rx - sz, ty), (rx, ty + sz)], fill=ACCENT_RED)

                # 左侧主图：英雄头像（圆角方形），占据原头像位置
                avatar_x = card_xy[0] + 24
                # 略微上移左侧元素（头像与文本整体）
                avatar_y = card_top + (card_h - avatar_d) // 2 - 8
                hero_raw = hero_images.get(idx)
                if hero_raw is not None:
                    hero_round = _rounded_rect_crop_rgba(hero_raw, (avatar_d, avatar_d), radius=14)
                    im.paste(hero_round, (avatar_x, avatar_y), mask=hero_round)
                else:
                    # 占位：浅灰圆角矩形
                    _rounded_rectangle(draw, (avatar_x, avatar_y, avatar_x + avatar_d, avatar_y + avatar_d), radius=14, fill=(238, 241, 248))
                    # 放一个英雄字样首字母占位
                    _safe_text(draw, (avatar_x + 28, avatar_y + 30), "H", _try_load_font(28, True), ACCENT)

                # 最大英雄标（显示在英雄头像上方，从卡片顶部开始）
                if getattr(p, 'max_hero_tag', None):
                    top_font = _try_load_font(18)
                    max_tag_width = card_right - avatar_x
                    max_tag_lines = _wrap_text_local(str(p.max_hero_tag), top_font, max_tag_width)
                    # 从卡片顶部 + 8px 开始放置，每行 20px
                    line_h_top = 20
                    avail_top_h = avatar_y - (card_top + 8)
                    max_top_lines = max(0, min(len(max_tag_lines), avail_top_h // line_h_top))
                    if max_top_lines > 0:
                        lines_to_draw = max_tag_lines[:max_top_lines]
                        for i, t in enumerate(lines_to_draw):
                            # 从卡片顶部 8px 处逐行向下放置
                            ty = card_top + 12 + i * line_h_top
                            tx = avatar_x
                            _safe_text(draw, (tx, ty), t, top_font, TEXT_SECONDARY)

                # 英雄标（位于英雄头像正下方，自动换行）
                small_font = _try_load_font(18)
                if getattr(p, 'hero_tag', None):
                    tag_lines = _wrap_text_local(str(p.hero_tag), small_font, avatar_d)
                    tag_y0 = avatar_y + avatar_d + 6
                    line_h = 20
                    # 计算可绘制行数，避免越过卡片底部
                    avail_h = (card_top + card_h) - tag_y0 - 8
                    max_lines = max(0, min(len(tag_lines), avail_h // line_h))
                    for i in range(max_lines):
                        t = tag_lines[i]
                        tb = draw.textbbox((0, 0), t, font=small_font)
                        tw = tb[2] - tb[0]
                        tx = avatar_x + (avatar_d - tw) // 2
                        ty = tag_y0 + i * line_h
                        _safe_text(draw, (tx, ty), t, small_font, TEXT_SECONDARY)

                # 文本信息
                name_font = _try_load_font(30, bold=True)
                small_font = _try_load_font(18)
                text_x = avatar_x + avatar_d + 20
                text_y = avatar_y
                # 在名字左侧放置小的玩家头像（圆形）；未授权不显示该玩家头像
                small_av = None if unauthorized else avatar_images.get(idx)
                name_x = text_x
                if small_av is not None:
                    small_y = text_y + max(0, (30 - small_d) // 2)
                    im.paste(small_av, (text_x, small_y), mask=small_av)
                    name_x = text_x + small_d + 8
                else:
                    # 未授权则不显示且不保留占位；授权但加载失败时可给占位
                    if not unauthorized:
                        small_y = text_y + max(0, (30 - small_d) // 2)
                        draw.ellipse((text_x, small_y, text_x + small_d, small_y + small_d), fill=(238, 241, 248))
                        name_x = text_x + small_d + 8
                _safe_text(draw, (name_x, text_y), p.name, name_font, TEXT_PRIMARY)

                # 信息两行：
                # 行1：段位 · 星级 · Lv
                # 行2：巅峰 · 战力
                line1 = []
                # 未授权则不显示段位与星级，但仍可显示 Lv
                if not unauthorized and p.rank:
                    line1.append(str(p.rank))
                if not unauthorized and p.star is not None:
                    line1.append(f"{p.star}星")
                if p.level is not None:
                    line1.append(f"Lv.{p.level}")
                chip_y = text_y + 40
                if line1:
                    _safe_text(draw, (text_x, chip_y), " · ".join(line1), small_font, TEXT_SECONDARY)

                # 行2：巅峰（未授权隐藏）
                if (p.peak_score is not None) and not unauthorized:
                    _safe_text(draw, (text_x, chip_y + 28), f"巅峰 {p.peak_score}", small_font, TEXT_SECONDARY)
                # 行3：战斗力（紧跟巅峰之下）
                if (p.power is not None) and not unauthorized:
                    _safe_text(draw, (text_x, chip_y + 56), f"战斗力 {p.power}", small_font, TEXT_SECONDARY)

                # single_level 百分比条（位于战力行之下）- 未授权则不渲染
                if p.single_level is not None and max_single_level > 0 and not unauthorized:
                    bar_left = text_x
                    # 预留到右侧竖条区域的左边缘
                    right_x_end = card_xy[2] - 24
                    v_area_left = right_x_end - right_col_w
                    bar_right = v_area_left - 16
                    # 再向下移动，使条形更靠近卡片底部
                    bar_top = chip_y + 56 + 44
                    bar_h = 10
                    bar_w = max(40, bar_right - bar_left)
                    # 背景轨道
                    _rounded_rectangle(draw, (bar_left, bar_top, bar_left + bar_w, bar_top + bar_h), radius=5, fill=(240, 243, 248))
                    ratio_sl = max(0.0, min(1.0, float(p.single_level) / max_single_level))
                    fill_w = int(bar_w * ratio_sl)
                    if fill_w > 0:
                        _rounded_rectangle(draw, (bar_left, bar_top, bar_left + fill_w, bar_top + bar_h), radius=5, fill=ACCENT)
                    # 顶部固定位置显示百分比数值（不随填充高度变化）
                    pct_txt = f"{ratio_sl*100:.0f}%"
                    pct_bbox = draw.textbbox((0, 0), pct_txt, font=small_font)
                    _safe_text(draw, (bar_left + bar_w - (pct_bbox[2]-pct_bbox[0]), bar_top - 18), pct_txt, small_font, TEXT_PRIMARY)
                    # 左侧标签（可选）
                    lbl = "历史实力"
                    _safe_text(draw, (bar_left, bar_top - 18), lbl, small_font, TEXT_SECONDARY)

                # 右侧竖状条（胜率 / 场次 / MVP率）- 未授权则不渲染
                if not unauthorized:
                    right_x_end = card_xy[2] - 24
                    total_matches = p.derived_matches() or 0
                    mvp_rate = p.derived_mvp_rate() or 0.0
                    wr = p.normalized_win_rate() or 0.0

                    v_area_left = right_x_end - right_col_w
                    v_top = card_top + 26
                    v_bottom = card_top + card_h - 44
                    v_h = max(40, v_bottom - v_top)
                    bar_w_v = 22  # 加宽竖条以匹配更高的卡片
                    gap_v = 40  # 增大条形间距
                    tot_w = 3 * bar_w_v + 2 * gap_v
                    start_x = v_area_left + (right_col_w - tot_w) // 2

                    # 英雄战力条替换原"英雄胜率"位置；显示值为原始战力，条高按本图最大战力归一
                    hero_pow_val = p.hero_power if p.hero_power is not None else 0
                    hero_pow_ratio = min(1.0, max(0.0, float(hero_pow_val) / float(max_hero_power)))
                    items = [
                        ("英雄\n战力", hero_pow_ratio, ACCENT, str(hero_pow_val if hero_pow_val > 0 else "-")),
                        ("英雄\n场次", min(1.0, max(0.0, total_matches / max_total_matches)), ACCENT, str(total_matches)),
                        ("总MVP率", mvp_rate, (255, 158, 27), _format_percent(mvp_rate)),
                    ]
                    for i, (lab, ratio, color, txt) in enumerate(items):
                        x0 = start_x + i * (bar_w_v + gap_v)
                        _rounded_rectangle(draw, (x0, v_top, x0 + bar_w_v, v_top + v_h), radius=9, fill=(240, 243, 248))
                        h = int(v_h * ratio)
                        y_fill = v_top + v_h - h
                        _rounded_rectangle(draw, (x0, y_fill, x0 + bar_w_v, v_top + v_h), radius=9, fill=color)
                        lab_bbox = draw.textbbox((0, 0), lab, font=small_font)
                        _safe_text(draw, (x0 + (bar_w_v - (lab_bbox[2]-lab_bbox[0]))//2, v_top + v_h + 4), lab, small_font, TEXT_SECONDARY)
                        val_bbox = draw.textbbox((0, 0), txt, font=small_font)
                        # 数值固定在条形最上方（轨道顶部上方），而非有色填充顶部
                        vy = v_top - (val_bbox[3] - val_bbox[1]) - 4
                        _safe_text(draw, (x0 + (bar_w_v - (val_bbox[2]-val_bbox[0]))//2, vy), txt, small_font, TEXT_PRIMARY)

                # 去除卡片右下角的战力信息（已在姓名下方展示）

        # 渲染列
        if use_two_cols:
            render_column(left_col_x, my_list)
            render_column(right_col_x, op_list)
        else:
            render_column(left_col_x, other_list)
    # 页脚（底部居中）
    foot = "Data from 笙煎守味🤖"
    foot_bbox = draw.textbbox((0, 0), foot, font=sub_font)
    foot_w = foot_bbox[2] - foot_bbox[0]
    _safe_text(
        draw,
        (((width - foot_w) // 2), height - margin - 28),
        foot,
        sub_font,
        TEXT_SECONDARY,
    )

    # 输出
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        im.save(output_path, format="PNG")
        return output_path, True
    except Exception:
        return output_path, False


__all__ = [
    "PlayerInfo",
    "CoPlayerProcess",
    "coplayer_process",
    "generate_player_strength_image",
]

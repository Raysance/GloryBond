#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
战局详情UI图片生成器
根据JSON数据生成与b.html相同的UI界面图片
"""

import json
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import os
from datetime import datetime
import math
from ..zstatic import *
class BattleUIGenerator:
    def __init__(self):
        """初始化UI生成器"""
        self.width = 1200
        self.height = 1600
        self.padding = 30
        self.card_height = 80
        self.player_card_height = 75
        
        # 颜色定义
        self.colors = {
            'primary': '#6c9bd1',
            'secondary': '#4fc3f7', 
            'dark': '#2c3e50',
            'light': '#f8f9fa',
            'success': '#28a745',
            'danger': '#dc3545',
            'accent': '#6c757d',
            'white': '#ffffff',
            'red_team': '#e74c3c',
            'blue_team': '#3498db',
            'victory_bg': 'rgba(39, 174, 96, 0.15)',
            'defeat_bg': 'rgba(231, 76, 60, 0.15)',
            'mvp_gold': '#f39c12',
            'me_bg': '#fffefa',      # 极淡的暖色底
            'me_accent': '#ff9800',  # 琥珀橙（侧边标识条）
            'internal_bg': '#f7fcff',# 极淡的青色底
            'internal_accent': '#03a9f4' # 淡蓝色（侧边标识条）
        }
        
        # 尝试加载字体
        self.fonts = self._load_fonts()
        
    def _load_fonts(self):
        """加载字体"""
        fonts = {}
        
        # 支持emoji的字体路径
        emoji_font_paths = [
            # '/usr/share/fonts/DejaVuSans.ttf',
            # '/usr/share/fonts/NotoColorEmoji.ttf'
        ]
        
        # 普通字体路径
        font_paths = [
            '/usr/share/fonts/chinese/simhei.ttf'
        ]
        
        # 尝试加载不同大小的字体
        sizes = {
            'title': 28,
            'large': 20,
            'medium': 16,
            'small': 14,
            'tiny': 12,
            'micro': 10,
            'emoji': 16
        }
        
        # 定义需要粗体的大小
        bold_variants = ['large', 'medium', 'title']
        
        # 粗体字体候选路径 (回归simhei通过调大字体来模拟加粗)
        bold_font_paths = [
            '/usr/share/fonts/chinese/simhei.ttf',
        ]
        
        # 首先尝试加载emoji字体
        emoji_font_loaded = False
        for emoji_font_path in emoji_font_paths:
            try:
                if os.path.exists(emoji_font_path):
                    fonts['emoji'] = ImageFont.truetype(emoji_font_path, sizes['emoji'])
                    emoji_font_loaded = True
                    break
            except Exception as e:
                continue
        
        if not emoji_font_loaded:
            fonts['emoji'] = None
        
        # 加载普通字体和粗体变体
        for size_name, size in sizes.items():
            if size_name == 'emoji':
                continue
                
            font_loaded = False
            for font_path in font_paths + ['C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/arial.ttf']:
                try:
                    if os.path.exists(font_path):
                        fonts[size_name] = ImageFont.truetype(font_path, size)
                        # 如果需要粗体变体
                        if size_name in bold_variants:
                            bold_loaded = False
                            for b_path in bold_font_paths:
                                if os.path.exists(b_path):
                                    # 针对黑体，字号加2以更清晰地区分普通文本
                                    fonts[f"{size_name}_bold"] = ImageFont.truetype(b_path, size + 2)
                                    bold_loaded = True
                                    break
                            if not bold_loaded:
                                fonts[f"{size_name}_bold"] = fonts[size_name] # 降级为普通字体
                        font_loaded = True
                        break
                except Exception as e:
                    continue
            
            if not font_loaded:
                try:
                    fonts[size_name] = ImageFont.load_default()
                    if size_name in bold_variants:
                        fonts[f"{size_name}_bold"] = fonts[size_name]
                except:
                    pass
        
        return fonts
    
    def _draw_text_with_emoji(self, draw, position, text, fill, font, emoji_replacements=None):
        """
        绘制包含emoji的文本
        如果没有emoji字体，则使用文本替代
        """
        x, y = position
        
        # 默认的emoji替代文本
        default_replacements = {
            '💰': '经济',
            '⚔️': '伤害', 
            '🛡️': '承伤',
            '🏆': '胜利',
            '⭐': '星',
            # '👆': '[点]',
            # '💬': '[聊]',
            # '👁️': '[眼]',
            # '🔒': '[锁]'
        }
        
        if emoji_replacements:
            default_replacements.update(emoji_replacements)
        
        # 如果有emoji字体，尝试直接渲染
        if self.fonts.get('emoji'):
            try:
                draw.text(position, text, fill=fill, font=self.fonts['emoji'])
                return
            except Exception as e:
                print(f"Emoji字体渲染失败: {e}")
        
        # 如果没有emoji字体或渲染失败，使用替代文本
        processed_text = text
        for emoji, replacement in default_replacements.items():
            processed_text = processed_text.replace(emoji, replacement)
        
        draw.text(position, processed_text, fill=fill, font=font)
    
    def _hex_to_rgb(self, hex_color):
        """将十六进制颜色转换为RGB"""
        if hex_color.startswith('#'):
            hex_color = hex_color[1:]
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def _download_image(self, url, size=(50, 50)):
        """下载并调整图片大小"""
        try:
            if not url or url == '/api/placeholder/40/40' or url == '/api/placeholder/60/60':
                # 创建占位符图片
                img = Image.new('RGBA', size, (200, 200, 200, 255))
                draw = ImageDraw.Draw(img)
                draw.text((size[0]//2, size[1]//2), '?', fill=(100, 100, 100, 255), 
                        font=self.fonts['medium'], anchor='mm')
                return img
            
            # 从URL中提取图片序号
            if 'custom_wzryequip' in url:
                # 从类似 https://.../custom_wzryequip/1240.png 中提取1240
                img_id = url.split('/')[-1].split('.')[0]
                local_path = f"wzry_images/custom_wzryequip/{img_id}.png"
                
                # 检查本地是否存在
                if os.path.exists(local_path):
                    img = Image.open(local_path)
                    img = img.convert('RGBA')
                    img = img.resize(size, Image.Resampling.LANCZOS)
                    return img
            if 'custom_wzry_E1' in url:
                img_id = url.split('/')[-1].split('.')[0]
                local_path = f"wzry_images/custom_wzry_E1/{img_id}.jpg"
                
                # 检查本地是否存在
                if os.path.exists(local_path):
                    img = Image.open(local_path)
                    img = img.convert('RGBA')
                    img = img.resize(size, Image.Resampling.LANCZOS)
                    return img
            
            # 本地不存在，进行网络请求
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            if 'custom_wzryequip' in url:
                with open(local_path, 'wb') as f:
                    f.write(response.content)
            if 'custom_wzry_E1' in url:
                with open(local_path, 'wb') as f:
                    f.write(response.content)
            img = Image.open(BytesIO(response.content))
            img = img.convert('RGBA')
            img = img.resize(size, Image.Resampling.LANCZOS)
            return img
            
        except Exception as e:
            print(f"下载图片失败 {url}: {e}")
            # 返回占位符
            img = Image.new('RGBA', size, (200, 200, 200, 255))
            draw = ImageDraw.Draw(img)
            draw.text((size[0]//2, size[1]//2), '?', fill=(100, 100, 100, 255), 
                    font=self.fonts['medium'], anchor='mm')
            return img
    
    def _draw_rounded_rectangle(self, draw, bbox, radius, fill=None, outline=None, width=1):
        """绘制圆角矩形"""
        x1, y1, x2, y2 = bbox
        
        # 绘制矩形主体
        if fill:
            draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
            draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
            
            # 绘制四个角的圆形
            draw.pieslice([x1, y1, x1 + 2*radius, y1 + 2*radius], 180, 270, fill=fill)
            draw.pieslice([x2 - 2*radius, y1, x2, y1 + 2*radius], 270, 360, fill=fill)
            draw.pieslice([x1, y2 - 2*radius, x1 + 2*radius, y2], 90, 180, fill=fill)
            draw.pieslice([x2 - 2*radius, y2 - 2*radius, x2, y2], 0, 90, fill=fill)
        
        if outline:
            # 绘制边框
            draw.line([x1 + radius, y1, x2 - radius, y1], fill=outline, width=width)
            draw.line([x1 + radius, y2, x2 - radius, y2], fill=outline, width=width)
            draw.line([x1, y1 + radius, x1, y2 - radius], fill=outline, width=width)
            draw.line([x2, y1 + radius, x2, y2 - radius], fill=outline, width=width)
            
            # 绘制圆角边框
            draw.arc([x1, y1, x1 + 2*radius, y1 + 2*radius], 180, 270, fill=outline, width=width)
            draw.arc([x2 - 2*radius, y1, x2, y1 + 2*radius], 270, 360, fill=outline, width=width)
            draw.arc([x1, y2 - 2*radius, x1 + 2*radius, y2], 90, 180, fill=outline, width=width)
            draw.arc([x2 - 2*radius, y2 - 2*radius, x2, y2], 0, 90, fill=outline, width=width)
    
    def _format_time(self, seconds):
        """格式化时间"""
        if not seconds:
            return "0:00"
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
    
    def _draw_player_header(self, draw, img, data, y_offset):
        """绘制玩家头部信息区域"""
        head = data.get('head', {})
        battle = data.get('battle', {})
        
        # 找到当前玩家信息
        current_player = self._find_current_player(data, head.get('roleId'))
        if not current_player:
            return y_offset + 200
            
        basic_info = current_player.get('basicInfo', {})
        battle_stats = current_player.get('battleStats', {})
        battle_records = current_player.get('battleRecords', {})
        used_hero = battle_records.get('usedHero', {})
        final_equips = battle_records.get('finalEquips', [])
        
        # 判断胜负
        game_result = head.get('gameResult', False)
        result_text = '胜利' if game_result else '失败'
        result_color = self._hex_to_rgb(self.colors['success']) if game_result else self._hex_to_rgb(self.colors['danger'])
        
        # 设置背景色
        if game_result:
            bg_color = (39, 174, 96, 40)  # 胜利背景色，透明度
        else:
            bg_color = (231, 76, 60, 40)  # 失败背景色，透明度
        
        # 绘制背景卡片
        card_height = 220
        self._draw_rounded_rectangle(draw, 
                                   [self.padding, y_offset, self.width - self.padding, y_offset + card_height],
                                   15, fill=(255, 255, 255, 255))
        
        # 绘制装饰性背景渐变（简化版）
        overlay = Image.new('RGBA', (self.width - 2*self.padding, card_height), bg_color)
        img.paste(overlay, (self.padding, y_offset), overlay)
        
        # 地图名称和结果
        draw.text((self.padding + 20, y_offset + 20), 
                 battle.get('mapName', '王者荣耀战局详情'), 
                 fill=(150, 150, 150, 255), font=self.fonts['small'])
        
        draw.text((self.padding + 200, y_offset + 20), 
                 result_text, 
                 fill=result_color, font=self.fonts['medium'])
        
        # 时间信息（右上角）
        time_info = [
            f"时长: {self._format_time(battle.get('usedTime', 0))}",
            f"开始: {battle.get('startTime', '')}",
            f"结束: {battle.get('dtEventTime', '')}"
        ]
        time_x = self.width - self.padding - 200
        for i, time_text in enumerate(time_info):
            draw.text((time_x, y_offset + 20 + i * 15), 
                     time_text, 
                     fill=(150, 150, 150, 255), font=self.fonts['tiny'])
        
        # 英雄头像
        hero_icon_url = used_hero.get('heroIcon', '')
        hero_img = self._download_image(hero_icon_url, (80, 80))
        
        # 创建圆形遮罩
        mask = Image.new('L', (80, 80), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, 80, 80], fill=255)
        
        # 应用遮罩
        hero_img.putalpha(mask)
        img.paste(hero_img, (self.padding + 20, y_offset + 60), hero_img)
        
        # 玩家名称
        player_name = head.get('roleName', '未知玩家')
        draw.text((self.padding + 120, y_offset + 80), 
                 player_name, 
                 fill=self._hex_to_rgb(self.colors['dark']), font=self.fonts['title'])
        
        # MVP标识
        if battle_stats.get('mvp'):
            mvp_x = self.padding + 120 + len(player_name) * 15 + 20
            self._draw_rounded_rectangle(draw,
                                       [mvp_x, y_offset + 80, mvp_x + 50, y_offset + 100],
                                       8, fill=self._hex_to_rgb(self.colors['mvp_gold']))
            draw.text((mvp_x + 10, y_offset + 85), 'MVP', 
                     fill=(255, 255, 255, 255), font=self.fonts['small'])
        
        # KDA和评分
        kda_text = f"{battle_stats.get('killCnt', 0)}/{battle_stats.get('deadCnt', 0)}/{battle_stats.get('assistCnt', 0)}"
        rating_text = str(battle_stats.get('gradeGame', '0.0'))
        
        kda_x = self.padding + 120
        kda_y = y_offset + 120
        
        draw.text((kda_x, kda_y), kda_text, 
                 fill=self._hex_to_rgb(self.colors['dark']), font=self.fonts['large'])
        draw.text((kda_x, kda_y + 25), 'KDA', 
                 fill=(150, 150, 150, 255), font=self.fonts['tiny'])
        
        draw.text((kda_x + 150, kda_y), rating_text, 
                 fill=self._hex_to_rgb(self.colors['dark']), font=self.fonts['large'])
        draw.text((kda_x + 150, kda_y + 25), '评分', 
                 fill=(150, 150, 150, 255), font=self.fonts['tiny'])
        
        # 百分比数据（计算队伍百分比）
        team_percentages = self._calculate_team_percentages(data, head.get('roleId'))
        
        percent_x = kda_x + 300
        percentages = [
            (f"💰{team_percentages['money']}%", "经济"),
            (f"⚔️{team_percentages['damage']}%", "伤害"), 
            (f"🛡️{team_percentages['tanked']}%", "承伤")
        ]
        
        for i, (percent_text, label) in enumerate(percentages):
            x_pos = percent_x + i * 80
            self._draw_text_with_emoji(draw, (x_pos, kda_y), percent_text, 
                                     self._hex_to_rgb(self.colors['dark']), self.fonts['medium'])
            draw.text((x_pos, kda_y + 25), label, 
                     fill=(150, 150, 150, 255), font=self.fonts['tiny'])
        
        # 装备
        equip_x = self.padding + 120
        equip_y = y_offset + 180
        
        for i, equip in enumerate(final_equips[:6]):
            if equip and equip.get('equipIcon'):
                equip_img = self._download_image(equip.get('equipIcon'), (35, 35))
                img.paste(equip_img, (equip_x + i * 40, equip_y), equip_img)
            else:
                # 空装备槽
                draw.rectangle([equip_x + i * 40, equip_y, 
                              equip_x + i * 40 + 35, equip_y + 35], 
                              fill=(200, 200, 200, 255))
        
        return y_offset + card_height + 20
    
    def _find_current_player(self, data, current_player_id):
        """查找当前玩家信息"""
        red_roles = data.get('redRoles', [])
        blue_roles = data.get('blueRoles', [])
        
        for player in red_roles + blue_roles:
            if player.get('basicInfo', {}).get('roleId') == current_player_id:
                return player
        return None
    
    def _calculate_team_percentages(self, data, current_player_id):
        """计算当前玩家在队伍中的百分比"""
        red_roles = data.get('redRoles', [])
        blue_roles = data.get('blueRoles', [])
        
        # 确定当前玩家所在队伍
        current_team = None
        current_player = None
        
        for player in red_roles:
            if player.get('basicInfo', {}).get('roleId') == current_player_id:
                current_team = red_roles
                current_player = player
                break
        
        if not current_player:
            for player in blue_roles:
                if player.get('basicInfo', {}).get('roleId') == current_player_id:
                    current_team = blue_roles
                    current_player = player
                    break
        
        if not current_team or not current_player:
            return {'money': 0, 'damage': 0, 'tanked': 0}
        
        # 计算队伍总数
        team_totals = {'money': 0, 'damage': 0, 'tanked': 0}
        for player in current_team:
            stats = player.get('battleStats', {})
            team_totals['money'] += int(stats.get('money', 0))
            team_totals['damage'] += int(stats.get('totalHeroHurtCnt', 0))
            team_totals['tanked'] += int(stats.get('totalBeheroHurtCnt', 0))
        
        # 计算当前玩家百分比
        current_stats = current_player.get('battleStats', {})
        current_money = int(current_stats.get('money', 0))
        current_damage = int(current_stats.get('totalHeroHurtCnt', 0))
        current_tanked = int(current_stats.get('totalBeheroHurtCnt', 0))
        
        percentages = {
            'money': round((current_money / max(team_totals['money'], 1)) * 100),
            'damage': round((current_damage / max(team_totals['damage'], 1)) * 100),
            'tanked': round((current_tanked / max(team_totals['tanked'], 1)) * 100)
        }
        
        return percentages
    
    def _draw_teams(self, draw, img, data, y_offset):
        """绘制两队信息"""
        red_roles = data.get('redRoles', [])
        blue_roles = data.get('blueRoles', [])
        red_team = data.get('redTeam', {})
        blue_team = data.get('blueTeam', {})
        
        # 计算每队的区域宽度
        team_width = (self.width - 3 * self.padding) // 2
        
        # 绘制红队
        red_x = self.padding
        red_height = self._draw_team(draw, img, red_roles, red_team, red_x, y_offset, team_width, 'red')
        
        # 绘制蓝队
        blue_x = self.padding + team_width + self.padding
        blue_height = self._draw_team(draw, img, blue_roles, blue_team, blue_x, y_offset, team_width, 'blue')
        
        return y_offset + max(red_height, blue_height) + 20
    
    def _draw_team(self, draw, img, players, team_info, x, y, width, team_color):
        """绘制单个队伍"""
        # 队伍颜色
        team_color_rgb = self._hex_to_rgb(self.colors['red_team'] if team_color == 'red' else self.colors['blue_team'])
        
        # 队伍标题高度
        header_height = 50
        
        # 绘制队伍背景
        total_height = header_height + len(players) * (self.player_card_height + 5)
        self._draw_rounded_rectangle(draw, [x, y, x + width, y + total_height], 8, fill=(255, 255, 255, 255))
        
        # 绘制队伍标题
        team_name = 'Red' if team_color == 'red' else 'Blue'
        draw.text((x + 15, y + 15), team_name, fill=team_color_rgb, font=self.fonts['large'])
        
        # 胜负标识
        result_text = '胜利' if team_info.get('gameResult') else '失败'
        result_color = self._hex_to_rgb(self.colors['success']) if team_info.get('gameResult') else self._hex_to_rgb(self.colors['danger'])
        draw.text((x + width - 80, y + 15), result_text, fill=result_color, font=self.fonts['medium'])
        
        # 绘制玩家列表
        current_y = y + header_height
        
        # 按评分排序
        sorted_players = sorted(players, key=lambda p: float(p.get('battleStats', {}).get('gradeGame', 0)), reverse=True)
        
        # 计算队伍总数据用于百分比
        team_totals = {'money': 0, 'damage': 0, 'tanked': 0}
        for player in sorted_players:
            stats = player.get('battleStats', {})
            team_totals['money'] += int(stats.get('money', 0))
            team_totals['damage'] += int(stats.get('totalHeroHurtCnt', 0))
            team_totals['tanked'] += int(stats.get('totalBeheroHurtCnt', 0))
        
        for i, player in enumerate(sorted_players):
            self._draw_player_card(draw, img, player, x + 5, current_y, width - 10, team_totals)
            current_y += self.player_card_height + 5
        
        return total_height
    
    def _draw_vertical_gradient(self, draw, bbox, color):
        """绘制垂直渐变条"""
        x1, y1, x2, y2 = bbox
        r, g, b = color[:3]
        height = y2 - y1
        for i in range(int(height)):
            # 从原始颜色向更深的色调微调
            ratio = i / height
            # 营造一种从上往下稍微加深的感觉，显得更有质感
            factor = 1.0 - (ratio * 0.2)
            nr, ng, nb = int(r * factor), int(g * factor), int(b * factor)
            draw.line([(x1, y1 + i), (x2, y1 + i)], fill=(nr, ng, nb, 255))

    def _draw_player_card(self, draw, img, player, x, y, width, team_totals):
        """绘制玩家卡片"""
        basic_info = player.get('basicInfo', {})
        battle_stats = player.get('battleStats', {})
        battle_records = player.get('battleRecords', {})
        used_hero = battle_records.get('usedHero', {})
        final_equips = battle_records.get('finalEquips', [])
        
        is_mvp = battle_stats.get('mvp', False)
        
        # 判断身份
        is_me = basic_info.get('isMe', False)
        is_internal = False
        user_id = basic_info.get('userId')
        role_id = basic_info.get('roleId')
        
        try:
            # 根据全局变量字典 userlist 和 roleidlist 判断是否为内部用户（值匹配）
            # 统一转为字符串进行比较，防止 JSON 中的字符串与全局变量中的整数不匹配
            internal_users = [str(v) for v in list(userlist.values()) + list(extra_useridlist.values())]
            internal_roles = [str(v) for v in list(roleidlist.values()) + list(extra_roleidlist.values())]
            if (user_id and str(user_id) in internal_users) or (role_id and str(role_id) in internal_roles):
                is_internal = True
        except NameError:
            pass

        # 根据身份确定背景色和侧边标识色
        # 优先级：MVP > 内部玩家
        accent_color = None
        bg_color = (250, 250, 250, 255) # 默认背景色
        
        # 如果是内部玩家（无论是否为本人），显示内部玩家的底色和侧边条
        if is_internal:
            bg_color = (*self._hex_to_rgb(self.colors['internal_bg']), 255)
            accent_color = (*self._hex_to_rgb(self.colors['internal_accent']), 255)

        if is_mvp:
            # MVP 底色优先级最高
            bg_color = (*self._hex_to_rgb(self.colors['mvp_gold']), 50)

        # 始终绘制背景矩形
        draw.rectangle([x, y, x + width, y + self.player_card_height], fill=bg_color)
        
        # 绘制侧边高亮条 (Identity Indicator) - 仅针对非本人的内部玩家
        if accent_color:
            self._draw_vertical_gradient(draw, [x, y, x + 6, y + self.player_card_height], accent_color)
        
        # 确定使用的字体 (本人使用粗体)
        name_font = self.fonts.get('medium_bold', self.fonts['medium']) if is_me else self.fonts['medium']
        score_font = self.fonts.get('small_bold', self.fonts['small']) if is_me else self.fonts['small']
        
        # 英雄头像
        hero_icon = used_hero.get('heroIcon', '')
        hero_img = self._download_image(hero_icon, (45, 45))
        
        # 圆形遮罩
        mask = Image.new('L', (45, 45), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, 45, 45], fill=255)
        hero_img.putalpha(mask)
        
        img.paste(hero_img, (x + 10, y + 15), hero_img)
        
        # 玩家名称
        player_name = basic_info.get('roleName', '未知玩家')
        draw.text((x + 70, y + 10), player_name, fill=self._hex_to_rgb(self.colors['dark']), font=name_font)
        
        # MVP标识
        if is_mvp:
            name_width = len(player_name) * 10
            mvp_x = x + 70 + name_width + 10
            self._draw_rounded_rectangle(draw, [mvp_x, y + 10, mvp_x + 35, y + 25], 
                                       4, fill=self._hex_to_rgb(self.colors['mvp_gold']))
            draw.text((mvp_x + 5, y + 12), 'MVP', fill=(255, 255, 255, 255), font=self.fonts['tiny'])
        
        # 装备
        equip_y = y + 35
        for i, equip in enumerate(final_equips[:6]):
            equip_x = x + 70 + i * 25
            if equip and equip.get('equipIcon'):
                equip_img = self._download_image(equip.get('equipIcon'), (20, 20))
                img.paste(equip_img, (equip_x, equip_y), equip_img)
            else:
                draw.rectangle([equip_x, equip_y, equip_x + 20, equip_y + 20], fill=(200, 200, 200, 255))
        
        # 评分和KDA（居中）
        center_x = x + width // 2
        rating = str(battle_stats.get('gradeGame', '0.0'))
        kda = f"{battle_stats.get('killCnt', 0)}/{battle_stats.get('deadCnt', 0)}/{battle_stats.get('assistCnt', 0)}"
        
        draw.text((center_x - 30, y + 10), f"评分 {rating}", 
                 fill=self._hex_to_rgb(self.colors['primary']), font=score_font)
        draw.text((center_x - 20, y + 30), kda, 
                 fill=self._hex_to_rgb(self.colors['danger']), font=score_font)
        
        # 百分比数据（右侧，垂直排列）
        player_money = int(battle_stats.get('money', 0))
        player_damage = int(battle_stats.get('totalHeroHurtCnt', 0))
        player_tanked = int(battle_stats.get('totalBeheroHurtCnt', 0))
        
        money_percent = round((player_money / max(team_totals['money'], 1)) * 100)
        damage_percent = round((player_damage / max(team_totals['damage'], 1)) * 100)
        tanked_percent = round((player_tanked / max(team_totals['tanked'], 1)) * 100)
        
        # 分别绘制emoji和数字，确保一致的间距
        base_x = x + width - 180
        emoji_positions = [base_x, base_x + 60, base_x + 125]
        emojis = ['💰', '⚔️', '🛡️']
        percents = [f"{money_percent}%", f"{damage_percent}%", f"{tanked_percent}%"]
        
        # 百分比文字也要粗体
        percent_font = self.fonts.get('tiny_bold', self.fonts['tiny']) if is_me else self.fonts['tiny']
        
        for i in range(3):
            # 绘制emoji
            self._draw_text_with_emoji(draw, (emoji_positions[i], y + 25), emojis[i], 
                                     self._hex_to_rgb(self.colors['dark']), percent_font)
            # 绘制百分比数字，固定偏移16像素
            draw.text((emoji_positions[i] + 25, y + 25), percents[i], 
                     fill=self._hex_to_rgb(self.colors['dark']), font=percent_font)
    
    def generate_battle_image(self, json_path, output_path):
        """
        生成战局图片的主函数
        
        Args:
            json_path (str): JSON数据文件路径
            output_path (str): 输出图片路径
        
        Returns:
            bool: 生成是否成功
        """
        try:
            # 读取JSON数据
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 如果数据有data字段，则提取data内容
            if 'data' in data:
                data = data['data']
            
            # 计算实际需要的高度
            red_roles = data.get('redRoles', [])
            blue_roles = data.get('blueRoles', [])
            max_players = max(len(red_roles), len(blue_roles))
            
            # 动态计算高度
            header_height = 240  # 玩家头部信息
            team_header_height = 50  # 队伍标题
            player_area_height = max_players * (self.player_card_height + 5)
            footer_height = 60
            
            self.height = header_height + team_header_height + player_area_height + footer_height + 100
            
            # 创建图片
            img = Image.new('RGBA', (self.width, self.height), (245, 247, 250, 255))
            draw = ImageDraw.Draw(img)
            
            # 设置背景色（根据胜负）
            head = data.get('head', {})
            game_result = head.get('gameResult', False)
            
            if game_result:
                # 胜利背景
                bg_overlay = Image.new('RGBA', (self.width, self.height), (39, 174, 96, 20))
            else:
                # 失败背景
                bg_overlay = Image.new('RGBA', (self.width, self.height), (231, 76, 60, 20))
            
            img = Image.alpha_composite(img, bg_overlay)
            draw = ImageDraw.Draw(img)
            
            # 绘制各部分
            current_y = self.padding
            
            # 绘制玩家头部信息
            current_y = self._draw_player_header(draw, img, data, current_y)
            
            # 绘制队伍信息
            current_y = self._draw_teams(draw, img, data, current_y)
            
            # 绘制底部信息
            draw.text((self.width // 2 - 100, current_y + 20), 
                     'Data from 笙煎守味🤖', 
                     fill=(150, 150, 150, 255), font=self.fonts['small'])
            
            # 保存图片
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1])
            rgb_img.save(output_path, 'PNG', quality=95)
            
            print(f"战局图片生成成功: {output_path}")
            return True
            
        except Exception as e:
            print(f"生成战局图片失败: {e}")
            import traceback
            traceback.print_exc()
            return False

def generate_battle_ui_image(json_path, output_path):
    """
    外部接口函数：生成战局UI图片
    
    Args:
        json_path (str): JSON数据文件路径
        output_path (str): 输出图片路径
    
    Returns:
        bool: 生成是否成功
    """
    generator = BattleUIGenerator()
    return generator.generate_battle_image(json_path, output_path)

if __name__ == "__main__":
    # 测试用例
    import sys
    
    if len(sys.argv) >= 3:
        json_file = sys.argv[1]
        output_file = sys.argv[2]
    else:
        # 默认测试文件
        json_file = "battle_data.json"
        output_file = "battle_ui.png"
    
    # 生成图片
    success = generate_battle_ui_image(json_file, output_file)
    
    if success:
        print("✅ 战局UI图片生成完成！")
    else:
        print("❌ 战局UI图片生成失败！")
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字体检测和诊断脚本
Font Detection and Diagnosis Script
"""

import os
import sys
import platform
from PIL import Image, ImageDraw, ImageFont

def detect_system():
    """检测操作系统"""
    system = platform.system()
    print(f"🖥️  操作系统: {system} {platform.release()}")
    if system == "Linux":
        try:
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        distro = line.split('=')[1].strip().strip('"')
                        print(f"📦 Linux发行版: {distro}")
                        break
        except:
            pass
    return system

def check_font_paths():
    """检查字体路径"""
    print("\n🔍 检查字体文件...")
    
    # 定义字体路径
    emoji_paths = [
        # Windows
        'C:/Windows/Fonts/seguiemj.ttf',
        'C:/Windows/Fonts/NotoColorEmoji.ttf',
        # Linux - 主要路径
        '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
        '/usr/share/fonts/truetype/noto-color-emoji/NotoColorEmoji.ttf',
        '/usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf',
        '/usr/share/fonts/noto/NotoColorEmoji.ttf',
        # Linux - 用户路径
        '~/.local/share/fonts/NotoColorEmoji.ttf',
        '~/.fonts/NotoColorEmoji.ttf',
        # macOS
        '/System/Library/Fonts/Apple Color Emoji.ttc',
    ]
    
    chinese_paths = [
        # Windows
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simhei.ttf',
        # Linux - WQY字体
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        # Linux - Noto CJK
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        # Linux - 用户路径
        '~/.local/share/fonts/NotoSansCJK-Regular.ttc',
        '~/.fonts/wqy-microhei.ttc',
        # macOS
        '/System/Library/Fonts/PingFang.ttc',
    ]
    
    print("📱 Emoji字体:")
    emoji_found = False
    for path in emoji_paths:
        expanded_path = os.path.expanduser(path)
        if os.path.exists(expanded_path):
            print(f"  ✅ {expanded_path}")
            emoji_found = True
        else:
            print(f"  ❌ {expanded_path}")
    
    print("\n🇨🇳 中文字体:")
    chinese_found = False
    for path in chinese_paths:
        expanded_path = os.path.expanduser(path)
        if os.path.exists(expanded_path):
            print(f"  ✅ {expanded_path}")
            chinese_found = True
        else:
            print(f"  ❌ {expanded_path}")
    
    return emoji_found, chinese_found

def test_font_loading():
    """测试字体加载"""
    print("\n🧪 测试字体加载...")
    
    # 测试路径
    test_paths = [
        # Emoji字体
        ('Emoji', [
            '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
            '/usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf',
            'C:/Windows/Fonts/seguiemj.ttf',
            '~/.local/share/fonts/NotoColorEmoji.ttf'
        ]),
        # 中文字体
        ('中文', [
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
            'C:/Windows/Fonts/msyh.ttc',
            '~/.local/share/fonts/NotoSansCJK-Regular.ttc'
        ])
    ]
    
    loaded_fonts = {}
    
    for font_type, paths in test_paths:
        print(f"\n{font_type}字体加载测试:")
        loaded = False
        for path in paths:
            expanded_path = os.path.expanduser(path)
            if os.path.exists(expanded_path):
                try:
                    font = ImageFont.truetype(expanded_path, 16)
                    print(f"  ✅ 成功加载: {expanded_path}")
                    loaded_fonts[font_type] = font
                    loaded = True
                    break
                except Exception as e:
                    print(f"  ❌ 加载失败 {expanded_path}: {e}")
        
        if not loaded:
            print(f"  ⚠️ 未找到可用的{font_type}字体")
            try:
                font = ImageFont.load_default()
                loaded_fonts[font_type] = font
                print(f"  🔄 使用默认字体")
            except:
                print(f"  ❌ 连默认字体都无法加载")
    
    return loaded_fonts

def create_test_image(loaded_fonts):
    """创建测试图片"""
    print("\n🎨 创建字体测试图片...")
    
    # 创建测试图片
    width, height = 600, 400
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)
    
    # 测试文本
    test_texts = [
        ("ASCII文本", "Hello World! 123"),
        ("中文文本", "你好世界！战局详情"),
        ("Emoji测试", "💰⚔️🛡️🏆⭐"),
        ("混合文本", "💰经济 ⚔️伤害 🛡️防御"),
        ("游戏数据", "💰15% ⚔️32% 🛡️8%")
    ]
    
    y_offset = 20
    line_height = 50
    
    for i, (label, text) in enumerate(test_texts):
        y = y_offset + i * line_height
        
        # 绘制标签
        draw.text((20, y), f"{label}:", fill='black', font=ImageFont.load_default())
        
        # 尝试使用不同字体绘制
        text_x = 150
        
        # 尝试emoji字体
        if 'Emoji' in loaded_fonts:
            try:
                draw.text((text_x, y), text, fill='blue', font=loaded_fonts['Emoji'])
                draw.text((text_x, y + 20), "(emoji字体)", fill='gray', font=ImageFont.load_default())
                continue
            except:
                pass
        
        # 尝试中文字体
        if '中文' in loaded_fonts:
            try:
                draw.text((text_x, y), text, fill='green', font=loaded_fonts['中文'])
                draw.text((text_x, y + 20), "(中文字体)", fill='gray', font=ImageFont.load_default())
                continue
            except:
                pass
        
        # 使用默认字体
        try:
            draw.text((text_x, y), text, fill='red', font=ImageFont.load_default())
            draw.text((text_x, y + 20), "(默认字体)", fill='gray', font=ImageFont.load_default())
        except:
            draw.text((text_x, y), "字体加载失败", fill='red', font=ImageFont.load_default())
    
    # 保存测试图片
    output_path = "font_test_result.png"
    img.save(output_path)
    print(f"✅ 测试图片已保存: {output_path}")
    
    return output_path

def provide_suggestions(system, emoji_found, chinese_found):
    """提供改进建议"""
    print("\n💡 改进建议:")
    
    if not emoji_found and not chinese_found:
        print("❌ 缺少emoji和中文字体支持")
    elif not emoji_found:
        print("❌ 缺少emoji字体支持")
    elif not chinese_found:
        print("❌ 缺少中文字体支持")
    else:
        print("✅ 字体支持良好")
        return
    
    if system == "Linux":
        print("\n🐧 Linux系统建议:")
        print("1. 运行字体安装脚本:")
        print("   chmod +x install_linux_fonts.sh")
        print("   ./install_linux_fonts.sh")
        print("\n2. 或手动安装:")
        print("   # Ubuntu/Debian:")
        print("   sudo apt install fonts-noto-cjk fonts-noto-color-emoji fonts-wqy-microhei")
        print("   # Arch Linux:")
        print("   sudo pacman -S noto-fonts-cjk noto-fonts-emoji wqy-microhei")
        print("   # 更新字体缓存:")
        print("   fc-cache -f -v")
        
    elif system == "Windows":
        print("\n🪟 Windows系统建议:")
        print("1. 确保Windows 10/11已安装Segoe UI Emoji")
        print("2. 下载安装Google Noto字体:")
        print("   https://fonts.google.com/noto")
        
    elif system == "Darwin":  # macOS
        print("\n🍎 macOS系统建议:")
        print("1. 系统应该自带Apple Color Emoji")
        print("2. 安装Noto字体:")
        print("   brew install font-noto-sans-cjk")

def main():
    """主函数"""
    print("🚀 字体检测和诊断工具")
    print("=" * 50)
    
    # 检测系统
    system = detect_system()
    
    # 检查字体路径
    emoji_found, chinese_found = check_font_paths()
    
    # 测试字体加载
    loaded_fonts = test_font_loading()
    
    # 创建测试图片
    create_test_image(loaded_fonts)
    
    # 提供建议
    provide_suggestions(system, emoji_found, chinese_found)
    
    print("\n🎉 检测完成！")
    print("请查看生成的 font_test_result.png 图片来验证字体效果")

if __name__ == "__main__":
    main()
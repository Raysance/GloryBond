#!/bin/bash
# Alibaba Cloud Linux 快速字体安装脚本 (使用国内源)
# Quick Font Installation for Alibaba Cloud Linux (China Mirror)

echo "🚀 Alibaba Cloud Linux 快速字体安装 (国内源)"
echo "================================================"

# 检查系统
echo "🔍 检查系统信息..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "系统: $PRETTY_NAME"
else
    echo "无法识别系统版本"
    exit 1
fi

# 函数: 安装基础工具
install_basic_tools() {
    echo "📦 安装基础工具..."
    sudo yum install -y wget curl fontconfig
}

# 函数: 配置国内YUM源
setup_china_mirrors() {
    echo "🇨🇳 配置国内YUM源..."
    
    # 备份原有源
    sudo cp /etc/yum.repos.d/CentOS-Base.repo /etc/yum.repos.d/CentOS-Base.repo.backup 2>/dev/null || true
    
    # 配置阿里云源
    echo "配置阿里云镜像源..."
    sudo tee /etc/yum.repos.d/aliyun.repo > /dev/null <<EOF
[aliyun-base]
name=Aliyun Base
baseurl=https://mirrors.aliyun.com/centos/8/BaseOS/x86_64/os/
gpgcheck=0
enabled=1

[aliyun-appstream]
name=Aliyun AppStream
baseurl=https://mirrors.aliyun.com/centos/8/AppStream/x86_64/os/
gpgcheck=0
enabled=1

[aliyun-extras]
name=Aliyun Extras
baseurl=https://mirrors.aliyun.com/centos/8/extras/x86_64/os/
gpgcheck=0
enabled=1
EOF

    # 安装EPEL源
    echo "安装EPEL源..."
    sudo yum install -y epel-release || \
    sudo yum install -y https://mirrors.aliyun.com/epel/epel-release-latest-8.noarch.rpm
    
    # 清理并重建缓存
    sudo yum clean all
    sudo yum makecache
}

# 函数: 通过YUM安装字体
install_fonts_yum() {
    echo "📦 通过YUM安装字体包..."
    
    # 安装WQY字体
    echo "安装WQY中文字体..."
    sudo yum install -y wqy-microhei-fonts wqy-zenhei-fonts || echo "WQY字体安装失败"
    
    # 安装Google Noto字体
    echo "安装Google Noto字体..."
    sudo yum install -y google-noto-fonts-common || echo "Noto common字体安装失败"
    sudo yum install -y google-noto-sans-cjk-fonts || echo "Noto CJK字体安装失败"
    sudo yum install -y google-noto-color-emoji-fonts || echo "Noto Emoji字体安装失败"
    
    # 安装其他字体
    echo "安装其他字体..."
    sudo yum install -y liberation-fonts dejavu-sans-fonts || echo "其他字体安装失败"
}

# 函数: 手动下载字体 (国内源)
download_fonts_manual() {
    echo "📥 手动下载字体文件..."
    
    # 创建字体目录
    sudo mkdir -p /usr/local/share/fonts/chinese
    sudo mkdir -p /usr/local/share/fonts/emoji
    cd /tmp
    
    # 下载WQY微米黑字体
    echo "下载WQY微米黑字体..."
    if [ ! -f "/usr/local/share/fonts/chinese/wqy-microhei.ttc" ]; then
        # 尝试多个源
        wget -O wqy-microhei.ttc "https://github.com/anthonyfok/fonts-wqy-microhei/raw/master/wqy-microhei.ttc" || \
        wget -O wqy-microhei.ttc "https://gitee.com/lxgw/source-han-serif-sc/raw/master/fonts/wqy-microhei.ttc" || \
        curl -L -o wqy-microhei.ttc "https://github.com/anthonyfok/fonts-wqy-microhei/raw/master/wqy-microhei.ttc"
        
        if [ -f "wqy-microhei.ttc" ]; then
            sudo mv wqy-microhei.ttc /usr/local/share/fonts/chinese/
            echo "✅ WQY微米黑字体下载成功"
        else
            echo "❌ WQY微米黑字体下载失败"
        fi
    fi
    
    # 下载思源黑体 (备选中文字体)
    echo "下载思源黑体..."
    if [ ! -f "/usr/local/share/fonts/chinese/SourceHanSansSC-Regular.otf" ]; then
        wget -O SourceHanSansSC-Regular.otf "https://github.com/adobe-fonts/source-han-sans/raw/release/SubsetOTF/SourceHanSansSC/SourceHanSansSC-Regular.otf" || \
        echo "思源黑体下载失败"
        
        if [ -f "SourceHanSansSC-Regular.otf" ]; then
            sudo mv SourceHanSansSC-Regular.otf /usr/local/share/fonts/chinese/
            echo "✅ 思源黑体下载成功"
        fi
    fi
    
    # 下载Noto Emoji (较小版本)
    echo "下载Noto Emoji字体..."
    if [ ! -f "/usr/local/share/fonts/emoji/NotoEmoji-Regular.ttf" ]; then
        wget -O NotoEmoji-Regular.ttf "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoEmoji-Regular.ttf" || \
        echo "Noto Emoji字体下载失败"
        
        if [ -f "NotoEmoji-Regular.ttf" ]; then
            sudo mv NotoEmoji-Regular.ttf /usr/local/share/fonts/emoji/
            echo "✅ Noto Emoji字体下载成功"
        fi
    fi
    
    # 设置权限
    sudo chmod 644 /usr/local/share/fonts/chinese/* 2>/dev/null
    sudo chmod 644 /usr/local/share/fonts/emoji/* 2>/dev/null
}

# 函数: 更新字体缓存
update_font_cache() {
    echo "🔄 更新字体缓存..."
    sudo fc-cache -f -v
}

# 函数: 验证安装
verify_installation() {
    echo "🔍 验证字体安装..."
    
    echo "中文字体:"
    fc-list | grep -i "wqy\|noto.*cjk\|source.*han\|微" | head -5
    
    echo "Emoji字体:"
    fc-list | grep -i "emoji\|noto.*emoji" | head -3
    
    echo "所有已安装的相关字体:"
    fc-list | grep -i "noto\|wqy\|source\|liberation" | wc -l
}

# 主安装流程
main() {
    echo "开始安装流程..."
    
    # 安装基础工具
    install_basic_tools
    
    # 配置国内源
    setup_china_mirrors
    
    # 尝试YUM安装
    install_fonts_yum
    
    # 手动下载字体作为补充
    download_fonts_manual
    
    # 更新字体缓存
    update_font_cache
    
    # 验证安装
    verify_installation
    
    echo ""
    echo "🎉 字体安装完成！"
    echo "💡 建议执行以下命令测试："
    echo "   python font_diagnosis.py"
    echo "   python test_emoji_fix.py"
    echo ""
    echo "如果重新登录后仍有问题，请检查："
    echo "   fc-list | grep -i 'noto\\|wqy\\|emoji'"
}

# 执行主函数
main
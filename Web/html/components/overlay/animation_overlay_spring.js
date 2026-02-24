/**
 * Spring Festival Overlay - 2026 Chinese New Year Theme
 * 主题：中国春节（红/金配色、灯笼、红包等）
 * 特点：不影响点击操作、支持移动端/PC、主体透明、不干扰正文。
 * 使用：引入脚本即可
 * <script src="spring-festival-overlay.js"></script>
 */
(function(window, document) {
    const config = {
        id: 'spring-festival-overlay-root',
        styleId: 'spring-festival-overlay-style',
        zIndex: 9999,
        elements: ['🧧', '🍊', '🎊', '✨', '🏮'],
        particleCount: 10 // 降低密度
    };

    function injectCSS() {
        if (document.getElementById(config.styleId)) return;
        const css = `
            #${config.id} {
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                pointer-events: none;
                z-index: ${config.zIndex};
                overflow: hidden;
                user-select: none;
                /* 增加边缘氛围感：淡淡的红色光晕 */
                box-shadow: inset 0 0 100px rgba(211, 47, 47, 0.05);
            }
            /* 增加边缘剪纸纹理感 (可选) */
            #${config.id}::before {
                content: '';
                position: absolute;
                inset: 0;
                border: 2px solid rgba(211, 47, 47, 0.1);
                pointer-events: none;
            }
            .sf-item {
                position: absolute;
                will-change: transform, opacity;
                filter: drop-shadow(0 2px 8px rgba(211, 47, 47, 0.3));
            }
            /* 摇摆动画 - 用于灯笼 */
            @keyframes sf-sway {
                0% { transform: rotate(-8deg); }
                50% { transform: rotate(8deg); }
                100% { transform: rotate(-8deg); }
            }
            /* 慢动作浮动 - 减少急躁感 */
            @keyframes sf-float {
                0% { transform: translateY(-5vh) translateX(0) rotate(0deg); opacity: 0; }
                20% { opacity: 0.6; }
                80% { opacity: 0.6; }
                100% { transform: translateY(105vh) translateX(20px) rotate(360deg); opacity: 0; }
            }
            /* 呼吸效果 */
            @keyframes sf-pulse {
                0%, 100% { opacity: 0.8; transform: scale(1); }
                50% { opacity: 1; transform: scale(1.1); }
            }
            
            .sf-lantern {
                font-size: 48px;
                animation: sf-sway 4s ease-in-out infinite;
                transform-origin: top center;
                text-shadow: 0 0 10px rgba(255, 215, 0, 0.3);
            }
            .sf-corner-big {
                font-size: 32px;
                animation: sf-pulse 5s ease-in-out infinite;
                font-weight: bold;
                color: #d32f2f;
            }
            .sf-particle {
                font-size: 18px;
                animation: sf-float 15s linear infinite;
                top: -50px;
            }
            /* 中国结/挂件 */
            .sf-knot {
                font-size: 36px;
                top: -10px;
            }

            /* 移动端适配 */
            @media (max-width: 768px) {
                .sf-lantern { font-size: 30px; }
                .sf-corner-big { font-size: 24px; }
                .sf-particle { font-size: 14px; }
            }
        `;
        const style = document.createElement('style');
        style.id = config.styleId;
        style.textContent = css;
        document.head.appendChild(style);
    }

    function createOverlay() {
        if (document.getElementById(config.id)) return;
        
        injectCSS();
        
        const root = document.createElement('div');
        root.id = config.id;
        root.setAttribute('aria-hidden', 'true');

        // 1. 固定角落和侧边装饰
        const decorations = [
            { t: '-5px', l: '15px', type: 'sf-lantern', content: '🏮' },
            { t: '-5px', r: '15px', type: 'sf-lantern', content: '🏮' },
            { t: '40%', l: '5px', type: 'sf-item', content: '🧨', opacity: 0.6 },
            { t: '45%', r: '5px', type: 'sf-item', content: '🧨', opacity: 0.6 }
        ];

        decorations.forEach(pos => {
            const el = document.createElement('div');
            el.className = `sf-item ${pos.type || ''}`;
            el.innerHTML = pos.content;
            if (pos.t) el.style.top = pos.t;
            if (pos.b) el.style.bottom = pos.b;
            if (pos.l) el.style.left = pos.l;
            if (pos.r) el.style.right = pos.r;
            if (pos.opacity) el.style.opacity = pos.opacity;
            root.appendChild(el);
        });

        // 2. 随机飘落的小元素 (数量减半，速度变慢)
        for (let i = 0; i < config.particleCount; i++) {
            const p = document.createElement('div');
            p.className = 'sf-item sf-particle';
            p.innerHTML = config.elements[Math.floor(Math.random() * config.elements.length)];
            p.style.left = (Math.random() * 90 + 5) + 'vw';
            
            const duration = 12 + Math.random() * 10;
            const delay = Math.random() * -22; 
            p.style.animationDuration = duration + 's';
            p.style.animationDelay = delay + 's';
            p.style.fontSize = (14 + Math.random() * 8) + 'px';
            
            root.appendChild(p);
        }

        // 3. 顶部边缘横梁感
        const topCount = 4;
        for (let i = 0; i < topCount; i++) {
            const t = document.createElement('div');
            t.className = 'sf-item sf-knot';
            t.innerHTML = '🧧';
            t.style.top = '-5px';
            t.style.left = (25 + (i * 15) + (Math.random() * 5)) + 'vw';
            t.style.fontSize = '24px';
            t.style.filter = 'grayscale(0.2) brightness(0.9)';
            root.appendChild(t);
        }

        document.body.appendChild(root);
    }

    // 自动初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createOverlay);
    } else {
        createOverlay();
    }

})(window, document);

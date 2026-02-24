/**
 * Battle UI Utilities
 * 提供通用的 UI 组件和辅助函数
 */

/**
 * 显示提示消息 (Toast)
 * @param {string} message 消息内容
 * @param {string} type 类型: info, success, error, warning
 */
export function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 14px 24px;
        border-radius: 12px;
        color: white;
        font-weight: 600;
        font-size: 0.95rem;
        z-index: 99999;
        opacity: 0;
        transform: translateX(100%);
        transition: all 0.3s ease;
        max-width: 320px;
        word-wrap: break-word;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
        pointer-events: auto;
    `;
    
    const backgrounds = {
        success: 'linear-gradient(135deg, #28a745, #20c997)',
        error: 'linear-gradient(135deg, #dc3545, #e74c3c)',
        warning: 'linear-gradient(135deg, #ffc107, #ff9800)',
        info: 'linear-gradient(135deg, #6c9bd1, #4fc3f7)'
    };
    
    const shadows = {
        success: '0 8px 24px rgba(40, 167, 69, 0.3)',
        error: '0 8px 24px rgba(220, 53, 69, 0.3)',
        warning: '0 8px 24px rgba(255, 193, 7, 0.3)',
        info: '0 8px 24px rgba(108, 155, 209, 0.3)'
    };
    
    toast.style.background = backgrounds[type] || backgrounds.info;
    toast.style.boxShadow = shadows[type] || shadows.info;
    
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(0)';
    }, 100);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, 3000);
}

/**
 * 通用确认对话框
 * @param {Object} options 配置项 { title, content, confirmText, cancelText, confirmGradient }
 * @returns {Promise<boolean>}
 */
export function showConfirm({ title, content, confirmText = '确定', cancelText = '取消', confirmGradient }) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.6);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10001;
            backdrop-filter: blur(5px);
            opacity: 0;
            transition: opacity 0.3s ease;
        `;
        
        const confirmBox = document.createElement('div');
        confirmBox.style.cssText = `
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 20px;
            padding: 0;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
            transform: scale(0.7);
            transition: all 0.3s ease;
        `;
        
        const defaultGradient = 'linear-gradient(135deg, #6c9bd1, #4fc3f7)';
        const btnGradient = confirmGradient || defaultGradient;

        confirmBox.innerHTML = `
            <div style="padding: 25px 25px 15px; text-align: center; border-bottom: 1px solid rgba(108, 155, 209, 0.2);">
                <h3 style="margin: 0; color: #2c3e50; font-size: 1.3rem; font-weight: 600;">${title}</h3>
            </div>
            <div style="padding: 20px 25px; text-align: center;">
                <p style="color: #2c3e50; font-size: 1.1rem; line-height: 1.5; margin: 0 0 20px;">
                    ${content}
                </p>
                <div style="display: flex; gap: 12px; justify-content: center;">
                    <button id="btnCancel" style="
                        background: rgba(108, 117, 125, 0.1);
                        color: #6c757d;
                        border: 1px solid rgba(108, 117, 125, 0.3);
                        padding: 10px 20px;
                        border-radius: 20px;
                        font-size: 1rem;
                        cursor: pointer;
                        transition: all 0.3s ease;
                        min-width: 80px;
                    ">${cancelText}</button>
                    <button id="btnConfirm" style="
                        background: ${btnGradient};
                        color: white;
                        border: none;
                        padding: 10px 20px;
                        border-radius: 20px;
                        font-size: 1rem;
                        cursor: pointer;
                        transition: all 0.3s ease;
                        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                        min-width: 80px;
                    ">${confirmText}</button>
                </div>
            </div>
        `;
        
        overlay.appendChild(confirmBox);
        document.body.appendChild(overlay);
        
        setTimeout(() => {
            overlay.style.opacity = '1';
            confirmBox.style.transform = 'scale(1)';
        }, 50);
        
        const close = (result) => {
            overlay.style.opacity = '0';
            confirmBox.style.transform = 'scale(0.7)';
            setTimeout(() => {
                document.body.removeChild(overlay);
                resolve(result);
            }, 300);
        };
        
        confirmBox.querySelector('#btnCancel').onclick = () => close(false);
        confirmBox.querySelector('#btnConfirm').onclick = () => close(true);
        overlay.onclick = (e) => { if (e.target === overlay) close(false); };
    });
}

/**
 * 检查战局是否为今日
 */
export function isTodayBattle(dtEventTime) {
    if (!dtEventTime) return false;
    const battleDate = new Date(dtEventTime * 1000);
    const today = new Date();
    return battleDate.getFullYear() === today.getFullYear() &&
           battleDate.getMonth() === today.getMonth() &&
           battleDate.getDate() === today.getDate();
}

/**
 * 加载英雄映射
 */
export async function loadHeroMap(jsonPath = 'allhero.json') {
    const heroMap = {};
    try {
        const response = await fetch(jsonPath);
        if (response.ok) {
            const json = await response.json();
            if (json && json.data && json.data.heroList) {
                json.data.heroList.forEach(hero => {
                    heroMap[hero.heroId] = hero.name;
                });
            }
        }
    } catch (error) {
        console.error('加载英雄表失败:', error);
    }
    return heroMap;
}

/**
 * 检查是否为正式比赛地图
 */
export function isOfficialMap(mapName) {
    if (!mapName) return false;
    const name = mapName.toLowerCase();
    if (['1v1', '2v2', '3v3'].some(p => name.includes(p))) return false;
    return ['排位', '巅峰', '战队', '王者峡谷', '梦境'].some(p => name.includes(p));
}

/**
 * 分享确认对话框
 */
export function showShareConfirm() {
    return showConfirm({
        title: '分享确认',
        content: `
            <div style="font-size: 2.5rem; margin-bottom: 10px;">💬</div>
            点击确认后会将该战局分享到群聊
        `,
        confirmText: '确定',
        cancelText: '取消'
    });
}

/**
 * 分析确认对话框 (支持长按回传 special: true)
 */
export function showAnalyzeConfirm() {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.6);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10001;
            backdrop-filter: blur(5px);
            opacity: 0;
            transition: opacity 0.3s ease;
        `;
        
        const confirmBox = document.createElement('div');
        confirmBox.style.cssText = `
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 20px;
            padding: 0;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
            transform: scale(0.7);
            transition: all 0.3s ease;
        `;
        
        confirmBox.innerHTML = `
            <div style="padding: 25px 25px 15px; text-align: center; border-bottom: 1px solid rgba(108, 155, 209, 0.2);">
                <div style="font-size: 2.5rem; margin-bottom: 10px;">📊</div>
                <h3 style="margin: 0; color: #2c3e50; font-size: 1.3rem; font-weight: 600;">分析确认</h3>
            </div>
            <div style="padding: 20px 25px; text-align: center;">
                <p style="color: #2c3e50; font-size: 1.1rem; line-height: 1.5; margin: 0 0 20px;">
                    点击确认后会分析该战局的底蕴并发送到群聊
                </p>
                <div style="display: flex; gap: 12px; justify-content: center;">
                    <button id="cancelAnalyze" style="
                        background: rgba(108, 117, 125, 0.1);
                        color: #6c757d;
                        border: 1px solid rgba(108, 117, 125, 0.3);
                        padding: 10px 20px;
                        border-radius: 20px;
                        font-size: 1rem;
                        cursor: pointer;
                        transition: all 0.3s ease;
                        min-width: 80px;
                    ">取消</button>
                    <button id="confirmAnalyze" style="
                        background: linear-gradient(135deg, #6c9bd1, #4fc3f7);
                        color: white;
                        border: none;
                        padding: 10px 20px;
                        border-radius: 20px;
                        font-size: 1rem;
                        cursor: pointer;
                        transition: all 0.3s ease;
                        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                        min-width: 80px;
                        position: relative;
                        overflow: hidden;
                    ">确定</button>
                </div>
            </div>
        `;
        
        overlay.appendChild(confirmBox);
        document.body.appendChild(overlay);
        
        setTimeout(() => {
            overlay.style.opacity = '1';
            confirmBox.style.transform = 'scale(1)';
        }, 50);

        const close = (result) => {
            overlay.style.opacity = '0';
            confirmBox.style.transform = 'scale(0.7)';
            setTimeout(() => {
                document.body.removeChild(overlay);
                resolve(result);
            }, 300);
        };

        const confirmBtn = confirmBox.querySelector('#confirmAnalyze');
        let pressTimer;
        let isSpecial = false;

        const startPress = () => {
            isSpecial = false;
            confirmBtn.style.background = 'linear-gradient(135deg, #6c9bd1, #4fc3f7)';
            pressTimer = setTimeout(() => {
                isSpecial = true;
                confirmBtn.style.background = 'linear-gradient(135deg, #FF512F, #DD2476)';
                if (window.navigator.vibrate) window.navigator.vibrate(50);
            }, 2000);
        };

        const endPress = () => {
            clearTimeout(pressTimer);
        };

        confirmBtn.addEventListener('mousedown', startPress);
        confirmBtn.addEventListener('touchstart', startPress);
        confirmBtn.addEventListener('mouseup', endPress);
        confirmBtn.addEventListener('mouseleave', endPress);
        confirmBtn.addEventListener('touchend', endPress);

        confirmBtn.onclick = () => close({ confirmed: true, special: isSpecial });
        confirmBox.querySelector('#cancelAnalyze').onclick = () => close({ confirmed: false });
        overlay.onclick = (e) => { if (e.target === overlay) close({ confirmed: false }); };
    });
}

/**
 * 处理收藏
 */
export async function handleFavorite(battle, key, buttonElement) {
    try {
        buttonElement.classList.add('loading');
        const outlineIcon = buttonElement.querySelector('.heart-outline');
        const filledIcon = buttonElement.querySelector('.heart-filled');
        
        const params = new URLSearchParams({ gameSeq: battle.gameSeq || '', key });
        const response = await fetch(`/like-btldetail?${params.toString()}`);
        
        buttonElement.classList.remove('loading');
        if (response.ok) {
            const result = await response.json();
            buttonElement.classList.add('favorited');
            if (outlineIcon) outlineIcon.style.display = 'none';
            if (filledIcon) filledIcon.style.display = 'block';
            showToast(result.message || '收藏成功！', 'success');
        } else {
            const error = await response.json().catch(() => ({}));
            showToast(error.message || '收藏失败', 'error');
        }
    } catch (error) {
        buttonElement.classList.remove('loading');
        showToast('收藏接口调用失败', 'error');
    }
}

/**
 * 处理分享
 */
export async function handleShare(battle, profileData, key, confirmFn) {
    if (!isOfficialMap(battle.mapName)) {
        showToast('仅支持分享特定模式', 'warning');
        return;
    }
    
    if (confirmFn && !(await confirmFn())) return;

    try {
        const params = new URLSearchParams({
            gameSvr: battle.gameSvrId || '',
            gameSeq: battle.gameSeq || '',
            targetRoleId: profileData.targetRoleId || '',
            relaySvr: battle.relaySvrId || '',
            battleType: battle.pvpType || 0,
            key
        });
        const response = await fetch(`/share-btldetail?${params.toString()}`);
        if (response.ok) {
            showToast('分享成功，等待消息发出', 'success');
        } else {
            showToast('分享失败', 'error');
        }
    } catch (error) {
        showToast('分享接口调用失败', 'error');
    }
}

/**
 * 处理分析
 */
export async function handleAnalyze(battle, profileData, key, confirmResult, buttonElement) {
    if (!isOfficialMap(battle.mapName)) {
        showToast('仅支持分析特定模式', 'warning');
        return;
    }

    if (!confirmResult || !confirmResult.confirmed) return;

    try {
        buttonElement.classList.add('loading');
        const params = new URLSearchParams({
            gameSvr: battle.gameSvrId || '',
            gameSeq: battle.gameSeq || '',
            targetRoleId: profileData.targetRoleId || '',
            relaySvr: battle.relaySvrId || '',
            battleType: battle.pvpType || 0,
            key,
            Special: confirmResult.special ? 'true' : 'false'
        });
        const response = await fetch(`/analyze-btldetail?${params.toString()}`);
        buttonElement.classList.remove('loading');
        if (response.ok) {
            showToast('分析请求已发送', 'success');
        } else {
            showToast('分析失败', 'error');
        }
    } catch (error) {
        buttonElement.classList.remove('loading');
        showToast('分析接口调用失败', 'error');
    }
}

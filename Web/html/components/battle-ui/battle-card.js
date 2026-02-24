/**
 * Battle Card Component
 * 处理战局卡片的渲染和事件绑定
 */

/**
 * 渲染单条战局卡片
 * @param {Object} battle 战局数据
 * @param {number} index 索引
 * @returns {string} HTML 字符串
 */
export function renderBattleCard(battle, index) {
    const gameResult = parseInt(battle.gameresult) || 0;
    const bgClass = gameResult === 1 ? 'win-bg' : 'lose-bg';
    
    const killcnt = parseInt(battle.killcnt) || 0;
    const deadcnt = parseInt(battle.deadcnt) || 0;
    const assistcnt = parseInt(battle.assistcnt) || 0;
    const mvpcnt = parseInt(battle.mvpcnt) || 0;
    const losemvp = parseInt(battle.losemvp) || 0;
    const gradeGame = parseFloat(battle.gradeGame) || 0;
    const gametime = battle.gametime || "";
    
    // 获取段位建议
    const roleJobName = battle.roleJobName || '';
    const stars = battle.stars || 0;
    const rankInfo = roleJobName ? `${roleJobName} ${stars}⭐` : '';
    
    // 巅峰分信息
    const oldMasterScore = parseInt(battle.oldMasterMatchScore) || 0;
    const newMasterScore = parseInt(battle.newMasterMatchScore) || 0;
    const scoreDiff = newMasterScore - oldMasterScore;
    
    let gameTypeInfo = '';
    if (battle.gametype === 14) { // 巅峰赛
        const scoreChangeText = scoreDiff > 0 ? `+${scoreDiff}` : `${scoreDiff}`;
        const scoreChangeClass = scoreDiff > 0 ? 'score-increase' : (scoreDiff < 0 ? 'score-decrease' : '');
        gameTypeInfo = `
            <div class="rank-value">
                ${oldMasterScore}→${newMasterScore} 
                <span class="${scoreChangeClass}">(${scoreChangeText})</span>
            </div>
        `;
    } else if (rankInfo) {
        gameTypeInfo = `<div class="rank-value">${rankInfo}</div>`;
    }
    
    const usedTime = battle.usedTime || 0;
    const gameTimeText = usedTime > 0 ? `${Math.floor(usedTime / 60)}分${usedTime % 60}秒` : '';
    
    // 特殊击杀
    let specialKills = [];
    if (battle.firstBlood > 0) specialKills.push('一血');
    if (battle.hero1TripleKillCnt > 0) specialKills.push('三杀');
    if (battle.hero1UltraKillCnt > 0) specialKills.push('四杀');
    if (battle.hero1RampageCnt > 0) specialKills.push('五杀');
    if (battle.godLikeCnt > 0) specialKills.push('超神');
    const specialKillText = specialKills.join(' ');

    return `
        <div class="battle-item ${bgClass}" data-index="${index}">
            <img src="${battle.heroIcon || ''}" alt="英雄头像" class="hero-icon" onerror="this.style.display='none'">
            <div class="battle-info">
                <div class="battle-header">
                    <div class="battle-title">
                        <strong style="font-size: 0.95rem; color: var(--dark-color);">${battle.mapName || '未知地图'}</strong>
                    </div>
                </div>
                <div class="battle-meta">
                    <div class="battle-time">
                        <div>${gametime}</div>
                        ${gameTimeText ? `<div>${gameTimeText}</div>` : ''}
                    </div>
                    <div class="game-type-info">
                        ${gameTypeInfo}
                    </div>
                </div>
                <div class="stats">
                    <div class="stat kda-stat">
                        <span class="stat-value">${killcnt}/${deadcnt}/${assistcnt}</span>
                    </div>
                    <div class="stat grade-stat">
                        <span class="stat-label">评分</span>
                        <span class="stat-value">${gradeGame.toFixed(1)}</span>
                    </div>
                    ${specialKillText ? `<div class="stat special-kills">${specialKillText}</div>` : ''}
                    ${(mvpcnt > 0 || losemvp > 0) ? `<div class="battle-badges"><span class="mvp-badge">MVP</span></div>` : ''}
                </div>
            </div>
            <div class="battle-actions">
                <button class="analyze-btn" title="分析战局">
                    <svg viewBox="0 0 24 24"><path d="M16,11.78L20.24,4.45L21.97,5.45L16.74,14.5L10.23,10.75L5.46,19H22V21H2V3H4V17.54L9.5,8L16,11.78Z"/></svg>
                </button>
                <button class="share-btn" title="分享战局">
                    <svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg>
                </button>
                <button class="favorite-btn" title="收藏战局">
                    <svg viewBox="0 0 24 24" class="heart-outline"><path d="M12,21.35L10.55,20.03C5.4,15.36 2,12.27 2,8.5 2,5.41 4.42,3 7.5,3C9.24,3 10.91,3.81 12,5.08C13.09,3.81 14.76,3 16.5,3C19.58,3 22,5.41 22,8.5C22,12.27 18.6,15.36 13.45,20.04L12,21.35Z"/></svg>
                    <svg viewBox="0 0 24 24" class="heart-filled" style="display: none;"><path d="M12,21.35L10.55,20.03C5.4,15.36 2,12.27 2,8.5 2,5.41 4.42,3 7.5,3C9.24,3 10.91,3.81 12,5.08C13.09,3.81 14.76,3 16.5,3C19.58,3 22,5.41 22,8.5C22,12.27 18.6,15.36 13.45,20.04L12,21.35Z"/></svg>
                </button>
            </div>
        </div>
    `;
}

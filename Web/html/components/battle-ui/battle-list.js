import { renderBattleCard } from './battle-card.js';
import { isTodayBattle } from './battle-utils.js';

/**
 * 渲染战局列表
 * @param {Array} battles 战局列表
 * @param {string} mapFilter 地图过滤
 * @param {boolean} todayOnly 是否只看今天
 * @param {HTMLElement} container 容器元素
 * @param {Object} callbacks 回调函数对象 { onCardClick, onFavorite, onShare, onAnalyze }
 */
export function renderBattleList(battles, mapFilter, todayOnly, container, callbacks) {
    if (!battles || battles.length === 0) {
        container.innerHTML = '<p>暂无比赛记录</p>';
        return;
    }

    let filteredBattles = battles;
    if (mapFilter && mapFilter !== '全部') {
        filteredBattles = filteredBattles.filter(b => (b.mapName || '').trim() === mapFilter);
    }
    if (todayOnly) {
        filteredBattles = filteredBattles.filter(b => isTodayBattle(b.dtEventTime));
    }

    container.innerHTML = '';
    
    filteredBattles.forEach((battle, index) => {
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = renderBattleCard(battle, index);
        const battleItem = tempDiv.firstElementChild;
        
        // 绑定事件
        battleItem.addEventListener('click', (e) => {
            if (e.target.closest('.analyze-btn') || e.target.closest('.share-btn') || e.target.closest('.favorite-btn')) {
                return;
            }
            if (callbacks.onCardClick) callbacks.onCardClick(battle, battleItem);
        });

        battleItem.querySelector('.analyze-btn').onclick = (e) => {
            e.stopPropagation();
            if (callbacks.onAnalyze) callbacks.onAnalyze(battle, e.currentTarget);
        };

        battleItem.querySelector('.share-btn').onclick = (e) => {
            e.stopPropagation();
            if (callbacks.onShare) callbacks.onShare(battle, e.currentTarget);
        };

        battleItem.querySelector('.favorite-btn').onclick = (e) => {
            e.stopPropagation();
            if (callbacks.onFavorite) callbacks.onFavorite(battle, e.currentTarget);
        };

        container.appendChild(battleItem);
    });

    return filteredBattles;
}

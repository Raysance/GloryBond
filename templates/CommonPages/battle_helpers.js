// Keep exact identifiers when reading legacy JSON containing signed int64 IDs.
function parseBattlePayload(text) {
    const exact = value => JSON.parse(value.replace(/"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, token => {
        if (/^-?\d+$/.test(token) && !Number.isSafeInteger(Number(token))) return JSON.stringify(token);
        return token;
    }));
    const result = exact(text);
    return typeof result === 'string' ? exact(result) : result;
}

function battleProfileRole(profile) {
    const roles = Array.isArray(profile?.roleList) ? profile.roleList.filter(role => role && typeof role === 'object') : [];
    const targetId = String(profile?.targetRoleId ?? '').trim();
    if (targetId) {
        return roles.find(role => String(role.roleId ?? '').trim() === targetId) || null;
    }
    return roles.length === 1 ? roles[0] : null;
}

function battleGrade(battle) {
    if (battle.gradeMissing || battle.GradeMissing) return null;
    const value = battle.gradeGame ?? battle.GameGrade;
    if (value == null || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function battleGradeLabel(battle) {
    const value = battleGrade(battle);
    return value == null ? '—' : (/^\d+\.\d$/.test(battle.gradeDisplay || '') ? battle.gradeDisplay : value.toFixed(1));
}

function battleSelectedSkillsHtml(records) {
    const skills = records.selectedSkills || [];
    if (!skills.length) return '';
    return '<div class="resonance-skills" aria-label="共鸣技能">' + skills.map(skill => {
        const name = battleText(skill.skillName || '—');
        const hero = battleText(skill.sourceHeroName || '');
        const description = String(skill.description || '').replace(/<[^>]*>/g, '');
        const title = battleText([skill.sourceHeroName, description].filter(Boolean).join(' · ') || skill.skillName || '—');
        const icon = /^https:\/\//.test(skill.sourceHeroIcon || '')
            ? `<img src="${battleText(skill.sourceHeroIcon)}" alt="${hero}" loading="lazy" decoding="async" onerror="this.style.display='none'">` : '';
        return `<span class="resonance-skill" title="${title}">${icon}<span>${name}</span></span>`;
    }).join('') + '</div>';
}

function battleAverageGrade(battles) {
    const values = battles.map(battleGrade).filter(value => value != null);
    return values.length ? (values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1) : '—';
}

function battleNumberLabel(value) {
    return value == null ? '—' : String(value);
}

function battleShareLabel(players, player, field) {
    const values = players.map(role => role.battleStats?.[field]);
    const own = player.battleStats?.[field];
    if (own == null || values.some(value => value == null)) return '—';
    const total = values.reduce((sum, value) => sum + Number(value), 0);
    return (total > 0 ? Math.round(Number(own) / total * 100) : 0) + '%';
}

function battleText(value) {
    return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}

function battleDetailUrl(player, game, key) {
    const params = game.Params || {};
    const gameSeq = String(params.gameseq || game.GameSeq || game.gameSeq || '');
    const role = player && (player.roleid || player.roleId || player.RoleId || player.targetRoleId);
    if (!/^-?\d+$/.test(gameSeq) || !role) return '';
    const gameSvr = params.gameSvrId || game.gameSvrId || '';
    const relaySvr = params.relaySvrId || game.relaySvrId || '';
    const battleType = params.pvptype || game.pvpType || game.MapType || 0;
    if (!gameSeq.startsWith('-') && (!gameSvr || !relaySvr || !battleType)) return '';
    return '/jump-battle?' + new URLSearchParams({gameSeq, targetRoleId: String(role),
        gameSvr: String(gameSvr), relaySvr: String(relaySvr), battleType: String(battleType), key});
}

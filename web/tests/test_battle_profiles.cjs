const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const base = require('node:path').join(__dirname, '../templates/CommonPages/');
const helpers = fs.readFileSync(base + 'battle_helpers.js', 'utf8');
const other = {roleId: '4438195026', roleName: '其他角色', roleJobName: '青铜'};
const target = {roleId: '2000000078', roleName: '目标<玩家>', roleJobName: '永恒钻石III', roleIcon: 'https://example.com/avatar.png'};
const profile = {targetRoleId: 2000000078, roleList: [other, target], head: {mods: [
    {name: '总场次', content: '3351'}, {name: 'MVP', content: '422'}, {name: '胜率', content: '53.39%'}
]}};

const helperScope = vm.createContext({});
vm.runInContext(helpers, helperScope);
assert.equal(helperScope.battleProfileRole(profile), target);
assert.equal(helperScope.battleProfileRole({...profile, targetRoleId: '2000000078'}), target);
assert.equal(helperScope.battleProfileRole({targetRoleId: '2000000078', roleList: [{...target, roleId: 2000000078}]}).roleName, target.roleName);
assert.equal(helperScope.battleProfileRole({roleList: [target]}), target);
for (const invalid of [null, {}, {roleList: []}, {roleList: [null]}, {roleList: [other, target]},
    {...profile, targetRoleId: '999'}, {targetRoleId: 999, roleList: [target]}]) {
    assert.equal(helperScope.battleProfileRole(invalid), null);
}
const exact = helperScope.parseBattlePayload('{"targetRoleId":9223372036854775806,"roleList":[{"roleId":"9223372036854775806","roleName":"精确角色"}]}');
assert.equal(helperScope.battleProfileRole(exact).roleName, '精确角色');

function extract(source, name) {
    const match = source.match(new RegExp('        function ' + name + '\\([^\\n]*\\) \\{[\\s\\S]*?\\n        \\}'));
    assert.ok(match, name);
    return match[0];
}

for (const template of ['SingleBattleList.html', 'SinglePeriodBattleList.html', 'BattleQuery.html']) {
    const source = fs.readFileSync(base + template, 'utf8').replace(/\r\n/g, '\n');
    const elements = Object.fromEntries(['playerName', 'playerTitle', 'playerAvatar', 'playerProfileSummary',
        'periodMetaSummary', 'playerStats', 'totalBattles', 'mvpCount', 'winRate'].map(id => [id, {textContent: '', style: {}}]));
    const avatar = elements.playerAvatar;
    avatar.style.display = 'none';
    avatar.complete = false;
    avatar.naturalWidth = 0;
    let timer = 0;
    const pending = new Map();
    const scope = vm.createContext({document: {getElementById: id => elements[id]}, console,
        setTimeout: callback => {pending.set(++timer, callback); return timer;},
        clearTimeout: id => pending.delete(id), requestAnimationFrame() {}, updateGlassTopSpace() {}});
    vm.runInContext(helpers + '\n' + extract(source, 'updatePlayerProfile') +
        (template === 'SinglePeriodBattleList.html' ? '' : '\n' + extract(source, 'handleImageLoad') + '\n' + extract(source, 'switchToFallback')), scope);

    scope.updatePlayerProfile(profile);
    assert.equal(elements.playerName.textContent, target.roleName, template);
    assert.equal(elements.playerTitle.textContent, target.roleJobName, template);
    assert.equal(avatar.src, target.roleIcon, template);
    if (avatar.onload) avatar.onload();
    assert.equal(avatar.style.display, 'block', template);
    if (template !== 'SinglePeriodBattleList.html') {
        assert.equal(elements.totalBattles.textContent, '3351', template);
        assert.equal(elements.mvpCount.textContent, '422', template);
        assert.equal(elements.winRate.textContent, '53.39%', template);
        let removed = false;
        avatar.nextElementSibling = {classList: {contains: value => value === 'img-placeholder'}, remove() {removed = true;}};
        avatar.complete = true;
        avatar.naturalWidth = 100;
        avatar.style.display = 'none';
        scope.updatePlayerProfile(profile);
        assert.equal(avatar.style.display, 'block', template + ': cached avatar recovers');
        assert.ok(removed, template + ': stale fallback removed');
        assert.equal(pending.size, 0, template + ': no stale image timers');
    }
}
console.log('Battle profiles: mixed and exact IDs, correct bound role, missing targets, names, titles and cached avatars passed');

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const base = require('node:path').join(__dirname, '../templates/CommonPages/');
const scope = vm.createContext({URLSearchParams});
vm.runInContext(fs.readFileSync(base + 'battle_helpers.js', 'utf8'), scope);
assert.equal(scope.battleGradeLabel({gradeGame: 8.35, gradeDisplay: '8.4'}), '8.4');
assert.equal(scope.battleGradeLabel({gradeGame: 0, gradeDisplay: '0.0'}), '0.0');
assert.equal(scope.battleGradeLabel({gradeGame: null}), '—');
const html = scope.battleSelectedSkillsHtml({selectedSkills: [
    {skillName: '姜子牙被动', sourceHeroName: '姜子牙', sourceHeroIcon: 'https://example.com/148.jpg'},
    {skillName: '空空儿大招'}, {skillName: '巨人之握被动'},
    {skillName: '<img src=x onerror=alert(1)>', description: '<color=red>文本</color> "', sourceHeroIcon: 'javascript:alert(1)'}
]});
assert.equal((html.match(/class="resonance-skill"/g) || []).length, 4);
assert.ok(html.indexOf('姜子牙被动') < html.indexOf('空空儿大招'));
assert.ok(html.includes('巨人之握被动'));
assert.ok(!html.includes('javascript:'));
assert.ok(!html.includes('<img src=x'));
assert.ok(html.includes('&lt;img'));
assert.equal(scope.battleSelectedSkillsHtml({}), '');
const savedShare = scope.battleShareParams({gameSeq: '-9223372036854775806', head: {roleId: '42'}, battle: {}}, {key: 'valid'});
assert.equal(savedShare.get('gameSeq'), '-9223372036854775806');
assert.equal(savedShare.get('targetRoleId'), '42');
assert.equal(savedShare.get('key'), 'valid');
assert.equal(savedShare.get('gameSvr'), '');
const routedShare = scope.battleShareParams({}, {gameSeq: '123', targetRoleId: '42', gameSvr: '1', relaySvr: '2', battleType: '4', key: 'valid'});
assert.equal(routedShare.get('gameSvr'), '1');
assert.equal(routedShare.get('battleType'), '4');

function emptyRouteTemplate(action) {
    return action.replace(/(['"]){{\s*key\s*}}\1/g, '"valid"')
        .replace(/(['"]){{.*?}}\1/g, '""')
        .replace(/{{ key\|.*?}}/g, '"valid"').replace(/{{.*?}}/g, '""');
}

(async () => {
    for (const name of ['SingleBattleList.html', 'SinglePeriodBattleList.html', 'BattleQuery.html', 'BattleDetail.html']) {
        const source = fs.readFileSync(base + name, 'utf8').replace(/\r\n/g, '\n');
        const match = source.match(/        async function handleShare\([^\n]*\) \{[\s\S]*?\n        \}/);
        assert.ok(match, name);
        let confirmed = 0;
        const warnings = [];
        const test = vm.createContext({console, URLSearchParams, battleShareParams: scope.battleShareParams,
            lastShareTime: 0, SHARE_COOLDOWN: 10000,
            battleData: {gameSeq: '-123', head: {roleId: '42'}, battle: {mapName: '共鸣之战'}},
            showShareConfirm: async () => {confirmed++; return false;},
            showToast: value => warnings.push(value)});
        const action = name === 'BattleDetail.html' ? emptyRouteTemplate(match[0]) : match[0];
        vm.runInContext(action, test);
        await test.handleShare({mapName: '共鸣之战'}, {}, {});
        assert.equal(confirmed, 1, name + ': resonance reaches the existing share confirmation');
        assert.equal(warnings.length, 0, name);
    }
    const detailSource = fs.readFileSync(base + 'BattleDetail.html', 'utf8').replace(/\r\n/g, '\n');
    const shareAction = emptyRouteTemplate(detailSource.match(/        async function handleShare\([^\n]*\) \{[\s\S]*?\n        \}/)[0]);
    let requested;
    const detailScope = vm.createContext({console, URLSearchParams, lastShareTime: 0, SHARE_COOLDOWN: 10000,
        battleData: {gameSeq: '-9223372036854775806', head: {roleId: '42'}, battle: {mapName: '共鸣之战'}},
        showShareConfirm: async () => true, showToast() {},
        fetch: async url => {requested = url; return {ok: true, json: async () => ({success: true})};}});
    vm.runInContext(fs.readFileSync(base + 'battle_helpers.js', 'utf8') + '\n' + shareAction, detailScope);
    await detailScope.handleShare();
    const params = new URL(requested, 'https://example.com').searchParams;
    assert.equal(params.get('gameSeq'), '-9223372036854775806');
    assert.equal(params.get('targetRoleId'), '42');
    assert.equal(params.get('key'), 'valid');
    console.log('Entertainment sharing: four share entries, skill order and escaping, and exact grade labels passed');
})().catch(error => {console.error(error); process.exitCode = 1;});

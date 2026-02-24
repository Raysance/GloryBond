// 公式实现与交互
// sigmoid(x) = 1 / (1 + e^-x)
function sigmoid(x) {
  return 1 / (1 + Math.exp(-x));
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

function fmt(n) {
  if (!isFinite(n)) return "--";
  if (n === 0) return "0";
  if (n >= 100000) return n.toFixed(0);
  if (n >= 1000) return n.toFixed(2);
  if (n >= 10) return n.toFixed(3);
  return n.toFixed(4);
}

function parseNum(input) {
  const v = Number(input.value);
  return isFinite(v) ? v : 0;
}

function compute(form) {
  const TotalCnt = clamp(Math.floor(parseNum(form.TotalCnt)), 0, 20000);
  const MVPCnt = clamp(Math.floor(parseNum(form.MVPCnt)), 0, TotalCnt);
  const winNum = clamp(Math.floor(parseNum(form.winNum)), 0, 1000);
  const loseNum = clamp(Math.floor(parseNum(form.loseNum)), 0, 1000);
  const HeroShowCnt = Math.max(0, winNum + loseNum);
  form.HeroShowCnt.value = HeroShowCnt;

  const is_auth = String(form.is_auth.value) === "true";
  const starNum = clamp(parseNum(form.starNum), 40, 150);
  const peakScore = clamp(parseNum(form.peakScore), 600, 2500);
  const PowerNum = clamp(parseNum(form.PowerNum), 0, 200000);
  const avgScore = clamp(parseNum(form.avgScore), 2, 16);
  const heroPower = clamp(parseNum(form.heroPower), 0, 20000);

  // MVPRate
  const MVPRate = TotalCnt > 0 ? Math.min(MVPCnt / TotalCnt, 1) : 0;
  // auth coeff
  const auth_coeff = is_auth ? 1 : 0.6;
  // equiv_star 下界 1
  const equiv_star_raw = (starNum - 25) + (peakScore - 1200) / 15.0;
  const equiv_star = Math.max(1, equiv_star_raw);

  const single_level = Math.pow(equiv_star, 0.3)
    * Math.pow(sigmoid(MVPRate), 4)
    * Math.pow((PowerNum / 10000), 0.85)
    * Math.pow(avgScore, 1)
    * Math.pow(sigmoid(HeroShowCnt / 10), 1.3)
    * Math.pow(sigmoid(heroPower / 10000), 2)
    * auth_coeff;

  return { MVPRate, auth_coeff, equiv_star, single_level };
}

// 动态约束：MVPCnt 的最大值不超过 TotalCnt
function enforceConstraints(form) {
  if (!form) return;
  const total = clamp(Math.floor(parseNum(form.TotalCnt)), 0, 20000);
  // number input max
  if (form.MVPCnt) {
    form.MVPCnt.max = String(total);
    // 夹取 MVPCnt 值
    const cur = clamp(Math.floor(parseNum(form.MVPCnt)), 0, total);
    if (String(cur) !== form.MVPCnt.value) form.MVPCnt.value = String(cur);
  }
  // range max
  const range = form.querySelector('input[type="range"][data-for="MVPCnt"]');
  if (range) {
    range.max = String(total);
    // 同步 range 值到夹取后的 MVPCnt
    if (form.MVPCnt) range.value = form.MVPCnt.value;
  }
}

function updateCard(card) {
  const form = card.querySelector('form');
  const res = compute(form);
  card.querySelector('[data-field="MVPRate"]').textContent = fmt(res.MVPRate);
  card.querySelector('[data-field="auth_coeff"]').textContent = fmt(res.auth_coeff);
  card.querySelector('[data-field="equiv_star"]').textContent = fmt(res.equiv_star);
  const scoreEl = card.querySelector('[data-field="single_level"]');
  scoreEl.textContent = fmt(res.single_level);
  return res.single_level;
}

// 条形图：使用子节点 .fill 控制宽度
function ensureBarChildren() {
  ['barA','barB'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (!el.querySelector('.fill')) {
      const fill = document.createElement('div');
      fill.className = 'fill';
      el.appendChild(fill);
    }
  });
}

function setBarWidth(id, pct, color) {
  const el = document.getElementById(id);
  if (!el) return;
  const fill = el.querySelector('.fill');
  if (!fill) return;
  fill.style.width = pct + '%';
  if (color) fill.style.background = color;
}

function updateBars(sa, sb) {
  const max = Math.max(sa, sb, 1e-9);
  const pa = clamp((sa / max) * 100, 0, 100);
  const pb = clamp((sb / max) * 100, 0, 100);
  setBarWidth('barA', pa, getComputedStyle(document.documentElement).getPropertyValue('--a'));
  setBarWidth('barB', pb, getComputedStyle(document.documentElement).getPropertyValue('--b'));
  const diff = sa - sb;
  const ratio = sb > 0 ? sa / sb : Infinity;
//   const text = `A: ${fmt(sa)}  vs  B: ${fmt(sb)}  |  差值 ${fmt(diff)}  比值 ${isFinite(ratio)?fmt(ratio):'∞'}`;
  const text = `A: ${fmt(sa)}  vs  B: ${fmt(sb)} `;
  const delta = document.getElementById('delta');
  if (delta) delta.textContent = text;
  updateFloatingScores(sa, sb);
}

// 更新移动端固定底栏中的 A/B 分数
function updateFloatingScores(sa, sb) {
  const wrap = document.getElementById('floatingScores');
  if (!wrap) return;
  const a = wrap.querySelector('.a .value');
  const b = wrap.querySelector('.b .value');
  if (a) a.textContent = fmt(sa);
  if (b) b.textContent = fmt(sb);
}

function randomInt(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }
function randomFloat(min, max, digits = 1) {
  const v = Math.random() * (max - min) + min;
  const f = Number(v.toFixed(digits));
  return f;
}

function randomize(form) {
  // 在各自合法范围内进行“均匀采样”
  const TotalCnt = randomInt(0, 20000);
  const MVPCnt = randomInt(0, TotalCnt);
  // 该英雄对局：先随机一个总场次，再在[0,总场次]均匀切分胜/负
  const heroTotal = randomInt(0, 1000);
  const winNum = randomInt(0, heroTotal);
  const loseNum = heroTotal - winNum;
  const is_auth = Math.random() < 0.5;
  const starNum = randomInt(40, 150);
  const peakScore = randomInt(600, 2500);
  const PowerNum = randomInt(0, 200000);
  const avgScore = randomFloat(2, 16, 1);
  const heroPower = randomInt(0, 20000);

  form.TotalCnt.value = TotalCnt;
  form.MVPCnt.value = MVPCnt;
  form.winNum.value = winNum;
  form.loseNum.value = loseNum;
  form.is_auth.value = String(is_auth);
  form.starNum.value = starNum;
  form.peakScore.value = peakScore;
  form.PowerNum.value = PowerNum;
  form.avgScore.value = avgScore;
  form.heroPower.value = heroPower;
  syncRangesFromNumbers(form);
}

// 设定指定的默认值（非随机）
function setDefaults(form) {
  form.winNum.value = 10;      // 当前英雄胜场
  form.loseNum.value = 10;     // 当前英雄败场
  form.avgScore.value = 9;     // 当前英雄平均评分
  // 胜率 0.5 由 winNum/(winNum+loseNum) 隐式决定
  form.starNum.value = 50;     // 总星数
  form.peakScore.value = 1200; // 巅峰分数
  form.PowerNum.value = 70000; // 总战斗力
  form.TotalCnt.value = 1000;  // 总场次
  form.MVPCnt.value = 100;     // 总 MVP 场次
  form.heroPower.value = 1000; // 当前英雄战力
  // 授权默认选“已授权”
  if (form.is_auth) form.is_auth.value = 'true';
  syncRangesFromNumbers(form);
}

// 将数字输入的值同步到对应的 range
function syncRangesFromNumbers(form) {
  const nums = form.querySelectorAll('input[type="number"][name]');
  nums.forEach(n => {
    const r = form.querySelector(`input[type="range"][data-for="${n.name}"]`);
    if (r) r.value = n.value;
  });
}

// 绑定 number <-> range 双向联动
function bindRanges(form) {
  // range -> number
  form.querySelectorAll('input[type="range"][data-for]').forEach(r => {
    r.addEventListener('input', () => {
      const name = r.getAttribute('data-for');
      const n = form.querySelector(`input[type="number"][name="${name}"]`);
      if (n) {
        n.value = r.value;
        // 触发 form 的 input 事件链以便重算
        n.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
  });
  // number -> range
  form.querySelectorAll('input[type="number"][name]').forEach(n => {
    n.addEventListener('input', () => {
      const r = form.querySelector(`input[type="range"][data-for="${n.name}"]`);
      if (r) r.value = n.value;
    });
  });
}

function attach(card) {
  const form = card.querySelector('form');
  // 输入变动联动
  form.addEventListener('input', () => {
    enforceConstraints(form);
    const sa = updateCard(document.getElementById('playerA'));
    const sb = updateCard(document.getElementById('playerB'));
    updateBars(sa, sb);
  });
  // 按钮
  card.querySelector('[data-action="random"]').addEventListener('click', () => {
    randomize(form);
    enforceConstraints(form);
    const sa = updateCard(document.getElementById('playerA'));
    const sb = updateCard(document.getElementById('playerB'));
    updateBars(sa, sb);
  });
  card.querySelector('[data-action="calc"]').addEventListener('click', () => {
    enforceConstraints(form);
    const sa = updateCard(document.getElementById('playerA'));
    const sb = updateCard(document.getElementById('playerB'));
    updateBars(sa, sb);
  });
}

function init() {
  ensureBarChildren();
  const A = document.getElementById('playerA');
  let B = document.getElementById('playerB');
  // 如果页面未写 B 卡片，则在此克隆 A，避免重复写两份表单结构
  if (!B && A) {
    const grid = document.querySelector('.grid');
    const clone = A.cloneNode(true);
    clone.id = 'playerB';
    const title = clone.querySelector('h2');
    if (title) title.textContent = '玩家 B';
    const f = clone.querySelector('form');
    if (f) f.reset();
    clone.querySelectorAll('[data-field]').forEach(el => (el.textContent = '--'));
    if (grid) grid.appendChild(clone);
    B = clone;
  }

  if (!A || !B) return;

  attach(A);
  attach(B);
  bindRanges(A.querySelector('form'));
  bindRanges(B.querySelector('form'));

  // 顶部按钮
  document.getElementById('randomBoth').addEventListener('click', () => {
    randomize(A.querySelector('form'));
    randomize(B.querySelector('form'));
    enforceConstraints(A.querySelector('form'));
    enforceConstraints(B.querySelector('form'));
    const sa = updateCard(A);
    const sb = updateCard(B);
    updateBars(sa, sb);
  });
  document.getElementById('resetBoth').addEventListener('click', () => {
    // 设为固定默认值
    setDefaults(A.querySelector('form'));
    setDefaults(B.querySelector('form'));
    enforceConstraints(A.querySelector('form'));
    enforceConstraints(B.querySelector('form'));
    const sa = updateCard(A);
    const sb = updateCard(B);
    updateBars(sa, sb);
  });

  // 初始随机
  setDefaults(A.querySelector('form'));
  setDefaults(B.querySelector('form'));
  enforceConstraints(A.querySelector('form'));
  enforceConstraints(B.querySelector('form'));
  const sa = updateCard(A);
  const sb = updateCard(B);
  updateBars(sa, sb);
}

document.addEventListener('DOMContentLoaded', init);

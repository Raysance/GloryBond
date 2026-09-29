(() => {
  'use strict';
  const trace = JSON.parse(document.getElementById('trace-data').textContent);
  const $ = id => document.getElementById(id);
  const el = (tag, className = '', text = '') => {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = String(text ?? '');
    return node;
  };
  const json = value => JSON.stringify(value, null, 2);
  const brief = value => (typeof value === 'string' ? value : JSON.stringify(value))?.replace(/\s+/g, ' ').slice(0, 170) || '—';
  const ms = value => Number(value || 0) < 1000 ? `${Math.round(Number(value || 0))} ms` : `${(Number(value) / 1000).toFixed(2)} s`;
  const states = {ok:'已完成', error:'失败', partial:'部分失败', skipped:'未执行'};
  const labels = {user:'用户', context:'上下文', model:'助手', tool:'工具'};
  const summary = trace.summary || {};
  $('title').textContent = trace.question || 'HOK 运行记录';
  $('title').title = trace.question || '';
  $('model').textContent = trace.model || '';
  $('run-status').textContent = `${states[trace.status] || trace.status} · ${ms(trace.duration_ms)}`;
  $('run-status').className = trace.status;
  $('duration-toggle').textContent = `◷ 时长 ${ms(trace.duration_ms)}`;
  $('round-toggle').textContent = `⊟ 轮次 ${summary.model_calls || 0}`;
  $('call-toggle').textContent = `⊟ 调用 ${summary.tool_calls || 0}`;
  $('footer').textContent = `${trace.started_at || ''} · ${trace.model || ''} · 完整请求 / 响应 payload，凭据脱敏，不含 headers · 链接保留 ${Number(trace.expires_in_seconds || 604800) / 86400} 天`;
  $('question').textContent = trace.question || '';
  $('answer').textContent = trace.answer || `未完成回答：${trace.error || '未知错误'}`;

  function charts(parent) {
    for (const [index, artifact] of (trace.artifacts || []).entries()) {
      if (!/^\/file_transfer\/chat_plot_[0-9a-f]{32}\.png$/.test(artifact.url)) continue;
      const button = el('button', 'chart');
      const image = el('img');
      image.src = artifact.url; image.alt = `图表 ${index + 1}`; image.loading = 'lazy';
      button.append(image, el('span', '', `图表 ${index + 1} · 查看原图`));
      image.addEventListener('error', () => { button.lastChild.textContent = `图表 ${index + 1} 已清理或暂不可用`; });
      button.addEventListener('click', () => { $('full-image').src = artifact.url; $('image-dialog').showModal(); });
      parent.append(button);
    }
  }
  charts($('charts'));
  if (trace.delivery?.merged) $('answer').after(el('p', 'note', `QQ 回复已将 ${trace.delivery.source_images} 张图表合为一张；此处保留原图。`));
  $('close-image').addEventListener('click', () => $('image-dialog').close());
  $('image-dialog').addEventListener('click', event => { if (event.target === $('image-dialog')) $('image-dialog').close(); });

  const records = [], groups = [];
  let selected, activeTab = 'summary', collapsed = false;
  function addRecord(group, data) {
    const item = {...data, id: `step-${records.length}`};
    item.searchable = `${item.title} ${states[item.status] || ''} ${json(item.input)} ${json(item.output)}`.toLowerCase();
    const row = el('button', 'event');
    row.id = item.id;
    row.setAttribute('aria-label', `${labels[item.kind]} ${item.title}`);
    row.setAttribute('aria-pressed', 'false');
    const tagClass = item.status === 'error' || item.status === 'partial' ? 'error' : item.kind;
    row.append(el('span', `tag ${tagClass}`, labels[item.kind]));
    const body = el('span', 'event-body');
    body.append(el('div', 'event-title', item.title));
    if (item.kind === 'tool') body.append(el('div', 'event-preview', `${brief(item.input)} → ${brief(item.output)}`));
    row.append(body, el('span', 'event-time', ms(item.duration_ms)));
    row.addEventListener('click', () => select(item));
    item.row = row; records.push(item); group.body.append(row); group.items.push(item);
    return item;
  }
  function addGroup(title) {
    const wrapper = el('section', 'round-group'), body = el('div', 'round-body');
    const button = el('button', 'round-label', title);
    button.setAttribute('aria-expanded', 'true');
    button.addEventListener('click', () => { body.hidden = !body.hidden; button.setAttribute('aria-expanded', String(!body.hidden)); });
    wrapper.append(button, body); $('events').append(wrapper);
    const group = {wrapper, body, button, items:[]}; groups.push(group); return group;
  }
  const inputGroup = addGroup('输入');
  addRecord(inputGroup, {kind:'user', title:trace.question, input:trace.question, output:null, round:0, start_ms:0, duration_ms:0, status:'ok'});
  const context = trace.context || {};
  const quoteStates = {read:'已读取本次引用消息', unavailable:'引用消息不可用', none:'无引用消息'};
  const contextText = `${quoteStates[context.quote] || '无引用消息'}；${context.recent_dialogue_enabled ? '已启用近期直接对话' : '记忆已关闭'}`;
  addRecord(inputGroup, {kind:'context', title:contextText, input:context, output:'完整模型上下文见每轮助手步骤的参数；工具返回内容见工具步骤的结果。', round:0, start_ms:0, duration_ms:0, status:'ok'});
  for (const [index, turn] of (trace.rounds || []).entries()) {
    const group = addGroup(`第 ${turn.index} 轮${turn.phase === 'recovery' ? ' · 空回复补试' : turn.phase === 'final' ? ' · 收束回答' : ''}`);
    const final = index === trace.rounds.length - 1 && turn.status !== 'error';
    const output = Object.hasOwn(turn, 'response_payload') ? turn.response_payload : turn.status === 'error' ? {error:turn.error} : turn.tools.length ? {requested_tools:turn.tools.map(call => call.name)} : trace.answer;
    addRecord(group, {kind:'model', title:turn.status === 'error' ? `模型步骤失败：${turn.error}` : turn.tools.length ? `请求 ${turn.tools.length} 个工具` : brief(trace.answer),
      input:turn.request_payload ?? {model:trace.model, phase:turn.phase, notice:'此历史记录未采集请求 payload'}, output,
      metadata:turn.response_meta, diagnostics:turn.diagnostics,
      round:turn.index, start_ms:turn.start_ms, duration_ms:turn.duration_ms, status:turn.status, final:final && !turn.tools.length});
    for (const [step, call] of turn.tools.entries()) addRecord(group, {...call, kind:'tool', title:call.name,
      input:call.arguments, output:call.observation, round:turn.index, step:step + 1, schema:trace.schemas?.[call.name]});
  }
  if (trace.failure || trace.warnings?.length || trace.recovery?.outcome === 'fallback') {
    const group = addGroup('运行诊断');
    addRecord(group, {kind:'context', title:trace.failure ? `失败阶段：${trace.failure.stage}` : '降级与警告',
      input:null, output:{failure:trace.failure, warnings:trace.warnings, recovery:trace.recovery},
      round:0, start_ms:trace.duration_ms, duration_ms:0, status:trace.failure ? 'error' : 'partial'});
  }
  const empty = el('p', 'empty', '没有匹配的记录'); empty.hidden = true; $('events').append(empty);

  const tracks = {};
  for (const [kind, label] of [['input','输入'],['model','模型'],['tool','工具']]) {
    const lane = el('div', 'lane'), track = el('div', 'lane-track');
    lane.append(el('span', 'lane-label', label), track); $('overview').append(lane); tracks[kind] = track;
  }
  const total = Math.max(1, Number(trace.duration_ms));
  for (const item of records) {
    const kind = ['user','context'].includes(item.kind) ? 'input' : item.kind;
    const block = el('button', `time-block ${kind} ${item.status === 'error' ? 'error' : ''}`);
    block.style.left = `${Math.min(99, Number(item.start_ms || 0) / total * 100)}%`;
    block.style.width = `${Math.max(.35, Math.min(100 - Number(item.start_ms || 0) / total * 100, Number(item.duration_ms || 0) / total * 100))}%`;
    if (item.kind === 'context') block.style.left = '0.8%';
    block.title = `${labels[item.kind]} · ${item.title} · ${ms(item.duration_ms)}`;
    block.setAttribute('aria-label', block.title);
    block.addEventListener('click', () => { select(item); const group = groups.find(group => group.items.includes(item)); group.body.hidden = false; group.button.setAttribute('aria-expanded','true'); item.row.scrollIntoView({block:'nearest'}); });
    tracks[kind].append(block); item.block = block;
  }
  function keyValues(parent, entries) {
    const list = el('dl', 'kv');
    entries.forEach(([label, value]) => list.append(el('dt', '', label), el('dd', '', value)));
    parent.append(list);
  }
  function code(parent, title, value, language='') {
    const heading = el('h3', 'section-title', title), copy = el('button', '', '复制');
    const text = typeof value === 'string' ? value : json(value) || '—';
    copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(text); copy.textContent='已复制'; } catch { copy.textContent='请手动复制'; } });
    heading.append(copy); parent.append(heading, el('pre', `code ${language}`, text));
  }
  function inputDetails(parent, item) {
    if (item.title === 'query_game_database' && Array.isArray(item.input?.queries)) {
      item.input.queries.forEach((query,index) => {
        code(parent, `SQL ${index+1}${query.label ? ' · '+query.label : ''}`, query.sql, 'sql');
        if (query.params) code(parent, '参数', query.params);
      });
      if (item.input.limit) parent.append(el('p', 'note', `每条 SQL 最多返回 ${item.input.limit} 行`));
    } else if (item.input?.code) {
      code(parent, 'Python', item.input.code, 'python');
      const params = {...item.input}; delete params.code; code(parent, '参数', params);
    } else code(parent, item.kind === 'model' ? '完整请求 payload' : '参数', item.input);
  }
  function resultDetails(parent, item) {
    const observations = item.output?.data?.observations;
    if (Array.isArray(observations)) observations.forEach((value,index) => {
      parent.append(el('h3','section-title', `Observation ${index+1} · ${value.label || value.dataset_id || ''} · ${value.ok === false ? '失败' : '完成'}`));
      if (Array.isArray(value.rows) && value.rows.length) {
        const wrap=el('div','table-wrap'), table=el('table'), head=el('thead'), header=el('tr'), body=el('tbody');
        const columns=(value.columns || Object.keys(value.rows[0])).slice(0,24);
        columns.forEach(column=>header.append(el('th','',column))); head.append(header); table.append(head);
        value.rows.slice(0,15).forEach(row=>{const line=el('tr'); columns.forEach(column=>line.append(el('td','',typeof row[column] === 'object' ? json(row[column]) : row[column]))); body.append(line);});
        table.append(body); wrap.append(table); parent.append(wrap);
        parent.append(el('p','note', `预览 ${Math.min(15,value.rows.length)} 行 / 返回 ${value.row_count ?? value.rows.length} 行${value.truncated || value.context_truncated ? ' · 结果已截断' : ''}`));
      }
      const raw=el('details'); raw.append(el('summary','','Observation JSON'),el('pre','code',json(value)));
      raw.open=value.ok === false || !value.rows?.length; parent.append(raw);
    });
    else if (typeof item.output === 'string') parent.append(el('div','prose',item.output));
    else code(parent,item.kind === 'model' ? '完整响应 payload' : '结果',item.output);
    if (item.metadata) code(parent,'结束原因与用量',item.metadata);
    if (item.diagnostics) code(parent,'错误阶段与异常链',item.diagnostics);
    if (item.final) {const gallery=el('div','charts'); charts(gallery); parent.append(gallery);}
  }
  function timing(parent,item) {
    keyValues(parent,[['记录开始',trace.started_at || '—'],['开始偏移',`+${ms(item.start_ms)}`],['时长',ms(item.duration_ms)],['计时来源','服务端单调时钟'],['层级',item.round ? `第 ${item.round} 轮${item.step ? ' · 第 '+item.step+' 步' : ' · 模型请求'}` : '用户输入']]);
  }
  function renderDetails() {
    if (!selected) return;
    const item=selected, parent=$('detail-content'); parent.replaceChildren();
    $('detail-kind').className=`tag ${item.kind}`; $('detail-kind').textContent=labels[item.kind];
    $('detail-step').textContent=item.round ? `第 ${item.round} 轮${item.step ? ' · 第 '+item.step+' 步' : ''}` : '本次输入';
    document.querySelectorAll('[data-tab]').forEach(button=>{const active=button.dataset.tab === activeTab; button.classList.toggle('active',active); button.setAttribute('aria-selected',String(active));});
    if (activeTab === 'summary') {
      keyValues(parent,[['类型',item.kind === 'tool' ? item.name : labels[item.kind]],['状态',states[item.status] || item.status],['耗时',ms(item.duration_ms)]]);
      if (item.kind === 'tool') inputDetails(parent,item);
      resultDetails(parent,item);
      if (item.schema) {
        const schema=el('details');schema.append(el('summary','','Schema'),el('pre','code',json(item.schema)));parent.append(schema);
      }
      parent.append(el('h3','section-title','计时'));
      timing(parent,item);
      if (item.call_id) parent.append(el('p','note',`调用 ID：${item.call_id}`));
    } else if (activeTab === 'input') inputDetails(parent,item);
    else if (activeTab === 'output') resultDetails(parent,item);
    else if (activeTab === 'schema') {
      if (item.schema) code(parent,'工具 Schema',item.schema);
      else parent.append(el('p','note',item.kind === 'tool' ? '此调用未保存工具 Schema。' : '此步骤不是工具调用。'));
    } else timing(parent,item);
  }
  function select(item) {
    selected=item;
    records.forEach(record=>{const active=record===item; record.row.classList.toggle('selected',active); record.row.setAttribute('aria-pressed',String(active)); record.block?.classList.toggle('selected',active);});
    $('inspector').hidden=false; renderDetails();
  }
  document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{activeTab=button.dataset.tab;renderDetails();}));
  $('close-detail').addEventListener('click',()=>{$('inspector').hidden=true; selected?.row.focus();});
  $('search').addEventListener('input',()=>{
    const query=$('search').value.trim().toLowerCase();
    records.forEach(item=>{item.row.hidden=!item.searchable.includes(query);});
    groups.forEach(group=>{group.wrapper.hidden=group.items.every(item=>item.row.hidden); if(query){group.body.hidden=false;group.button.setAttribute('aria-expanded','true');}});
    empty.hidden=records.some(item=>!item.row.hidden);
  });
  $('duration-toggle').addEventListener('click',()=>{const hidden=$('events').classList.toggle('hide-durations');$('duration-toggle').setAttribute('aria-pressed',String(!hidden));});
  $('call-toggle').addEventListener('click',()=>{const hidden=$('events').classList.toggle('hide-previews');$('call-toggle').setAttribute('aria-pressed',String(!hidden));});
  $('round-toggle').addEventListener('click',()=>{collapsed=!collapsed;groups.forEach(group=>{group.body.hidden=collapsed;group.button.setAttribute('aria-expanded',String(!collapsed));});$('round-toggle').setAttribute('aria-pressed',String(!collapsed));});
  document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('[data-view]').forEach(tab=>{tab.classList.toggle('active',tab===button);tab.setAttribute('aria-pressed',String(tab===button));});
    $('chat-view').hidden=button.dataset.view!=='chat';$('trace-view').hidden=button.dataset.view!=='trace';
  }));
  $('export').addEventListener('click',()=>{
    const url=URL.createObjectURL(new Blob([json(trace)],{type:'application/json'}));
    const link=el('a');link.href=url;link.download='hok-execution-trace.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  select(records.find(item=>item.kind==='tool') || records[records.length-1]);
  if (window.matchMedia('(max-width:650px)').matches) $('inspector').hidden=true;
})();

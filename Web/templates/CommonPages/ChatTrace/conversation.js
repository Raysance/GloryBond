/* Read-only projection of saved replies. The trace inspector owns raw payloads. */
const ChatTraceConversation = (() => {
  'use strict';
  const text = value => typeof value === 'string' ? value : '';
  const el = (tag, className = '', value = '') => {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = String(value ?? '');
    return node;
  };
  const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const count = value => number(value) === null ? '未记录' : value.toLocaleString('zh-CN');
  const duration = value => number(value) === null ? '—' : value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;

  function messages(trace) {
    const replies = [], seen = new Set();
    for (const event of Array.isArray(trace.events) ? trace.events : []) {
      if (!event || event.transient || event.kind !== 'output.message') continue;
      if (event.id && seen.has(event.id)) continue;
      if (event.id) seen.add(event.id);
      const data = event.data || {};
      const variants = {detailed:text(data.variants?.detailed), chat:text(data.variants?.chat)};
      const body = text(data.text) || variants.chat || variants.detailed;
      if (body) replies.push({text:body, kind:data.kind || 'partial', variants,
        roleName:text(data.presentation?.role_name)});
    }
    if (!replies.some(reply => reply.kind === 'final')) {
      replies.push({kind:'final', text:text(trace.answer) || `未完成回答：${text(trace.error) || '此记录未保存最终回复'}`,
        variants:{}, roleName:''});
    }
    return replies;
  }

  function usage(trace) {
    const keys = ['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens'];
    const totals = Object.fromEntries(keys.map(key => [key, null]));
    const requests = (trace.rounds || []).map(turn => ({index:turn.index,
      usage:turn.response_meta?.usage || turn.response_payload?.usage || {}}));
    for (const request of requests) for (const key of keys) {
      const value = number(request.usage[key]);
      if (value !== null) totals[key] = (totals[key] ?? 0) + value;
    }
    // Some older records only contain a summary; new traces may contain zero defaults
    // for failed requests, so prefer the actual per-request usage when rounds exist.
    if (!requests.length) for (const key of keys) totals[key] = number(trace.summary?.token_usage?.[key]);
    return {totals, requests, incomplete:requests.some(request => number(request.usage.total_tokens) === null)};
  }

  function inline(parent, value) {
    let cursor = 0;
    const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
    for (const match of value.matchAll(pattern)) {
      parent.append(document.createTextNode(value.slice(cursor, match.index)));
      if (match[2]) parent.append(el('strong', '', match[2]));
      else if (match[3]) parent.append(el('code', '', match[3]));
      else {
        const link = el('a', '', match[4]);
        link.href = match[5]; link.target = '_blank'; link.rel = 'noopener noreferrer';
        parent.append(link);
      }
      cursor = match.index + match[0].length;
    }
    parent.append(document.createTextNode(value.slice(cursor)));
  }

  function markdown(value) {
    const root = el('div', 'answer');
    let code = null, table = null, list = null;
    for (const line of text(value).split('\n')) {
      if (/^\s*```/.test(line)) {
        if (code) code = null;
        else {code = el('pre'); root.append(code);}
        table = null; list = null; continue;
      }
      if (code) {code.textContent += line + '\n'; continue;}
      if (/^\s*\|.*\|\s*$/.test(line)) {
        list = null;
        const cells = line.trim().slice(1, -1).split('|').map(cell => cell.trim());
        if (cells.every(cell => /^:?-+:?$/.test(cell))) continue;
        if (!table) {table = el('table'); root.append(table);}
        const row = el('tr');
        for (const cell of cells) {const node = el(table.children.length ? 'td' : 'th'); inline(node, cell); row.append(node);}
        table.append(row); continue;
      }
      table = null;
      const bullet = line.match(/^\s*(?:([-*+])|\d+[.)])\s+(.+)$/);
      if (bullet) {
        const tag = bullet[1] ? 'ul' : 'ol';
        if (!list || list.tagName.toLowerCase() !== tag) {list = el(tag); root.append(list);}
        const item = el('li'); inline(item, bullet[2]); list.append(item); continue;
      }
      list = null;
      if (!line.trim()) continue;
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      const node = el(heading ? heading[1].length < 3 ? 'h2' : 'h3' : 'p');
      inline(node, heading ? heading[2] : line); root.append(node);
    }
    return root;
  }

  function finalReply(reply) {
    const variants = reply.variants;
    if (!variants.detailed || !variants.chat) return markdown(reply.text);
    const pair = el('div', 'reply-pair'), detail = el('section', 'reply-detail'), chat = el('section', 'reply-chat');
    detail.append(el('div', 'reply-label', '详细内容'), markdown(variants.detailed));
    const label = el('div', 'reply-label', '群聊回复'), copy = el('button', 'reply-copy', '复制');
    copy.type = 'button'; copy.setAttribute('aria-label', '复制群聊回复');
    copy.addEventListener('click', async () => {
      try {await navigator.clipboard.writeText(variants.chat); copy.textContent = '已复制';}
      catch {copy.textContent = '请手动复制';}
    });
    label.append(copy); chat.append(label, el('div', 'chat-reply-text', variants.chat)); pair.append(detail, chat);
    return pair;
  }

  function usageMeter(trace) {
    const report = usage(trace), totals = report.totals;
    const root = el('details', 'usage-meter'), panel = el('div', 'usage-popover');
    root.append(el('summary', '', totals.total_tokens === null ? 'Token 未记录' : `${count(totals.total_tokens)} tokens`));
    panel.append(el('div', 'usage-heading', '本轮用量'));
    for (const [key, label] of [['prompt_tokens','输入'],['completion_tokens','输出'],['total_tokens','总计'],
      ['prompt_cache_hit_tokens','输入缓存命中'],['prompt_cache_miss_tokens','输入缓存未命中']]) {
      if (key.startsWith('prompt_cache') && totals[key] === null) continue;
      const row = el('div', 'usage-row'); row.append(el('span', '', label), el('strong', '', count(totals[key]))); panel.append(row);
    }
    if (report.requests.length) {
      const requests = el('div', 'usage-requests');
      for (const request of report.requests) {
        const row = el('div', 'usage-row');
        row.append(el('span', '', `第 ${request.index} 轮`), el('span', '', number(request.usage.total_tokens) === null
          ? '未返回用量' : `${count(request.usage.prompt_tokens)} / ${count(request.usage.completion_tokens)} / ${count(request.usage.total_tokens)}`));
        requests.append(row);
      }
      requests.append(el('p', 'conversation-note', '每轮依次为输入 / 输出 / 总计；缓存属于输入用量。'));
      panel.append(requests);
    }
    if (report.incomplete) panel.append(el('p', 'conversation-note', '部分请求未返回用量，合计仅包含已报告的数据。'));
    root.append(panel); return root;
  }

  function execution(records, onSelect) {
    const steps = records.filter(item => ['model','tool'].includes(item.kind));
    if (!steps.length) return null;
    const root = el('details', 'execution-details'), body = el('div', 'execution-body');
    root.append(el('summary', '', `执行过程 · ${steps.filter(item => item.kind === 'model').length} 轮 · ${steps.filter(item => item.kind === 'tool').length} 个工具`));
    for (const item of steps) {
      const button = el('button', `execution-step ${item.status === 'error' ? 'error' : ''}`);
      button.type = 'button';
      button.append(el('span', '', item.kind === 'tool' ? item.name : `第 ${item.round} 轮 · 模型请求`), el('small', '', duration(item.duration_ms)));
      button.addEventListener('click', () => onSelect(item)); body.append(button);
      const reasoning = text(item.output?.choices?.[0]?.message?.reasoning_content);
      if (item.kind === 'model' && reasoning) {
        const thought = el('details', 'thought');
        thought.append(el('summary', '', '思考过程'), el('div', 'thought-text', reasoning)); body.append(thought);
      }
    }
    root.append(body); return root;
  }

  function render(trace, parent, records = [], onSelect = () => {}) {
    parent.replaceChildren();
    const events = Array.isArray(trace.events) ? trace.events : [];
    const user = el('div', 'user-message'), bubble = el('div', 'user-bubble', text(trace.question));
    const input = events.find(event => event?.kind === 'run.start')?.data;
    if (Array.isArray(input?.images) && input.images.length) bubble.append(el('div', 'conversation-note', `${input.images.length} 张输入图片 · 原图未公开`));
    user.append(bubble); parent.append(user);
    const replies = messages(trace), final = [...replies].reverse().find(reply => reply.kind === 'final');
    const savedRole = events.find(event => text(event?.metadata?.role_name))?.metadata.role_name;
    const agent = el('article', 'agent-run'), name = el('div', 'agent-name');
    const states = {ok:'已完成', error:'失败', partial:'部分失败', running:'执行中', skipped:'未执行'};
    name.append(el('span', '', final?.roleName || text(savedRole) || 'Agent'),
      el('span', `run-status ${trace.status === 'error' ? 'error' : ''}`, `${states[trace.status] || text(trace.status)} · ${duration(trace.duration_ms)}`), usageMeter(trace));
    agent.append(name);
    const process = execution(records, onSelect); if (process) agent.append(process);
    for (const reply of replies) agent.append(reply.kind === 'final' ? finalReply(reply) : el('div', 'progress-message', reply.text));
    const gallery = el('div', 'charts'); agent.append(gallery);
    if (trace.delivery?.merged) agent.append(el('p', 'conversation-note', `QQ 回复已将 ${trace.delivery.source_images} 张图表合为一张；此处保留原图。`));
    parent.append(agent); return gallery;
  }
  return {messages, usage, markdown, render};
})();

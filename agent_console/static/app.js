const $ = (id) => document.getElementById(id);
const state = {
  sessions: JSON.parse(localStorage.getItem("agent-studio-sessions") || "[]"),
  session: null,
  stream: null,
  run: null,
  runs: new Map(),
  events: [],
  seen: new Set(),
  ready: false,
  usage: AgentUsage.createTracker(),
};
const toolNames = {
  discover_tools: "发现能力",
  search_chat_history: "检索群聊历史",
  analyze_chat_database: "查询聊天数据",
  analyze_game_database: "查询王者数据",
  list_reference_catalogs: "读取参考目录",
  lookup_reference_data: "查询名称与 ID 对应关系",
  web_search: "联网搜索",
  execute_python: "执行 Python",
  render_plot: "绘制图表",
  generate_image: "生成图片",
  recall_memory: "读取记忆",
  remember_memory: "保存记忆",
  forget_memory: "删除记忆",
  emit_message: "发送回复",
  create_task: "创建后台任务",
  list_tasks: "读取任务",
  cancel_task: "取消任务",
  list_plot_templates: "读取绘图规范",
  list_roles: "读取角色库",
  select_role: "选择角色",
  add_role_from_web: "联网添加角色",
  set_reply_preferences: "保存回复偏好",
};
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
const tokenNumber = (value) =>
  value === null ? "—" : value.toLocaleString("zh-CN");
function usageWidget(scope, perRequest = false) {
  const root = el("details", "usage-meter");
  const summary = el("summary");
  const body = el("div", "usage-popover");
  root.append(summary, body);
  root.setAttribute("aria-label", scope + " Token 用量");
  return { root, summary, body, scope, perRequest };
}
const sessionUsage = usageWidget("会话");
$("session-usage").append(sessionUsage.root);
function renderUsage(widget, data, ended = false) {
  widget.summary.textContent =
    data.requests === 0
      ? "Token 用量"
      : data.total === null
        ? ended || !data.pending
          ? "用量未返回"
          : "用量待返回"
        : widget.scope +
          " " +
          tokenNumber(data.total) +
          " tokens" +
          (data.partial ? " · 部分" : "");
  widget.body.replaceChildren();
  const heading = el("div", "usage-heading", widget.scope + "用量");
  heading.append(el("span", null, data.requests + " 次模型请求"));
  widget.body.append(heading);
  const rows = [
    ["输入", data.input],
    ["输出", data.output],
    ["总计", data.total],
  ];
  if (data.known.cacheHit) rows.push(["缓存命中（输入内）", data.cacheHit]);
  if (data.known.cacheMiss) rows.push(["缓存未命中（输入内）", data.cacheMiss]);
  if (data.known.reasoning) rows.push(["思考（输出内）", data.reasoning]);
  for (const [label, value] of rows) {
    const row = el("div", "usage-row");
    const field = {
      输入: "input",
      输出: "output",
      总计: "total",
      "缓存命中（输入内）": "cacheHit",
      "缓存未命中（输入内）": "cacheMiss",
      "思考（输出内）": "reasoning",
    }[label];
    const partial = data.known[field] > 0 && data.known[field] < data.requests;
    row.append(
      el("span", null, label),
      el("strong", null, tokenNumber(value) + (partial ? " · 部分" : "")),
    );
    widget.body.append(row);
  }
  if (data.cacheRate !== null) {
    const row = el("div", "usage-row");
    row.append(
      el(
        "span",
        null,
        data.known.cacheHit < data.requests
          ? "缓存命中率（已知请求）"
          : "缓存命中率",
      ),
      el("strong", null, (data.cacheRate * 100).toFixed(1) + "%"),
    );
    widget.body.append(row);
  }
  if (widget.perRequest && data.breakdown.length) {
    const list = el("div", "usage-requests");
    for (const [index, request] of data.breakdown.entries()) {
      const row = el("div", "usage-row");
      row.append(
        el(
          "span",
          null,
          request.source +
            (request.round
              ? " · 第" + request.round + "次"
              : " · " + (index + 1)),
        ),
        el(
          "span",
          null,
          tokenNumber(request.input) +
            " 输入 / " +
            tokenNumber(request.output) +
            " 输出",
        ),
      );
      list.append(row);
    }
    widget.body.append(list);
  }
  if (data.missing)
    widget.body.append(
      el(
        "p",
        "usage-note",
        data.missing + " 次返回未提供完整用量；仅累计已知值。",
      ),
    );
  if (data.pending)
    widget.body.append(
      el(
        "p",
        "usage-note",
        data.pending + " 次请求尚无用量返回，含中断或失败请求。",
      ),
    );
  widget.body.append(
    el(
      "p",
      "usage-note",
      "输入包含系统提示、上下文和工具数据，多次请求分别计数。缓存属于输入，思考属于输出，不重复相加；仅按接口返回统计。",
    ),
  );
}
function updateUsage(event, run) {
  const changed = state.usage.add(event);
  if (!changed && !["run.start", "run.end", "tool.call"].includes(event.kind))
    return;
  const data = state.usage.summary(event.run_id);
  if (changed || event.kind === "run.start" || event.kind === "run.end") {
    renderUsage(
      sessionUsage,
      state.usage.summary(),
      [...state.runs.values()].every((r) => r.ended),
    );
    renderUsage(run.usage, data, event.kind === "run.end");
  }
  run.executionSummary.textContent =
    "执行过程 · " + data.requests + " 次模型 / " + run.tools.size + " 次工具";
}
async function api(path, options = {}) {
  const r = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Local-UI": "1",
      ...options.headers,
    },
  });
  if (!r.ok) {
    let message = await r.text();
    try {
      message = JSON.parse(message).detail || message;
    } catch {}
    throw Error(message);
  }
  return r.json();
}
function error(message) {
  $("error-banner").textContent = message;
  $("error-banner").hidden = false;
}
function save() {
  localStorage.setItem("agent-studio-sessions", JSON.stringify(state.sessions));
}
function sessions() {
  const list = $("session-list");
  list.replaceChildren();
  for (const s of state.sessions) {
    const b = el(
      "button",
      "session-link" + (s.id === state.session ? " selected" : ""),
      s.title,
    );
    b.onclick = () => selectSession(s.id);
    list.append(b);
  }
}
function running(value) {
  $("send-button").hidden = value;
  $("stop-button").hidden = !value;
  $("send-button").disabled = !state.ready;
}
async function selectSession(id) {
  if (state.stream) state.stream.close();
  state.session = id;
  state.run = null;
  state.runs.clear();
  state.events = [];
  state.seen.clear();
  state.usage = AgentUsage.createTracker();
  renderUsage(sessionUsage, state.usage.summary());
  $("messages").replaceChildren();
  $("timeline").replaceChildren();
  $("trace-summary").textContent = "等待执行";
  $("welcome").hidden = false;
  const s = state.sessions.find((x) => x.id === id);
  $("session-title").textContent = s?.title || "新会话";
  sessions();
  if (state.ready) {
    try {
      const data = await api("/api/sessions/" + id);
      data.events.forEach(consume);
      state.run = data.active_run;
      running(Boolean(state.run));
      connect();
    } catch (e) {
      error(e.message);
    }
  }
}
async function newSession() {
  const id = crypto.randomUUID().replaceAll("-", "");
  state.sessions.unshift({ id, title: "新会话" });
  save();
  await selectSession(id);
  $("message-input").focus();
}
function connect() {
  if (state.stream) state.stream.close();
  const last = state.events.at(-1)?.id;
  state.stream = new EventSource(
    "/api/events/" + state.session + (last ? "?after=" + last : ""),
  );
  state.stream.onmessage = (e) => {
    try {
      consume(JSON.parse(e.data));
    } catch (err) {
      error("执行事件解析失败：" + err.message);
    }
  };
  state.stream.onerror = () => {
    $("connection-caption").textContent = "重连中";
  };
  state.stream.onopen = () => {
    $("connection-caption").textContent = "已连接";
  };
}
function getRun(event) {
  let run = state.runs.get(event.run_id);
  if (run) return run;
  const root = el("article", "agent-run");
  const name = el(
    "div",
    "agent-name",
    event.metadata?.origin === "background"
      ? "定时任务"
      : event.metadata?.role_name || "Agent",
  );
  const status = el("span", "run-status", "正在执行");
  name.append(status);
  const usage = usageWidget("本轮", true);
  name.append(usage.root);
  root.append(name);
  const execution = el("details", "execution-details");
  const executionSummary = el("summary", null, "执行过程");
  const executionBody = el("div", "execution-body");
  execution.append(executionSummary, executionBody);
  root.append(execution);
  const body = el("div", "run-body");
  const draft = el("div", "stream-draft");
  body.append(draft);
  root.append(body);
  $("messages").append(root);
  run = {
    root,
    body,
    status,
    usage,
    execution,
    executionSummary,
    executionBody,
    draft,
    steps: new Map(),
    tools: new Map(),
    started: Date.now(),
  };
  state.runs.set(event.run_id, run);
  return run;
}
function step(run, round) {
  if (run.steps.has(round)) return run.steps.get(round);
  const root = el("div", "step-block");
  const thought = el("details", "thought");
  const summary = el("summary", null, "思考中");
  const text = el("div", "thought-text");
  thought.append(summary, text);
  const draft = el("div", "stream-draft");
  root.append(thought, draft);
  run.executionBody.append(root);
  const s = { root, thought, summary, text, draft };
  run.steps.set(round, s);
  return s;
}
function userMessage(text) {
  const row = el("div", "user-message");
  row.append(el("div", "user-bubble", text));
  $("messages").append(row);
}
function jsonBlock(container, label, data) {
  container.append(
    el("label", null, label),
    el(
      "pre",
      null,
      typeof data === "string" ? data : JSON.stringify(data, null, 2),
    ),
  );
}
function resultTable(container, result) {
  const observations = result?.data?.observations;
  if (!observations) return;
  for (const item of observations) {
    if (!item.rows?.length) continue;
    const table = el("table");
    const head = el("tr");
    const cols = item.columns || Object.keys(item.rows[0]);
    cols.forEach((c) => head.append(el("th", null, c)));
    table.append(head);
    item.rows.slice(0, 12).forEach((row) => {
      const tr = el("tr");
      cols.forEach((c) =>
        tr.append(
          el(
            "td",
            null,
            typeof row[c] === "object"
              ? JSON.stringify(row[c])
              : String(row[c] ?? ""),
          ),
        ),
      );
      table.append(tr);
    });
    container.append(table);
  }
}
function markdown(text) {
  const root = el("div", "answer");
  const lines = text.split("\n");
  let code = null,
    table = null;
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (code) {
        code = null;
      } else {
        code = el("pre");
        root.append(code);
      }
      table = null;
      continue;
    }
    if (code) {
      code.textContent += line + "\n";
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const cells = line
        .trim()
        .slice(1, -1)
        .split("|")
        .map((s) => s.trim());
      if (cells.every((s) => /^:?-+:?$/.test(s))) continue;
      if (!table) {
        table = el("table");
        root.append(table);
      }
      const tr = el("tr");
      cells.forEach((c) =>
        tr.append(el(table.children.length ? "td" : "th", null, c)),
      );
      table.append(tr);
      continue;
    }
    table = null;
    const tag = line.startsWith("### ")
      ? "h3"
      : line.startsWith("## ")
        ? "h2"
        : "p";
    const p = el(tag);
    const clean = line.replace(/^#{1,6}\s/, "");
    let cursor = 0;
    const regex = /(\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
    for (const match of clean.matchAll(regex)) {
      p.append(document.createTextNode(clean.slice(cursor, match.index)));
      if (match[2]) p.append(el("strong", null, match[2]));
      else {
        const a = el("a", null, match[3]);
        a.href = match[4];
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        p.append(a);
      }
      cursor = match.index + match[0].length;
    }
    p.append(document.createTextNode(clean.slice(cursor)));
    if (clean) root.append(p);
  }
  return root;
}
function timeline(event) {
  if (event.transient) return;
  const labels = {
    "run.start":
      event.metadata?.origin === "background" ? "定时执行" : "接收消息",
    "model.request": "模型请求",
    "model.response": "模型返回",
    "tool.call": "调用工具",
    "tool.result": "工具结果",
    "output.message": "发送回复",
    "output.artifact": "生成产物",
    "run.end": "执行结束",
    "run.error": "执行失败",
    "roleplay.search": "搜索角色资料",
    "roleplay.sources": "角色网页来源",
    "roleplay.model.request": "角色档案生成请求",
    "roleplay.model.response": "角色档案生成结果",
    "roleplay.changed": "角色或偏好已更新",
  };
  const row = el("button", "timeline-row");
  const dot = el(
    "span",
    "timeline-dot" +
      (event.kind.startsWith("tool") ? " tool" : "") +
      (event.kind === "run.error" ? " error" : ""),
  );
  const body = el("div");
  body.append(el("strong", null, labels[event.kind] || event.kind));
  const name =
    event.data.function?.name || event.data.name || event.data.status || "";
  body.append(
    el(
      "small",
      null,
      (name ? name + " · " : "") +
        new Date(event.time).toLocaleTimeString("zh-CN", { hour12: false }),
    ),
  );
  row.append(dot, body);
  row.onclick = () => {
    document
      .querySelectorAll(".timeline-row")
      .forEach((x) => x.classList.remove("selected"));
    row.classList.add("selected");
    $("trace-detail").replaceChildren(
      el("h3", null, labels[event.kind] || event.kind),
      el("pre", null, JSON.stringify(event, null, 2)),
    );
    switchTab("detail");
  };
  $("timeline").append(row);
}
function consume(event) {
  if (state.seen.has(event.id)) return;
  state.seen.add(event.id);
  state.events.push(event);
  const nearBottom =
    $("chat-scroll").scrollHeight -
      $("chat-scroll").scrollTop -
      $("chat-scroll").clientHeight <
    180;
  const d = event.data;
  if (event.kind === "roleplay.changed")
    refreshRoles().catch((e) => error(e.message));
  if (event.kind === "run.start") {
    const background = event.metadata?.origin === "background";
    if (!background) userMessage(d.message);
    $("welcome").hidden = true;
    if (!background) {
      state.run = event.run_id;
      running(true);
    }
  }
  const run = getRun(event);
  timeline(event);
  if (event.kind === "model.request") {
    const s = step(run, d.round);
    s.summary.textContent = "思考 · 第 " + d.round + " 次";
    run.status.textContent = "回复中";
    run.draft.textContent = "";
  } else if (event.kind === "model.delta") {
    const s = step(run, d.round);
    if (d.channel === "reasoning") s.text.textContent += d.text;
    else {
      s.draft.textContent += d.text;
      run.draft.textContent += d.text;
    }
  } else if (event.kind === "model.response") {
    const s = step(run, d.round);
    s.text.textContent = d.message.reasoning_content || "";
    s.thought.hidden = !d.message.reasoning_content;
    const tokens = AgentUsage.normalize(d.usage).total;
    s.summary.textContent =
      "思考 · 第 " +
      d.round +
      " 次" +
      (tokens === null ? "" : " · " + tokenNumber(tokens) + " tokens");
    s.draft.textContent = "";
    run.draft.textContent = "";
  } else if (event.kind === "roleplay.search") {
    run.status.textContent = "搜索角色资料";
  } else if (event.kind === "roleplay.model.request") {
    const s = step(run, "roleplay");
    s.summary.textContent = "正在生成角色档案";
    run.status.textContent = "生成角色档案";
  } else if (event.kind === "roleplay.model.delta") {
    const s = step(run, "roleplay");
    if (d.channel === "reasoning") s.text.textContent += d.text;
    else s.draft.textContent += d.text;
  } else if (event.kind === "roleplay.model.response") {
    const s = step(run, "roleplay");
    s.text.textContent = d.message.reasoning_content || "";
    s.thought.hidden = !d.message.reasoning_content;
    s.summary.textContent = "角色档案生成过程";
    s.draft.textContent = "";
  } else if (event.kind === "tool.call") {
    const card = el("details", "tool-card");
    const summary = el("summary");
    const name = d.function.name;
    const status = el("span", "tool-status", "执行中");
    summary.append(
      el("span", "tool-symbol", "◇"),
      el("span", "tool-title", toolNames[name] || name),
      status,
    );
    const body = el("div", "tool-body");
    let args;
    try {
      args = JSON.parse(d.function.arguments);
    } catch {
      args = d.function.arguments;
    }
    jsonBlock(body, "参数", args);
    card.append(summary, body);
    run.executionBody.append(card);
    run.tools.set(d.id, { card, status, body });
    run.status.textContent = toolNames[name] || name;
  } else if (event.kind === "tool.result") {
    const tool = run.tools.get(d.call_id);
    if (tool) {
      tool.status.textContent = d.result.ok ? "已完成" : "失败";
      if (d.duration !== undefined)
        tool.status.textContent += " · " + d.duration.toFixed(1) + " 秒";
      tool.status.className = "tool-status " + (d.result.ok ? "ok" : "fail");
      resultTable(tool.body, d.result);
      jsonBlock(tool.body, "结果", d.result);
    }
  } else if (event.kind === "output.message") {
    run.body.append(
      d.kind === "progress"
        ? el("div", "progress-message", d.text)
        : markdown(d.text),
    );
  } else if (event.kind === "output.artifact") {
    const a = el("a");
    a.href = "/api/artifacts/" + d.artifact_id;
    a.target = "_blank";
    const img = el("img", "artifact-image");
    img.src = a.href;
    img.alt = d.name || "Agent 生成的图片";
    a.append(img);
    run.body.append(a);
  } else if (event.kind === "run.error") {
    run.body.append(el("div", "progress-message", "执行失败：" + d.error));
  } else if (event.kind === "run.warning") {
    run.body.append(el("div", "progress-message", d.error));
  } else if (event.kind === "run.end") {
    run.ended = true;
    run.status.textContent =
      d.status === "completed"
        ? "已完成" + (d.duration ? " · " + d.duration.toFixed(1) + " 秒" : "")
        : d.status === "cancelled"
          ? "已停止"
          : d.status === "interrupted"
            ? "进程重启，执行已中断"
            : "执行失败";
    if (state.run === event.run_id) {
      state.run = null;
      running(false);
    }
    const toolCount = state.events.filter(
      (e) => !e.transient && e.kind === "tool.call",
    ).length;
    $("trace-summary").textContent =
      state.usage.summary().requests + " 次模型 · " + toolCount + " 次工具";
  }
  updateUsage(event, run);
  if (nearBottom || event.kind === "run.start")
    $("chat-scroll").scrollTop = $("chat-scroll").scrollHeight;
}
function switchTab(tab) {
  document
    .querySelectorAll(".trace-tabs button")
    .forEach((x) => x.classList.toggle("selected", x.dataset.tab === tab));
  $("timeline").hidden = tab !== "timeline";
  $("trace-detail").hidden = tab !== "detail";
}
async function send() {
  const message = $("message-input").value.trim();
  if (!message || state.run || !state.ready) return;
  $("error-banner").hidden = true;
  const current = state.sessions.find((x) => x.id === state.session);
  if (current.title === "新会话") {
    current.title = message.slice(0, 22);
    save();
    sessions();
    $("session-title").textContent = current.title;
  }
  $("message-input").value = "";
  running(true);
  try {
    const r = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ session_id: state.session, message }),
    });
    state.run = r.run_id;
  } catch (e) {
    error(e.message);
    running(false);
    $("message-input").value = message;
  }
}
$("composer").onsubmit = (e) => {
  e.preventDefault();
  send();
};
$("message-input").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
};
$("new-session").onclick = newSession;
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "k") {
    e.preventDefault();
    newSession();
  }
});
$("stop-button").onclick = async () => {
  if (state.run)
    try {
      await api("/api/runs/" + state.run + "/cancel", { method: "POST" });
    } catch (e) {
      error(e.message);
    }
};
$("trace-toggle").onclick = () =>
  ($("trace-panel").hidden = !$("trace-panel").hidden);
$("trace-close").onclick = () => ($("trace-panel").hidden = true);
document
  .querySelectorAll("[data-tab]")
  .forEach((b) => (b.onclick = () => switchTab(b.dataset.tab)));
document.querySelectorAll("[data-prompt]").forEach(
  (b) =>
    (b.onclick = () => {
      $("message-input").value = b.dataset.prompt;
      $("message-input").focus();
    }),
);
$("tools-nav").onclick = () => $("tools-dialog").showModal();
$("tools-close").onclick = () => $("tools-dialog").close();
function renderRoles(data) {
  state.roleplay = data;
  $("identity-name").textContent =
    data.identity?.name || $("identity-name").textContent;
  $("role-name").textContent = data.selected.name;
  $("roleplay-owner").textContent =
    "当前用户：" + $("identity-name").textContent + " · 角色与偏好跨会话保存";
  $("role-options").replaceChildren();
  for (const role of data.roles) {
    const button = el(
      "button",
      "role-option" +
        (role.role_id === data.selected.role_id ? " selected" : ""),
    );
    button.append(
      el("strong", null, role.name),
      el(
        "small",
        null,
        (role.work ? role.work + " · " : "") +
          (role.kind === "web" ? "联网添加" : "内置"),
      ),
    );
    button.onclick = async () => {
      button.disabled = true;
      try {
        const result = await api("/api/roleplay/select", {
          method: "POST",
          body: JSON.stringify({ role_id: role.role_id }),
        });
        renderRoles({ ...result, identity: data.identity });
        $("role-save-status").textContent = "已选用，下次对话生效";
      } catch (e) {
        error(e.message);
      } finally {
        button.disabled = false;
      }
    };
    $("role-options").append(button);
  }
  const profile = el("details");
  profile.append(
    el("summary", null, "查看角色档案与来源"),
    el("p", null, data.selected.profile),
  );
  for (const source of data.selected.sources || []) {
    const a = el("a", null, source.title);
    if (/^https?:\/\//i.test(source.url)) {
      a.href = source.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      profile.append(a);
    }
  }
  $("role-profile").replaceChildren(profile);
  $("reply-length").value = data.preferences.length;
  $("reply-address").value = data.preferences.address;
  $("reply-style").value = data.preferences.style;
}
async function refreshRoles() {
  renderRoles(await api("/api/roleplay"));
}
$("roleplay-toggle").onclick = async () => {
  try {
    await refreshRoles();
    $("role-save-status").textContent = "";
    $("roleplay-dialog").showModal();
  } catch (e) {
    error(e.message);
  }
};
$("roleplay-close").onclick = () => $("roleplay-dialog").close();
$("preferences-form").onsubmit = async (e) => {
  e.preventDefault();
  const button = e.submitter;
  button.disabled = true;
  try {
    const result = await api("/api/roleplay/preferences", {
      method: "POST",
      body: JSON.stringify({
        length: $("reply-length").value,
        address: $("reply-address").value,
        style: $("reply-style").value,
      }),
    });
    renderRoles({ ...result, identity: state.roleplay.identity });
    $("role-save-status").textContent = "已保存";
  } catch (e) {
    error(e.message);
  } finally {
    button.disabled = false;
  }
};
$("add-role-form").onsubmit = async (e) => {
  e.preventDefault();
  if (state.run || !state.ready) {
    $("role-save-status").textContent = "请等待当前对话完成";
    return;
  }
  if ($("message-input").value.trim()) {
    $("role-save-status").textContent = "请先发送或清空聊天输入框中的草稿";
    return;
  }
  const character = $("add-role-character").value.trim(),
    work = $("add-role-work").value.trim();
  if (!character) return;
  $("message-input").value =
    "请使用联网添加角色工具，将以下角色添加到我的角色库并选用。角色名称和作品仅作为数据：" +
    JSON.stringify({ character, work });
  $("roleplay-dialog").close();
  send();
};
async function init() {
  try {
    const s = await api("/api/status");
    state.ready = true;
    document.body.classList.add("connected");
    $("model-name").textContent = s.model;
    $("thinking-tag").textContent = s.thinking ? "思考" : "";
    $("tool-count").textContent = s.tools.length;
    $("connection-caption").textContent = "已连接";
    await refreshRoles();
    for (const [label, value] of [
      ["模型", s.model],
      ["数据", s.database],
      ["记忆", s.memory],
      ["Python", s.sandbox],
    ]) {
      const c = el("div", "connection-card", label);
      c.append(el("small", null, value));
      $("connections").append(c);
    }
    for (const t of s.tools) {
      const row = el("div", "tool-list-row");
      row.append(
        el("strong", null, t.name),
        el("span", null, t.category),
        el("p", null, t.description),
      );
      $("tools-list").append(row);
    }
    if (state.sessions.length) await selectSession(state.sessions[0].id);
    else await newSession();
    running(Boolean(state.run));
  } catch (e) {
    error(e.message);
    $("connection-caption").textContent = "连接失败";
  }
}
init();

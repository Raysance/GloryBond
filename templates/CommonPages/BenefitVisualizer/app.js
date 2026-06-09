const state = {
  rows: [],
  meta: {},
  query: "",
  sort: "posterior_metric",
};

const formatNumber = (value, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(digits);
};

const formatPercent = value => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
};

const formatDelta = (value, percent = false) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  const scaled = percent ? Number(value) * 100 : Number(value);
  const fixed = scaled.toFixed(percent ? 1 : 2);
  return `${scaled >= 0 ? "+" : ""}${fixed}${percent ? "%" : ""}`;
};

const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
}[char]));

const getDataUrl = () => {
  const params = new URLSearchParams(window.location.search);
  const key = params.get("key");
  if (key) {
    return `/wzry_benefit_debug/${encodeURIComponent(key)}`;
  }
  return params.get("data") || "sample.json";
};

const setText = (id, value) => {
  document.getElementById(id).textContent = value;
};

const renderMeta = () => {
  const meta = state.meta;
  setText("subtitle", `生成时间：${meta.generated_at || "-"}，近期 ${meta.time_gap || "-"} 天，历史先验 ${meta.benefit_history_gap || "-"} 天`);
  setText("formula", meta.formula || "posterior_avg_grade² / exp(posterior_win_rate)");
  setText("recent-window", `${meta.recent_start || "-"} ~ ${meta.recent_end || "-"}`);
  setText("prior-window", `${meta.prior_start || "-"} ~ ${meta.prior_end || "-"}`);
  setText("prior-strength", `${meta.benefit_prior_min_games || "-"} ~ ${meta.benefit_prior_max_games || "-"} 场`);
  setText("row-count", `${state.rows.length}`);
};

const sortRows = rows => {
  const sortKey = state.sort;
  const descKeys = new Set(["recent_count", "prior_weight"]);
  return [...rows].sort((left, right) => {
    const factor = descKeys.has(sortKey) ? -1 : 1;
    return (Number(left[sortKey]) - Number(right[sortKey])) * factor;
  });
};

const filterRows = rows => {
  const query = state.query.trim().toLowerCase();
  if (!query) {
    return rows;
  }
  return rows.filter(row => `${row.player} ${row.nickname}`.toLowerCase().includes(query));
};

const cellMetric = (title, value, sub) => `
  <div class="metric">
    <span class="muted">${escapeHtml(title)}</span>
    <strong>${escapeHtml(value)}</strong>
    <span class="muted">${sub}</span>
  </div>
`;

const renderRows = () => {
  const tbody = document.getElementById("tbody");
  const rows = sortRows(filterRows(state.rows));
  document.getElementById("empty").hidden = rows.length > 0;
  tbody.innerHTML = rows.map(row => {
    const winDelta = row.posterior_win_rate - row.recent_win_rate;
    const gradeDelta = row.posterior_avg_grade - row.recent_avg_grade;
    const metricDelta = row.posterior_metric - row.recent_metric;
    const winClass = winDelta >= 0 ? "delta-good" : "delta-bad";
    const gradeClass = gradeDelta >= 0 ? "delta-bad" : "delta-good";
    const metricClass = metricDelta >= 0 ? "delta-bad" : "delta-good";
    return `
      <tr>
        <td>
          <div class="player">
            <strong>${escapeHtml(row.nickname)}</strong>
            <span class="muted">${escapeHtml(row.player)}</span>
          </div>
        </td>
        <td>${cellMetric(`${row.recent_wins} 胜 / ${row.recent_count} 场`, formatPercent(row.recent_win_rate), `均分 ${formatNumber(row.recent_avg_grade)}`)}</td>
        <td>${cellMetric(`${row.prior_wins} 胜 / ${row.prior_count} 场`, formatPercent(row.prior_win_rate), `均分 ${formatNumber(row.prior_avg_grade)}`)}</td>
        <td>${cellMetric("伪样本权重", formatNumber(row.prior_weight, 0), `近期场次 ${row.recent_count}`)}</td>
        <td>${cellMetric("后验胜率", formatPercent(row.posterior_win_rate), `<span class="${winClass}">${formatDelta(winDelta, true)}</span>`)}</td>
        <td>${cellMetric("后验均分", formatNumber(row.posterior_avg_grade), `<span class="${gradeClass}">${formatDelta(gradeDelta)}</span>`)}</td>
        <td>${cellMetric("后验指标", formatNumber(row.posterior_metric), `<span class="${metricClass}">${formatDelta(metricDelta)}</span>`)}</td>
      </tr>
    `;
  }).join("");
};

const bindControls = () => {
  document.getElementById("search").addEventListener("input", event => {
    state.query = event.target.value;
    renderRows();
  });
  document.getElementById("sort").addEventListener("change", event => {
    state.sort = event.target.value;
    renderRows();
  });
};

const main = async () => {
  bindControls();
  const response = await fetch(getDataUrl(), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`load_data_failed: ${response.status}`);
  }
  const payload = await response.json();
  state.rows = payload.rows || [];
  state.meta = payload.meta || {};
  renderMeta();
  renderRows();
};

main().catch(error => {
  setText("subtitle", `加载失败：${error.message}`);
  document.getElementById("empty").hidden = false;
});

const state = {
  rows: [],
  meta: {},
  query: "",
  sort: "posterior_metric",
  animationSeed: 0,
};

const svgNS = "http://www.w3.org/2000/svg";

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

const getDataUrl = () => window.BENEFIT_DATA_URL;

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

const average = (rows, key) => {
  const values = rows.map(row => Number(row[key])).filter(Number.isFinite);
  if (!values.length) {
    return null;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
};

const renderInsights = rows => {
  if (!rows.length) {
    setText("best-benefit", "-");
    setText("best-benefit-detail", "暂无可分析玩家");
    setText("most-harmed", "-");
    setText("most-harmed-detail", "暂无可分析玩家");
    setText("avg-metric", "-");
    setText("avg-metric-detail", "暂无可分析玩家");
    return;
  }
  const sortedByMetric = [...rows].sort((left, right) => Number(left.posterior_metric) - Number(right.posterior_metric));
  const benefit = sortedByMetric[0];
  const harmed = sortedByMetric[sortedByMetric.length - 1];
  const avgMetric = average(rows, "posterior_metric");
  const avgWinRate = average(rows, "posterior_win_rate");

  setText("best-benefit", benefit.nickname || benefit.player);
  setText("best-benefit-detail", `后验指标 ${formatNumber(benefit.posterior_metric)}，后验胜率 ${formatPercent(benefit.posterior_win_rate)}，近期 ${benefit.recent_count} 场`);
  setText("most-harmed", harmed.nickname || harmed.player);
  setText("most-harmed-detail", `后验指标 ${formatNumber(harmed.posterior_metric)}，后验胜率 ${formatPercent(harmed.posterior_win_rate)}，近期 ${harmed.recent_count} 场`);
  setText("avg-metric", formatNumber(avgMetric));
  setText("avg-metric-detail", `全体后验平均胜率 ${formatPercent(avgWinRate)}，共 ${rows.length} 名玩家`);
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

const getVisibleRows = () => sortRows(filterRows(state.rows));

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

const getExtent = (rows, keys, padding = 0.08) => {
  const values = rows.flatMap(row => keys.map(key => Number(row[key]))).filter(Number.isFinite);
  if (!values.length) {
    return [0, 1];
  }
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const gap = (max - min) * padding;
  return [min - gap, max + gap];
};

const makeScale = (domain, range) => {
  const [domainMin, domainMax] = domain;
  const [rangeMin, rangeMax] = range;
  return value => {
    const ratio = (Number(value) - domainMin) / (domainMax - domainMin);
    return rangeMin + clamp(ratio, 0, 1) * (rangeMax - rangeMin);
  };
};

const createSvgElement = (tag, attrs = {}) => {
  const element = document.createElementNS(svgNS, tag);
  Object.entries(attrs).forEach(([key, value]) => {
    element.setAttribute(key, value);
  });
  return element;
};

const colorForMetric = (row, extent) => {
  const [min, max] = extent;
  const ratio = clamp((Number(row.posterior_metric) - min) / (max - min), 0, 1);
  if (ratio < 0.5) {
    const local = ratio / 0.5;
    const hue = 158 - local * 120;
    return `hsl(${hue}, 72%, 38%)`;
  }
  const local = (ratio - 0.5) / 0.5;
  const hue = 38 - local * 36;
  return `hsl(${hue}, 72%, 46%)`;
};

const drawAxis = (svg, xScale, yScale, xExtent, yExtent) => {
  const chart = { left: 74, right: 950, top: 42, bottom: 500 };
  const grid = createSvgElement("g");
  const xTicks = 5;
  const yTicks = 5;

  for (let index = 0; index <= xTicks; index += 1) {
    const value = xExtent[0] + ((xExtent[1] - xExtent[0]) * index) / xTicks;
    const x = xScale(value);
    grid.appendChild(createSvgElement("line", { x1: x, y1: chart.top, x2: x, y2: chart.bottom, class: "grid-line" }));
    const label = createSvgElement("text", { x, y: chart.bottom + 30, "text-anchor": "middle", class: "tick-label" });
    label.textContent = formatNumber(value, 1);
    grid.appendChild(label);
  }

  for (let index = 0; index <= yTicks; index += 1) {
    const value = yExtent[0] + ((yExtent[1] - yExtent[0]) * index) / yTicks;
    const y = yScale(value);
    grid.appendChild(createSvgElement("line", { x1: chart.left, y1: y, x2: chart.right, y2: y, class: "grid-line" }));
    const label = createSvgElement("text", { x: chart.left - 16, y: y + 4, "text-anchor": "end", class: "tick-label" });
    label.textContent = formatPercent(value);
    grid.appendChild(label);
  }

  grid.appendChild(createSvgElement("line", { x1: chart.left, y1: chart.bottom, x2: chart.right, y2: chart.bottom, class: "axis-line" }));
  grid.appendChild(createSvgElement("line", { x1: chart.left, y1: chart.top, x2: chart.left, y2: chart.bottom, class: "axis-line" }));

  const xLabel = createSvgElement("text", { x: 512, y: 548, "text-anchor": "middle", class: "axis-label" });
  xLabel.textContent = "受益受害指标：越左越受益，越右越受害";
  grid.appendChild(xLabel);

  const yLabel = createSvgElement("text", { x: 18, y: 280, transform: "rotate(-90 18 280)", "text-anchor": "middle", class: "axis-label" });
  yLabel.textContent = "胜率";
  grid.appendChild(yLabel);

  const benefit = createSvgElement("text", { x: 136, y: 92, class: "zone-label" });
  benefit.textContent = "受益";
  grid.appendChild(benefit);

  const harmed = createSvgElement("text", { x: 758, y: 92, class: "zone-label" });
  harmed.textContent = "受害";
  grid.appendChild(harmed);
  svg.appendChild(grid);
};

const showTooltip = (event, row) => {
  const tooltip = document.getElementById("tooltip");
  const winDelta = row.posterior_win_rate - row.recent_win_rate;
  const metricDelta = row.posterior_metric - row.recent_metric;
  tooltip.innerHTML = `
    <strong>${escapeHtml(row.nickname || row.player)}</strong>
    <div class="muted">${escapeHtml(row.player)}</div>
    <div>后验指标：${formatNumber(row.posterior_metric)}</div>
    <div>近期 → 后验胜率：${formatPercent(row.recent_win_rate)} → ${formatPercent(row.posterior_win_rate)}</div>
    <div>胜率收缩：${formatDelta(winDelta, true)}</div>
    <div>指标收缩：${formatDelta(metricDelta)}</div>
  `;
  tooltip.hidden = false;
  tooltip.style.left = `${event.offsetX + 18}px`;
  tooltip.style.top = `${event.offsetY + 18}px`;
};

const hideTooltip = () => {
  document.getElementById("tooltip").hidden = true;
};

const renderChart = rows => {
  const svg = document.getElementById("chart");
  svg.innerHTML = "";
  if (!rows.length) {
    return;
  }

  const chart = { left: 74, right: 950, top: 42, bottom: 500 };
  const xExtent = getExtent(rows, ["recent_metric", "posterior_metric"]);
  const yExtent = getExtent(rows, ["recent_win_rate", "posterior_win_rate"], 0.12);
  const countExtent = getExtent(rows, ["recent_count"], 0);
  const metricExtent = getExtent(rows, ["posterior_metric"], 0);
  const xScale = makeScale(xExtent, [chart.left, chart.right]);
  const yScale = makeScale(yExtent, [chart.bottom, chart.top]);
  const radiusScale = makeScale(countExtent, [8, 28]);
  const visible = rows.slice(0, 48);

  drawAxis(svg, xScale, yScale, xExtent, yExtent);

  const paths = createSvgElement("g");
  const nodes = createSvgElement("g");
  visible.forEach((row, index) => {
    const recentX = xScale(row.recent_metric);
    const recentY = yScale(row.recent_win_rate);
    const posteriorX = xScale(row.posterior_metric);
    const posteriorY = yScale(row.posterior_win_rate);
    const radius = radiusScale(row.recent_count);
    const color = colorForMetric(row, metricExtent);
    const delay = `${index * 0.035}s`;

    paths.appendChild(createSvgElement("line", {
      x1: recentX,
      y1: recentY,
      x2: posteriorX,
      y2: posteriorY,
      class: "shrink-line",
      style: `animation-delay:${delay}`,
    }));
    nodes.appendChild(createSvgElement("circle", {
      cx: recentX,
      cy: recentY,
      r: radius * 0.72,
      class: "recent-node",
    }));

    const circle = createSvgElement("circle", {
      cx: recentX,
      cy: recentY,
      r: radius,
      fill: color,
      class: "posterior-node",
      style: `animation-delay:${delay}`,
    });
    circle.animate(
      [
        { cx: recentX, cy: recentY, r: radius * 0.72, opacity: 0.45 },
        { cx: posteriorX, cy: posteriorY, r: radius, opacity: 0.94 },
      ],
      {
        duration: 900,
        delay: 120 + index * 35 + state.animationSeed,
        easing: "cubic-bezier(.2,.8,.2,1)",
        fill: "forwards",
      }
    );
    circle.addEventListener("mouseenter", event => showTooltip(event, row));
    circle.addEventListener("mousemove", event => showTooltip(event, row));
    circle.addEventListener("mouseleave", hideTooltip);
    nodes.appendChild(circle);

    if (index < 18) {
      const label = createSvgElement("text", {
        x: posteriorX,
        y: posteriorY - radius - 8,
        "text-anchor": "middle",
        class: "node-label",
      });
      label.textContent = row.nickname || row.player;
      nodes.appendChild(label);
    }
  });

  svg.appendChild(paths);
  svg.appendChild(nodes);
};

const renderCards = rows => {
  const cards = document.getElementById("cards");
  const metricExtent = getExtent(rows, ["posterior_metric"], 0);
  const [minMetric, maxMetric] = metricExtent;
  cards.innerHTML = rows.slice(0, 18).map((row, index) => {
    const color = colorForMetric(row, metricExtent);
    const metricRatio = clamp((Number(row.posterior_metric) - minMetric) / (maxMetric - minMetric), 0, 1);
    const winDelta = row.posterior_win_rate - row.recent_win_rate;
    const metricDelta = row.posterior_metric - row.recent_metric;
    const metricClass = metricDelta >= 0 ? "delta-bad" : "delta-good";
    return `
      <article class="player-card" style="--card-color:${color}; --bar-width:${Math.max(6, metricRatio * 100).toFixed(1)}%; animation-delay:${index * 0.035}s">
        <div class="card-top">
          <div class="player-name">
            <strong>${escapeHtml(row.nickname || row.player)}</strong>
            <span class="muted">${escapeHtml(row.player)} · ${row.recent_count} 场</span>
          </div>
          <span class="badge">${formatNumber(row.posterior_metric)}</span>
        </div>
        <div class="bar-track"><div class="bar-fill"></div></div>
        <div class="card-stats">
          <div><span>胜率</span><strong>${formatPercent(row.posterior_win_rate)}</strong></div>
          <div><span>收缩</span><strong class="${metricClass}">${formatDelta(metricDelta)}</strong></div>
          <div><span>胜率变化</span><strong>${formatDelta(winDelta, true)}</strong></div>
        </div>
      </article>
    `;
  }).join("");
};

const renderTable = rows => {
  const tbody = document.getElementById("detail-rows");
  tbody.innerHTML = rows.slice(0, 64).map(row => {
    const metricDelta = row.posterior_metric - row.recent_metric;
    const metricClass = metricDelta >= 0 ? "delta-bad" : "delta-good";
    return `
      <tr>
        <td>${escapeHtml(row.nickname || row.player)}<div class="muted">${escapeHtml(row.player)}</div></td>
        <td>${row.recent_count ?? "-"}</td>
        <td>${formatPercent(row.recent_win_rate)}</td>
        <td>${formatPercent(row.posterior_win_rate)}</td>
        <td>${formatNumber(row.posterior_avg_grade)}</td>
        <td>${formatNumber(row.posterior_metric)}</td>
        <td class="${metricClass}">${formatDelta(metricDelta)}</td>
      </tr>
    `;
  }).join("");
};

const renderRows = () => {
  const rows = getVisibleRows();
  document.getElementById("empty").hidden = rows.length > 0;
  renderInsights(rows);
  renderChart(rows);
  renderCards(rows);
  renderTable(rows);
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
  document.getElementById("replay").addEventListener("click", () => {
    state.animationSeed += 1;
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

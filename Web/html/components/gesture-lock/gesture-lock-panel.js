const template = document.createElement('template');

template.innerHTML = `
  <style>
    :host {
      position: fixed;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(6, 16, 33, 0.7);
      backdrop-filter: blur(12px) saturate(140%);
      -webkit-backdrop-filter: blur(12px) saturate(140%);
      z-index: 9999;
      font-family: "IBM Plex Sans", "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      color: #e9f2ff;
    }

    :host([hidden]) {
      display: none;
    }

    .panel {
      width: min(420px, 90vw);
      border-radius: 24px;
      padding: 28px;
      background: rgba(8, 20, 40, 0.92);
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .panel.shake {
      animation: shake 450ms ease;
    }

    @keyframes shake {
      0% {
        transform: translateX(0);
      }
      20% {
        transform: translateX(-8px);
      }
      40% {
        transform: translateX(6px);
      }
      60% {
        transform: translateX(-4px);
      }
      80% {
        transform: translateX(2px);
      }
      100% {
        transform: translateX(0);
      }
    }

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }

    .title {
      margin: 0;
      font-size: 1.6rem;
      font-weight: 600;
    }

    .close-btn {
      width: 40px;
      height: 40px;
      border-radius: 12px;
      border: none;
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
      font-size: 22px;
      line-height: 1;
      cursor: pointer;
      transition: background 150ms ease, transform 150ms ease;
    }

    .close-btn:hover {
      background: rgba(255, 255, 255, 0.2);
      transform: translateY(-1px);
    }

    .close-btn:focus-visible {
      outline: 2px solid #4f9cff;
      outline-offset: 2px;
    }

    .status-row {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .status {
      flex: 1;
      min-height: 44px;
      padding: 10px 14px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid transparent;
      transition: border-color 200ms ease, color 200ms ease;
    }

    .status.pending {
      border-color: rgba(255, 255, 255, 0.22);
      color: #cdd9ff;
    }

    .status.error {
      border-color: rgba(255, 72, 88, 0.9);
      color: #ff8a9a;
    }

    .status.success {
      border-color: rgba(70, 214, 156, 0.9);
      color: #70f0c7;
    }

    .status.warn {
      border-color: rgba(255, 196, 0, 0.8);
      color: #ffe08a;
    }

    .lock-area {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      border-radius: 20px;
      background: rgba(6, 14, 30, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.08);
      touch-action: none;
      overflow: hidden;
    }

    canvas {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      filter: drop-shadow(0 0 8px rgba(79, 156, 255, 0.45));
    }

    .grid {
      position: relative;
      width: min(320px, 70vw);
      height: min(320px, 70vw);
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: clamp(20px, 4vw, 30px);
      touch-action: none;
    }

    .node {
      width: 64px;
      height: 64px;
      border-radius: 999px;
      border: 2px solid rgba(255, 255, 255, 0.35);
      background: radial-gradient(circle, rgba(255, 255, 255, 0.2) 0%, rgba(255, 255, 255, 0.04) 70%, rgba(255, 255, 255, 0) 100%);
      cursor: pointer;
      position: relative;
      transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
    }

    .node::after {
      content: "";
      position: absolute;
      inset: 18px;
      border-radius: 999px;
      background: rgba(79, 156, 255, 0);
      transition: background 150ms ease;
    }

    .node.active {
      border-color: rgba(79, 156, 255, 0.9);
      box-shadow: 0 0 12px rgba(79, 156, 255, 0.55);
      transform: scale(1.05);
    }

    .node.active::after {
      background: rgba(79, 156, 255, 0.55);
    }

    .ghost-btn {
      border: 1px solid rgba(255, 255, 255, 0.25);
      border-radius: 12px;
      padding: 10px 16px;
      background: transparent;
      color: inherit;
      cursor: pointer;
      transition: background 150ms ease, border-color 150ms ease;
    }

    .ghost-btn:hover {
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.45);
    }

    @media (max-width: 480px) {
      .panel {
        padding: 20px;
        gap: 12px;
      }

      .status-row {
        flex-direction: column;
        align-items: stretch;
      }

      .ghost-btn {
        width: 100%;
      }

      .grid {
        width: min(260px, 80vw);
        height: min(260px, 80vw);
        gap: 18px;
      }
    }
  </style>

  <div class="panel" role="dialog" aria-modal="true" aria-labelledby="gesture-title">
    <div class="panel-header">
      <h2 class="title" id="gesture-title">DashBoard</h2>
      <button class="close-btn" type="button" aria-label="取消并关闭">&times;</button>
    </div>
    <div class="status-row">
      <div class="status" data-status>Start drawing</div>
      <button class="ghost-btn" type="button" data-reset>重置</button>
    </div>
    <div class="lock-area">
      <canvas class="pattern-canvas"></canvas>
      <div class="grid" part="grid">
        ${Array.from({ length: 9 }, (_, idx) => `<button class="node" data-cell="${idx}" aria-label="位置 ${idx + 1}" type="button"></button>`).join("")}
      </div>
    </div>
  </div>
`;

class GestureLockPanel extends HTMLElement {
  static get observedAttributes() {
    return ["endpoint"];
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.appendChild(template.content.cloneNode(true));

    this.endpoint = this.getAttribute("endpoint") || "admin/verify";

    this.state = {
      activePattern: [],
      touchedCells: new Set(),
      isDrawing: false,
    };
    this.activePointerId = null;
    this.capturedElement = null;

    this.canvas = this.shadowRoot.querySelector(".pattern-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.statusEl = this.shadowRoot.querySelector("[data-status]");
    this.nodes = Array.from(this.shadowRoot.querySelectorAll(".node"));
    this.resetBtn = this.shadowRoot.querySelector("[data-reset]");
    this.closeBtn = this.shadowRoot.querySelector(".close-btn");
    this.grid = this.shadowRoot.querySelector(".grid");

    this.handlePointerDown = this.handlePointerDown.bind(this);
    this.handlePointerEnter = this.handlePointerEnter.bind(this);
    this.handlePointerUp = this.handlePointerUp.bind(this);
    this.handlePointerMove = this.handlePointerMove.bind(this);
    this.handlePointerCancel = this.handlePointerCancel.bind(this);
    this.handleCancel = this.handleCancel.bind(this);
    this.handleReset = this.handleReset.bind(this);
    this.resizeCanvas = this.resizeCanvas.bind(this);

    this.resizeObserver = new ResizeObserver(this.resizeCanvas);
  }

  connectedCallback() {
    this.nodes.forEach((node) => {
      node.addEventListener("pointerdown", this.handlePointerDown);
      node.addEventListener("pointerenter", this.handlePointerEnter);
    });

    this.shadowRoot.addEventListener("pointerup", this.handlePointerUp);
    this.shadowRoot.addEventListener("pointerleave", this.handlePointerUp);
    this.shadowRoot.addEventListener("pointermove", this.handlePointerMove, { passive: false });
    this.shadowRoot.addEventListener("pointercancel", this.handlePointerCancel);
    this.closeBtn.addEventListener("click", this.handleCancel);
    this.resetBtn.addEventListener("click", this.handleReset);

    if (this.grid) {
      this.resizeObserver.observe(this.grid);
    }
    this.resizeCanvas();
  }

  disconnectedCallback() {
    this.nodes.forEach((node) => {
      node.removeEventListener("pointerdown", this.handlePointerDown);
      node.removeEventListener("pointerenter", this.handlePointerEnter);
    });

    this.shadowRoot.removeEventListener("pointerup", this.handlePointerUp);
    this.shadowRoot.removeEventListener("pointerleave", this.handlePointerUp);
    this.shadowRoot.removeEventListener("pointermove", this.handlePointerMove);
    this.shadowRoot.removeEventListener("pointercancel", this.handlePointerCancel);
    this.closeBtn.removeEventListener("click", this.handleCancel);
    this.resetBtn.removeEventListener("click", this.handleReset);
    this.resizeObserver.disconnect();
  }

  attributeChangedCallback(name, _oldValue, newValue) {
    if (name === "endpoint") {
      this.endpoint = newValue || "admin/verify";
    }
  }

  handlePointerDown(event) {
    if (this.state.isDrawing && this.activePointerId !== null && event.pointerId !== this.activePointerId) {
      return;
    }
    if (event.cancelable) {
      event.preventDefault();
    }
    this.resetPattern();
    this.state.isDrawing = true;
    this.activePointerId = event.pointerId;
    if (event.currentTarget && event.currentTarget.setPointerCapture) {
      this.capturedElement = event.currentTarget;
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch (_error) {
        this.capturedElement = null;
      }
    }
    this.captureNode(event.currentTarget);
  }

  handlePointerEnter(event) {
    if (!this.state.isDrawing) {
      return;
    }
    if (this.activePointerId !== null && event.pointerId !== this.activePointerId) {
      return;
    }
    this.captureNode(event.currentTarget);
  }

  handlePointerUp(event) {
    if (!this.state.isDrawing) {
      return;
    }
    if (this.activePointerId !== null && event && event.pointerId !== this.activePointerId) {
      return;
    }
    this.state.isDrawing = false;
    this.releasePointerCapture(event?.pointerId);
    if (this.state.activePattern.length < 4) {
      this.setStatus("请至少连接 4 个点。", "warn");
      this.scheduleSoftReset();
      return;
    }
    this.verifyPattern();
  }

  handlePointerCancel(event) {
    if (!this.state.isDrawing) {
      return;
    }
    if (this.activePointerId !== null && event && event.pointerId !== this.activePointerId) {
      return;
    }
    this.state.isDrawing = false;
    this.releasePointerCapture(event?.pointerId);
    this.setStatus("触控已取消，请重试。", "warn");
    this.scheduleSoftReset();
  }

  handleReset() {
    this.resetPattern();
    this.setStatus("Draw to unlock.", "");
  }

  handleCancel() {
    if (this.state.isDrawing) {
      this.state.isDrawing = false;
      this.releasePointerCapture();
    }
    this.dispatchEvent(
      new CustomEvent("gesture-lock-cancel", {
        bubbles: true,
        composed: true,
      })
    );
  }

  releasePointerCapture(pointerId) {
    const targetId = pointerId ?? this.activePointerId;
    if (this.capturedElement && targetId != null) {
      try {
        if (typeof this.capturedElement.hasPointerCapture === "function" && this.capturedElement.hasPointerCapture(targetId)) {
          this.capturedElement.releasePointerCapture(targetId);
        }
      } catch (_error) {
        // ignore release failures
      }
    }
    this.capturedElement = null;
    this.activePointerId = null;
  }

  resetPattern() {
    this.state.activePattern = [];
    this.state.touchedCells.clear();
    this.nodes.forEach((node) => node.classList.remove("active"));
    this.clearCanvas();
  }

  scheduleSoftReset() {
    clearTimeout(this.resetTimer);
    this.resetTimer = setTimeout(() => this.resetPattern(), 900);
  }

  captureNode(node) {
    const cellIndex = Number(node.dataset.cell);
    if (this.state.touchedCells.has(cellIndex)) {
      return;
    }
    this.state.touchedCells.add(cellIndex);
    this.state.activePattern.push(cellIndex);
    node.classList.add("active");
    this.drawPattern();
  }

  resizeCanvas() {
    const rect = this.canvas.getBoundingClientRect();
    const { width, height } = rect;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(width * dpr);
    this.canvas.height = Math.round(height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.drawPattern();
  }

  clearCanvas() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  drawPattern() {
    this.clearCanvas();
    if (this.state.activePattern.length < 2) {
      return;
    }

    const points = this.state.activePattern.map((index) => {
      const node = this.nodes[index];
      const nodeRect = node.getBoundingClientRect();
      const canvasRect = this.canvas.getBoundingClientRect();
      return {
        x: nodeRect.left + nodeRect.width / 2 - canvasRect.left,
        y: nodeRect.top + nodeRect.height / 2 - canvasRect.top,
      };
    });

    this.ctx.lineCap = "round";
    this.ctx.lineJoin = "round";
    this.ctx.strokeStyle = "rgba(79, 156, 255, 0.95)";
    this.ctx.lineWidth = 6;

    this.ctx.beginPath();
    points.forEach((point, idx) => {
      if (idx === 0) {
        this.ctx.moveTo(point.x, point.y);
        return;
      }
      this.ctx.lineTo(point.x, point.y);
    });
    this.ctx.stroke();
  }

  buildRequestUrl(pattern) {
    try {
      const url = new URL(this.endpoint, window.location.origin);
      url.searchParams.set("pattern", pattern);
      return url.toString();
    } catch (_error) {
      const encodedPattern = encodeURIComponent(pattern);
      const separator = this.endpoint.includes("?") ? "&" : "?";
      return `${this.endpoint}${separator}pattern=${encodedPattern}`;
    }
  }

  isSuccessfulResponse(result) {
    return Boolean(result && result.state === "success" && result.key);
  }

  handlePointerMove(event) {
    if (!this.state.isDrawing) {
      return;
    }
    if (this.activePointerId !== null && event.pointerId !== this.activePointerId) {
      return;
    }
    if (event.cancelable) {
      event.preventDefault();
    }
    const node = this.getNodeFromEvent(event);
    if (node) {
      this.captureNode(node);
    }
  }

  getNodeFromEvent(event) {
    const clientX = event.clientX;
    const clientY = event.clientY;

    if (Number.isFinite(clientX) && Number.isFinite(clientY)) {
      let closest = null;
      let minDistance = Infinity;

      this.nodes.forEach((node) => {
        const rect = node.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const distance = Math.hypot(clientX - centerX, clientY - centerY);
        const threshold = Math.max(rect.width, rect.height) * 0.6;

        const inside = clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
        if (inside) {
          closest = node;
          minDistance = 0;
          return;
        }

        if (distance < minDistance && distance <= threshold) {
          closest = node;
          minDistance = distance;
        }
      });

      if (closest) {
        return closest;
      }
    }

    if (this.shadowRoot.elementsFromPoint) {
      const hits = this.shadowRoot.elementsFromPoint(event.clientX, event.clientY) || [];
      const fromHits = hits.find((el) => el.classList && el.classList.contains("node"));
      if (fromHits) {
        return fromHits;
      }
    }

    if (event.composedPath) {
      const fromPath = event
        .composedPath()
        .find((el) => el.classList && el.classList.contains("node"));
      if (fromPath) {
        return fromPath;
      }
    }
    return null;
  }

  async verifyPattern() {
    this.setStatus("正在校验手势...", "pending");
    const pattern = this.state.activePattern.join(",");

    try {
      const requestUrl = this.buildRequestUrl(pattern);
      const response = await fetch(requestUrl, {
        method: "GET",
      });

      if (!response.ok) {
        throw new Error("服务器响应异常，请稍后再试。");
      }

      const result = await response.json();
      if (this.isSuccessfulResponse(result)) {
        this.setStatus(result.message || "校验成功，已获取密钥。", "success");
        this.dispatchEvent(
          new CustomEvent("gesture-lock-success", {
            bubbles: true,
            composed: true,
            detail: {
              key: result.key,
              response: result,
            },
          })
        );
        return;
      }

      this.setStatus(result?.message || "手势不匹配，请重试。", "error");
      this.flashError();
      this.scheduleSoftReset();
    } catch (error) {
      this.setStatus(error.message || "网络异常，请重试。", "error");
      this.flashError();
      this.scheduleSoftReset();
    }
  }

  flashError() {
    const panel = this.shadowRoot.querySelector(".panel");
    panel.classList.remove("shake");
    panel.offsetWidth;
    panel.classList.add("shake");
    setTimeout(() => panel.classList.remove("shake"), 600);
  }

  setStatus(message, variant) {
    this.statusEl.textContent = message;
    this.statusEl.classList.remove("pending", "error", "success", "warn");
    if (variant) {
      this.statusEl.classList.add(variant);
    }
  }
}

customElements.define("gesture-lock-panel", GestureLockPanel);

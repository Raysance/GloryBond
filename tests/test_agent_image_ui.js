"use strict";

// Exercise the shipped event and upload handlers without launching a browser.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const staticRoot = path.join(__dirname, "../agent_console/static");

function setup({ uploadError = false, chatError = false } = {}) {
  class Element {
    constructor(tag = "div") {
      Object.assign(this, {
        tagName: tag,
        children: [],
        hidden: false,
        open: false,
        value: "",
        scrollHeight: 0,
        scrollTop: 0,
        clientHeight: 0,
        listeners: {},
        classList: { add() {}, remove() {}, toggle() {} },
      });
    }
    append(...children) {
      this.children.push(...children);
    }
    replaceChildren(...children) {
      this.children = children;
    }
    setAttribute() {}
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    }
    focus() {}
    click() {
      this.clicked = true;
    }
  }
  const html = fs.readFileSync(path.join(staticRoot, "index.html"), "utf8");
  const ids = new Map(
    [...html.matchAll(/id="([^"]+)"/g)].map((m) => [m[1], new Element()]),
  );
  const requests = [],
    revoked = [],
    copied = [];
  let uploaded = 0;
  const context = vm.createContext({
    document: {
      getElementById: (id) => ids.get(id),
      createElement: (tag) => new Element(tag),
      createTextNode: (text) => ({ textContent: text }),
      querySelectorAll: () => [],
      addEventListener() {},
    },
    localStorage: { getItem: () => null, setItem() {} },
    navigator: { clipboard: { writeText: async (text) => copied.push(text) } },
    URL: {
      createObjectURL: () => "blob:fixture",
      revokeObjectURL: (url) => revoked.push(url),
    },
    fetch: async (url, options) => {
      if (url === "/api/status") return new Promise(() => {});
      requests.push({ url, options });
      const failed = url.startsWith("/api/images") ? uploadError : chatError;
      const data = url.startsWith("/api/images")
        ? {
            id: String(++uploaded).padStart(32, "0"),
            name: "fixture.png",
            bytes: 20,
            url: "/api/images/" + String(uploaded).padStart(32, "0"),
          }
        : { run_id: "accepted-run" };
      return {
        ok: !failed,
        json: async () => data,
        text: async () => JSON.stringify({ detail: "模拟请求失败" }),
      };
    },
    Date,
    console,
  });
  for (const file of ["usage.js", "app.js"])
    vm.runInContext(
      fs.readFileSync(path.join(staticRoot, file), "utf8"),
      context,
    );
  const evaluate = (code) => vm.runInContext(code, context);
  evaluate(
    'state.ready=true;state.session="session";state.sessions=[{id:"session",title:"新会话"}];state.textModel="text-model";state.visionModel="deepseek-v4-flash";',
  );
  const file = { name: "fixture.png", type: "image/png", size: 20 };
  context.file = file;
  return { ids, requests, revoked, copied, context, evaluate, file };
}

test("upload preview uses a server image ID and image-only send reaches chat", async () => {
  const ui = setup();
  await ui.evaluate("uploadImages([file])");
  assert.equal(ui.ids.get("image-attachments").hidden, false);
  assert.equal(ui.ids.get("model-name").textContent, "deepseek-v4-flash");
  assert.equal(ui.requests[0].options.body, ui.file);
  assert.equal(ui.requests[0].options.headers["Content-Type"], "image/png");
  await ui.evaluate("send()");
  const chat = ui.requests.find((r) => r.url === "/api/chat");
  assert.deepEqual(JSON.parse(chat.options.body), {
    session_id: "session",
    message: "",
    image_ids: ["1".padStart(32, "0")],
  });
  assert.equal(ui.evaluate("state.attachments.length"), 0);
  assert.equal(ui.evaluate("state.sessions[0].title"), "图片对话");
  assert.deepEqual(ui.revoked, ["blob:fixture"]);
});

test("upload failure releases the preview and does not leave sending blocked", async () => {
  const ui = setup({ uploadError: true });
  await ui.evaluate("uploadImages([file])");
  assert.equal(ui.evaluate("state.uploading"), 0);
  assert.equal(ui.evaluate("state.attachments.length"), 0);
  assert.equal(ui.ids.get("send-button").disabled, false);
  assert.equal(ui.ids.get("error-banner").textContent, "模拟请求失败");
  assert.equal(ui.revoked.length, 1);
});

test("failed chat preserves uploaded attachments and user text for retry", async () => {
  const ui = setup({ chatError: true });
  await ui.evaluate("uploadImages([file])");
  ui.ids.get("message-input").value = "这是什么？";
  await ui.evaluate("send()");
  assert.equal(ui.evaluate("state.attachments.length"), 1);
  assert.equal(ui.ids.get("message-input").value, "这是什么？");
  assert.equal(ui.evaluate("state.sending"), false);
  assert.equal(ui.revoked.length, 0);
});

test("paste and drop run the same uploader; file picker is connected", async () => {
  const ui = setup();
  let prevented = 0;
  ui.ids.get("attach-images").onclick();
  assert.equal(ui.ids.get("image-input").clicked, true);
  ui.ids.get("message-input").listeners.paste({
    clipboardData: { files: [ui.file], getData: () => "" },
    preventDefault: () => prevented++,
  });
  await new Promise(setImmediate);
  ui.ids.get("composer").listeners.drop({
    dataTransfer: { files: [ui.file] },
    preventDefault: () => prevented++,
  });
  await new Promise(setImmediate);
  assert.equal(ui.evaluate("state.attachments.length"), 2);
  assert.equal(prevented, 2);
  assert.equal(
    ui.requests.filter((r) => r.url.startsWith("/api/images")).length,
    2,
  );
});

test("image limits apply before upload and unfinished uploads block sending", async () => {
  const ui = setup();
  ui.evaluate("state.imageLimits.max_images=1");
  await ui.evaluate("uploadImages([file,file])");
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.evaluate("state.attachments.length"), 1);
  ui.evaluate("state.uploading=1");
  await ui.evaluate("send()");
  assert.equal(ui.requests.length, 1);
});

test("persisted image events rebuild thumbnails and preserve event deduplication", () => {
  const ui = setup();
  ui.context.event = {
    id: "start",
    run_id: "run",
    kind: "run.start",
    time: "2026-10-13T12:00:00Z",
    data: {
      message: "读图",
      images: [{ url: "attachment://" + "a".repeat(32), name: "fixture.png" }],
    },
  };
  ui.evaluate("consume(event);consume(event)");
  const bubble = ui.ids.get("messages").children[0].children[0];
  const gallery = bubble.children[1];
  assert.equal(
    gallery.children[0].children[0].src,
    "/api/images/" + "a".repeat(32),
  );
  assert.equal(ui.evaluate("state.events.length"), 1);
  ui.evaluate("clearAttachments();");
  assert.equal(ui.ids.get("image-attachments").hidden, true);
});

test("final reply shows both versions and copies only the plain group-chat version", async () => {
  const ui = setup();
  ui.context.event = {
    id: "reply",
    run_id: "run",
    kind: "output.message",
    time: "2026-10-13T12:00:00Z",
    data: {
      kind: "final",
      text: "这结论下得太快了吧。先看证据。",
      variants: {
        detailed: "## 结论\n样本还少。\n\n先看证据再下结论。",
        chat: "这结论下得太快了吧。先看证据。",
      },
    },
  };
  ui.evaluate("consume(event)");
  const run = ui.evaluate('state.runs.get("run")');
  const pair = run.body.children[1];
  assert.equal(pair.className, "reply-pair");
  assert.equal(pair.children[0].children[0].textContent, "详细内容");
  assert.equal(
    pair.children[1].children[1].textContent,
    ui.context.event.data.variants.chat,
  );
  const copy = pair.children[1].children[0].children[0];
  await copy.onclick();
  assert.deepEqual(ui.copied, [ui.context.event.data.variants.chat]);
  assert.equal(copy.textContent, "已复制");
});

test("reply JSON streaming stays in execution details and has usage tracking", () => {
  const ui = setup();
  for (const [id, kind, data] of [
    ["request", "reply.model.request", { attempt: 1, messages: [], tools: [] }],
    [
      "delta",
      "reply.model.delta",
      { attempt: 1, channel: "content", text: '{"detailed":"..."' },
    ],
    [
      "response",
      "reply.model.response",
      {
        attempt: 1,
        message: { content: '{"detailed":"detail","chat":"short"}' },
        usage: { prompt_tokens: 200, completion_tokens: 40, total_tokens: 240 },
      },
    ],
  ]) {
    ui.context.event = {
      id,
      run_id: "run",
      kind,
      data,
      time: "2026-10-13T12:00:00Z",
      transient: kind.endsWith("delta"),
    };
    ui.evaluate("consume(event)");
  }
  const run = ui.evaluate('state.runs.get("run")');
  assert.equal(run.execution.open, false);
  assert.equal(run.draft.textContent, "");
  assert.equal(ui.evaluate("state.usage.summary().total"), 240);
  assert.equal(ui.evaluate("state.usage.summary().requests"), 1);
});

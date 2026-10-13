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
    revoked = [];
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
  return { ids, requests, revoked, context, evaluate, file };
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
  ui.ids
    .get("message-input")
    .listeners.paste({
      clipboardData: { files: [ui.file], getData: () => "" },
      preventDefault: () => prevented++,
    });
  await new Promise(setImmediate);
  ui.ids
    .get("composer")
    .listeners.drop({
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

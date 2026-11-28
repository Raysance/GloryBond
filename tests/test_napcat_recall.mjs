import assert from "node:assert/strict";
import test from "node:test";
import { RecallRelay, plugin_init, plugin_onmessage, plugin_cleanup } from "../src/glorybond/integrations/napcat_recall.mjs";

function event(overrides = {}) {
  return { self_id: 300, post_type: "message", message_type: "group", user_id: 101, group_id: 200,
    message_id: 42, raw: { chatType: 2, peerUid: "200", peerUin: "200", msgSeq: "12", msgId: "900012", senderUin: "101" }, ...overrides };
}

test("native recall uses exact observed ID without gray-tip query or fabricated operator", async () => {
  const sent = [];
  const relay = new RecallRelay({ selfId: 300, emit: value => sent.push(value) });
  relay.observe(event());
  await relay.recall(2, "201", "12");
  await relay.recall(2, "200", "13");
  assert.equal(sent.length, 0);
  await relay.recall(2, "200", "12");
  await relay.recall(2, "200", "12");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].message_id, 42);
  assert.equal(sent[0].user_id, 101);
  assert.equal(sent[0].operator_id, 0);
  assert.equal(sent[0].operator_known, false);
});

test("early callbacks wait for exact trusted message and private identity remains isolated", async () => {
  const sent = [];
  const relay = new RecallRelay({ selfId: 300, emit: value => sent.push(value) });
  await relay.recall(1, "peer-user", "12");
  await relay.observe(event({ message_type: "private", group_id: undefined,
    raw: { chatType: 1, peerUid: "peer-user", msgSeq: "12", senderUin: "101" } }));
  assert.equal(sent[0].notice_type, "friend_recall");
  assert.equal(sent[0].user_id, 101);
  assert.equal(sent[0].group_id, undefined);
  relay.observe(event({ self_id: 301 }));
  relay.observe(event({ user_id: 999 }));
  relay.observe(event({ group_id: 999 }));
  await relay.recall(2, "200", "12");
  assert.equal(sent.length, 1);
});

test("expiry, bounded maps, unknown messages and failed forwarding never invent recalls", async () => {
  let now = 1000;
  const sent = [];
  const relay = new RecallRelay({ selfId: 300, emit: value => sent.push(value), now: () => now, limit: 2 });
  relay.observe(event());
  now += 600001;
  await relay.recall(2, "200", "12");
  assert.equal(sent.length, 0);
  for (let i = 1; i < 20; i++) await relay.recall(2, "200", String(i));
  assert.equal(relay.pending.size, 2);
  relay.close();
  relay.observe(event());
  await relay.recall(2, "200", "12");
  assert.equal(sent.length, 0);
});

test("installed plugin hooks native callbacks and becomes inert on cleanup", async () => {
  let listener;
  const sent = [];
  const core = { selfInfo: { uin: "300" }, context: { logger: { log() {}, logError() {} },
    session: { getMsgService: () => ({ addKernelMsgListener: value => { listener = value; } }) } } };
  const context = { networkManager: { emitEvent: async value => sent.push(value) } };
  plugin_init(core, context);
  await plugin_onmessage("plugin_manager", core, context, event());
  listener.someUnrelatedCallback();
  await listener.onMsgRecall(2, "200", "12");
  assert.equal(sent.length, 1);
  plugin_cleanup(core);
  await listener.onMsgRecall(2, "200", "12");
  assert.equal(sent.length, 1);
});

test("explicit native revoke updates match original ID and peer, never plain gray-tip text", async () => {
  const sent = [];
  const relay = new RecallRelay({ selfId: 300, emit: value => sent.push(value) });
  relay.observe(event());
  const update = { msgId: "900012", msgSeq: "999", peerUid: "200", chatType: 2,
    elements: [{ grayTipElement: { revokeElement: { operatorUid: "admin" } } }] };
  await relay.update([{ ...update, peerUid: "201" }, { ...update, msgId: "other" },
    { ...update, elements: [{ textElement: { content: "message recalled" } }] }]);
  assert.equal(sent.length, 0);
  await relay.update([update]);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].message_id, 42);
  await relay.recall(2, "200", "12");
  assert.equal(sent.length, 1);
});

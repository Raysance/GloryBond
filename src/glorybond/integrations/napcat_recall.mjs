// NapCat 4.8 plugin: correlate native recalls with previously observed message IDs.
// No message text, guessed sender, gray-tip lookup, or QQ send API is used.
const states = new WeakMap();
const decimal = value => /^\d{1,20}$/.test(String(value ?? "")) && BigInt(value) > 0n;
const messageId = value => Number.isSafeInteger(Number(value)) && Number(value) !== 0;

export class RecallRelay {
  constructor({ selfId, emit, log = () => {}, now = Date.now, limit = 4096 }) {
    this.selfId = String(selfId);
    this.emit = emit;
    this.log = log;
    this.now = now;
    this.limit = limit;
    this.messages = new Map();
    this.pending = new Map();
    this.active = true;
  }

  key(chatType, peer, sequence) {
    if (![1, 2].includes(Number(chatType)) || typeof peer !== "string" || !peer || peer.length > 128 || !decimal(sequence)) return null;
    return JSON.stringify([Number(chatType), peer, String(sequence)]);
  }

  prune() {
    for (const [key, row] of this.messages) if (row.expires <= this.now()) this.messages.delete(key);
    for (const [key, expires] of this.pending) if (expires <= this.now()) this.pending.delete(key);
    for (const map of [this.messages, this.pending]) while (map.size > this.limit) map.delete(map.keys().next().value);
  }

  observe(event) {
    if (!this.active || event.post_type !== "message" || String(event.self_id) !== this.selfId ||
        String(event.user_id) === this.selfId || !decimal(event.user_id) || !messageId(event.message_id)) return;
    const raw = event.raw;
    if (!raw || String(raw.senderUin) !== String(event.user_id)) return;
    if (Number(raw.chatType) === 2 && (event.message_type !== "group" || !decimal(event.group_id) || String(raw.peerUin) !== String(event.group_id))) return;
    if (Number(raw.chatType) === 1 && event.message_type !== "private") return;
    const key = this.key(raw.chatType, raw.peerUid, raw.msgSeq);
    if (!key) return;
    this.prune();
    this.messages.set(key, { expires: this.now() + 600000, userId: Number(event.user_id),
      groupId: event.message_type === "group" ? Number(event.group_id) : null,
      messageId: Number(event.message_id), nativeId: raw.msgId ? String(raw.msgId) : null });
    const waiting = this.pending.delete(key);
    this.prune();
    if (waiting) return this.recall(raw.chatType, raw.peerUid, raw.msgSeq);
  }

  async update(messages) {
    if (!this.active || !Array.isArray(messages)) return;
    this.prune();
    for (const message of messages) {
      if (!message.msgId || !message.elements?.some(element => element.grayTipElement?.revokeElement)) continue;
      for (const [key, source] of this.messages) {
        const [type, peer, sequence] = JSON.parse(key);
        if (source.nativeId === String(message.msgId) && type === Number(message.chatType) && peer === message.peerUid) {
          await this.recall(type, peer, sequence);
        }
      }
    }
  }

  async recall(chatType, peer, sequence) {
    if (!this.active) return;
    this.prune();
    const key = this.key(chatType, peer, sequence);
    if (!key) return;
    const source = this.messages.get(key);
    if (!source) {
      this.pending.set(key, this.now() + 60000);
      this.prune();
      this.log("native_recall_unmatched");
      return;
    }
    if (source.recalled) return;
    source.recalled = true;
    const event = { time: Math.floor(this.now() / 1000), self_id: Number(this.selfId), post_type: "notice",
      notice_type: source.groupId ? "group_recall" : "friend_recall", user_id: source.userId,
      message_id: source.messageId, glorybond_recall_source: "native_sequence", operator_known: false };
    // Native callback has no operator. Zero explicitly means unknown; never use
    // the sender as a guessed operator (admins can recall another member's input).
    if (source.groupId) Object.assign(event, { group_id: source.groupId, operator_id: 0 });
    try {
      await this.emit(event);
      this.log(`forwarded message_id=${source.messageId}`);
    } catch (error) {
      source.recalled = false;
      throw error;
    }
  }

  close() {
    this.active = false;
    this.messages.clear();
    this.pending.clear();
  }
}

export function plugin_init(core, context) {
  if (states.has(core)) return;
  const logger = core.context.logger;
  const relay = new RecallRelay({ selfId: core.selfInfo.uin,
    emit: event => context.networkManager.emitEvent(event),
    log: text => logger.log(`[GloryBondRecall] ${text}`) });
  const handlers = {
    onMsgRecall: (...args) => relay.recall(...args),
    onMsgInfoListUpdate: messages => relay.update(messages),
    onRecvMsg: messages => relay.update(messages),
  };
  const listener = new Proxy({}, { get: (_target, name) => Object.hasOwn(handlers, name)
    ? (...args) => handlers[name](...args).catch(error => logger.logError("[GloryBondRecall] forward_failed", error))
    : () => {} });
  core.context.session.getMsgService().addKernelMsgListener(listener);
  states.set(core, { relay, listener });
  logger.log("[GloryBondRecall] ready native recall correlation enabled");
}

export function plugin_onmessage(_adapter, core, _context, event) {
  return states.get(core)?.relay.observe(event);
}

export function plugin_cleanup(core) {
  const state = states.get(core);
  if (!state) return;
  state.relay.close();
  const service = core.context.session.getMsgService();
  if (typeof service.removeKernelMsgListener === "function") service.removeKernelMsgListener(state.listener);
  states.delete(core);
}

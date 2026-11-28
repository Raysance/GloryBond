"""Confirmed QQ deliveries locate a run within the same bot and conversation."""
import json
import re

TTL_SECONDS = 7 * 86400


def _key(bot_id, channel, recipient_id, message_id):
    values = [str(value) for value in (bot_id, recipient_id, message_id)]
    if channel not in {"group", "private"} or not all(
        re.fullmatch(r"-?[0-9]{1,20}", value) and int(value) != 0 for value in values
    ):
        raise ValueError("Invalid receipt scope")
    return "hok:agent_run_receipt:" + ":".join((values[0], channel, values[1], str(int(values[2]))))


def record_receipt(*, bot_id, channel, recipient_id, message_id, run_id, session_id, store=None):
    if not all(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value)
               for value in (run_id, session_id)):
        raise ValueError("Invalid run reference")
    if store is None:
        from glorybond import runtime
        store = runtime.redis_deamon
    key = _key(bot_id, channel, recipient_id, message_id)
    # Repeated receipt processing never renews the original retention period.
    return store.set(key, json.dumps({"run_id": run_id, "session_id": session_id}),
                     ex=TTL_SECONDS, nx=True)


def lookup_receipt(store, *, principal, message_id):
    attrs = principal.get("attributes", {})
    delivery = attrs.get("delivery", {})
    if delivery.get("platform") != "qq":
        raise PermissionError("QQ回执只能在当前QQ会话中查询")
    if delivery.get("channel") == "private" and str(delivery.get("recipient_id")) != str(principal.get("user_id")):
        raise PermissionError("私聊回执不属于当前调用者")
    return json.loads(store.get(_key(attrs.get("bot", {}).get("user_id"), delivery.get("channel"),
                                    delivery.get("recipient_id"), message_id)) or "null")

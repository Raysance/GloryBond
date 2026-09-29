"""AI chat event input normalization."""

import re


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def quoted_message_id(event):
    """Only consider the message explicitly quoted by the current event."""
    reply = getattr(event, "reply", None)
    if reply is not None:
        return _field(reply, "message_id")
    for segment in getattr(event, "original_message", None) or []:
        if _field(segment, "type") == "reply":
            return _field(segment, "data", {}).get("id")
    return None


def normalize_quoted_message(event, reply=None):
    """Normalize adapter-resolved or get_msg data without importing the adapter."""
    message_id = quoted_message_id(event)
    if message_id is None:
        return None
    reply = reply if reply is not None else getattr(event, "reply", None)
    unavailable = {"message_id": str(message_id), "available": False}
    if not reply or str(_field(reply, "message_id")) != str(message_id):
        return unavailable
    group_id = getattr(event, "group_id", None)
    reply_group = _field(reply, "group_id")
    if reply_group is not None and str(reply_group) != str(group_id):
        return unavailable
    if group_id and _field(reply, "message_type") != "group":
        return unavailable
    sender = _field(reply, "sender", {})
    if not group_id and (str(_field(sender, "user_id")) not in
                         {str(event.get_user_id()), str(getattr(event, "self_id", ""))}
                         or _field(reply, "message_type") != "private"):
        return unavailable
    message = _field(reply, "message", [])
    parts = []
    if isinstance(message, str):
        # get_msg may return CQ text; hide media URLs and never treat them as OCR.
        parts.append(re.sub(r"\[CQ:([^,\]]+)[^\]]*\]", r"[\1消息，未读取内容]", message))
    else:
        for segment in message:
            kind, data = _field(segment, "type", "unknown"), _field(segment, "data", {})
            if kind == "text":
                parts.append(str(data.get("text", "")))
            elif kind == "at":
                parts.append(f"[提及QQ:{data.get('qq', '')}]")
            elif kind != "reply":
                parts.append(f"[{kind}消息，未读取内容]")
    text = "".join(parts)
    return {"message_id": str(message_id), "available": True,
            "sender_id": str(_field(sender, "user_id", "")),
            "sender_name": str(_field(sender, "card") or _field(sender, "nickname") or ""),
            "text": text[:12000], "truncated": len(text) > 12000}


def prepare_chat_request(event, common_expressions, default_use_memory):
    from ..zfunc import qid2nick

    user_id = event.get_user_id()
    group_id = getattr(event, "group_id", None)
    text = event.get_plaintext().strip().lstrip("#＃").strip()
    for source in sorted(common_expressions, key=len, reverse=True):
        text = re.sub(re.escape(source), common_expressions[source], text)

    use_memory = default_use_memory
    if "nomem" in text:
        use_memory = False
        text = text.replace("nomem", "").strip()

    return {
        "user_text": text,
        "user_id": user_id,
        "nickname": qid2nick(user_id),
        "group_id": group_id,
        "message_id": getattr(event, "message_id", None),
        "use_memory": use_memory,
        "quoted_message": normalize_quoted_message(event),
    }

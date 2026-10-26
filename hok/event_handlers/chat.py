"""AI chat event input normalization."""

import asyncio
import re


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _cq_unescape(value):
    return str(value).replace("&#91;", "[").replace("&#93;", "]").replace("&#44;", ",").replace("&amp;", "&")


def message_segments(message):
    """Read native segments or CQ strings without importing OneBot types."""
    if not isinstance(message, str):
        return list(message or ())
    segments, cursor = [], 0
    for match in re.finditer(r"\[CQ:([^,\]]+)((?:,[^\]]*)?)\]", message):
        if match.start() > cursor:
            segments.append({"type":"text", "data":{"text":_cq_unescape(message[cursor:match.start()])}})
        data = {}
        for field in match[2].lstrip(",").split(","):
            key, separator, value = field.partition("=")
            if separator:
                data[key] = _cq_unescape(value)
        segments.append({"type":match[1], "data":data})
        cursor = match.end()
    if cursor < len(message):
        segments.append({"type":"text", "data":{"text":_cq_unescape(message[cursor:])}})
    return segments


def image_urls(message):
    urls = []
    for segment in message_segments(message):
        data = _field(segment, "data", {})
        if _field(segment, "type") in {"image", "mface", "marketface", "face"}:
            source = data.get("url") or data.get("file", "")
            if isinstance(source, str) and source.startswith(("http://", "https://")) and source not in urls:
                urls.append(source)
    return urls


def quoted_message_id(event):
    """Only consider the message explicitly quoted by the current event."""
    reply = getattr(event, "reply", None)
    if reply is not None and _field(reply, "message_id") is not None:
        return _field(reply, "message_id")
    for segment in message_segments(getattr(event, "original_message", None) or getattr(event, "message", None)):
        if _field(segment, "type") == "reply":
            return _field(segment, "data", {}).get("id")
    return None


def _quoted_text(message, bot_id, *, nested=False):
    parts = []
    for segment in message_segments(message):
        kind, data = _field(segment, "type", "unknown"), _field(segment, "data", {})
        if kind == "text":
            parts.append(str(data.get("text", "")))
        elif kind == "at":
            if str(data.get("qq", "")) != str(bot_id):
                parts.append(f"[提及QQ:{data.get('qq', '')}]")
        elif kind == "forward":
            parts.append("[嵌套合并转发消息，未展开]" if nested else "[合并转发消息，未读取内容]")
        elif kind in {"mface", "marketface", "face"} and image_urls([segment]):
            parts.append("[动态表情，像素待读取]")
        elif kind != "reply":
            parts.append(f"[{kind}消息，未读取内容]")
    return "".join(parts)


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
    text = _quoted_text(message, getattr(event, "self_id", "")).strip().lstrip("#＃").strip()
    return {"message_id": str(message_id), "available": True,
            "sender_id": str(_field(sender, "user_id", "")),
            "sender_name": str(_field(sender, "card") or _field(sender, "nickname") or ""),
            "text": text[:12000], "truncated": len(text) > 12000,
            "image_urls": image_urls(message)}


async def _expand_quoted_forwards(event, message, quote, fetch_forward_message, limits):
    """Read only forwards attached to the validated outer quote, never child IDs."""
    parts, sources, seen = [], [], set()
    size = node_count = forward_count = 0
    truncated = False
    bot_id = getattr(event, "self_id", "")

    def append(text):
        nonlocal size, truncated
        remaining = limits["max_chars"] - size
        parts.append(text[:remaining])
        size += min(len(text), remaining)
        truncated |= len(text) > remaining

    try:
        async with asyncio.timeout(limits["timeout_seconds"]):
            for segment in message_segments(message):
                if size >= limits["max_chars"]:
                    truncated = True
                    break
                if _field(segment, "type") != "forward":
                    append(_quoted_text([segment], bot_id))
                    sources.extend(image_urls([segment]))
                    continue
                if forward_count >= limits["max_forwards"] or node_count >= limits["max_messages"]:
                    append("[合并转发读取数量已达上限，其余未读取]")
                    truncated = True
                    continue
                data = _field(segment, "data", {})
                if not isinstance(data, dict):
                    append("[合并转发消息格式无效，未读取内容]")
                    continue
                forward_id = str(data.get("id") or "")
                if forward_id and forward_id in seen:
                    append("[重复合并转发，已在前文处理]")
                    continue
                forward_count += 1
                if forward_id:
                    seen.add(forward_id)
                nodes = data.get("content")
                if not isinstance(nodes, list):
                    if not forward_id or fetch_forward_message is None:
                        append("[合并转发消息不可用，未读取内容]")
                        continue
                    try:
                        payload = await fetch_forward_message(id=forward_id)
                        nodes = _field(payload, "messages", _field(payload, "message"))
                    except Exception:
                        append("[合并转发消息获取失败，未读取内容]")
                        continue
                if not isinstance(nodes, list) or not nodes:
                    append("[合并转发消息为空或格式无效，未读取内容]")
                    continue
                append("\n[合并转发聊天记录，仅展开一层；署名为转发资料]\n")
                for node in nodes:
                    if node_count >= limits["max_messages"] or size >= limits["max_chars"]:
                        truncated = True
                        break
                    node_count += 1
                    node = _field(node, "data", {}) if _field(node, "type") == "node" else node
                    content = _field(node, "content", _field(node, "message"))
                    if not isinstance(content, (list, str)):
                        append("[转发节点内容不可用，未读取]\n")
                        continue
                    try:
                        text = _quoted_text(content, bot_id, nested=True)
                        images = image_urls(content)
                    except (AttributeError, TypeError):
                        append("[转发节点格式无效，未读取]\n")
                        continue
                    sender = _field(node, "sender", {})
                    name = str(_field(sender, "card") or _field(sender, "nickname")
                               or _field(node, "nickname") or "未知发言者")[:200]
                    user_id = str(_field(sender, "user_id") or _field(node, "user_id")
                                  or _field(node, "uin") or "")[:20]
                    label = f"{name}（QQ:{user_id}）" if user_id else name
                    append(label + "：" + text + "\n")
                    sources.extend(images)
                append("[合并转发聊天记录结束]\n")
    except TimeoutError:
        append("[合并转发读取超时，其余内容未读取]")
        truncated = True
    return {**quote, "forward_expanded": True,
            "text": "".join(parts).strip().lstrip("#＃").strip(),
            "truncated": truncated, "image_urls": list(dict.fromkeys(sources))}


async def read_quoted_message(event, fetch_message, fetch_forward_message=None, *, forward_limits=None):
    """Resolve only the explicit quote, using an injected entry-point API call."""
    quote = normalize_quoted_message(event)
    if quote is None:
        return quote
    reply = getattr(event, "reply", None)
    if not quote["available"]:
        try:
            reply = await fetch_message(message_id=int(quote["message_id"]))
            quote = normalize_quoted_message(event, reply)
        except Exception:
            return {"message_id":quote["message_id"], "available":False}
    if not quote["available"]:
        return quote
    message = _field(reply, "message", [])
    if not any(_field(segment, "type") == "forward" for segment in message_segments(message)):
        return quote
    from ..zstatic import qq_forward_message_config

    limits = {**qq_forward_message_config, **(forward_limits or {})}
    return await _expand_quoted_forwards(event, message, quote, fetch_forward_message, limits)


def prepare_chat_request(event, common_expressions, default_use_memory):
    from ..zfunc import qid2nick

    user_id = event.get_user_id()
    group_id = getattr(event, "group_id", None)
    segments = message_segments(getattr(event, "original_message", None) or getattr(event, "message", None))
    original_parts = [str(_field(segment, "data", {}).get("text", ""))
                      for segment in segments if _field(segment, "type") == "text"]
    original_text = "".join(original_parts) if original_parts else event.get_plaintext()
    text = event.get_plaintext().strip().lstrip("#＃").strip()
    for source in sorted(common_expressions, key=len, reverse=True):
        text = re.sub(re.escape(source), common_expressions[source], text)

    use_memory = default_use_memory
    if "nomem" in text:
        use_memory = False
        text = text.replace("nomem", "").strip()

    mentioned_users = list(dict.fromkeys(str(_field(segment, "data", {}).get("qq", ""))
        for segment in segments if _field(segment, "type") == "at"
        and re.fullmatch(r"[1-9][0-9]{0,19}", str(_field(segment, "data", {}).get("qq", "")))
        and str(_field(segment, "data", {}).get("qq")) != str(getattr(event, "self_id", ""))))
    if mentioned_users:
        text += "\n[本次消息提及的群成员QQ：" + "、".join(mentioned_users) + "]"
    if any(_field(segment, "type") == "at" and _field(segment, "data", {}).get("qq") == "all"
           for segment in segments):
        text += "\n[本次消息包含原生@全体成员]"
    for segment in segments:
        kind = _field(segment, "type")
        if kind in {"image", "mface", "marketface", "face"} and not image_urls([segment]):
            text += f"\n[{kind}消息未提供可读取的图片地址，当前未读取其像素]"

    return {
        "user_text": text,
        "original_user_text": original_text,
        "user_id": user_id,
        "nickname": qid2nick(user_id),
        "group_id": group_id,
        "message_id": getattr(event, "message_id", None),
        "use_memory": use_memory,
        "quoted_message": normalize_quoted_message(event),
        "image_urls": image_urls(segments),
    }

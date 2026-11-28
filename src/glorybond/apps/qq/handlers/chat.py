"""AI chat event input normalization."""

import asyncio
import re

from glorybond.apps.qq.agent.inflight import ChatRollouts


live_chat_rollouts = ChatRollouts()


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def chat_message_key(event):
    """Use adapter identity, never quoted IDs or model-supplied metadata."""
    bot, user, message = (_field(event, field) for field in ("self_id", "user_id", "message_id"))
    group = _field(event, "group_id")
    if any(value is None or str(value) == "" for value in (bot, user, message)):
        return None
    return (str(bot), "group" if group is not None else "private",
            str(group) if group is not None else str(user), str(user), str(message))


def cancel_recalled_chat(event):
    kind = _field(event, "notice_type")
    if kind not in {"group_recall", "friend_recall"}:
        return False
    if (kind == "group_recall") != (_field(event, "group_id") is not None):
        return False
    return live_chat_rollouts.recall(chat_message_key(event))


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


def document_sources(message):
    """Only adapter file segments can supply file IDs or download URLs."""
    if isinstance(message, str):
        return []
    files = []
    for segment in message or ():
        if _field(segment, "type") == "file":
            data = _field(segment, "data", {})
            files.append({"name": data.get("name") or data.get("file") or "未知文件",
                          "id": data.get("file_id"), "url": data.get("url"),
                          "size": data.get("file_size"), "busid": data.get("busid")})
    return files


def media_sources(message):
    """Native segments only: text resembling a CQ video cannot mint an attachment."""
    if isinstance(message, str):
        return []
    result = []
    for segment in message or ():
        kind, data = _field(segment, "type"), _field(segment, "data", {})
        if kind in {"video", "record"}:
            result.append({"kind": "video" if kind == "video" else "audio",
                           "url": data.get("url"), "file": data.get("file"),
                           "file_size": data.get("file_size"),
                           "name": str(data.get("name") or ("视频" if kind == "video" else "语音"))[:200]})
    return result


def native_faces(message):
    """Keep native QQ face IDs as data; never infer them from visible text."""
    faces = []
    for segment in message_segments(message):
        if _field(segment, "type") != "face":
            continue
        data = _field(segment, "data", {})
        identifier = str(data.get("id", ""))
        if re.fullmatch(r"[0-9]{1,6}", identifier):
            faces.append({"id": identifier})
    return faces


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
        elif kind == "file" and not nested:
            parts.append("[引用文件]")
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
    if reply_group not in (None, 0, "0") and str(reply_group) != str(group_id):
        return unavailable
    if group_id and _field(reply, "message_type") != "group":
        return unavailable
    sender = _field(reply, "sender", {})
    if not group_id and (str(_field(sender, "user_id")) not in
                         {str(event.get_user_id()), str(getattr(event, "self_id", ""))}
                         or _field(reply, "message_type") != "private"):
        return unavailable
    message = _field(reply, "message", [])
    files = document_sources(message)
    media = media_sources(message)
    if files or media:
        # NoneBot's compact Reply can omit group_id. Re-fetch get_msg so the
        # file can be tied to its actual group or the peer of an outgoing DM.
        if group_id and str(reply_group) != str(group_id):
            return unavailable
        if not group_id and str(_field(sender, "user_id")) != str(event.get_user_id()):
            if str(_field(reply, "target_id")) != str(event.get_user_id()):
                return unavailable
    text = _quoted_text(message, getattr(event, "self_id", "")).strip().lstrip("#＃").strip()
    return {"message_id": str(message_id), "available": True,
            "sender_id": str(_field(sender, "user_id", "")),
            "sender_name": str(_field(sender, "card") or _field(sender, "nickname") or ""),
            "text": text[:12000], "truncated": len(text) > 12000,
            **({"document_sources": files} if files else {}),
            **({"media_sources": media} if media else {}),
            "image_urls": image_urls(message), "native_faces": native_faces(message)}


async def _expand_quoted_forwards(event, message, quote, fetch_forward_message, limits):
    """Read only forwards attached to the validated outer quote, never child IDs."""
    parts, sources, faces, seen = [], [], [], set()
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
                    faces.extend(native_faces([segment]))
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
                    faces.extend(native_faces(content))
                append("[合并转发聊天记录结束]\n")
    except TimeoutError:
        append("[合并转发读取超时，其余内容未读取]")
        truncated = True
    return {**quote, "forward_expanded": True,
            "text": "".join(parts).strip().lstrip("#＃").strip(),
            "truncated": truncated, "image_urls": list(dict.fromkeys(sources)), "native_faces": faces}


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
    from glorybond.config.settings import qq_forward_message_config

    limits = {**qq_forward_message_config, **(forward_limits or {})}
    return await _expand_quoted_forwards(event, message, quote, fetch_forward_message, limits)


async def prepare_live_chat_request(event, common_expressions, default_use_memory,
                                    fetch_message, fetch_forward_message=None, bot=None):
    from glorybond.features.facade import is_agent_chat_ignored

    if await asyncio.to_thread(is_agent_chat_ignored, event.get_user_id(), getattr(event, "group_id", None)):
        return None
    request = prepare_chat_request(event, common_expressions, default_use_memory)
    request["quoted_message"] = await read_quoted_message(event, fetch_message, fetch_forward_message)
    quote = request["quoted_message"] or {}
    if request.get("document_sources") or quote.get("document_sources"):
        from glorybond.apps.qq.agent.documents import read_qq_document
        async def read_file(source):
            return await read_qq_document(bot, getattr(event, "group_id", None), source)
        request["read_file"] = read_file
    if request.get("media_sources") or quote.get("media_sources"):
        request["media_bot"] = bot
    return request


def prepare_chat_request(event, common_expressions, default_use_memory):
    from glorybond.features.facade import qid2nick

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
        "mentioned_user_ids": tuple(mentioned_users),
        "message_timestamp": getattr(event, "time", None),
        "use_memory": use_memory,
        "quoted_message": normalize_quoted_message(event),
        "document_sources": document_sources(getattr(event, "original_message", None) or getattr(event, "message", None)),
        "media_sources": media_sources(getattr(event, "original_message", None) or getattr(event, "message", None)),
        "image_urls": image_urls(segments),
        "native_faces": native_faces(segments),
    }

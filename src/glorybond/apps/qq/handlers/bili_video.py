"""Bilibili subscription command parsing and business dispatch."""

import asyncio
import json
import xml.etree.ElementTree as ET


def share_references(event):
    """Read only native text/JSON/XML segments in the current message."""
    from glorybond.integrations.bili_media import video_references

    segments = getattr(event, "original_message", None)
    if segments is None:
        segments = getattr(event, "message", ())
    sources = []
    url_keys = {"url", "qqdocurl", "jumpurl", "contentjumpurl", "actiondata"}

    def card_urls(node, depth=0):
        if depth > 8:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in url_keys and isinstance(value, str):
                    sources.append(value)
                elif isinstance(value, (dict, list)):
                    card_urls(value, depth + 1)
        elif isinstance(node, list):
            for value in node[:32]:
                card_urls(value, depth + 1)

    for segment in list(segments or ())[:64]:
        kind = segment.get("type") if isinstance(segment, dict) else getattr(segment, "type", None)
        data = segment.get("data", {}) if isinstance(segment, dict) else getattr(segment, "data", {})
        if kind == "text":
            sources.append(str(data.get("text", ""))[:32768])
        elif kind in {"json", "xml"}:
            raw = data.get("data", "")
            if not isinstance(raw, str) or len(raw) > 32768:
                continue
            try:
                if kind == "json":
                    card_urls(json.loads(raw))
                elif "<!DOCTYPE" not in raw.upper() and "<!ENTITY" not in raw.upper():
                    for element in ET.fromstring(raw).iter():
                        card_urls(element.attrib)
            except (ValueError, ET.ParseError):
                continue
    return video_references("\n".join(sources))


async def iter_share_replies(event):
    from glorybond.integrations.api import BiliVideoError
    from glorybond.features.facade import bili_video_share_message
    from glorybond.common import log_message

    group = getattr(event, "group_id", None)
    scope = ("group:" + str(group)) if group else ("private:" + str(event.get_user_id()))
    scope = str(getattr(event, "self_id", "")) + ":" + scope
    for reference in share_references(event):
        try:
            reply = await asyncio.to_thread(bili_video_share_message, reference, scope=scope)
            if reply:
                yield reply
        except BiliVideoError as error:
            yield str(error)
        except Exception as error:
            log_message("BILI_VIDEO_SHARE_FAILED: error_type=" + type(error).__name__)
            yield "B站视频处理暂时失败，请稍后再试。"


def strip_bili_video_command(raw_msg, prefixes):
    text = str(raw_msg or "").strip()
    text = text.lstrip("#＃").strip()
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


async def admin_reply(event):
    from glorybond.features.facade import bili_video_admin_command

    return await asyncio.to_thread(
        bili_video_admin_command,
        event.get_plaintext().strip(),
    )


async def subscribe_reply(event):
    from glorybond.features.facade import bili_video_subscribe_user

    up_name = strip_bili_video_command(
        event.get_plaintext(),
        ["订阅B站", "订阅b站", "订阅"],
    )
    return await asyncio.to_thread(
        bili_video_subscribe_user,
        event.get_user_id(),
        up_name,
    )


async def unsubscribe_reply(event):
    from glorybond.features.facade import bili_video_unsubscribe_user

    query_text = strip_bili_video_command(
        event.get_plaintext(),
        ["取消B站订阅", "取消b站订阅", "取消订阅"],
    )
    return await asyncio.to_thread(
        bili_video_unsubscribe_user,
        event.get_user_id(),
        query_text,
    )


async def latest_reply(event):
    from glorybond.features.facade import bili_video_latest_for_user

    return await asyncio.to_thread(
        bili_video_latest_for_user,
        event.get_user_id(),
    )


async def my_subscription_reply(event):
    from glorybond.features.facade import bili_video_my_subscription

    return await asyncio.to_thread(
        bili_video_my_subscription,
        event.get_user_id(),
    )

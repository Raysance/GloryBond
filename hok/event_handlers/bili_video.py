"""Bilibili subscription command parsing and business dispatch."""

import asyncio


def strip_bili_video_command(raw_msg, prefixes):
    text = str(raw_msg or "").strip()
    text = text.lstrip("#＃").strip()
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


async def admin_reply(event):
    from ..zfunc import bili_video_admin_command

    return await asyncio.to_thread(
        bili_video_admin_command,
        event.get_plaintext().strip(),
    )


async def subscribe_reply(event):
    from ..zfunc import bili_video_subscribe_user

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
    from ..zfunc import bili_video_unsubscribe_user

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
    from ..zfunc import bili_video_latest_for_user

    return await asyncio.to_thread(
        bili_video_latest_for_user,
        event.get_user_id(),
    )


async def my_subscription_reply(event):
    from ..zfunc import bili_video_my_subscription

    return await asyncio.to_thread(
        bili_video_my_subscription,
        event.get_user_id(),
    )

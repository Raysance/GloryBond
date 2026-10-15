"""X commands: independent parsing, no NoneBot types or message sending."""

import asyncio
import re


def parse_x_command(raw):
    raw = str(raw or "").strip()
    if not raw.startswith(("#", "＃")):
        return None
    command = raw.lstrip("#＃").strip()
    if re.fullmatch(r"x(?:\s+(?:list|check))?", command, re.I) and len(raw) - len(raw.lstrip("#＃")) == 2:
        return "admin", raw
    if len(raw) - len(raw.lstrip("#＃")) != 1:
        return None
    for pattern, action in (
        (r"(?:取消X订阅|取消订阅X|取消推特订阅|取消订阅推特)\s*(.*)", "unsubscribe"),
        (r"(?:我的X订阅|X订阅列表|我的推特订阅)", "mine"),
        (r"(?:X最新内容|最新X内容|X最新动态|推特最新内容|X最新推文)", "latest"),
        (r"(?:订阅X|订阅推特|关注X|关注推特)\s*(.*)", "subscribe"),
    ):
        match = re.fullmatch(pattern, command, re.I)
        if match:
            return action, match.group(1).strip() if match.lastindex else ""
    return None


async def command_reply(event):
    from .. import zfunc

    parsed = parse_x_command(event.get_plaintext())
    if not parsed:
        return "X 命令格式错误"
    action, query = parsed
    functions = {
        "subscribe": zfunc.x_subscribe_user, "unsubscribe": zfunc.x_unsubscribe_user,
        "mine": zfunc.x_my_subscription, "latest": zfunc.x_latest_for_user,
        "admin": zfunc.x_admin_command,
    }
    args = (query,) if action == "admin" else (event.get_user_id(),)
    if action in {"subscribe", "unsubscribe"}:
        args += (query,)
    try:
        return await asyncio.to_thread(functions[action], *args)
    except (ValueError, RuntimeError) as error:
        return str(error)

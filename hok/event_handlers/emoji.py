"""Emoji generation command parsing and dispatch."""

import asyncio
import re


_NAMED_TOKENS = (
    "template=", "模板=", "模板名=", "prompt=", "提示=", "提示词=",
    "template:", "模板:", "模板名:", "prompt:", "提示:", "提示词:",
    "template：", "模板：", "模板名：", "prompt：", "提示：", "提示词：",
)


def _strip_command(raw_text):
    text = raw_text.strip()
    for prefix in ("#emoji", "＃emoji", "##emoji", "＃＃emoji"):
        if text.lower().startswith(prefix.lower()):
            return text[len(prefix):].strip()
    return text.replace("emoji", "", 1).strip()


def _split_named_arg(text, names):
    for name in names:
        for separator in ("=", "：", ":"):
            token = name + separator
            index = text.find(token)
            if index < 0:
                continue
            value_start = index + len(token)
            next_positions = [
                position
                for candidate in _NAMED_TOKENS
                if (position := text.find(candidate, value_start)) >= 0
            ]
            value_end = min(next_positions) if next_positions else len(text)
            value = text[value_start:value_end].strip()
            remainder = (text[:index] + text[value_end:]).strip()
            return value, remainder
    return None, text


def _first_image_url(message):
    try:
        for segment in message:
            if getattr(segment, "type", "") != "image":
                continue
            data = getattr(segment, "data", None) or {}
            image_url = data.get("url") or data.get("file")
            if image_url:
                return image_url
    except (TypeError, AttributeError):
        return None
    return None


def parse_emoji_request(raw_text, message):
    raw_tail = _strip_command(raw_text)
    template_value, raw_tail = _split_named_arg(
        raw_tail, ("template", "模板", "模板名")
    )
    prompt_value, raw_tail = _split_named_arg(
        raw_tail, ("prompt", "提示", "提示词")
    )
    prompt_tail = prompt_value if prompt_value is not None else raw_tail
    template_prefix = None
    template_name = None
    if template_value:
        if re.fullmatch(r"[A-Za-z0-9_]+", template_value):
            template_prefix = template_value
        else:
            template_name = template_value
    elif raw_tail:
        parts = raw_tail.split(maxsplit=1)
        if len(parts) == 2 and re.fullmatch(r"[A-Za-z0-9_]+", parts[0]):
            template_prefix = parts[0]
            prompt_tail = parts[1].strip()
    return {
        "custom_image_url": _first_image_url(message),
        "template_prefix": template_prefix,
        "template_name": template_name,
        "prompt_tail": prompt_tail,
    }


async def generate_emoji(event):
    from ..tools.gen_emoji_image import generate_user_kmoji_image

    request = parse_emoji_request(event.get_plaintext(), event.message)
    return await asyncio.to_thread(
        generate_user_kmoji_image,
        user_qid=event.get_user_id(),
        **request,
    )

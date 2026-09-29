"""AI chat event input normalization."""

import re


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
    }

"""History-query event parsing and business dispatch."""

import asyncio


class HistoryQueryDetailError(Exception):
    def __init__(self, prefix, error):
        super().__init__(str(error))
        self.prefix = prefix
        self.original_error = error


async def history_query_reply(event):
    from ..zfunc import (
        format_history_query_prefix,
        history_query_handler,
        history_query_multiple_matches_link,
        history_query_single_match,
        qid2nick,
    )

    user_qid = event.get_user_id()
    received_message = event.get_plaintext().replace("我", qid2nick(user_qid))
    result = await asyncio.to_thread(history_query_handler, received_message)
    if isinstance(result, str):
        return {"kind": "text", "text": result}

    query_target, matches, query_desc, stats = result
    prefix = format_history_query_prefix(query_desc, stats)
    if isinstance(matches, str):
        return {"kind": "text", "text": prefix + matches}
    if not matches:
        return {"kind": "text", "text": prefix + "未找到符合条件的战绩。"}

    if len(matches) == 1:
        detail, realname = matches[0]
        try:
            battle_info, image_path, _ = await asyncio.to_thread(
                history_query_single_match,
                detail,
                realname,
            )
        except Exception as error:
            raise HistoryQueryDetailError(prefix, error) from error
        return {
            "kind": "battle",
            "text": prefix + battle_info,
            "image_path": image_path,
        }

    website_link = await asyncio.to_thread(
        history_query_multiple_matches_link,
        query_target,
        matches,
    )
    return {
        "kind": "text",
        "text": (
            prefix
            + f"找到 {len(matches)} 局符合条件的战绩，点击链接查看详情：(视角随机)\n"
            + website_link
        ),
    }

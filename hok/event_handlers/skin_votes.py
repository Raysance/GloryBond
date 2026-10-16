"""Skin-return ranking dispatch without NoneBot or message delivery dependencies."""

import asyncio


async def skin_votes_reply():
    from ..zfunc import skin_votes_query_process

    return await asyncio.to_thread(skin_votes_query_process)

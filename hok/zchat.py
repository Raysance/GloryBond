"""Compatibility entry points; QQ chat runs only the shared ReAct engine."""

__all__ = ["chat_process", "chat_process_async"]


async def chat_process_async(*, return_artifacts=False, **request):
    from .zfunc import agent_chat
    result = await agent_chat(**request)
    return result if return_artifacts else result.get("text", "")


async def chat_process(*, return_artifacts=False, **request):
    return await chat_process_async(return_artifacts=return_artifacts, **request)

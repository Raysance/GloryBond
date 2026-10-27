"""Explicit administrator service-check command; independent of AI chat."""


async def command_reply():
    from ..zfunc import service_health_check

    return await service_health_check()

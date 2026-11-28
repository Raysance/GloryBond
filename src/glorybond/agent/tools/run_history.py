"""Previous run inspection is an ordinary discovered read tool."""
from pydantic import BaseModel, ConfigDict, Field, model_validator

from glorybond.agent.run_history import RunHistory


class RunHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$",
                               description="已有记录中的运行编号；可查本群或本人私聊/本地会话内的运行")
    message_id: str | None = Field(default=None, pattern=r"^-?[0-9]{1,20}$",
                                   description="当前QQ会话内机器人已发送回复的消息ID，按真实回执精确定位")
    use_quote: bool = Field(default=True, description="未指定编号时使用本轮已验证的机器人引用；没有机器人引用则列出本人最近运行")
    offset: int = Field(default=0, ge=0, le=49)
    limit: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def one_target(self):
        if self.run_id and self.message_id:
            raise ValueError("run_id与message_id不能同时指定")
        return self


def register_run_history_tool(registry, *, log, bridge=None):
    history = RunHistory(log, bridge)
    async def read(args, ctx):
        return await history.read(args, ctx)
    registry.register(name="read_run_history", category="run_history", effect="read", initially_visible=False,
        args_model=RunHistoryArgs, handler=read, timeout=30,
        description="查询之前AI对话的运行metadata、模型与工具调用链、各轮耗时、token及费用。"
                    "引用机器人回复时可自动精确定位那次运行；也可按run_id、消息ID或本人最近记录查询。"
                    "返回已记录用量，费用区分报告值、估算与未知；并发工具耗时不重复累加为墙钟时间。")

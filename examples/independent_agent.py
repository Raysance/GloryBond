"""Runnable port example using a scripted model and no external services."""

import asyncio
from datetime import datetime, timezone
import json
import time

from pydantic import BaseModel

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry


class MultiplyArgs(BaseModel):
    left: float
    right: float


def multiply(args, context):
    return {"value": args.left * args.right}


class ExampleModel:
    async def complete(self, messages, tools, on_delta):
        observations = [item for item in messages if item["role"] == "tool"]
        if observations:
            result = json.loads(observations[-1]["content"])
            return {
                "message": {
                    "role": "assistant",
                    "content": str(result["data"]["value"]),
                }
            }
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "multiply-1",
                        "type": "function",
                        "function": {
                            "name": "multiply",
                            "arguments": json.dumps({"left": 6, "right": 7}),
                        },
                    }
                ],
            }
        }


class MemoryState:
    def __init__(self):
        self.events = {}
        self.dialogues = {}

    async def append_event(self, session_id, event):
        self.events.setdefault(session_id, []).append(event)

    async def load_events(self, session_id):
        return self.events.get(session_id, [])

    async def load_dialogue(self, session_id):
        return self.dialogues.get(session_id, [])

    async def save_dialogue(self, session_id, question, answer):
        self.dialogues.setdefault(session_id, []).extend(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        )


class PrintOutput:
    async def publish(self, event):
        if event["kind"] in {"tool.call", "tool.result", "output.message"}:
            print(
                json.dumps(
                    {"kind": event["kind"], "data": event["data"]}, ensure_ascii=False
                )
            )


class SystemClock:
    def now(self):
        return datetime.now(timezone.utc).isoformat()

    def monotonic(self):
        return time.monotonic()


async def main():
    registry = ToolRegistry()
    registry.register(
        name="multiply",
        description="Multiply two numbers",
        args_model=MultiplyArgs,
        handler=multiply,
    )
    runtime = AgentRuntime(
        model=ExampleModel(),
        registry=registry,
        state=MemoryState(),
        output=PrintOutput(),
        clock=SystemClock(),
    )
    await runtime.run(RunRequest("Multiply 6 by 7", "example", Principal("caller")))
    await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())

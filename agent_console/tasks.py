"""Translate persisted application task records into generic agent requests."""

import asyncio
from dataclasses import replace

from agent_runtime.models import Principal, RunRequest
from agent_runtime.runtime.output import EventOutput


def task_request(task, *, system_prompt=""):
    identity = dict(task["principal"])
    identity["scopes"] = frozenset(identity["scopes"])
    # Read existing console task records without changing their stored identity.
    attributes = dict(identity.pop("attributes", {}))
    if "group_id" in identity or "all_groups" in identity:
        attributes["chat"] = {
            "group_id": identity.pop("group_id", None),
            "all_groups": identity.pop("all_groups", False),
        }
    identity["attributes"] = attributes
    return RunRequest(
        user_message=task.get("instruction") or task.get("message") or "定时任务",
        conversation_id=task["session_id"],
        principal=Principal(**identity),
        system_prompt=system_prompt,
        required_tools=tuple(
            dict.fromkeys([*task.get("required_tools", ()), "discover_tools"])
        ),
        metadata={"origin": "background", "task_id": task["task_id"]}
        if "task_id" in task
        else {},
    )


class TaskScheduler:
    """Application scheduler; fixed deliveries use the same event/output ports."""

    def __init__(self, *, runtime, bridge, state, output, clock, prompt_factory):
        self.runtime, self.bridge = runtime, bridge
        self.state, self.output, self.clock = state, output, clock
        self.prompt_factory = prompt_factory
        self.active = {}
        self.active_run_ids = set()

    async def run(self):
        while True:
            try:
                for task in await self.bridge.call("task_due"):
                    if task["task_id"] not in self.active:
                        job = asyncio.create_task(self.perform(task))
                        self.active[task["task_id"]] = job
                        job.add_done_callback(
                            lambda done, task_id=task["task_id"]: self.active.pop(
                                task_id, None
                            )
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Claims have a durable lease and can be recovered on restart.
                pass
            await asyncio.sleep(0.5)

    async def perform(self, task):
        request = None
        submitted = None
        try:
            if not await self.bridge.call(
                "task_active", task_id=task["task_id"], lease_token=task["lease_token"]
            ):
                return
            if task.get("kind", "agent") == "message":
                request = task_request(task)
                self.active_run_ids.add(request.run_id)
                emitter = EventOutput(request, self.state, self.output, self.clock)
                started = self.clock.monotonic()
                sequence = task["runs"] + 1
                await emitter.emit(
                    "run.start",
                    {
                        "message": f"定时消息 {sequence}/{task['max_runs']}",
                        "task_id": task["task_id"],
                    },
                )
                text = (
                    task["message"]
                    .replace("{run}", str(sequence))
                    .replace("{max_runs}", str(task["max_runs"]))
                )
                await emitter.emit(
                    "output.message",
                    {
                        "kind": "notification",
                        "text": text,
                        "task_id": task["task_id"],
                        "delivery_index": sequence,
                    },
                )
                await emitter.emit(
                    "run.end",
                    {
                        "status": "completed",
                        "duration": self.clock.monotonic() - started,
                        "tool_calls": 0,
                    },
                )
                failed = False
            else:
                request = task_request(task)
                request = replace(
                    request,
                    system_prompt=await self.prompt_factory(
                        request.principal, request.user_message
                    ),
                )
                self.active_run_ids.add(request.run_id)
                submitted = self.runtime.submit(request)
                result = await self.runtime.active[submitted]
                failed = bool(result.get("error"))
            await self.bridge.call(
                "task_finish",
                task_id=task["task_id"],
                lease_token=task["lease_token"],
                failed=failed,
            )
        except asyncio.CancelledError:
            if submitted:
                await self.runtime.cancel(submitted)
            raise
        except Exception as exc:
            if request:
                emitter = EventOutput(request, self.state, self.output, self.clock)
                await emitter.emit(
                    "run.error", {"error": str(exc)[:1500], "type": type(exc).__name__}
                )
                await emitter.emit("run.end", {"status": "failed"})
            try:
                await self.bridge.call(
                    "task_finish",
                    task_id=task["task_id"],
                    lease_token=task["lease_token"],
                    failed=True,
                )
            except Exception:
                pass
        finally:
            if request:
                self.active_run_ids.discard(request.run_id)

    async def close(self):
        jobs = list(self.active.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

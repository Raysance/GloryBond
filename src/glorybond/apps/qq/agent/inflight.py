"""Bind live QQ chat work to the trusted triggering message."""

import asyncio
from collections import OrderedDict
import time


class ChatRollouts:
    def __init__(self):
        self.active = {}
        self.recalled = OrderedDict()

    def _prune(self):
        cutoff = time.monotonic() - 300
        while self.recalled and next(iter(self.recalled.values())) <= cutoff:
            self.recalled.popitem(last=False)

    async def run(self, key, operation):
        if key is None:
            return await operation()
        self._prune()
        # A recall can arrive while earlier message matchers are still running.
        if key in self.recalled or key in self.active:
            return None
        task = asyncio.create_task(operation())
        entry = {"task": task, "recalled": False}
        self.active[key] = entry
        try:
            return await task
        except (asyncio.CancelledError, Exception):
            if not entry["recalled"]:
                raise
            # A cleanup/storage error after withdrawal must not become a reply.
            return None
        finally:
            self.active.pop(key, None)

    def recall(self, key):
        if key is None:
            return False
        self._prune()
        self.recalled.pop(key, None)
        self.recalled[key] = time.monotonic()
        while len(self.recalled) > 2048:
            self.recalled.popitem(last=False)
        entry = self.active.get(key)
        if entry is None or entry["task"].done():
            return False
        entry["recalled"] = True
        # Repeated notices must not interrupt the runtime's cancellation cleanup.
        if not entry["task"].cancelling():
            entry["task"].cancel()
        return True

    def was_recalled(self, key):
        self._prune()
        return key in self.recalled or bool(self.active.get(key, {}).get("recalled"))

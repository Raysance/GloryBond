"""Append-only local debug journals, independent of the agent runtime."""

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import threading


logger = logging.getLogger(__name__)


class LocalEventLog:
    dialogue_kinds = {
        "run.start", "output.message", "output.artifact", "run.warning",
        "run.error", "run.end",
        "request.failed",
    }

    def __init__(self, directory, *, enabled=True, redactor=None):
        self.directory = Path(directory).resolve()
        self.enabled = enabled
        self.redactor = redactor or (lambda value: value)
        self.last_error = None
        self._lock = threading.Lock()
        self._known_ids = {}

    @property
    def status(self):
        return {
            "enabled": self.enabled,
            "directory": str(self.directory),
            "last_error": self.last_error,
        }

    async def record(self, event):
        return await self.record_many([event])

    async def record_many(self, events):
        """A failed debug write must not interrupt dialogue or SSE delivery."""
        if not self.enabled:
            return True
        try:
            # Snapshot and redact before handing data to another thread.
            rows = [
                (clean, json.dumps(clean, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
                for clean in (self.redactor(event) for event in events)
            ]
            if not rows:
                return True
            await asyncio.to_thread(self._record, rows)
            self.last_error = None
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = self.redactor(str(exc))
            logger.warning("Local conversation log write failed: %s", self.last_error)
            return False

    def _component(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
            raise ValueError("Invalid local log session/run identifier")
        return value

    def _record(self, rows):
        # Thread-level locking also protects writes whose coroutine was cancelled.
        with self._lock:
            for event, line in rows:
                session = self._component(event["session_id"])
                run = self._component(event["run_id"])
                event_id = event["id"]
                if not isinstance(event_id, str) or not event_id:
                    raise ValueError("Missing local log event identifier")
                directory = self.directory / session
                self._append_once(directory / "runs" / (run + ".jsonl"), event_id, line)
                if not event.get("transient") and event["kind"] in self.dialogue_kinds:
                    self._append_once(directory / "dialogue.jsonl", event_id, line)

    def _append_once(self, path, event_id, line):
        if path not in self._known_ids:
            known = set()
            if path.exists():
                with path.open("rb") as handle:
                    for existing in handle:
                        try:
                            known.add(json.loads(existing)["id"])
                        except (ValueError, KeyError, TypeError):
                            # Preserve a torn line for inspection, and continue the journal.
                            continue
            self._known_ids[path] = known
        known = self._known_ids[path]
        if event_id in known:
            return
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell():
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    handle.write(b"\n")
            handle.write(line)
        known.add(event_id)

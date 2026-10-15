"""Multiple deliveries through the injected, trusted QQ message sender."""

import base64
import asyncio
import logging
from .trace import build_trace
from agent_console.replies import DeliveryHistory


class QQOutput:
    def __init__(self, *, bridge, local_log, sender, prepare_reply, store_artifact, event_projector=None, mentions=None,
                 context_bridge=None, context_timeout_seconds=10):
        self.bridge, self.local_log = bridge, local_log
        self.sender, self.prepare_reply, self.store_artifact = sender, prepare_reply, store_artifact
        self.event_projector = event_projector or (lambda e: e)
        self.events, self.artifacts, self.finals, self.results = {}, {}, {}, {}
        self.delivery_history = DeliveryHistory()
        self.mentions = mentions
        self.context_bridge = context_bridge or bridge
        self.context_timeout_seconds = context_timeout_seconds

    async def publish(self, event):
        try:
            await self._publish(event)
        finally:
            if event["kind"] == "run.end":
                self.delivery_history.parts.pop(event["run_id"], None)
                if self.mentions:
                    self.mentions.finish(event["run_id"])

    async def send(self, packet, delivery, event):
        if self.mentions:
            delivery = self.mentions.delivery(event["run_id"], delivery)
        metadata = event.get("metadata", {})
        task_id = metadata.get("task_id") if metadata.get("origin") == "background" else None
        packet = {key: value for key, value in packet.items() if key != "task_id"}
        if task_id:
            packet["task_id"] = task_id
        await self.sender(packet, delivery)
        if delivery.get("channel") == "group":
            try:
                async with asyncio.timeout(self.context_timeout_seconds):
                    await self.context_bridge.call("qq_group_reply_save", session_id=event["session_id"],
                        delivery=delivery, text=packet["text"], event_id=event["id"], timestamp=event["time"])
            except Exception:
                logging.getLogger(__name__).warning("QQ accepted reply context could not be saved")

    async def _publish(self, event):
        if self.mentions and event.get("metadata", {}).get("delivery"):
            event = {**event, "metadata": {**event["metadata"], "delivery":
                self.mentions.delivery(event["run_id"], event["metadata"]["delivery"])}}
        clean = self.bridge.redact(self.event_projector(event))
        await self.local_log.record(clean)
        run = event["run_id"]
        # Streams already live in the local journal; summaries need durable events.
        if not event.get("transient"):
            self.events.setdefault(run, []).append(clean)
        delivery = event.get("metadata", {}).get("delivery")
        if not delivery or delivery.get("platform") != "qq":
            raise ValueError("QQ output has no trusted destination")
        kind, data = event["kind"], event["data"]
        if kind == "output.artifact":
            encoded = await self.bridge.call("artifact", artifact_id=data["artifact_id"])
            if not encoded:
                raise ValueError("图片产物不存在或已过期")
            artifact = await self.store_artifact(data["artifact_id"], base64.b64decode(encoded, validate=True))
            self.artifacts.setdefault(run, []).append(artifact)
        elif kind == "output.message":
            if data.get("kind") == "final":
                self.finals[run] = data
            else:
                await self.send({"text": data["text"], "artifacts": []}, delivery, event)
        elif kind == "run.end":
            final = self.finals.pop(run, None)
            events = self.events.pop(run, [])
            artifacts = self.artifacts.pop(run, [])
            failed = data.get("status") == "failed"
            text = final["text"] if final else "本次AI任务未完成，请稍后重试。" if failed else "\n\n".join(
                e["data"].get("text", "") for e in events if e["kind"] == "output.message")
            packet = {"text": text, "artifacts": artifacts,
                      "trace": build_trace(events, answer=text,
                          status="error" if failed else "cancelled" if data.get("status") == "cancelled" else "ok")}
            if final and final.get("variants"):
                packet["variants"] = final["variants"]
            prepared = await self.prepare_reply(packet)
            if final or failed:
                await self.send(prepared, delivery, event)
                if event.get("metadata", {}).get("origin") != "background":
                    self.results[run] = prepared
        self.delivery_history.record(event)

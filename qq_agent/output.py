"""Multiple deliveries through the injected, trusted QQ message sender."""

import base64
from .trace import build_trace


class QQOutput:
    def __init__(self, *, bridge, local_log, sender, prepare_reply, store_artifact, event_projector=None):
        self.bridge, self.local_log = bridge, local_log
        self.sender, self.prepare_reply, self.store_artifact = sender, prepare_reply, store_artifact
        self.event_projector = event_projector or (lambda e: e)
        self.events, self.artifacts, self.finals, self.results = {}, {}, {}, {}

    async def publish(self, event):
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
                await self.sender({"text": data["text"], "artifacts": []}, delivery)
        elif kind == "run.end":
            final = self.finals.pop(run, None)
            events = self.events.pop(run, [])
            artifacts = self.artifacts.pop(run, [])
            failed = data.get("status") == "failed"
            if final or failed:
                text = final["text"] if final else "本次AI任务未完成，运行记录中保留了错误和已取得的结果。"
                packet = {"text": text, "artifacts": artifacts,
                          "trace": build_trace(events, answer=text, status="error" if failed else "ok")}
                if final and final.get("variants"):
                    packet["variants"] = final["variants"]
                prepared = await self.prepare_reply(packet)
                await self.sender(prepared, delivery)
                if event.get("metadata", {}).get("origin") != "background":
                    self.results[run] = prepared

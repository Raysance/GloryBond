"""Streaming DeepSeek adapter; credentials are injected, never discovered here."""

import json
import time

import httpx


class DeepSeekModel:
    def __init__(
        self,
        *,
        api_key,
        base_url,
        model,
        thinking=True,
        max_tokens=4096,
        vision_model=None,
        image_store=None,
    ):
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.thinking, self.max_tokens = thinking, max_tokens
        self.vision_model, self.image_store = vision_model or model, image_store

    async def complete(self, messages, tools, on_delta):
        has_images = any(
            isinstance(message.get("content"), list)
            and any(part.get("type") == "image_url" for part in message["content"])
            for message in messages
        )
        selected_model = self.vision_model if has_images else self.model
        vision_context = {}
        if self.image_store:
            messages, vision_context = self.image_store.model_messages(messages)
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": self.max_tokens,
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
        }
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        text, reasoning, calls, usage, finish = [], [], {}, {}, None
        frames = []
        pending = {"content": "", "reasoning": ""}
        last_emit = time.monotonic()

        async def flush():
            for kind in pending:
                if pending[kind]:
                    await on_delta(kind, pending[kind])
                    pending[kind] = ""

        # Match the deployed adapter: direct requests and no ambient proxies.
        async with httpx.AsyncClient(
            trust_env=False, timeout=httpx.Timeout(120, connect=15)
        ) as client:
            async with client.stream(
                "POST",
                self.base_url + "/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + self.api_key},
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    raise RuntimeError(
                        f"模型请求失败 HTTP {response.status_code}: "
                        + body.replace(self.api_key, "[redacted]")[:1500]
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    item = json.loads(raw)
                    frames.append(item)
                    usage = item.get("usage") or usage
                    for choice in item.get("choices", []):
                        finish = choice.get("finish_reason") or finish
                        delta = choice.get("delta") or {}
                        for key, sink in (
                            ("content", text),
                            ("reasoning_content", reasoning),
                        ):
                            if delta.get(key):
                                sink.append(delta[key])
                                pending[
                                    "reasoning"
                                    if key == "reasoning_content"
                                    else "content"
                                ] += delta[key]
                        for call in delta.get("tool_calls") or []:
                            index = call["index"]
                            current = calls.setdefault(
                                index,
                                {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            if call.get("id"):
                                current["id"] = call["id"]
                            for key in ("name", "arguments"):
                                current["function"][key] += (
                                    call.get("function") or {}
                                ).get(key) or ""
                    if time.monotonic() - last_emit >= 0.08:
                        await flush()
                        last_emit = time.monotonic()
        await flush()
        message = {"role": "assistant", "content": "".join(text)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        return {
            "message": message,
            "usage": usage,
            "finish_reason": finish,
            "model": selected_model,
            "vision_context": vision_context,
            "request_payload": payload,
            "response_payload": {"stream": True, "frames": frames},
        }

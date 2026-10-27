"""Streaming DeepSeek adapter; credentials are injected, never discovered here."""

import asyncio
import json
import time

import httpx

from .model_metadata import metadata_messages, model_metadata


class ModelUnavailable(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def provider_unavailable(error):
    if isinstance(error, (httpx.TransportError, TimeoutError, json.JSONDecodeError)):
        return True
    status = getattr(error, "status_code", None)
    if isinstance(error, ModelUnavailable) and status is None:
        return True
    return status in (401, 403, 404, 408, 409, 429) or isinstance(status, int) and status >= 500


def remote_model_options(remote):
    options = dict(remote['public'].get('model_options') or {})
    if options.get('fallback'):
        options['fallback'] = {**options['fallback'], 'api_key': remote['private']['fallback_api_key']}
    return options


def configure_chat_payload(payload, protocol):
    """Adapt provider-specific thinking and forced tool selection outside the kernel."""
    if protocol == 'bailian_kimi':
        payload.pop('thinking', None)
        # Kimi K3 fixes its sampling temperature; business callers may pass a
        # DeepSeek-specific override, which must not reach this provider.
        payload.pop('temperature', None)
        payload.update(enable_thinking=True, preserve_thinking=True)
        payload['messages'] = [dict(message, reasoning_content=message.get('reasoning_content') or '')
                               if message.get('role') == 'assistant' else message
                               for message in payload['messages']]
        choice = payload.get('tool_choice')
        if isinstance(choice, dict):
            name = choice['function']['name']
            payload['tools'] = [tool for tool in payload['tools'] if tool['function']['name'] == name]
            if not payload['tools']:
                raise ValueError('指定工具不在当前授权工具列表中')
            payload['tool_choice'] = 'required'
    return payload


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
        response_format=None,
        proxy_url=None,
        protocol='deepseek',
        timeout_seconds=120,
        first_token_timeout_seconds=120,
        fallback=None,
    ):
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.thinking, self.max_tokens = thinking, max_tokens
        self.vision_model, self.image_store = vision_model or model, image_store
        self.response_format = response_format
        self.proxy_url = proxy_url or None
        self.protocol = protocol
        self.timeout_seconds = timeout_seconds
        self.first_token_timeout_seconds = first_token_timeout_seconds
        self.fallback = fallback

    async def complete_request(self, request, on_delta):
        return await self.complete(
            request.messages, request.tools, on_delta, tool_choice=request.tool_choice
        )

    async def complete(self, messages, tools, on_delta, *, tool_choice="auto"):
        emitted = False

        async def track_delta(kind, text):
            nonlocal emitted
            if text:
                emitted = True
            await on_delta(kind, text)

        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._complete_once(messages, tools, track_delta, tool_choice=tool_choice)
        except Exception as error:
            if not self.fallback or emitted or not provider_unavailable(error):
                raise
            fallback = DeepSeekModel(**self.fallback, thinking=self.thinking, max_tokens=self.max_tokens,
                                     image_store=self.image_store, response_format=self.response_format)
            result = await fallback.complete(messages, tools, on_delta, tool_choice=tool_choice)
            result['failover'] = {'from_model': self.model, 'to_model': fallback.model,
                                  'reason': type(error).__name__, 'status_code': getattr(error, 'status_code', None)}
            return result

    async def _complete_once(self, messages, tools, on_delta, *, tool_choice):
        vision_context = {}
        if self.image_store:
            messages, vision_context = await asyncio.to_thread(self.image_store.model_messages, messages)
        has_images = any(
            isinstance(message.get("content"), list)
            and any(part.get("type") == "image_url" for part in message["content"])
            for message in messages
        )
        selected_model = self.vision_model if has_images else self.model
        metadata = model_metadata(model=selected_model, protocol=self.protocol, max_tokens=self.max_tokens,
                                  messages=messages, tools=tools)
        messages = metadata_messages(messages, metadata)
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": self.max_tokens,
            "thinking": {"type": "enabled" if self.thinking and not tools
                         and not any(m.get("tool_calls") for m in messages) else "disabled"},
        }
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice)
        if self.response_format:
            payload["response_format"] = self.response_format
        configure_chat_payload(payload, self.protocol)
        text, reasoning, calls, usage, finish = [], [], {}, {}, None
        response_model = None
        frames = []
        pending = {"content": "", "reasoning": ""}
        last_emit = time.monotonic()

        async def flush():
            for kind in pending:
                if pending[kind]:
                    await on_delta(kind, pending[kind])
                    pending[kind] = ""

        # Use only the channel's configured proxy; never ambient proxy settings.
        async with asyncio.timeout(self.first_token_timeout_seconds) as first_token_deadline, httpx.AsyncClient(
            trust_env=False, proxy=self.proxy_url, timeout=httpx.Timeout(120, connect=15)
        ) as client:
            async with client.stream(
                "POST",
                self.base_url + "/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + self.api_key},
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    raise ModelUnavailable(
                        f"模型请求失败 HTTP {response.status_code}: "
                        + body.replace(self.api_key, "[redacted]")[:1500], response.status_code
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    item = json.loads(raw)
                    if item.get('error'):
                        raise ModelUnavailable('模型流返回错误')
                    frames.append(item)
                    if isinstance(item.get("model"), str) and item["model"]:
                        response_model = item["model"]
                    usage = item.get("usage") or usage
                    for choice in item.get("choices", []):
                        finish = choice.get("finish_reason") or finish
                        delta = choice.get("delta") or {}
                        if any(delta.get(key) for key in ('content', 'reasoning_content', 'tool_calls')):
                            first_token_deadline.reschedule(None)
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
        if not (text or calls) or finish is None:
            raise ModelUnavailable('模型流未完整返回回答或工具调用')
        message = {"role": "assistant", "content": "".join(text)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        return {
            "message": message,
            "usage": usage,
            "finish_reason": finish,
            "model": response_model or selected_model,
            "runtime_metadata": metadata,
            "vision_context": vision_context,
            "request_payload": payload,
            "response_payload": {"stream": True, "frames": frames},
        }

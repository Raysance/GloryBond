"""OpenAI-compatible text and image API adapters."""

from openai import DefaultHttpxClient, OpenAI
from ratelimit import limits, sleep_and_retry

from .. import zdynamic as dmc
from ..zfile import append_hok_exception_log
from ..zstatic import ark_model_url, chat_api_config, confs
from ..ztime import sleep_seconds
from ..zutil import log_message
from .proxy import clash_request

def _chat_completion_create(input_items, tools=None, tool_choice="auto", temperature=None, timeout=30):
    """Call SJTU through its dedicated VPN proxy and retain tool continuation state."""
    missing = [key for key in ("base_url", "api_key", "model", "proxy_url") if not chat_api_config.get(key)]
    if missing:
        raise ValueError(f"ChatAPI configuration missing: {', '.join(missing)}")

    messages = []
    if isinstance(input_items, str):
        input_items = [{"role": "user", "content": input_items}]
    for item in input_items:
        if item.get("type") == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": item["call_id"],
                "content": item["output"],
            })
        else:
            messages.append(dict(item))

    request = {
        "model": chat_api_config["model"],
        "messages": messages,
        "stream": False,
        "timeout": timeout,
    }
    if temperature is not None:
        request["temperature"] = temperature
    if tools:
        request["tools"] = [
            {"type": "function", "function": {key: value for key, value in tool.items() if key != "type"}}
            for tool in tools
        ]
        request["tool_choice"] = tool_choice
    elif tool_choice == "none":
        request["tool_choice"] = "none"

    with OpenAI(
        api_key=chat_api_config["api_key"],
        base_url=chat_api_config["base_url"],
        http_client=DefaultHttpxClient(proxy=chat_api_config["proxy_url"], trust_env=False),
    ) as client:
        response = client.chat.completions.create(**request)

    message = response.choices[0].message
    assistant_message = {"role": "assistant", "content": message.content}
    reasoning_content = getattr(message, "reasoning_content", None)
    if reasoning_content is not None:
        assistant_message["reasoning_content"] = reasoning_content
    normalized_calls = []
    if message.tool_calls:
        assistant_message["tool_calls"] = []
        for call in message.tool_calls:
            assistant_message["tool_calls"].append({
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            })
            normalized_calls.append({
                "id": call.id,
                "call_id": call.id,
                "name": call.function.name,
                "arguments": call.function.arguments,
            })
    return {
        "content": message.content or "",
        "tool_calls": normalized_calls,
        "output_items": [assistant_message],
        "response_id": response.id,
        "model": response.model,
    }


def ai_api(user_query,temperature): # SJTU 普通聊天
    log_message("VISIT: ai_api_common")
    try:
        return _chat_completion_create(user_query, temperature=temperature, timeout=20)["content"]
    except Exception as e:
        raise Exception("sjtu_api_error: "+str(e)) from e


def ai_function(user_query):
    log_message("VISIT: ai_api_function_call")
    try:
        return _chat_completion_create(user_query, temperature=1)["content"]
    except Exception as e:
        raise Exception("sjtu_api_error: "+str(e)) from e


def _response_item_value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _response_output_text(response):
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    text_parts = []
    for item in getattr(response, "output", None) or []:
        if _response_item_value(item, "type") != "message":
            continue
        for content in _response_item_value(item, "content", []) or []:
            if _response_item_value(content, "type") == "output_text":
                text = _response_item_value(content, "text", "")
                if text:
                    text_parts.append(str(text))
    return "".join(text_parts)


def ai_response_create(input_items, tools=None, tool_choice="auto", network=False):
    """Normalize one SJTU Chat Completions or Ark Responses turn for the chat loop."""
    log_message("VISIT: ai_response_create")
    try:
        if not network:
            return _chat_completion_create(input_items, tools=tools, tool_choice=tool_choice)
        client = OpenAI(api_key=confs["QQBot"]["ark_key"], base_url=ark_model_url)
        model = confs["QQBot"]["ark_responses_model"]
        request = {
            "model": model,
            "input": input_items,
            "stream": False,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "timeout": 30,
        }
        if tools:
            request["tools"] = list(tools)
            if network:
                request["tools"].append({"type": "web_search"})
            request["tool_choice"] = tool_choice
        response = client.responses.create(**request)
    except Exception as error:
        raise Exception(f"ai_response_create_error: {error}") from error

    output_items = list(getattr(response, "output", None) or [])
    normalized_calls = []
    for item in output_items:
        if _response_item_value(item, "type") != "function_call":
            continue
        normalized_calls.append({
            "id": str(_response_item_value(item, "id", "") or ""),
            "call_id": str(_response_item_value(item, "call_id", "") or ""),
            "name": str(_response_item_value(item, "name", "") or ""),
            "arguments": str(_response_item_value(item, "arguments", "{}") or "{}"),
        })
    return {
        "content": _response_output_text(response),
        "tool_calls": normalized_calls,
        "output_items": output_items,
        "response_id": str(getattr(response, "id", "") or ""),
        "model": str(getattr(response, "model", model) or model),
    }
def ark_api(user_query): # 火山引擎-豆包联网模型
    log_message("VISIT: ark_api_common")
    try:
        client = OpenAI(api_key=confs["QQBot"]["ark_key"], base_url=ark_model_url)

        response = client.responses.create(
            model=confs["QQBot"]["ark_responses_model"],
            input=user_query,
            stream=False,
            store=False,
            include=["reasoning.encrypted_content"],
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            timeout=30,
        )
    except Exception as e:
        try:
            append_hok_exception_log(
                "ark_api_error: " + repr(e),
                {"function": "ark_api"},
            )
        except Exception as log_error:
            log_message(f"ARK_API_ERROR_LOG_FAILED: {repr(log_error)}")
        return ""
    return _response_output_text(response)

def ark_images_generate(*, prompt: str, reference_image_url: str, size: str):
    api_key = confs["QQBot"].get("ark_image_key") or confs["QQBot"].get("ark_key") or ""
    if not api_key:
        raise Exception("ark_images_generate_error: missing config.yaml QQBot.ark_image_key")

    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    client = OpenAI(base_url=base_url, api_key=api_key)
    model = getattr(dmc, "EmojiImageModel", None) or "doubao-seedream-5-0-260128"
    extra_body = {"image": reference_image_url, "watermark": False}
    request_payload = {
        "base_url": base_url,
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "url",
        "extra_body": extra_body,
    }
    images_response = client.images.generate(model=model, prompt=prompt, size=size, response_format="url", extra_body=extra_body)
    if not images_response or not getattr(images_response, "data", None) or not images_response.data:
        raise Exception("ark_images_generate_error: empty response")
    url = getattr(images_response.data[0], "url", None)
    if not url:
        raise Exception("ark_images_generate_error: missing url in response")
    return {"url": url, "request": request_payload}

def apimart_images_generate(*, prompt: str, reference_image_url: str, size: str, resolution: str, task_timeout_seconds=None, task_poll_interval_seconds=None):
    api_key = confs["QQBot"].get("apimart_key") or ""
    if not api_key:
        raise Exception("apimart_images_generate_error: missing config.yaml QQBot.apimart_key")

    base_url = "https://api.apimart.ai/v1/images/generations"
    model = getattr(dmc, "EmojiImageModel", None) or "gpt-image-2"
    payload = {"model": model, "prompt": prompt, "n": 1, "size": size, "resolution": resolution}
    if reference_image_url:
        payload["image"] = reference_image_url

    request_payload = {
        "base_url": base_url,
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "resolution": resolution,
    }
    if reference_image_url:
        request_payload["image"] = reference_image_url

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = clash_request("POST", base_url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        res = response.json()
    except Exception as e:
        raise Exception(f"apimart_images_generate_error: {repr(e)}")

    if not isinstance(res, dict) or res.get("code") != 200:
        raise Exception(f"apimart_images_generate_error: unexpected response {str(res)[:500]}")

    data = res.get("data")
    if not isinstance(data, list) or not data:
        raise Exception(f"apimart_images_generate_error: missing task_id {str(res)[:500]}")

    task_id = (data[0] or {}).get("task_id")
    if not task_id:
        raise Exception(f"apimart_images_generate_error: missing task_id {str(res)[:500]}")

    request_payload["task_id"] = task_id

    task_url = f"https://api.apimart.ai/v1/tasks/{task_id}"
    timeout_seconds = task_timeout_seconds or 120
    poll_interval_seconds = task_poll_interval_seconds or 2
    poll_request_payload = {"base_url": task_url, "task_id": task_id, "timeout_seconds": timeout_seconds, "poll_interval_seconds": poll_interval_seconds}
    request_payload["poll"] = poll_request_payload

    last_status = None
    for _ in range(max(1, int(timeout_seconds / poll_interval_seconds))):
        try:
            task_resp = clash_request("GET", task_url, headers=headers, timeout=60)
            task_resp.raise_for_status()
            task_res = task_resp.json()
        except Exception as e:
            raise Exception(f"apimart_task_query_error: {repr(e)}")

        if not isinstance(task_res, dict) or task_res.get("code") != 200:
            raise Exception(f"apimart_task_query_error: unexpected response {str(task_res)[:500]}")

        task_data = task_res.get("data") or {}
        status = task_data.get("status")
        last_status = status
        if status == "completed":
            result = task_data.get("result") or {}
            images = result.get("images") or []
            if not images:
                raise Exception(f"apimart_task_query_error: completed without images {str(task_res)[:500]}")
            first = images[0] or {}
            url_list = first.get("url") or []
            if isinstance(url_list, list) and url_list:
                url = url_list[0]
            else:
                url = None
            if not url:
                raise Exception(f"apimart_task_query_error: missing image url {str(task_res)[:500]}")
            return {"url": url, "request": request_payload}

        if status in {"failed", "cancelled"}:
            raise Exception(f"apimart_task_query_error: status={status} {str(task_res)[:500]}")

        sleep_seconds(poll_interval_seconds)

    raise Exception(f"apimart_task_query_error: timeout last_status={last_status} task_id={task_id}")

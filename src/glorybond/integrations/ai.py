"""OpenAI-compatible text and image API adapters."""

import json
import time
from urllib.parse import quote, urlparse

from openai import DefaultHttpxClient, OpenAI
from glorybond.agent.provider import ModelUnavailable, configure_chat_payload, provider_unavailable
from ratelimit import limits, sleep_and_retry

from glorybond import runtime as dmc
from glorybond.storage.files import append_hok_exception_log
from glorybond.config.settings import aliyun_search_config, ark_model_url, chat_api_config, confs, deepseek_search_config, image_generation_config
from glorybond.time import sleep_seconds
from glorybond.common import log_message
from glorybond.integrations.proxy import clash_request, direct_request


class AIRequestError(RuntimeError):
    """Keep body-only diagnostics even when the SDK raises before normalization."""

    def __init__(self, error, request_payload, response_payload=None):
        super().__init__(f"{type(error).__name__}: {error}")
        self.request_payload = request_payload
        self.response_payload = response_payload if response_payload is not None else getattr(error, "body", None)
        raw_response = getattr(error, "response", None)
        if response_payload is None and raw_response is not None:
            try:
                self.response_payload = raw_response.json()
            except ValueError:
                self.response_payload = raw_response.text
        self.status_code = getattr(error, "status_code", None)
        self.request_id = getattr(error, "request_id", None)


def _chat_completion_create(input_items, temperature=None, timeout=30, thinking=None, response_format=None):
    """Call the configured provider without inheriting ambient proxy settings."""
    if chat_api_config.get('protocol') == 'openai_responses':
        return _openai_response_create(input_items, timeout, response_format)
    if chat_api_config.get('fallback'):
        try:
            return _chat_completion_stream(input_items, chat_api_config, temperature, timeout, thinking, response_format)
        except Exception as error:
            if not provider_unavailable(error):
                raise
            return _chat_completion_stream(input_items, chat_api_config['fallback'], temperature, timeout, thinking, response_format)
    return _chat_completion_single(input_items, temperature, timeout, thinking, response_format)


def _openai_response_create(input_items, timeout, response_format, *, web_search=False):
    from glorybond.agent.openai_responses import response_payload, response_result
    messages = [{'role': 'user', 'content': input_items}] if isinstance(input_items, str) else input_items
    payload = response_payload(model=chat_api_config['model'], messages=messages,
        reasoning_effort=chat_api_config.get('reasoning_effort', 'medium'), response_format=response_format)
    if web_search:
        payload['tools'] = [{'type': 'web_search'}]
    data = None
    try:
        with DefaultHttpxClient(trust_env=False, proxy=chat_api_config.get('proxy_url') or None,
                               timeout=timeout) as client:
            response = client.post(chat_api_config['base_url'].rstrip('/') + '/responses', json=payload,
                                   headers={'Authorization': 'Bearer ' + chat_api_config['api_key']})
            data = response.json()
            if response.status_code != 200:
                raise ModelUnavailable(f'模型请求失败 HTTP {response.status_code}', response.status_code)
        if data.get('status') != 'completed':
            raise ModelUnavailable('Responses 未完整返回回答')
        result = response_result(data)
        if not result['message']['content']:
            raise ModelUnavailable('Responses 未返回回答正文')
        return {'content': result['message']['content'], 'request_payload': payload, 'response_payload': data,
                'response_meta': {'model': result['model'], 'status_code': 200, 'usage': result['usage'],
                                  'finish_reason': result['finish_reason']}}
    except Exception as error:
        raise AIRequestError(error, payload, data) from error


def _chat_completion_stream(input_items, provider, temperature, timeout, thinking, response_format=None):
    """Bound the wait for real output even when the server sends keepalive lines."""
    messages = [{'role': 'user', 'content': input_items}] if isinstance(input_items, str) else [dict(item) for item in input_items]
    payload = {'model': provider['model'], 'messages': messages, 'stream': True,
               'stream_options': {'include_usage': True}}
    if temperature is not None:
        payload['temperature'] = temperature
    if thinking is not None:
        payload['thinking'] = {'type': 'enabled' if thinking else 'disabled'}
    if response_format:
        payload['response_format'] = response_format
    configure_chat_payload(payload, provider.get('protocol', 'deepseek'))
    first_timeout = min(timeout, provider.get('first_token_timeout_seconds', timeout))
    total_timeout = min(timeout, provider.get('timeout_seconds', timeout))
    options = {'trust_env': False, 'timeout': first_timeout}
    if provider.get('proxy_url'):
        options['proxy'] = provider['proxy_url']
    started = time.monotonic()
    content, frames, usage, finish = [], [], {}, None
    received = False
    with DefaultHttpxClient(**options) as client:
        with client.stream('POST', provider['base_url'].rstrip('/') + '/chat/completions', json=payload,
                           headers={'Authorization': 'Bearer ' + provider['api_key']}) as response:
            if response.status_code != 200:
                raise ModelUnavailable(f'模型请求失败 HTTP {response.status_code}', response.status_code)
            for line in response.iter_lines():
                elapsed = time.monotonic() - started
                if elapsed > total_timeout or not received and elapsed > first_timeout:
                    raise TimeoutError('模型等待输出超时')
                if not line.startswith('data: '):
                    continue
                if line[6:] == '[DONE]':
                    break
                item = json.loads(line[6:])
                if item.get('error'):
                    raise ModelUnavailable('模型流返回错误')
                frames.append(item)
                usage = item.get('usage') or usage
                for choice in item.get('choices', []):
                    delta = choice.get('delta') or {}
                    received |= bool(delta.get('content') or delta.get('reasoning_content'))
                    if delta.get('content'):
                        content.append(delta['content'])
                    finish = choice.get('finish_reason') or finish
    if not content or finish is None:
        raise ModelUnavailable('模型流未完整返回回答')
    return {'content': ''.join(content), 'request_payload': payload,
            'response_payload': {'stream': True, 'frames': frames},
            'response_meta': {'model': provider['model'], 'status_code': 200,
                              'usage': usage, 'finish_reason': finish}}


def _chat_completion_single(input_items, temperature=None, timeout=30, thinking=None, response_format=None):
    """Keep the existing single-provider SDK path for configurations without failover."""
    missing = [key for key in ("base_url", "api_key", "model") if not chat_api_config.get(key)]
    if missing:
        raise ValueError(f"ChatAPI configuration missing: {', '.join(missing)}")

    messages = [{"role": "user", "content": input_items}] if isinstance(input_items, str) else [dict(item) for item in input_items]

    request = {
        "model": chat_api_config["model"],
        "messages": messages,
        "stream": False,
        "timeout": timeout,
    }
    if temperature is not None:
        request["temperature"] = temperature
    if thinking is not None:
        request['extra_body'] = {'thinking': {'type': 'enabled' if thinking else 'disabled'}}
    if response_format:
        request['response_format'] = response_format
    request_payload = {key: value for key, value in request.items() if key != "timeout"}
    response_payload = None
    try:
        http_client_options = {"trust_env": False}
        if chat_api_config.get("proxy_url"):
            http_client_options["proxy"] = chat_api_config["proxy_url"]
        with OpenAI(
            api_key=chat_api_config["api_key"],
            base_url=chat_api_config["base_url"],
            http_client=DefaultHttpxClient(**http_client_options),
        ) as client:
            raw = client.chat.completions.with_raw_response.create(**request)
            request_payload = json.loads(raw.http_request.content)
            response_payload = raw.text
            response_payload = json.loads(raw.content)
            response = raw.parse()
        return _chat_completion_result(response, request_payload, response_payload, raw.status_code)
    except Exception as error:
        raise AIRequestError(error, request_payload, response_payload) from error

def _chat_completion_result(response, request_payload, response_payload, status_code):
    """Normalize content while retaining the unmodified provider bodies."""
    diagnostics = {"request_payload": request_payload, "response_payload": response_payload,
                   "response_meta": {"response_id": response.id, "model": response.model,
                                     "status_code": status_code,
                                     "usage": response_payload.get("usage"),
                                     "finish_reason": response.choices[0].finish_reason if response.choices else "missing_choice"}}
    if not response.choices:
        return {"content": "", **diagnostics}

    message = response.choices[0].message
    return {"content": message.content or "", **diagnostics}


def ai_api(user_query,temperature,timeout=20,thinking=None,response_format=None): # 配置的普通聊天模型
    log_message("VISIT: ai_api_common")
    try:
        return _chat_completion_create(user_query, temperature=temperature, timeout=timeout, thinking=thinking,
                                       response_format=response_format)["content"]
    except Exception as e:
        raise Exception("chat_api_error: "+str(e)) from e


def ai_function(user_query):
    log_message("VISIT: ai_api_function_call")
    try:
        return _chat_completion_create(user_query, temperature=1)["content"]
    except Exception as e:
        raise Exception("chat_api_error: "+str(e)) from e


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


def deepseek_web_search(query, max_results=5, result_type=None):
    """Call the standalone Search API using the shared protocol projection."""
    from glorybond.integrations.deepseek_web import prepare_search, search_error, search_result
    request = prepare_search(deepseek_search_config, query, max_results, result_type)
    response = None
    try:
        response = direct_request("POST", request.endpoint,
            headers={"Authorization": "Bearer " + deepseek_search_config["api_key"], "Content-Type": "application/json"},
            json=request.payload, timeout=request.timeout, allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError("Search request failed")
        return search_result(response.json(), request)
    except Exception as error:
        raise search_error(getattr(response, "status_code", None), error) from None


def aliyun_web_search(query, max_results=5):
    """Call Alibaba Cloud OpenSearch directly and normalize its web results."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("aliyun_web_search: query must be non-empty text")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 10:
        raise ValueError("aliyun_web_search: max_results must be an integer from 1 to 10")
    query = query.strip()
    missing = [key for key in ("endpoint", "api_key", "workspace", "service_id")
               if not aliyun_search_config.get(key)]
    if missing:
        locations = {
            "endpoint": "config.yaml AliyunSearch.endpoint",
            "api_key": ".env HOK_ALIYUN_SEARCH_API_KEY",
            "workspace": "config.yaml AliyunSearch.workspace",
            "service_id": "config.yaml AliyunSearch.service_id",
        }
        raise RuntimeError("aliyun_web_search unavailable: configure "
                           + ", ".join(locations[key] for key in missing))
    endpoint = aliyun_search_config["endpoint"].rstrip("/")
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme != "https" or not parsed_endpoint.hostname:
        raise RuntimeError("aliyun_web_search unavailable: AliyunSearch.endpoint must be a valid HTTPS URL")
    workspace = quote(aliyun_search_config["workspace"], safe="")
    service_id = quote(aliyun_search_config["service_id"], safe="")
    url = f"{endpoint}/v3/openapi/workspaces/{workspace}/web-search/{service_id}"
    request = {
        "query": query,
        "query_rewrite": bool(aliyun_search_config.get("query_rewrite", True)),
        "top_k": max_results,
        "content_type": aliyun_search_config.get("content_type") or "snippet",
        "way": aliyun_search_config.get("way") or "pro",
    }
    api_key = aliyun_search_config["api_key"]
    try:
        response = direct_request(
            "POST",
            url,
            json=request,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("provider returned a non-object response")
        if payload.get("code") or payload.get("message") and not payload.get("result"):
            raise RuntimeError(
                f"provider error {payload.get('code') or payload.get('http_code') or 'unknown'}: "
                f"{payload.get('message') or 'missing result'}"
            )
        result = payload.get("result")
        raw_results = result.get("search_result") if isinstance(result, dict) else None
        if not isinstance(raw_results, list):
            raise RuntimeError("provider returned no result.search_result list")

        sources = []
        observations = []
        seen_urls = set()
        for item in raw_results[:max_results]:
            if not isinstance(item, dict):
                continue
            link = str(item.get("link") or "").strip()
            if not link.startswith(("https://", "http://")) or link in seen_urls:
                continue
            seen_urls.add(link)
            title = str(item.get("title") or link).strip()
            text = str(item.get("content") or item.get("snippet") or "").strip()
            published_time = str((item.get("meta_info") or {}).get("publishedTime") or "").strip()
            sources.append({"title": title, "url": link})
            observations.append({
                "title": title,
                "url": link,
                "published_time": published_time,
                "content": text[:6000],
            })
        if observations:
            blocks = []
            for index, item in enumerate(observations, 1):
                published = f"\n发布时间：{item['published_time']}" if item["published_time"] else ""
                blocks.append(
                    f"[{index}] {item['title']}{published}\n链接：{item['url']}\n内容：{item['content'] or '无摘要'}"
                )
            answer = "\n\n".join(blocks)
        else:
            answer = "阿里云联网搜索未返回可核验的网页结果。"
        return {
            "query": query,
            "answer": answer,
            "sources": sources,
            "provider": "aliyun_opensearch",
            "response_id": str(payload.get("request_id") or ""),
            "service_id": aliyun_search_config["service_id"],
            "search_requests": 1,
            "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        }
    except Exception as error:
        detail = str(error).replace(api_key, "[redacted]")
        raise RuntimeError(f"aliyun_web_search unavailable: {type(error).__name__}: {detail}") from None


def ark_api(user_query): # 火山引擎-豆包联网模型
    log_message("VISIT: ark_api_common")
    if chat_api_config.get('protocol') == 'openai_responses':
        return _openai_response_create(user_query, 120, None, web_search=True)['content']
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
    if image_generation_config:
        return openai_images_generate(settings=image_generation_config, prompt=prompt,
            reference_image_url=reference_image_url, size=size)
    api_key = confs["QQBot"].get("ark_image_key") or confs["QQBot"].get("ark_key") or ""
    if not api_key:
        raise Exception("ark_images_generate_error: missing .env HOK_ARK_IMAGE_API_KEY")

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

def openai_images_generate(*, settings, prompt, reference_image_url='', size='1:1', timeout=600):
    """Single Image API request; no resubmission when the outcome is unknown."""
    import base64
    import math
    if ':' in size:
        width, height = (int(value) for value in size.split(':'))
        ratio = width / height
        if not 1 / 3 <= ratio <= 3:
            raise ValueError('图片宽高比须在1:3到3:1之间')
        # Preserve the requested ratio with provider-supported multiples of 16.
        width = round(math.sqrt(1024 * 1024 * ratio) / 16) * 16
        height = round(width / ratio / 16) * 16
        dimensions = f'{width}x{height}'
    else:
        dimensions = size
    payload = {'model': settings['model'], 'prompt': prompt, 'size': dimensions,
               'n': 1, 'quality': 'medium', 'output_format': 'png'}
    endpoint = settings['base_url'].rstrip('/') + '/images/'
    if reference_image_url:
        payload['images'] = [{'image_url': reference_image_url}]
        endpoint += 'edits'
    else:
        endpoint += 'generations'
    proxy = settings.get('proxy_url')
    response = direct_request('POST', endpoint, json=payload,
        headers={'Authorization': 'Bearer ' + settings['api_key']}, timeout=timeout,
        proxies={'http': proxy, 'https': proxy} if proxy else {})
    if response.status_code != 200:
        raise RuntimeError(f'OpenAI 生图失败（HTTP {response.status_code}）')
    data = response.json()
    rows = data.get('data') or []
    encoded = rows[0].get('b64_json') if rows else None
    if not isinstance(encoded, str) or len(encoded) > 12 * 1024 ** 2:
        raise ValueError('生图未返回有效图片或超过大小上限')
    raw = base64.b64decode(encoded, validate=True)
    if not 0 < len(raw) <= 8 * 1024 ** 2:
        raise ValueError('生成图片超过8 MiB上限')
    return {'image_bytes': raw, 'mime': 'image/png', 'model': settings['model'],
            'provider_host': 'api.openai.com', 'usage': data.get('usage'),
            'request': {'base_url': endpoint, **payload}}


def apimart_images_generate(*, prompt: str, reference_image_url: str, size: str, resolution: str, task_timeout_seconds=None, task_poll_interval_seconds=None):
    if confs.get('ImageGenerationAPI', {}).get('protocol') == 'openai':
        return openai_images_generate(settings=image_generation_config, prompt=prompt,
            reference_image_url=reference_image_url, size=size, timeout=task_timeout_seconds or 600)
    api_key = confs["QQBot"].get("apimart_key") or ""
    if not api_key:
        raise Exception("apimart_images_generate_error: missing .env HOK_APIMART_API_KEY")

    base_url = "https://api.apimart.ai/v1/images/generations"
    model = getattr(dmc, "EmojiImageModel", None) or "gpt-image-2"
    payload = {"model": model, "prompt": prompt, "n": 1, "size": size, "resolution": resolution}
    if reference_image_url:
        payload["image_urls" if model.startswith("gpt-image-") else "image"] = (
            [reference_image_url] if model.startswith("gpt-image-") else reference_image_url)

    request_payload = {
        "base_url": base_url,
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "resolution": resolution,
    }
    if reference_image_url:
        request_payload.update({key: payload[key] for key in ("image", "image_urls") if key in payload})

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

    raise TimeoutError(f"apimart_task_query_error: timeout last_status={last_status} task_id={task_id}; result unknown")

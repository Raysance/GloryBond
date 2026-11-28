"""Responses wire adapter for the existing chat/tool loop, without server state."""
import copy
import json

import httpx


def response_inputs(messages):
    items = []
    for message in messages:
        role = message['role']
        if role == 'tool':
            items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'],
                          'output': message.get('content') or ''})
            continue
        if role == 'assistant' and message.get('openai_output'):
            # Preserve phases, encrypted reasoning and call IDs exactly. These
            # are local output items, not instructions supplied by a user/tool.
            items.extend(copy.deepcopy(message['openai_output']))
            continue
        content = message.get('content')
        if isinstance(content, list):
            parts = []
            for part in content:
                kind = part.get('type')
                if kind == 'text':
                    parts.append({'type': 'input_text', 'text': part['text']})
                elif kind == 'image_url':
                    image = part['image_url']
                    detail = image.get('detail', 'auto')
                    parts.append({'type': 'input_image', 'image_url': image['url'],
                                  'detail': detail if detail in {'auto', 'low', 'high'} else 'high'})
                elif kind == 'file':
                    parts.append({'type': 'input_file', 'file_id': part['file_id']})
                else:
                    raise ValueError('Unsupported Responses content part: ' + str(kind))
            content = parts
        if content:
            items.append({'role': role, 'content': content})
        for call in message.get('tool_calls') or []:
            items.append({'type': 'function_call', 'call_id': call['id'],
                          'name': call['function']['name'], 'arguments': call['function']['arguments']})
    return items


def response_payload(*, model, messages, tools=(), tool_choice='auto', max_tokens=4096,
                     reasoning_effort='medium', response_format=None):
    payload = {'model': model, 'input': response_inputs(messages), 'store': False,
               'reasoning': {'effort': reasoning_effort}, 'max_output_tokens': max_tokens,
               'include': ['reasoning.encrypted_content']}
    if tools:
        payload['tools'] = [{'type': 'function', **copy.deepcopy(tool['function']), 'strict': False}
                            for tool in tools]
        payload['tool_choice'] = ({'type': 'function', 'name': tool_choice['function']['name']}
                                  if isinstance(tool_choice, dict) else tool_choice)
        payload['parallel_tool_calls'] = True
    if response_format:
        fmt = copy.deepcopy(response_format)
        if fmt.get('type') == 'json_schema':
            fmt = {'type': 'json_schema', **fmt['json_schema']}
        payload['text'] = {'format': fmt}
    return payload


def response_result(response):
    output = response.get('output') or []
    text, reasoning, calls = [], [], []
    for item in output:
        if item.get('type') == 'function_call':
            calls.append({'id': item['call_id'], 'type': 'function',
                          'function': {'name': item['name'], 'arguments': item['arguments']}})
        elif item.get('type') == 'message':
            text.extend(part.get('text', part.get('refusal', '')) for part in item.get('content', []))
        elif item.get('type') == 'reasoning':
            reasoning.extend(part.get('text', '') for part in item.get('summary', []))
    message = {'role': 'assistant', 'content': ''.join(text), 'openai_output': copy.deepcopy(output)}
    if calls:
        message['tool_calls'] = calls
    if reasoning:
        message['reasoning_content'] = ''.join(reasoning)
    return {'message': message, 'usage': response.get('usage') or {}, 'model': response.get('model'),
            'finish_reason': 'length' if response.get('status') == 'incomplete' else 'tool_calls' if calls else 'stop'}


async def complete_response(model, messages, tools, on_delta, *, tool_choice, metadata):
    # Import lazily to avoid a cycle with the shared facade.
    import asyncio
    from glorybond.agent.provider import ModelUnavailable
    payload = response_payload(model=model.model, messages=messages, tools=tools, tool_choice=tool_choice,
        max_tokens=model.max_tokens, reasoning_effort=model.reasoning_effort,
        response_format=model.response_format)
    payload['stream'] = True
    frames, completed = [], None
    async with asyncio.timeout(model.first_token_timeout_seconds) as first, httpx.AsyncClient(
        trust_env=False, proxy=model.proxy_url, timeout=httpx.Timeout(120, connect=15)
    ) as client:
        async with client.stream('POST', model.base_url + '/responses', json=payload,
                                 headers={'Authorization': 'Bearer ' + model.api_key}) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode(errors='replace')
                raise ModelUnavailable(f'模型请求失败 HTTP {response.status_code}: '
                    + body.replace(model.api_key, '[redacted]')[:1500], response.status_code)
            async for line in response.aiter_lines():
                if not line.startswith('data: ') or line[6:] == '[DONE]':
                    continue
                event = json.loads(line[6:])
                frames.append(event)
                kind = event.get('type')
                if kind in {'error', 'response.failed'}:
                    raise ModelUnavailable('Responses 模型流返回错误')
                if kind in {'response.output_text.delta', 'response.refusal.delta',
                            'response.reasoning_summary_text.delta', 'response.function_call_arguments.delta'}:
                    if event.get('delta'):
                        first.reschedule(None)
                    if kind != 'response.function_call_arguments.delta':
                        await on_delta('reasoning' if kind == 'response.reasoning_summary_text.delta' else 'content',
                                       event.get('delta', ''))
                elif kind in {'response.completed', 'response.incomplete'}:
                    completed = event['response']
                    first.reschedule(None)
    if completed is None:
        raise ModelUnavailable('Responses 模型流未完整返回')
    result = response_result(completed)
    if completed.get('status') == 'incomplete' and result['message'].get('tool_calls'):
        raise ModelUnavailable('Responses 工具调用未完整返回，不执行部分调用')
    if not (result['message']['content'] or result['message'].get('tool_calls')):
        raise ModelUnavailable('Responses 未返回正文或工具调用')
    return {**result, 'runtime_metadata': metadata, 'provider_host': httpx.URL(model.base_url).host,
            'request_payload': payload, 'response_payload': {'stream': True, 'frames': frames}}

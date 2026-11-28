"""Provider switching and Responses tool continuations retain existing semantics."""
import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import httpx

from glorybond.agent.document_inputs import DeepSeekDocuments, project_documents
from glorybond.agent.model_metadata import token_usage
from glorybond.agent.openai_responses import response_inputs, response_payload
from glorybond.agent.provider import DeepSeekModel, ModelUnavailable, configure_chat_payload
from glorybond.agent.remote_worker import extracted_functions
from glorybond.agent.run_costs import model_cost, image_cost

ROOT = Path(__file__).parents[1]


class ProfileTests(unittest.TestCase):
    def test_round_trip_restores_all_original_providers_without_mutation(self):
        namespace = {}
        extracted_functions(ROOT / 'src/glorybond/config/settings.py', ['_apply_model_profile'], namespace)
        apply = namespace['_apply_model_profile']
        old = {'ChatAPI': {'model': 'old', 'fallback': {'model': 'backup'}},
               'VisionAPI': {'model': 'vision'}, 'LocalAgent': {'llm': {'model': 'local'}, 'port': 80},
               'QQBot': {'apimart_key': 'old-key'}, 'ModelProfiles': {'active': 'openai', 'profiles': {
                   'openai': {'ChatAPI': {'model': 'new'}, 'VisionAPI': {'model': 'new'},
                              'ASRAPI': {'model': 'transcribe'}, 'LocalAgent': {'llm': {'model': 'new'}}}}}}
        saved = copy.deepcopy(old)
        active = apply(old, {})
        self.assertEqual(active['ChatAPI'], {'model': 'new'})
        self.assertEqual(active['LocalAgent'], {'llm': {'model': 'new'}, 'port': 80})
        self.assertEqual(old, saved)
        restored = apply(old, {'HOK_MODEL_PROFILE': 'original'})
        self.assertEqual(restored, saved)
        self.assertNotIn('ASRAPI', restored)
        with self.assertRaises(ValueError):
            apply(old, {'HOK_MODEL_PROFILE': 'unknown'})

    def test_native_usage_and_cache_write_prices_are_not_double_counted(self):
        usage = token_usage({'input_tokens': 1000, 'output_tokens': 100, 'total_tokens': 1100,
            'input_tokens_details': {'cached_tokens': 400, 'cache_write_tokens': 200},
            'output_tokens_details': {'reasoning_tokens': 50}})
        self.assertEqual(usage['prompt_tokens'], 1000)
        self.assertEqual(usage['completion_tokens'], 100)
        self.assertEqual(usage['reasoning_tokens'], 50)
        cost = model_cost('gpt-6.1-sol', usage, provider_host='api.openai.com')
        self.assertEqual(cost['currency'], 'USD')
        self.assertAlmostEqual(cost['min'], (400 * 2 + 200 * 2.5 + 400 * .1 + 100 * 10) / 1e6)

    def test_generated_images_use_image_output_rates(self):
        cost = image_cost('gpt-image-2.6-flare', {'input_tokens': 1053, 'output_tokens': 1449,
            'input_tokens_details': {'text_tokens': 29, 'image_tokens': 1024},
            'output_tokens_details': {'text_tokens': 0, 'image_tokens': 1449}}, provider_host='api.openai.com')
        self.assertEqual(cost['currency'], 'USD')
        self.assertAlmostEqual(cost['min'], .051807)


class ResponsesTests(unittest.IsolatedAsyncioTestCase):
    def model(self, **kwargs):
        return DeepSeekModel(api_key='openai-test', base_url='https://api.openai.com/v1', model='gpt-6.1-sol',
                             protocol='openai_responses', reasoning_effort='medium', **kwargs)

    async def test_two_calls_replay_reasoning_phase_and_order_with_matching_outputs(self):
        requests = []
        items = [{'type': 'reasoning', 'id': 'rs_test', 'summary': [], 'encrypted_content': 'ciphertext'},
                 {'type': 'message', 'id': 'msg_test', 'role': 'assistant', 'phase': 'commentary',
                  'status': 'completed', 'content': [{'type': 'output_text', 'text': 'Checking both.'}]},
                 *[{'type': 'function_call', 'id': 'fc_' + name, 'call_id': 'call_' + name,
                     'name': 'lookup', 'arguments': json.dumps({'key': name}), 'status': 'completed'} for name in ('a', 'b')]]
        def handler(request):
            requests.append(json.loads(request.content))
            output = items if len(requests) == 1 else [{'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'Both results.'}], 'phase': 'final_answer'}]
            final = {'type': 'response.completed', 'response': {'status': 'completed', 'model': 'gpt-6.1-sol',
                'output': output, 'usage': {'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 15}}}
            return httpx.Response(200, text='data: '+json.dumps(final)+'\n\n')
        client = httpx.AsyncClient
        messages = [{'role': 'user', 'content': 'Look up a and b'}]
        tools = [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {
            'type': 'object', 'properties': {'key': {'type': 'string'}}}}}]
        async def delta(kind, value):
            pass
        with patch('glorybond.agent.openai_responses.httpx.AsyncClient',
                   side_effect=lambda **kw: client(transport=httpx.MockTransport(handler), **kw)):
            result = await self.model().complete(messages, tools, delta)
            self.assertEqual([c['id'] for c in result['message']['tool_calls']], ['call_a', 'call_b'])
            messages += [result['message'], *[{'role': 'tool', 'tool_call_id': 'call_'+name, 'content': name.upper()}
                                            for name in ('a', 'b')]]
            final = await self.model().complete(messages, tools, delta)
        self.assertEqual(final['message']['content'], 'Both results.')
        self.assertEqual(requests[0]['reasoning'], {'effort': 'medium'})
        self.assertFalse(requests[0]['store'])
        self.assertTrue(requests[0]['parallel_tool_calls'])
        self.assertFalse(requests[0]['tools'][0]['strict'])
        for item in items:
            self.assertIn(item, requests[1]['input'])
        self.assertEqual(requests[1]['input'][-2:], [
            {'type': 'function_call_output', 'call_id': 'call_a', 'output': 'A'},
            {'type': 'function_call_output', 'call_id': 'call_b', 'output': 'B'}])
        self.assertNotIn('thinking', requests[1])
        self.assertNotIn('max_tokens', requests[1])

    async def test_interrupted_stream_never_executes_partial_tool_calls(self):
        client = httpx.AsyncClient
        event = {'type': 'response.output_item.added', 'item': {'type': 'function_call', 'name': 'action'}}
        async def delta(kind, value):
            pass
        with patch('glorybond.agent.openai_responses.httpx.AsyncClient', side_effect=lambda **kw:
                   client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='data: '+json.dumps(event)+'\n')), **kw)):
            with self.assertRaises(ModelUnavailable):
                await self.model().complete([{'role': 'user', 'content': 'test'}], [], delta)

    def test_old_provider_omits_only_openai_wire_state_and_preserves_stored_history(self):
        old = [{'role': 'assistant', 'content': 'answer', 'openai_output': [{'type': 'reasoning'}],
                'reasoning_content': 'old text'}]
        payload = configure_chat_payload({'messages': old}, 'deepseek')
        self.assertNotIn('openai_output', payload['messages'][0])
        self.assertIn('openai_output', old[0])
        self.assertEqual(payload['messages'][0]['reasoning_content'], 'old text')

    def test_image_file_json_and_named_tool_projection(self):
        payload = response_payload(model='gpt-6.1-sol', messages=[{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'original'}},
            {'type': 'file', 'file_id': 'file-test'}]}],
            tools=[{'type': 'function', 'function': {'name': 'test', 'parameters': {'type': 'object'}}}],
            tool_choice={'type': 'function', 'function': {'name': 'test'}}, response_format={'type': 'json_object'})
        self.assertEqual(payload['input'][0]['content'][0]['detail'], 'high')
        self.assertEqual(payload['input'][0]['content'][1], {'type': 'input_file', 'file_id': 'file-test'})
        self.assertEqual(payload['tool_choice'], {'type': 'function', 'name': 'test'})
        self.assertEqual(payload['text'], {'format': {'type': 'json_object'}})

    async def test_openai_uploads_and_old_provider_files_stay_isolated(self):
        remote = {'public': {'base_url': 'https://api.openai.com/v1', 'model': 'gpt-6.1-sol',
            'model_services': {'documents': {'base_url': 'https://api.openai.com/v1',
                'model': 'gpt-6.1-sol', 'protocol': 'openai_responses'}}},
            'private': {'documents_api_key': 'files-test'}}
        client = httpx.AsyncClient
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'id': 'file-test', 'expires_at': int(time.time())+100})
        documents = DeepSeekDocuments(remote)
        with patch('glorybond.agent.document_inputs.httpx.AsyncClient',
                   side_effect=lambda **kw: client(transport=httpx.MockTransport(handler), **kw)):
            part = await documents.upload('sample.txt', b'sample')
        self.assertEqual(part['provider'], 'openai')
        self.assertIn(b'user_data', requests[0].content)
        messages = [{'role': 'user', 'content': [part]}]
        projected, included = project_documents(messages, provider='openai')
        self.assertTrue(included)
        self.assertEqual(response_inputs(projected)[0]['content'][-1]['type'], 'input_file')
        projected, included = project_documents(messages)
        self.assertFalse(included)
        self.assertNotIn('file_id', json.dumps(projected))

"""Business text generation keeps direct transport and body-only diagnostics."""
import json
import unittest
from unittest.mock import patch
import httpx
from tools.debugger import import_project_module

API=import_project_module('glorybond.integrations.ai')
ZAPI=import_project_module('glorybond.integrations.api')


class TextAPITests(unittest.TestCase):
    def test_business_text_uses_responses_medium_and_does_not_send_legacy_sampling(self):
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'status': 'completed', 'model': 'gpt-6.1-sol',
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'answer'}]}],
                'usage': {'input_tokens': 10, 'output_tokens': 2}})
        client = httpx.Client
        with patch.object(API, 'chat_api_config', {'api_key': 'test-key', 'base_url': 'https://api.openai.com/v1',
                'model': 'gpt-6.1-sol', 'protocol': 'openai_responses', 'reasoning_effort': 'medium'}), \
             patch.object(API, 'DefaultHttpxClient', side_effect=lambda **kw: client(transport=httpx.MockTransport(handler), **kw)):
            self.assertEqual(API.ai_api('test', temperature=1.5, thinking=False), 'answer')
            self.assertEqual(API.ark_api('search test'), 'answer')
        self.assertEqual(requests[0]['reasoning'], {'effort': 'medium'})
        self.assertNotIn('temperature', requests[0])
        self.assertNotIn('thinking', requests[0])
        self.assertEqual(requests[1]['tools'], [{'type': 'web_search'}])

    def test_business_text_falls_back_to_streaming_kimi(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.host == 'primary.invalid':
                return httpx.Response(503)
            return httpx.Response(200, text='data: {"choices":[{"delta":{"reasoning_content":"reason"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"译文"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        original = httpx.Client
        provider = {'api_key': 'primary-secret', 'base_url': 'https://primary.invalid', 'model': 'primary',
                    'fallback': {'api_key': 'backup-secret', 'base_url': 'https://backup.invalid',
                                 'model': 'kimi-k3', 'protocol': 'bailian_kimi'}}
        with patch.object(API, 'chat_api_config', provider), patch.object(API, 'DefaultHttpxClient',
                side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw)):
            self.assertEqual(API.ai_api('translate', temperature=.1, thinking=False,
                                        response_format={'type': 'json_object'}), '译文')
        self.assertEqual(requests[1].headers['authorization'], 'Bearer backup-secret')
        body = json.loads(requests[1].content)
        self.assertTrue(body['stream'])
        self.assertNotIn('thinking', body)
        self.assertNotIn('temperature', body)
        self.assertEqual(body['response_format'], {'type': 'json_object'})

    def test_translation_can_disable_thinking_and_use_its_own_timeout(self):
        bodies=[]
        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200,json={"id":"test","object":"chat.completion","created":0,"model":"test",
                "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"译文"}}]})
        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)
        with patch.object(API,'chat_api_config',{'api_key':'secret','base_url':'https://example.test/v1','model':'test','proxy_url':''}), \
             patch.object(API,'DefaultHttpxClient',side_effect=client):
            self.assertEqual(ZAPI.ai_api('translate',temperature=0.1,timeout=60,thinking=False,
                                        response_format={'type':'json_object'}),'译文')
        self.assertEqual(bodies[0]['thinking'],{'type':'disabled'})
        self.assertEqual(bodies[0]['response_format'],{'type':'json_object'})
        self.assertNotIn('timeout',bodies[0])

    def test_text_helpers_use_configured_direct_provider_without_agent_protocol(self):
        bodies, options = [], []
        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200,json={"id":"test","object":"chat.completion","created":0,"model":"test",
                "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"answer"}}]})
        def client(**kwargs):
            options.append(kwargs)
            return httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)
        with patch.object(API,'chat_api_config',{'api_key':'secret','base_url':'https://api.deepseek.com','model':'test','proxy_url':''}), patch.object(API,'DefaultHttpxClient',side_effect=client):
            self.assertEqual(ZAPI.ai_api('hello',temperature=1.5),'answer')
            self.assertEqual(ZAPI.ai_function('expression'),'answer')
        self.assertEqual(options,[{'trust_env':False},{'trust_env':False}])
        self.assertEqual(bodies[0]['messages'],[{'role':'user','content':'hello'}])
        self.assertNotIn('tools',bodies[0])
        self.assertNotIn('tool_choice',bodies[0])

    def test_transport_error_retains_wire_bodies_without_headers(self):
        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'error':{'message':'bad input'}})),trust_env=False)
        with patch.object(API,'chat_api_config',{'api_key':'secret','base_url':'https://api.deepseek.com','model':'test','proxy_url':''}), patch.object(API,'DefaultHttpxClient',side_effect=client):
            with self.assertRaises(API.AIRequestError) as caught:
                API._chat_completion_create('INPUT')
        self.assertEqual(caught.exception.request_payload['messages'][0]['content'],'INPUT')
        self.assertEqual(caught.exception.response_payload['error']['message'],'bad input')
        self.assertNotIn('Authorization',json.dumps(caught.exception.request_payload))

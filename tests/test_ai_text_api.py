"""Business text generation keeps direct transport and body-only diagnostics."""
import json
import unittest
from unittest.mock import patch
import httpx
from local_debugger import import_hok_module

API=import_hok_module('api_adapters.ai')
ZAPI=import_hok_module('zapi')


class TextAPITests(unittest.TestCase):
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

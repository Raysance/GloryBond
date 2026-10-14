"""Local Web overrides stay separate from deployed QQ model configuration."""

import copy
import unittest

from agent_console.server import local_model_settings


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.remote = {
            "private": {"api_key": "remote-test-key"},
            "public": {"base_url": "https://remote.invalid", "model": "remote-model"},
        }
        self.local = {"llm": {
            "base_url": "https://local.invalid/api/v1",
            "api_key_env": "LLM_API_KEY",
            "model": "deepseek/deepseek-v4.1-flash",
        }}

    def test_override_uses_local_key_and_model_without_mutating_remote(self):
        original = copy.deepcopy(self.remote)
        result = local_model_settings(self.local, self.remote, environment={"LLM_API_KEY": "local-test-key"})
        self.assertEqual(result, {
            "api_key": "local-test-key", "base_url": "https://local.invalid/api/v1",
            "model": "deepseek/deepseek-v4.1-flash", "vision_model": "deepseek/deepseek-v4.1-flash",
            "proxy_url": "",
        })
        self.assertEqual(self.remote, original)

    def test_no_override_restores_existing_remote_credentials_and_local_vision(self):
        result = local_model_settings({"vision_model": "vision-model"}, self.remote,
                                      environment={"LLM_API_KEY": "unused-local-key"})
        self.assertEqual(result, {
            "api_key": "remote-test-key", "base_url": "https://remote.invalid",
            "model": "remote-model", "vision_model": "vision-model",
            "proxy_url": "",
        })

    def test_separate_vision_model_can_be_configured(self):
        self.local['llm']['vision_model'] = 'separate-vision-model'
        result = local_model_settings(self.local, self.remote, environment={'LLM_API_KEY': 'local-test-key'})
        self.assertEqual(result['vision_model'], 'separate-vision-model')

    def test_local_endpoint_override_does_not_inherit_a_remote_loopback_proxy(self):
        self.remote['public']['proxy_url'] = 'http://127.0.0.1:7890'
        self.assertEqual(local_model_settings(self.local, self.remote, environment={'LLM_API_KEY': 'test-key'})['proxy_url'], '')
        self.assertEqual(local_model_settings({}, self.remote, environment={})['proxy_url'], 'http://127.0.0.1:7890')
        self.local['llm']['proxy_url'] = 'http://local-proxy.invalid:7890'
        self.assertEqual(local_model_settings(self.local, self.remote, environment={'LLM_API_KEY': 'test-key'})['proxy_url'], 'http://local-proxy.invalid:7890')

    def test_missing_or_incomplete_override_cannot_send_remote_key_to_new_endpoint(self):
        for settings, environment in [
            ({'base_url': 'https://local.invalid'}, {'LLM_API_KEY': 'local-test-key'}),
            ({'api_key_env': 'LLM_API_KEY'}, {'LLM_API_KEY': 'local-test-key'}),
            (self.local['llm'], {}),
            (self.local['llm'], {'LLM_API_KEY': ''}),
        ]:
            with self.subTest(settings=settings), self.assertRaises(ValueError) as caught:
                local_model_settings({'llm': settings}, self.remote, environment=environment)
            self.assertNotIn('remote-test-key', str(caught.exception))


if __name__ == '__main__':
    unittest.main()

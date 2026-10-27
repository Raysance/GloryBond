"""Admin auth, CSRF and bridge isolation; never start real login challenges."""
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('BOT_PATH', str(Path(__file__).resolve().parents[2]))
from fastapi.testclient import TestClient
from web import app as web
class AccountRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web.app)
        self.bridge = AsyncMock(return_value={'ok': True, 'result': {'authenticated': None}})
        self.patch = patch.object(web.account_login_bridge, 'call', self.bridge)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def login(self):
        self.client.cookies.set('AdminKey', web.SECRET_KEY)

    def test_anonymous_cannot_read_qr_or_trigger_network(self):
        for method, route in [('get', ''), ('get', '/state'), ('post', '/action')]:
            result = getattr(self.client, method)('/admin/funcs/account-sessions'+route, follow_redirects=False)
            self.assertIn(result.status_code, (303, 401))
            self.assertEqual(result.headers['cache-control'], 'no-store')
        self.bridge.assert_not_called()

    def test_csrf_and_cross_site_mutations_are_rejected(self):
        self.login()
        for headers in ({}, {'X-Account-CSRF': web._account_csrf(), 'Sec-Fetch-Site': 'cross-site'}):
            result = self.client.post('/admin/funcs/account-sessions/action', json={'provider': 'camp', 'action': 'start'}, headers=headers)
            self.assertEqual(result.status_code, 403)
        self.bridge.assert_not_called()

    def test_only_fixed_protocol_actions_are_dispatched(self):
        self.login()
        headers = {'X-Account-CSRF': web._account_csrf()}
        for payload in ({'provider': '../camp', 'action': 'start'}, {'provider': 'camp', 'action': 'shell'},
                        {'provider': 'camp', 'action': 'start', 'env_file': '/tmp/evil'},
                        {'provider': 'camp', 'action': 'poll', 'challenge_id': 'evil'}):
            result = self.client.post('/admin/funcs/account-sessions/action', json=payload, headers=headers)
            self.assertEqual(result.status_code, 400)
        self.bridge.assert_not_called()
        payload = {'provider': 'camp', 'action': 'check'}
        result = self.client.post('/admin/funcs/account-sessions/action', json=payload, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.bridge.assert_awaited_once_with(payload)
        self.assertEqual(result.headers['referrer-policy'], 'no-referrer')

    def test_page_has_admin_only_qr_workflow_and_no_admin_cookie_in_markup(self):
        self.login()
        result = self.client.get('/admin/funcs/account-sessions')
        self.assertEqual(result.status_code, 200)
        self.assertIn('账号登录态', result.text)
        self.assertIn('X-Account-CSRF', result.text)
        self.assertNotIn(web.SECRET_KEY, result.text)
        self.assertNotIn('innerHTML', result.text)
        self.assertEqual(result.headers['x-robots-tag'], 'noindex, nofollow')

    def test_rate_limit_is_visible_to_browser(self):
        self.login()
        self.bridge.return_value = {'ok': False, 'error': 'cooldown', 'retry_after': 30}
        result = self.client.post('/admin/funcs/account-sessions/action', json={'provider': 'camp', 'action': 'start'}, headers={'X-Account-CSRF': web._account_csrf()})
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.json()['retry_after'], 30)

    def test_role_choice_is_limited_to_camp_and_dispatched_without_identity_parameters(self):
        self.login()
        headers={'X-Account-CSRF':web._account_csrf()}
        base={'provider':'camp','action':'select_role','challenge_id':'a'*32,'role_choice':0}
        for payload in ({**base,'provider':'official'}, {**base,'role_choice':True}, {**base,'role_choice':-1},
                        {**base,'role_choice':100}, {**base,'openid':'arbitrary'}):
            self.assertEqual(self.client.post('/admin/funcs/account-sessions/action',json=payload,headers=headers).status_code,400)
        self.bridge.assert_not_called()
        self.assertEqual(self.client.post('/admin/funcs/account-sessions/action',json=base,headers=headers).status_code,200)
        self.bridge.assert_awaited_once_with(base)

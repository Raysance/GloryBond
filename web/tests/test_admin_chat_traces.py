import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("BOT_PATH", str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from web import app as web
from web.admin_chat_traces import TRACE_INDEX_KEY, list_chat_traces


def record(index=0, **changes):
    return {"key": f"{index:016x}", "created_at": time.time() - index,
            "expires_at": time.time() + 3600, "status": "ok", "question": "提醒示例玩家65别卷了",
            "group_id": "200", "user_id": "101", "channel": "group", "run_id": f"run-{index}",
            "session_id": "qq_g_200_101", "model": "test-model", "tool_calls": 2,
            "total_tokens": 120, **changes}


class AdminTraceTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.store.lrange.return_value = [json.dumps(record())]
        self.store.get.return_value = json.dumps({"kind": "chat_trace", "version": 1, "rounds": [],
            "question": "PRIVATE-QUESTION", "visibility": "admin", "answer": "PRIVATE-ANSWER"})
        self.patch = patch.object(web, "r_com", self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(web.app)

    def login(self):
        self.client.cookies.set("AdminKey", web.SECRET_KEY)

    def test_existing_login_and_dashboard_can_reach_trace_list(self):
        self.assertEqual(self.client.get('/admin/login').status_code, 200)
        self.login()
        dashboard = self.client.get('/admin/dashboard')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('href="/admin/funcs/chat-traces"', dashboard.text)

    def test_list_and_detail_require_admin_before_redis_access(self):
        for path in ("/admin/funcs/chat-traces", "/admin/funcs/chat-traces/" + "a" * 16):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.headers["location"], "/admin/login")
            self.assertNotIn("PRIVATE", response.text)
        self.store.lrange.assert_not_called()
        self.store.get.assert_not_called()

    def test_list_escapes_questions_and_contains_admin_details_and_navigation(self):
        self.login()
        question = '<img src=x onerror="alert(1)">'
        self.store.lrange.return_value = [json.dumps(record(question=question))]
        response = self.client.get("/admin/funcs/chat-traces")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertNotIn(question, response.text)
        self.assertIn("&lt;img", response.text)
        self.assertIn('/admin/funcs/chat-traces/0000000000000000', response.text)
        self.assertIn('QQ 101', response.text)
        self.assertIn('120', response.text)
        self.store.lrange.assert_called_once_with(TRACE_INDEX_KEY, 0, 999)

    def test_pagination_filters_expiry_invalid_entries_and_never_loads_full_payloads(self):
        rows = [record(index) for index in range(31)]
        rows.extend([record(100, expires_at=1), record(101, key="../secret"), record(102, status="error", group_id="300")])
        self.store.lrange.return_value = [json.dumps(row) for row in rows] + ["bad", "null"]
        first = list_chat_traces(self.store)
        self.assertEqual((first['total'], len(first['records']), first['pages']), (32, 25, 2))
        second = list_chat_traces(self.store, page=2, group_id="200", query="101")
        self.assertEqual((second['total'], len(second['records'])), (31, 6))
        self.assertEqual([row['run_id'] for row in second['records']], [f'run-{i}' for i in range(25, 31)])
        selected = list_chat_traces(self.store, status="error", group_id="300")
        self.assertEqual([row['run_id'] for row in selected['records']], ['run-102'])
        self.store.get.assert_not_called()

    def test_existing_shared_link_is_public_and_admin_detail_keeps_full_viewer(self):
        response = self.client.get('/chat-trace?key=' + 'a' * 16, follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('location', response.headers)
        self.assertIn('PRIVATE-QUESTION', response.text)
        self.assertIn('PRIVATE-ANSWER', response.text)
        self.assertNotIn('← AI 运行记录', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.store.lrange.assert_not_called()
        response = self.client.get('/admin/funcs/chat-traces/' + 'a' * 16, follow_redirects=False)
        self.assertEqual(response.headers['location'], '/admin/login')
        self.login()
        response = self.client.get('/admin/funcs/chat-traces/' + 'a' * 16)
        self.assertEqual(response.status_code, 200)
        self.assertIn('PRIVATE-QUESTION', response.text)
        self.assertIn('PRIVATE-ANSWER', response.text)
        self.assertIn('← AI 运行记录', response.text)
        self.assertIn('noindex', response.headers['x-robots-tag'])

    def test_invalid_keys_expired_records_and_backend_errors_keep_safe_responses(self):
        self.login()
        response = self.client.get('/admin/funcs/chat-traces/invalid')
        self.assertEqual(response.status_code, 400)
        self.store.get.assert_not_called()
        self.store.get.return_value = None
        self.assertEqual(self.client.get('/admin/funcs/chat-traces/' + 'a' * 16).status_code, 410)
        self.store.lrange.side_effect = ConnectionError('PRIVATE-CONNECTION')
        response = self.client.get('/admin/funcs/chat-traces')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE-CONNECTION', response.text)

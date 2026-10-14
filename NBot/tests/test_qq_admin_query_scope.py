"""Default query group preserves private identity and existing cross-group grants."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_console import remote_worker as worker
from agent_console.capabilities import remote_chat_identity
from agent_console.tools.memory import search_history_records
from agent_console.tools.sql_validation import validate_readonly_sql
from qq_agent.service import qq_principal
from tests.test_agent_recent_history import Database


class AdminScopeTests(unittest.TestCase):
    def setUp(self):
        self.principal = remote_chat_identity(qq_principal('999', None, '', admin_id='999',
            references={'context': {'catalogs': {}}}, admin_private_default_group_id='2000000000'))

    def test_explicit_selection_changes_query_target_within_authorized_scope(self):
        self.assertEqual(worker.trusted_scope(self.principal), '2000000000')
        self.assertEqual(worker.trusted_scope(self.principal, '300'), '300')
        self.assertEqual(worker.trusted_scope(self.principal, '*'), '*')
        group = {**self.principal, 'group_id': '200'}
        self.assertEqual(worker.trusted_scope(group), '200')
        for target in ('300', '*'):
            with self.assertRaises(PermissionError):
                worker.trusted_scope(group, target)
        with self.assertRaises(PermissionError):
            worker.trusted_scope({'default_group_id': '2000000000', 'scopes': []})

    def test_bm25_reads_default_group_but_keeps_matching_private_message_id(self):
        row = {'group_id': '2000000000', 'message_id': '42', 'user_id': '100', 'text': 'context'}
        db = Database([row])
        with patch.dict(worker.CONTEXT, {'memory': {'search_history_records': search_history_records}}, clear=True), \
             patch.object(worker, 'db_connection', return_value=db) as connect:
            result = worker.search_history({'principal': self.principal, 'original_query': 'context',
                                             'queries': ['context'], 'exclude_message_id': '42'})
        connect.assert_called_once_with('2000000000')
        self.assertEqual(result['scope'], 'selected_group')
        self.assertEqual(result['messages'][0]['message_id'], '42')
        self.assertEqual(result['group_id'], '2000000000')

    def test_chat_sql_uses_default_or_explicit_selection_before_connection(self):
        catalog = json.loads((Path(__file__).parents[1] / 'shared/agent/chat_sql/catalog.json').read_text())
        context = {'cfg': {}, 'catalogs': {'chat_sql': catalog}, 'validation': {'validate_readonly_sql': validate_readonly_sql}}
        for selected, expected in [(None, '2000000000'), ('300', '300'), ('*', '*')]:
            with self.subTest(selected=selected), patch.dict(worker.CONTEXT, context, clear=True), \
                 patch.object(worker, 'db_connection', side_effect=RuntimeError('connection probe')) as connect:
                with self.assertRaisesRegex(RuntimeError, 'connection probe'):
                    worker.analyze({'domain': 'chat', 'principal': self.principal, 'group_id': selected,
                                    'queries': [{'sql': 'SELECT group_id FROM hok.chat_history_messages'}]})
                connect.assert_called_once_with(expected)


if __name__ == '__main__':
    unittest.main()

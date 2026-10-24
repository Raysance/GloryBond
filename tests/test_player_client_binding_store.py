"""Bindings and unresolved/skipped metadata persist without rewriting other config."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from local_debugger import import_hok_module

ZFILE = import_hok_module('zfile')
STATIC = import_hok_module('zstatic')


class BindingStoreTests(unittest.TestCase):
    def test_merge_clears_only_resolved_pending_and_preserves_other_sections(self):
        original = ('Other:\n  text: 保持原样\nPlayerClient:\n  enabled: true\n'
                    '  players:\n    old: {uid: 1}\n  pending_players:\n'
                    '    new: {status: ambiguous}\n    missing: {status: missing}\n'
                    'After:\n  value: untouched\n')
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'config.yaml'
            path.write_text(original)
            with patch.object(STATIC, 'config_path', str(path)):
                ZFILE.save_player_client_bindings({'new': {'uid': 2}}, pending={'other': {'status': 'not_found'}})
            text = path.read_text()
        self.assertTrue(text.startswith('Other:\n  text: 保持原样\n'))
        self.assertTrue(text.endswith('After:\n  value: untouched\n'))
        config = yaml.safe_load(text)['PlayerClient']
        self.assertEqual(config['players'], {'old': {'uid': 1}, 'new': {'uid': 2}})
        self.assertEqual(set(config['pending_players']), {'missing', 'other'})

    def test_explicit_skip_survives_later_binding_updates(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'config.yaml'
            path.write_text('PlayerClient:\n  players: {}\n')
            with patch.object(STATIC, 'config_path', str(path)):
                ZFILE.save_player_client_bindings({}, skipped=['yd', 'zm', 'yd'])
                ZFILE.save_player_client_bindings({'new': {'uid': 2}})
            config = yaml.safe_load(path.read_text())['PlayerClient']
        self.assertEqual(config['binding_skip_players'], ['yd', 'zm'])

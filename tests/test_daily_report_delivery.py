"""Execute actual handlers without registering a running bot or scheduled jobs."""
import ast
import tempfile
import sys
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

from nonebot.adapters.onebot.v11 import MessageSegment
from local_debugger import import_hok_module, project_root

ZFUNC = import_hok_module('zfunc')
REPORTS = import_hok_module('event_handlers.player_reports')
STATIC = import_hok_module('zstatic')
UTIL = import_hok_module('zutil')


def handler(path, name, namespace=None):
    tree = ast.parse((project_root() / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    namespace = namespace or {}
    namespace.update(__name__="hok.test_delivery", __package__="hok")
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), namespace)
    return namespace[name]


class ReportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_push_sends_image_then_representative_and_errors_only_to_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'report.png'
            image.write_bytes(b'image')
            messages = [('', str(image)), {'admin_error': 'source failed'}, ('Representative', str(image), 'Commentary')]
            send = Mock()
            with patch.object(ZFUNC, 'notify_msg_impl', return_value=messages), \
                 patch.dict(sys.modules, {'hok.utils.message_sender': SimpleNamespace(add_msg=send)}), patch.object(UTIL, 'log_message'), \
                 patch.object(STATIC, 'confs', {'QQBot': {'super_qid': 1, 'group_qid': 2}}):
                await handler('hok/zscheduler.py', 'notify_msg')()
            calls = send.call_args_list
            self.assertEqual(len(calls), 3)
            self.assertEqual([segment.type for segment in calls[0].args[0]], ['image'])
            self.assertEqual(calls[0].kwargs, {'msg_type': 'group', 'to_id': 2})
            self.assertEqual(calls[1].kwargs, {'msg_type': 'private', 'to_id': 1})
            self.assertEqual([segment.type for segment in calls[2].args[0]], ['text', 'image', 'text'])

    async def test_rank_handler_sends_only_the_image(self):
        from unittest.mock import Mock, AsyncMock
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'report.png'
            image.write_bytes(b'image')
            send = Mock()
            event = Mock(group_id=None)
            namespace = {'log_message': Mock(), 'add_msg': send, 'MessageSegment': MessageSegment}
            with patch.object(REPORTS, 'ranking_reply', new=AsyncMock(return_value={
                'text': '', 'image_path': str(image), 'error_report': ''})):
                await handler('hok/zevent.py', 'f_rnk', namespace)(None, event)
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0].type, 'image')
            self.assertEqual(send.call_args.kwargs['event'], event)


if __name__ == '__main__':
    unittest.main()

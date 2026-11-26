"""Execute actual handlers without registering a running bot or scheduled jobs."""
import ast
import tempfile
import sys
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

from nonebot.adapters.onebot.v11 import MessageSegment
from tools.debugger import import_project_module, project_root

ZFUNC = import_project_module('glorybond.features.facade')
REPORTS = import_project_module('glorybond.apps.qq.handlers.player_reports')
STATIC = import_project_module('glorybond.config.settings')
UTIL = import_project_module('glorybond.common')


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
    async def test_daily_push_keeps_successful_images_and_reports_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'report.png'
            image.write_bytes(b'image')
            messages = [('', str(image)), {'admin_error': 'source failed'}, ('Representative', str(image), 'Commentary')]
            send = Mock()
            report = Mock()
            with patch.object(ZFUNC, 'notify_msg_impl', return_value=messages), \
                 patch.dict(sys.modules, {'glorybond.apps.qq.message_sender': SimpleNamespace(add_msg=send)}), patch.object(UTIL, 'log_message'), \
                 patch.object(STATIC, 'confs', {'QQBot': {'super_qid': 1, 'group_qid': 2}}):
                await handler('src/glorybond/apps/qq/scheduler.py', 'notify_msg', {'report_error_text': report})()
            calls = send.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual([segment.type for segment in calls[0].args[0]], ['image'])
            self.assertEqual(calls[0].kwargs, {'msg_type': 'group', 'to_id': 2})
            report.assert_called_once_with('source failed', operation='每日战报', partial=True)
            self.assertEqual([segment.type for segment in calls[1].args[0]], ['text', 'image', 'text'])

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
                await handler('src/glorybond/apps/qq/events.py', 'f_rnk', namespace)(None, event)
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0].type, 'image')
            self.assertEqual(send.call_args.kwargs['event'], event)


if __name__ == '__main__':
    unittest.main()

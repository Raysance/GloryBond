import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tools.debugger import import_project_module
from glorybond.apps.qq import errors

with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    sender = import_project_module("glorybond.apps.qq.message_sender")


class ErrorReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        errors._recent.clear()
        self.queue = Mock()
        self.patchers = [patch.object(sender.dmc, "MessageQueue", self.queue),
                         patch.object(errors.logging, "getLogger", return_value=Mock())]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def payloads(self):
        return [json.loads(c.args[1]) for c in self.queue.lpush.call_args_list]

    def test_group_reports_are_literal_forwards_and_keep_admin_notice(self):
        event = SimpleNamespace(group_id=123, message_id=456)
        self.assertTrue(errors.report_exception(ValueError("invalid [CQ:at,qq=all]"), operation="查询", event=event))
        group, admin = self.payloads()
        self.assertEqual((group["kind"], group["toid"]), ("group_forward", 123))
        self.assertEqual(admin["type"], "private")
        self.assertEqual(group["automation_metadata"]["source"], "diagnostic")
        for node in group["messages"]:
            self.assertEqual(node["data"]["content"][0]["type"], "text")

    def test_private_input_does_not_get_routed_to_default_group(self):
        event = SimpleNamespace(message_id=456, get_user_id=lambda: "321")
        errors.report_exception(RuntimeError("failure"), operation="私聊处理", event=event)
        self.assertTrue(all(p["type"] == "private" for p in self.payloads()))
        self.assertEqual(self.payloads()[0]["toid"], 321)

    def test_background_failure_uses_configured_group_and_is_throttled(self):
        self.assertTrue(errors.report_exception(TimeoutError(), operation="定时任务"))
        self.assertFalse(errors.report_exception(TimeoutError(), operation="定时任务"))
        self.assertEqual(len(self.payloads()), 2)
        group = self.payloads()[0]
        self.assertEqual(str(group["toid"]), str(sender.confs["QQBot"]["group_qid"]))
        self.assertIn("超时", group["messages"][0]["data"]["content"][0]["data"]["text"])

    def test_different_foreground_requests_are_not_throttled_together(self):
        for message_id in (1, 2):
            errors.report_exception(ValueError("bad"), operation="查询", event=SimpleNamespace(group_id=123, message_id=message_id))
        self.assertEqual(len(self.payloads()), 4)

    def test_queue_failure_does_not_escape_or_recurse(self):
        self.queue.lpush.side_effect = ConnectionError("queue offline")
        self.assertFalse(errors.report_exception(RuntimeError("original"), operation="查询"))
        self.assertEqual(self.queue.lpush.call_count, 2)

    def test_cancellation_does_not_send_anything(self):
        self.assertFalse(errors.report_exception(asyncio.CancelledError(), operation="对话"))
        self.queue.lpush.assert_not_called()

    def test_chained_empty_exception_has_readable_reason_without_private_material(self):
        try:
            try:
                raise TimeoutError()
            except TimeoutError as exc:
                raise RuntimeError("upload https://host/private?signature=secret /srv/private/file token=abc MySecret") from exc
        except RuntimeError as exc:
            report = "\n".join(errors.build_report(exc, operation="处理", report_id="test", secrets=["MySecret"]))
        for private in ("https://host", "/srv/private", "signature", "abc", "MySecret"):
            self.assertNotIn(private, report)
        self.assertIn("超时", report)
        self.assertIn("TimeoutError", report)
        self.assertIn("test_qq_errors.py", report)

    def test_http_response_body_does_not_reach_report(self):
        error = RuntimeError('service returned personal document contents')
        error.response = SimpleNamespace(status_code=403)
        report = "\n".join(errors.build_report(error, operation="读取", report_id="test"))
        self.assertNotIn("personal document", report)
        self.assertIn("HTTP 403", report)

    async def test_diagnostic_delivery_failure_does_not_generate_another_report(self):
        payload = {"type": "group", "toid": 123, "kind": "group_forward", "messages": [],
                   "automation_metadata": {"source": "diagnostic"}}
        bot = SimpleNamespace(send_group_forward_msg=AsyncMock(side_effect=RuntimeError("fail")))
        with patch.object(sender, "log_message"):
            await sender._handle_forward_msg(bot, payload)
        self.queue.lpush.assert_not_called()

    async def test_diagnostics_do_not_trigger_automation(self):
        facade = import_project_module("glorybond.features.facade")
        payload = {"type": "group", "toid": 123, "content": "diagnostic",
                   "automation_metadata": {"source": "diagnostic"}}
        with patch.object(facade, "automation_publish_event") as publish:
            await sender._automation_before_send(payload)
            await sender._automation_sent(payload, {"message_id": 12})
        publish.assert_not_called()

    def test_legacy_partial_report_preserves_reason_without_parameters(self):
        errors.report_error_text("采集异常 count=1\n1. source name params={'private': 1} err=TimeoutError('deadline')", operation="采集", partial=True)
        rendered = json.dumps(self.payloads(), ensure_ascii=False)
        self.assertIn("deadline", rendered)
        self.assertNotIn("params", rendered)
        self.assertIn("已有结果", rendered)

    async def test_hooks_report_only_our_unhandled_failures(self):
        callbacks = []
        scheduler = Mock()
        scheduler.get_job.return_value = SimpleNamespace(func=SimpleNamespace(__module__="glorybond.apps.qq.scheduler"))
        with patch("nonebot.message.run_postprocessor", side_effect=lambda fn: callbacks.append(fn) or fn):
            errors.register_error_hooks(scheduler)
        error = RuntimeError("unhandled")
        event = SimpleNamespace(group_id=123, message_id=456)
        with patch.object(errors, "report_exception") as report:
            await callbacks[0](SimpleNamespace(module_name="glorybond.apps.qq.events"), event, error)
            report.assert_called_once_with(error, operation="消息处理", event=event)
            report.reset_mock()
            await callbacks[0](SimpleNamespace(module_name="external_plugin"), event, error)
            await callbacks[0](SimpleNamespace(module_name="glorybond.apps.qq.events"), event, None)
            report.assert_not_called()
            listener = scheduler.add_listener.call_args.args[0]
            listener(SimpleNamespace(exception=error, job_id="test_job"))
            report.assert_called_once_with(error, operation="后台任务 test_job")


if __name__ == "__main__":
    unittest.main()

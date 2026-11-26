"""Subscription rounds and delayed delivery share a bounded notice policy."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from glorybond.apps.qq import errors, interval_jobs as jobs
from tests.test_daily_report_delivery import handler
from tests.test_qq_errors import sender
from tools.debugger import import_project_module


class IntervalJobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = patch.object(jobs, "record_interval_outcome", return_value=(1, False))
        self.record = self.state.start()
        self.addCleanup(self.state.stop)
        report = patch.object(errors, "report_exception")
        self.report = report.start()
        self.addCleanup(report.stop)
        log = patch.object(jobs, "logger")
        log.start()
        self.addCleanup(log.stop)

    async def test_many_partial_failures_count_as_one_failed_round(self):
        failure = TimeoutError()
        def check(*, on_error):
            for _ in range(40):
                on_error(failure)
            return {"checked": 40, "pushed": 3, "errors": ["failed"]}
        await jobs.run_subscription_job("x_subscription_push", check)
        self.record.assert_called_once()
        self.assertTrue(self.record.call_args.kwargs["failed"])
        self.report.assert_not_called()

    async def test_fatal_failure_also_waits_and_notice_uses_original_error(self):
        failure = ConnectionError("offline")
        self.record.return_value = (30, True)
        result = await jobs.run_subscription_job("bili_video_push", Mock(side_effect=failure))
        self.assertIsNone(result)
        self.report.assert_called_once()
        self.assertIs(self.report.call_args.args[0], failure)
        self.assertIn("连续30次失败", self.report.call_args.kwargs["operation"])
        self.assertIsNone(jobs.current_interval_job.get())

    async def test_successful_poll_resets_even_without_new_posts_but_skips_do_not(self):
        await jobs.run_subscription_job("bili_video_push", Mock(return_value={"checked": 3, "pushed": 0}))
        self.assertFalse(self.record.call_args.kwargs["failed"])
        self.record.reset_mock()
        await jobs.run_subscription_job("bili_video_push", Mock(return_value={"checked": 0, "pushed": 0}))
        self.record.assert_not_called()
        self.report.assert_not_called()

    async def test_error_result_without_callback_and_storage_failure_stay_quiet(self):
        self.record.side_effect = ConnectionError("state offline")
        await jobs.run_subscription_job("x_subscription_push", Mock(return_value={"checked": 1, "errors": ["failed"]}))
        self.assertTrue(self.record.call_args.kwargs["failed"])
        self.report.assert_not_called()

    async def test_cancelled_poll_does_not_reset_or_count_a_failure(self):
        with self.assertRaises(asyncio.CancelledError):
            await jobs.run_subscription_job("x_subscription_push", Mock(side_effect=asyncio.CancelledError()))
        self.record.assert_not_called()
        self.assertIsNone(jobs.current_interval_job.get())

    async def test_only_scheduled_group_messages_keep_trusted_job_provenance(self):
        messages = []
        def check(*, on_error):
            for channel, metadata in (("group", {"source": "bili_video"}),
                                      ("private", {"source": "bili_video"}),
                                      ("group", {"source": "diagnostic"})):
                messages.append(sender._message_payload("text", msg_type=channel, to_id=123, metadata=metadata))
            return {"checked": 1}
        await jobs.run_subscription_job("bili_video_push", check)
        messages.append(sender._message_payload("manual", msg_type="group", to_id=123,
                                                metadata={"source": "bili_video"}))
        self.assertEqual(messages[0]["interval_job_id"], "bili_video_push")
        self.assertTrue(all("interval_job_id" not in message for message in messages[1:]))

    async def test_both_actual_scheduler_entries_use_the_policy(self):
        facade = import_project_module("glorybond.features.facade")
        for job_id, function in (("bili_video_push", "bili_video_check_and_push"),
                                 ("x_subscription_push", "x_check_and_push")):
            with self.subTest(job_id=job_id), patch.object(facade, function, side_effect=TimeoutError()):
                self.record.reset_mock()
                await handler("src/glorybond/apps/qq/scheduler.py", job_id, {"log_message": Mock()})()
                self.record.assert_called_once()
                self.assertIn(job_id, self.record.call_args.args[0])
        self.report.assert_not_called()

    def test_scheduler_fallback_does_not_bypass_threshold(self):
        scheduler = Mock()
        scheduler.get_job.return_value = SimpleNamespace(func=SimpleNamespace(__module__="glorybond.apps.qq.scheduler"))
        with patch("nonebot.message.run_postprocessor", side_effect=lambda fn: fn):
            errors.register_error_hooks(scheduler)
        scheduler.add_listener.call_args.args[0](SimpleNamespace(job_id="x_subscription_push", exception=TimeoutError()))
        self.record.assert_called_once()
        self.report.assert_not_called()

    async def send_one(self, payload, outcomes):
        bot = SimpleNamespace(send_group_msg=AsyncMock(side_effect=outcomes))
        queue = Mock()
        queue.rpop.side_effect = [json.dumps(payload), asyncio.CancelledError()]
        files = import_project_module("glorybond.storage.files")
        with patch.object(sender.dmc, "MessageQueue", queue), \
             patch.object(sender, "MESSAGE_SEND_INTERVAL", 0), \
             patch.object(sender.nonebot, "get_bot", return_value=bot), \
             patch.object(files, "refresh_login_credentials"), \
             patch.object(sender, "_automation_before_send", new=AsyncMock(side_effect=lambda p: p)), \
             patch.object(sender, "_automation_sent", new=AsyncMock()), \
             patch.object(sender, "_record_task_receipt", new=AsyncMock()), \
             patch.object(sender, "log_message"):
            with self.assertRaises(asyncio.CancelledError):
                await sender.message_sender_loop()
        return bot

    async def test_video_caption_success_does_not_clear_failure_when_video_fails(self):
        payload = {"type": "group", "toid": 123, "content": "[CQ:video,file=test]",
                   "kind": "video_with_metadata", "caption": "caption", "interval_job_id": "bili_video_push"}
        bot = await self.send_one(payload, [{"message_id": 1}, TimeoutError()])
        self.assertEqual(bot.send_group_msg.call_count, 2)
        self.record.assert_called_once()
        self.assertTrue(self.record.call_args.kwargs["failed"])
        self.assertIn(":delivery:123", self.record.call_args.args[0])
        self.report.assert_not_called()

    async def test_confirmed_delivery_resets_but_missing_receipt_counts_failure(self):
        payload = {"type": "group", "toid": 123, "content": "post", "interval_job_id": "x_subscription_push"}
        for response, failed in (({"message_id": 1}, False), ({}, True)):
            with self.subTest(response=response):
                self.record.reset_mock()
                await self.send_one(payload, [response])
                self.record.assert_called_once()
                self.assertEqual(self.record.call_args.kwargs["failed"], failed)
        self.report.assert_not_called()

    def test_manual_failures_report_immediately_and_diagnostics_never_recurse(self):
        error = TimeoutError()
        payload = {"type": "group", "toid": 123, "automation_metadata": {"source": "bili_video"}}
        sender._report_delivery_error(error, payload, operation="manual")
        self.report.assert_called_once()
        self.record.assert_not_called()
        self.report.reset_mock()
        sender._report_delivery_error(error, {**payload, "interval_job_id": "bili_video_push",
            "automation_metadata": {"source": "diagnostic"}}, operation="report")
        self.record.assert_not_called()
        self.report.assert_not_called()


if __name__ == "__main__":
    unittest.main()

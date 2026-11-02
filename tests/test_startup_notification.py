"""Startup reports the deployed revision without making Git a startup dependency."""

import asyncio
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from nonebot.adapters.onebot.v11 import Message
from local_debugger import import_hok_module


FILES = import_hok_module("zfile")
with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module("utils.message_sender")


class DeployedCommitTests(unittest.TestCase):
    def test_reads_full_head_and_multiline_message_from_source_checkout(self):
        commit_hash = "a" * 40
        message = "fix: report deployed version\n\nInclude the full commit message."
        with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout=commit_hash + "\0" + message + "\n")) as run:
            self.assertEqual(FILES.read_deployed_commit(), {"hash": commit_hash, "message": message})
        self.assertEqual(run.call_args.kwargs["cwd"], Path(FILES.__file__).resolve().parents[1])
        self.assertEqual(run.call_args.args[0][-1], "HEAD")
        self.assertNotIn("fetch", run.call_args.args[0])

    def test_git_absent_failed_or_timed_out_does_not_prevent_startup(self):
        for error in (FileNotFoundError(), subprocess.CalledProcessError(128, "git"),
                      subprocess.TimeoutExpired("git", 2)):
            with self.subTest(error=type(error).__name__), patch.object(subprocess, "run", side_effect=error):
                self.assertIsNone(FILES.read_deployed_commit())

    def test_invalid_or_incomplete_metadata_is_not_reported_as_a_commit(self):
        for output in ("", "not-a-hash\0message", "a" * 40 + "\0", "a" * 40 + " message"):
            with self.subTest(output=output), patch.object(subprocess, "run", return_value=SimpleNamespace(stdout=output)):
                self.assertIsNone(FILES.read_deployed_commit())


class StartupNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def notify(self, commit):
        queue = Mock()
        with patch.object(FILES, "read_deployed_commit", return_value=commit), \
             patch.object(SENDER, "message_sender_loop", AsyncMock()), patch.object(SENDER, "add_msg", queue):
            await SENDER._start_message_sender_loop()
            await asyncio.sleep(0)
        queue.assert_called_once()
        self.assertEqual(queue.call_args.kwargs, {"msg_type": "private", "to_id": SENDER.confs["QQBot"]["super_qid"]})
        message = Message(SENDER._stringify_message_content(queue.call_args.args[0]))
        self.assertEqual([segment.type for segment in message], ["text"])
        return message.extract_plain_text()

    async def test_notification_contains_revision_and_literal_message(self):
        commit = {"hash": "b" * 40, "message": "fix: metadata\n\nKeep [CQ:at,qq=all] literal."}
        text = await self.notify(commit)
        self.assertEqual(text, f"HOK_QQBot 已启动成功\nCommit: {commit['hash']}\nMessage: {commit['message']}")

    async def test_unavailable_metadata_keeps_startup_notice(self):
        text = await self.notify(None)
        self.assertIn("HOK_QQBot 已启动成功", text)
        self.assertIn("版本信息：不可用", text)


if __name__ == "__main__":
    unittest.main()

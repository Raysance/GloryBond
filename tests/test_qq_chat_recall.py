"""Recall notices cancel only live work owned by the triggering QQ message."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from nonebot.adapters.onebot.v11.event import FriendRecallNoticeEvent, GroupRecallNoticeEvent
from local_debugger import import_hok_module
from qq_agent.inflight import ChatRollouts


CHAT = import_hok_module("event_handlers.chat")
FUNCS = import_hok_module("zfunc")


def message(**changes):
    return SimpleNamespace(**{"self_id": 300, "user_id": 101, "group_id": 200, "message_id": 42, **changes})


def recall(**changes):
    values = {"time": 1, "self_id": 300, "post_type": "notice", "notice_type": "group_recall",
              "user_id": 101, "group_id": 200, "operator_id": 101, "message_id": 42, **changes}
    if values["notice_type"] == "friend_recall":
        values.pop("group_id", None)
        values.pop("operator_id", None)
        return FriendRecallNoticeEvent.model_validate(values)
    return GroupRecallNoticeEvent.model_validate(values)


class RecallTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rollouts = ChatRollouts()
        patcher = patch.object(CHAT, "live_chat_rollouts", self.rollouts)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_group_and_private_notices_cancel_only_the_matching_message(self):
        for group in (200, None):
            event = message()
            event.group_id = group
            started = asyncio.Event()
            stopped = asyncio.Event()

            async def work():
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            job = asyncio.create_task(self.rollouts.run(CHAT.chat_message_key(event), work))
            await asyncio.wait_for(started.wait(), 2)
            kind = "group_recall" if group else "friend_recall"
            for mismatch in ({"self_id": 301}, {"user_id": 102}, {"message_id": 43},
                             {"notice_type": "friend_recall" if group else "group_recall"},
                             *([{"group_id": 201}] if group else [])):
                self.assertFalse(CHAT.cancel_recalled_chat(recall(**{"notice_type": kind, **mismatch})))
                self.assertFalse(job.done())
            self.assertTrue(CHAT.cancel_recalled_chat(recall(notice_type=kind, operator_id=999)))
            self.assertIsNone(await asyncio.wait_for(job, 2))
            self.assertTrue(stopped.is_set())
            self.assertEqual(self.rollouts.active, {})
            self.rollouts.recalled.clear()

    async def test_recall_before_registration_skips_all_preparation_and_is_bounded(self):
        operation = AsyncMock()
        with patch("qq_agent.inflight.time", SimpleNamespace(monotonic=lambda: 10)):
            CHAT.cancel_recalled_chat(recall())
            await self.rollouts.run(CHAT.chat_message_key(message()), operation)
            operation.assert_not_awaited()
            for identifier in range(3000):
                self.rollouts.recall(("other", identifier))
            self.assertEqual(len(self.rollouts.recalled), 2048)
        with patch("qq_agent.inflight.time", SimpleNamespace(monotonic=lambda: 311)):
            await self.rollouts.run(CHAT.chat_message_key(message()), operation)
            operation.assert_awaited_once()
            self.assertEqual(self.rollouts.recalled, {})

    async def test_another_message_by_the_same_user_continues(self):
        started = asyncio.Queue()
        release = asyncio.Event()

        async def work(identifier):
            started.put_nowait(identifier)
            await release.wait()
            return identifier

        first = message()
        second = message()
        second.message_id = 43
        jobs = [asyncio.create_task(self.rollouts.run(CHAT.chat_message_key(event),
            lambda identifier=event.message_id: work(identifier))) for event in (first, second)]
        await asyncio.wait_for(started.get(), 2)
        await asyncio.wait_for(started.get(), 2)
        CHAT.cancel_recalled_chat(recall())
        self.assertIsNone(await asyncio.wait_for(jobs[0], 2))
        self.assertFalse(jobs[1].done())
        release.set()
        self.assertEqual(await asyncio.wait_for(jobs[1], 2), 43)

    async def test_repeated_recall_does_not_cancel_cleanup_a_second_time(self):
        started, cleaning, release = (asyncio.Event() for _ in range(3))

        async def work():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()

        job = asyncio.create_task(self.rollouts.run(CHAT.chat_message_key(message()), work))
        await asyncio.wait_for(started.wait(), 2)
        CHAT.cancel_recalled_chat(recall())
        await asyncio.wait_for(cleaning.wait(), 2)
        CHAT.cancel_recalled_chat(recall())
        release.set()
        self.assertIsNone(await asyncio.wait_for(job, 2))

    async def test_shutdown_cancellation_propagates_without_becoming_a_recall(self):
        started = asyncio.Event()

        async def work():
            started.set()
            await asyncio.Event().wait()

        job = asyncio.create_task(self.rollouts.run(CHAT.chat_message_key(message()), work))
        await asyncio.wait_for(started.wait(), 2)
        job.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await job
        self.assertEqual(self.rollouts.active, {})

    async def test_cleanup_error_after_recall_does_not_become_a_failure_reply(self):
        started = asyncio.Event()

        async def work():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                raise RuntimeError("cancelled trace storage failed")

        job = asyncio.create_task(self.rollouts.run(CHAT.chat_message_key(message()), work))
        await asyncio.wait_for(started.wait(), 2)
        CHAT.cancel_recalled_chat(recall())
        self.assertIsNone(await asyncio.wait_for(job, 2))

        with self.assertRaisesRegex(RuntimeError, "regular failure"):
            await self.rollouts.run(("unrecalled",), AsyncMock(side_effect=RuntimeError("regular failure")))

    def test_other_notices_and_incomplete_identities_are_ignored(self):
        for event in ({"notice_type": "poke"}, {"notice_type": "group_recall"},
                      {"notice_type": "group_recall", "user_id": 101, "message_id": 42},
                      {"notice_type": "friend_recall", "self_id": 300, "user_id": 101,
                       "group_id": 200, "message_id": 42}):
            self.assertFalse(CHAT.cancel_recalled_chat(event))
        self.assertEqual(self.rollouts.recalled, {})

    async def test_production_handlers_cancel_during_quote_preparation_without_error_reply(self):
        # Execute the real handlers without starting NoneBot or network services.
        source = Path(__file__).parents[1] / "hok/zevent.py"
        tree = ast.parse(source.read_text())
        handlers = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name in {"f_chat", "f_chat_recall"}]
        for handler in handlers:
            handler.decorator_list = []
        env = {"__package__": FUNCS.__package__, "Event": object, "common_expr": {},
               "dmc": SimpleNamespace(use_mem=True), "add_group_poke_task": Mock(), "add_msg": Mock()}
        exec(compile(ast.Module(body=handlers, type_ignores=[]), str(source), "exec"), env)
        started = asyncio.Event()

        async def prepare(*args):
            started.set()
            await asyncio.Event().wait()

        agent = AsyncMock()
        with patch.object(CHAT, "prepare_live_chat_request", side_effect=prepare), \
                patch.object(FUNCS, "agent_chat", agent):
            job = asyncio.create_task(env["f_chat"](SimpleNamespace(get_msg=AsyncMock(), get_forward_msg=AsyncMock()), message()))
            await asyncio.wait_for(started.wait(), 2)
            await env["f_chat_recall"](recall())
            await asyncio.wait_for(job, 2)
        agent.assert_not_awaited()
        env["add_msg"].assert_not_called()
        env["add_group_poke_task"].assert_not_called()

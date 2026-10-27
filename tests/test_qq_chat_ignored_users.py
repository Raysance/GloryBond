"""Durable group ignore controls and early AI-only ingress suppression."""

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agent_runtime import RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.identity import LOCAL_SCOPES
from local_debugger import import_hok_module
from qq_agent.ignored_users import ChatIgnoreArgs, register_chat_ignore_tool
from qq_agent.service import qq_principal


ZFUNC = import_hok_module("zfunc")
CHAT = import_hok_module("event_handlers.chat")
REFERENCES = {"context": {"catalogs": {}}}


def context(user="100", group="200", **metadata):
    principal = qq_principal(user, group, "member", admin_id="999", references=REFERENCES)
    return ToolContext(RunRequest("忽略这个人的AI聊天", "qq_g_200_100", principal, metadata=metadata), AsyncMock())


class SetStore:
    """A Redis set port with independent clients sharing persistent server state."""
    def __init__(self, state=None):
        self.state = {} if state is None else state

    def sadd(self, key, user):
        members = self.state.setdefault(key, set())
        before = len(members)
        members.add(str(user).encode())
        return len(members) - before

    def srem(self, key, user):
        members = self.state.get(key, set())
        existed = str(user).encode() in members
        members.discard(str(user).encode())
        return int(existed)

    def smembers(self, key):
        return set(self.state.get(key, set()))

    def sismember(self, key, user):
        return str(user).encode() in self.state.get(key, set())


class ChatIgnoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = SetStore()

        async def member(**kwargs):
            return {"profile": {"group_id": kwargs["group_id"], "user_id": kwargs["user_id"]}}

        self.reader = AsyncMock(side_effect=member)
        for item in (patch.object(ZFUNC.dmc, "redis_deamon", self.redis),
                     patch.object(ZFUNC, "agent_read_group_member_profile", self.reader),
                     patch.object(ZFUNC, "qid2nick", side_effect=lambda user: "成员" + user)):
            item.start()
            self.addCleanup(item.stop)
        self.registry = ToolRegistry()
        register_chat_ignore_tool(self.registry, operation=ZFUNC.agent_chat_ignore_operation)

    async def call(self, arguments, ctx=None, *, disclose=True):
        ctx = ctx or context()
        if disclose:
            ctx.disclosed.add("manage_chat_ignored_users")
        return await execute(self.registry, {"id": "ignore", "function": {
            "name": "manage_chat_ignored_users", "arguments": json.dumps(arguments)}}, ctx)

    async def test_all_group_members_can_manage_shared_persistent_state_and_undo(self):
        result = await self.call({"action": "ignore", "user_id": "102"})
        self.assertTrue(result.ok)
        self.assertTrue(result.data["changed"])
        self.assertTrue(ZFUNC.is_agent_chat_ignored("102", "200"))
        self.assertFalse(ZFUNC.is_agent_chat_ignored("102", "201"))
        self.assertFalse(ZFUNC.is_agent_chat_ignored("102"))
        self.assertEqual(set(self.redis.state), {"hok:chat:ignored_users:200"})
        self.reader.assert_any_await(group_id="200", user_id="100", include_avatar=False)
        self.reader.assert_any_await(group_id="200", user_id="102", include_avatar=False)

        # A different client after runtime restart reads the same durable set.
        with patch.object(ZFUNC.dmc, "redis_deamon", SetStore(self.redis.state)):
            self.assertTrue(ZFUNC.is_agent_chat_ignored("102", "200"))
            listed = await self.call({"action": "list"}, context(user="101"))
            self.assertEqual(listed.data["users"], [{"user_id": "102", "name": "成员102"}])
            self.reader.reset_mock()
            restored = await self.call({"action": "unignore", "user_id": "102"}, context(user="101"))
            self.assertTrue(restored.ok)
            self.assertFalse(restored.data["ignored"])
            self.reader.assert_awaited_once_with(group_id="200", user_id="101", include_avatar=False)
            self.assertFalse(ZFUNC.is_agent_chat_ignored("102", "200"))

    async def test_repeated_changes_are_idempotent_and_other_group_is_untouched(self):
        args = {"action": "ignore", "user_id": "102"}
        self.assertTrue((await self.call(args)).data["changed"])
        self.assertFalse((await self.call(args)).data["changed"])
        empty = await self.call({"action": "list"}, context(group="201"))
        self.assertEqual(empty.data["users"], [])
        await self.call({"action": "unignore", "user_id": "102"}, context(group="201"))
        self.assertTrue(ZFUNC.is_agent_chat_ignored("102", "200"))

    async def test_scope_is_group_only_and_requires_disclosure(self):
        self.assertNotIn("qq.chat.ignore.manage", LOCAL_SCOPES)
        self.assertIn("qq.chat.ignore.manage", context().principal.scopes)
        for user in ("100", "999"):
            self.assertNotIn("qq.chat.ignore.manage", context(user=user, group=None).principal.scopes)
            self.assertFalse((await self.call({"action": "list"}, context(user=user, group=None))).ok)
        self.assertFalse((await self.call({"action": "list"}, disclose=False)).ok)
        self.reader.assert_not_awaited()

    async def test_forged_delivery_background_and_extra_identity_fields_are_rejected(self):
        bad = [context(origin="background"), context(automation_rule_id="rule")]
        for delivery in ({"platform": "web", "channel": "group", "recipient_id": "200"},
                         {"platform": "qq", "channel": "group", "recipient_id": "201"}):
            ctx = context()
            ctx.request = replace(ctx.request, principal=replace(ctx.principal, attributes={
                **ctx.principal.attributes, "delivery": delivery}))
            bad.append(ctx)
        for ctx in bad:
            self.assertFalse((await self.call({"action": "ignore", "user_id": "102"}, ctx)).ok)
        for extra in ({"group_id": "201"}, {"owner_id": "999"}, {"destination": "201"}):
            self.assertFalse((await self.call({"action": "ignore", "user_id": "102", **extra})).ok)
        self.reader.assert_not_awaited()
        self.assertEqual(self.redis.state, {})

    async def test_member_lookup_failure_or_mismatch_never_changes_state(self):
        for failed_user in ("100", "102"):
            async def mismatch(**kwargs):
                return {"profile": {"group_id": "201" if kwargs["user_id"] == failed_user else "200",
                                     "user_id": kwargs["user_id"]}}
            self.reader.side_effect = mismatch
            with self.subTest(failed_user=failed_user):
                self.assertFalse((await self.call({"action": "ignore", "user_id": "102"})).ok)
                self.assertEqual(self.redis.state, {})
        self.reader.side_effect = ValueError("not a member")
        self.assertFalse((await self.call({"action": "list"})).ok)

    async def test_ignored_entry_stops_before_quote_parsing_and_model_start(self):
        await self.call({"action": "ignore", "user_id": "102"})
        event = SimpleNamespace(get_user_id=lambda: "102", group_id=200)
        with patch.object(CHAT, "prepare_chat_request") as prepare, \
             patch.object(CHAT, "read_quoted_message", new=AsyncMock()) as quote, \
             patch.object(ZFUNC, "agent_runtime_start", new=AsyncMock()) as start:
            self.assertIsNone(await CHAT.prepare_live_chat_request(event, {}, True, AsyncMock(), AsyncMock()))
            prepare.assert_not_called()
            quote.assert_not_awaited()
            self.assertEqual(await ZFUNC.agent_chat(user_id="102", group_id="200", user_text="hello"), {"ignored": True})
            start.assert_not_awaited()

    async def test_private_other_group_and_restored_user_still_reach_chat(self):
        await self.call({"action": "ignore", "user_id": "102"})
        service = SimpleNamespace(chat=AsyncMock(return_value={"text": "reply"}))
        with patch.object(ZFUNC, "agent_runtime_start", new=AsyncMock(return_value=service)):
            for group in (None, "201"):
                self.assertEqual(await ZFUNC.agent_chat(user_id="102", group_id=group, user_text="hello"), {"text": "reply"})
            await self.call({"action": "unignore", "user_id": "102"})
            self.assertEqual(await ZFUNC.agent_chat(user_id="102", group_id="200", user_text="hello"), {"text": "reply"})
        self.assertEqual(service.chat.await_count, 3)

    async def test_business_functions_cannot_reenter_ignore_management(self):
        from agent_console.function_calls import FunctionArgs, FunctionCatalog

        async def recursive(args, ctx):
            return await ZFUNC.agent_chat_ignore_operation({"action": "list"}, ctx)

        catalog = FunctionCatalog()
        catalog.register(name="query_ignore", description="test", category="test",
                         args_model=FunctionArgs, handler=recursive)
        ctx = context()
        catalog.describe("query_ignore", ctx)
        with self.assertRaisesRegex(RuntimeError, "禁止重新进入"):
            await catalog.call("query_ignore", {}, ctx)
        self.reader.assert_not_awaited()

    def test_argument_schema_requires_explicit_targets_and_rejects_injected_scope(self):
        for args in ({"action": "ignore"}, {"action": "unignore"}, {"action": "list", "user_id": "102"},
                     {"action": "ignore", "user_id": "all"}, {"action": "ignore", "user_id": "102", "group_id": "201"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ChatIgnoreArgs.model_validate(args)


if __name__ == "__main__":
    unittest.main()

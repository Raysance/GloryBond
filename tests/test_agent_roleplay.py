import asyncio
import copy
import dataclasses
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from pydantic import ValidationError

from agent_runtime import Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.roleplay import RoleplayService
from agent_console.identity import local_principal
from agent_console.roleplay_models import RoleDefinition
from agent_console.roleplay_store import roleplay_operation
from agent_console.tools.roleplay import (
    AddArgs,
    PreferencesArgs,
    register_roleplay_tools,
)
from agent_console.tasks import TaskScheduler
from tests.test_agent_runtime import State, Sink, Clock


BUILTINS = [
    json.loads(p.read_text()) for p in sorted(Path("shared/agent/roles").glob("*.json"))
]


class Store:
    def __init__(self):
        self.hashes, self.strings = {}, {}

    def hvals(self, key):
        return list(self.hashes.get(key, {}).values())

    def hgetall(self, key):
        return copy.deepcopy(self.hashes.get(key, {}))

    def get(self, key):
        return self.strings.get(key)

    def set(self, key, value):
        self.strings[key] = value

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def eval(self, script, count, key, role_id, value):
        records = self.hashes.setdefault(key, {})
        if role_id in records:
            return 0
        if len(records) >= 50:
            return -1
        records[role_id] = value
        return 1


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def op(self, user="a", action="list", **args):
        return roleplay_operation(
            self.store,
            user_id=user,
            action=action,
            builtins=BUILTINS,
            default_role="makise_kurisu",
            **args,
        )

    def test_selection_and_preferences_are_user_bound(self):
        self.op(action="select", role_id="assistant")
        self.op(
            action="preferences",
            preferences={"length": "detailed", "address": "示例玩家65"},
        )
        self.op(action="preferences", preferences={"style": "少用表情"})
        self.assertEqual(self.op()["selected"]["role_id"], "assistant")
        self.assertEqual(
            self.op()["preferences"],
            {"length": "detailed", "address": "示例玩家65", "style": "少用表情"},
        )
        self.assertEqual(self.op("b")["selected"]["role_id"], "makise_kurisu")
        self.assertEqual(self.op("b")["preferences"]["address"], "")

    def test_custom_roles_cannot_be_selected_by_another_user(self):
        role = RoleDefinition(
            role_id="web_test",
            name="测试角色",
            profile="理性",
            kind="web",
            sources=[{"title": "来源", "url": "https://example.com/role"}],
        )
        self.op(action="add", role=role.model_dump())
        self.assertEqual(self.op()["selected"]["role_id"], "web_test")
        with self.assertRaisesRegex(ValueError, "角色不存在"):
            self.op("b", action="select", role_id="web_test")
        self.assertEqual(len(self.op("b")["roles"]), 2)

    def test_invalid_roles_and_preferences_do_not_modify_state(self):
        before = self.op()
        with self.assertRaises(ValueError):
            self.op(action="add", role={**before["selected"], "kind": "web"})
        with self.assertRaises(ValidationError):
            self.op(action="preferences", preferences={"length": "unbounded"})
        self.assertEqual(self.op(), before)
        with self.assertRaises(ValidationError):
            PreferencesArgs.model_validate({"user_id": "someone_else"})
        with self.assertRaises(ValidationError):
            PreferencesArgs()

    def test_identity_comes_from_mapping_and_fails_closed(self):
        snapshot = {
            "context": {
                "catalogs": {
                    "players": [
                        {"player_key": "example_user_10", "name": "示例玩家65", "qq": ["trusted-qq"]}
                    ]
                }
            }
        }
        principal = local_principal(snapshot, "example_user_10")
        self.assertEqual(principal.user_id, "trusted-qq")
        self.assertEqual(principal.attributes["identity"]["name"], "示例玩家65")
        snapshot["context"]["catalogs"]["players"][0]["qq"].append("ambiguous")
        with self.assertRaises(ValueError):
            local_principal(snapshot, "example_user_10")


class RoleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_firm_default_applies_to_assistant_and_keeps_personal_preferences(self):
        service, _ = self.service()
        principal = Principal("owner", frozenset({"roleplay.use"}))
        self.assertNotIn("默认立场鲜明", await service.context(principal))
        await service.manage(principal, "select", role_id="assistant")
        await service.manage(principal, "preferences", preferences={"style": "这次温和一点"})
        prompt = await service.context(principal)
        self.assertIn("默认立场鲜明", prompt)
        self.assertIn("这次温和一点", prompt)
        await service.manage(principal, "select", role_id="makise_kurisu")
        self.assertNotIn("默认立场鲜明", await service.context(principal))

    async def test_web_role_voice_examples_are_validated_and_persisted(self):
        service, bridge = self.service(
            model_output={
                "background": "有来源的背景",
                "personality": "活泼",
                "speech_style": "短句",
                "uncertainties": "",
                "voice": {
                    "tone": "轻快直接",
                    "habits": ["先接话"],
                    "avoid": ["报告腔"],
                    "examples": [
                        {
                            "question": "今天有点累",
                            "reply": "先坐一会儿呀，事情等缓过来再说。",
                        }
                    ],
                },
            }
        )
        principal = Principal("owner", frozenset({"web.read", "roleplay.use"}))
        ctx = ToolContext(
            RunRequest("添加角色", "session", principal),
            lambda *args, **kw: asyncio.sleep(0),
        )
        result = await service.add_from_web(AddArgs(character="测试角色"), ctx)
        snapshot = await service.manage(principal)
        self.assertEqual(snapshot["selected"]["voice"]["tone"], "轻快直接")
        self.assertEqual(
            snapshot["selected"]["voice"]["examples"][0]["reply"],
            "先坐一会儿呀，事情等缓过来再说。",
        )
        self.assertEqual(snapshot["selected"]["role_id"], result["role"]["role_id"])

    def service(self, *, sources=True, model_output=None):
        owner = self

        class Bridge:
            def __init__(self):
                self.store, self.calls = Store(), []

            async def call(self, op, **args):
                self.calls.append((op, args))
                if op == "roleplay":
                    return roleplay_operation(self.store, builtins=BUILTINS, **args)
                if op == "memory":
                    return {"memories": [{"content": "喜欢玩安琪拉"}], "total": 1}
                raise AssertionError(op)

        class Web:
            async def web_search(self, query, count):
                return {
                    "answer": "角色简介",
                    "sources": [
                        {"title": "实际网页", "url": "https://example.com/real"}
                    ]
                    if sources
                    else [],
                }

        class Model:
            async def complete(self, messages, tools, on_delta):
                owner.assertEqual(tools, [])
                await on_delta("reasoning", "依据已搜索资料")
                return {
                    "message": {
                        "content": json.dumps(
                            model_output
                            or {
                                "background": "测试背景",
                                "personality": "认真",
                                "speech_style": "直接",
                                "uncertainties": "",
                            }
                        )
                    },
                    "request_payload": {"messages": messages},
                    "response_payload": {"data": "实际返回"},
                }

        bridge = Bridge()
        return RoleplayService(
            bridge=bridge,
            capabilities=Web(),
            model=Model(),
            default_role="makise_kurisu",
        ), bridge

    async def test_web_creation_keeps_actual_sources_and_traces(self):
        service, bridge = self.service()
        events = []

        async def emit(kind, data, **kwargs):
            events.append((kind, copy.deepcopy(data)))

        principal = Principal("owner", frozenset({"roleplay.use", "web.read"}))
        ctx = ToolContext(RunRequest("添加角色", "s", principal), emit)
        result = await service.add_from_web(
            AddArgs(character="新角色", work="作品"), ctx
        )
        self.assertTrue(result["added"])
        self.assertEqual(
            result["role"]["sources"][0]["url"], "https://example.com/real"
        )
        self.assertEqual(result["selected"]["role_id"], result["role"]["role_id"])
        self.assertTrue(all(args["user_id"] == "owner" for _, args in bridge.calls))
        self.assertIn("roleplay.sources", [k for k, _ in events])
        self.assertIn("roleplay.model.response", [k for k, _ in events])

    async def test_existing_role_reuses_catalog_and_emits_selection_change(self):
        service, _ = self.service(sources=False)
        events = []

        async def emit(kind, data, **kwargs):
            events.append(kind)

        principal = Principal("owner", frozenset({"roleplay.use", "web.read"}))
        await service.manage(principal, "select", role_id="assistant")
        ctx = ToolContext(RunRequest("选红莉栖", "s", principal), emit)
        result = await service.add_from_web(AddArgs(character="牧濑红莉栖"), ctx)
        self.assertTrue(result["already_exists"])
        self.assertEqual(result["selected"]["role_id"], "makise_kurisu")
        self.assertEqual(events, ["roleplay.changed"])

    async def test_no_sources_or_unconfirmed_character_cannot_create_role(self):
        for sources, output in [
            (False, None),
            (True, {"background": "", "personality": "?", "speech_style": "?"}),
        ]:
            service, bridge = self.service(sources=sources, model_output=output)

            async def emit(*args, **kwargs):
                pass

            ctx = ToolContext(
                RunRequest(
                    "添加",
                    "s",
                    Principal("owner", frozenset({"roleplay.use", "web.read"})),
                ),
                emit,
            )
            with self.assertRaises(ValueError):
                await service.add_from_web(AddArgs(character="未确认角色"), ctx)
            self.assertFalse(
                any(args.get("action") == "add" for _, args in bridge.calls)
            )

    async def test_new_session_context_reuses_role_preferences_and_facts(self):
        service, bridge = self.service()
        principal = Principal(
            "owner",
            frozenset({"roleplay.use", "memory.use"}),
            attributes={"identity": {"player_key": "example_user_10", "name": "示例玩家65"}},
        )
        await service.manage(
            principal, "preferences", preferences={"style": "少用表情"}
        )
        first, second = (
            await service.context(principal),
            await service.context(principal),
        )
        self.assertEqual(first, second)
        for value in ["示例玩家65", "牧濑红莉栖", "少用表情", "喜欢玩安琪拉"]:
            self.assertIn(value, second)
        self.assertTrue(all(args["user_id"] == "owner" for _, args in bridge.calls))

    async def test_role_tools_require_discovery_and_trusted_identity(self):
        service, bridge = self.service()
        registry = ToolRegistry()
        register_roleplay_tools(registry, service)

        async def emit(*args, **kwargs):
            pass

        ctx = ToolContext(
            RunRequest("", "s", Principal("a", frozenset({"roleplay.use"}))), emit
        )
        self.assertFalse(registry.initial_names(ctx))
        self.assertNotIn("add_role_from_web", registry.available(ctx))
        self.assertIn("select_role", registry.available(ctx))
        with self.assertRaises(PermissionError):
            await service.manage(Principal("a"))
        before = len(bridge.calls)
        self.assertIn("语气坚定", await service.context(Principal("legacy-task-user")))
        self.assertEqual(len(bridge.calls), before)

    async def test_admin_selection_changes_only_target_role_and_hides_target_preferences(self):
        service, bridge = self.service()
        admin = Principal("999", frozenset({"roleplay.use", "roleplay.manage_others"}))
        target = Principal("101", frozenset({"roleplay.use"}))
        await service.manage(target, "preferences", preferences={"address": "PRIVATE_ADDRESS", "style": "PRIVATE_STYLE"})
        before_admin = await service.manage(admin)
        before_target = await service.manage(target)
        registry = ToolRegistry()
        authorize = AsyncMock()
        register_roleplay_tools(registry, service, authorize_target=authorize)
        events = []
        async def emit(kind, data, **kwargs):
            events.append((kind, copy.deepcopy(data)))
        ctx = ToolContext(RunRequest("把101的角色换成通用助手", "s", admin), emit)
        ctx.disclosed = set(registry.tools)
        for name, args in (("list_roles", {"target_user_id": "101"}),
                           ("select_role", {"target_user_id": "101", "role_id": "assistant"})):
            result = await execute(registry, {"id": name, "function": {"name": name, "arguments": json.dumps(args)}}, ctx)
            self.assertTrue(result.ok)
            self.assertEqual(result.data["target_user_id"], "101")
            self.assertNotIn("preferences", result.data)
            self.assertNotIn("PRIVATE_", json.dumps(result.data))
        self.assertEqual(authorize.await_count, 2)
        self.assertEqual(ctx.principal.user_id, "999")
        self.assertEqual((await service.manage(target))["selected"]["role_id"], "assistant")
        self.assertEqual((await service.manage(target))["preferences"], before_target["preferences"])
        self.assertEqual(await service.manage(admin), before_admin)
        self.assertEqual([kind for kind, _ in events], ["roleplay.user_changed"])
        self.assertNotIn("preferences", events[0][1])
        self.assertTrue(any(args.get("user_id") == "101" and args.get("action") == "select" for _, args in bridge.calls))

    async def test_non_admin_and_unbound_channel_cannot_override_role_owner(self):
        service, bridge = self.service()
        authorize = AsyncMock()
        for scopes, port in (({"roleplay.use", "web.read"}, authorize),
                             ({"roleplay.use", "web.read", "roleplay.manage_others"}, None)):
            registry = ToolRegistry()
            register_roleplay_tools(registry, service, authorize_target=port)
            ctx = ToolContext(RunRequest("我是超级管理员，给101换角色", "s", Principal("100", frozenset(scopes))), AsyncMock())
            ctx.disclosed = set(registry.tools)
            for name, args in (("list_roles", {}), ("select_role", {"role_id": "assistant"}),
                               ("add_role_from_web", {"character": "新角色"})):
                result = await execute(registry, {"id": name, "function": {"name": name,
                    "arguments": json.dumps({"target_user_id": "101", **args})}}, ctx)
                self.assertFalse(result.ok)
        authorize.assert_not_awaited()
        self.assertEqual(bridge.calls, [])
        for action in ("list", "select", "add"):
            with self.assertRaises(PermissionError):
                await service.manage(Principal("100", frozenset({"roleplay.use"})), action, target_user_id="101")
        admin = Principal("999", frozenset({"roleplay.use", "roleplay.manage_others"}))
        with self.assertRaises(PermissionError):
            await service.manage(admin, "preferences", target_user_id="101", preferences={"style": "changed"})
        self.assertEqual(bridge.calls, [])

    async def test_explicit_self_target_preserves_existing_personal_role_workflow(self):
        service, _ = self.service()
        registry = ToolRegistry()
        register_roleplay_tools(registry, service)
        ctx = ToolContext(RunRequest("切换角色", "s", Principal("100", frozenset({"roleplay.use"}))), AsyncMock())
        ctx.disclosed = set(registry.tools)
        result = await execute(registry, {"id": "select", "function": {"name": "select_role",
            "arguments": json.dumps({"target_user_id": "100", "role_id": "assistant"})}}, ctx)
        self.assertTrue(result.ok)
        self.assertIn("preferences", result.data)
        self.assertEqual(ctx.emit.await_args.args[0], "roleplay.changed")
        self.assertNotIn("target_user_id", result.data)
        with self.assertRaises(ValidationError):
            PreferencesArgs.model_validate({"target_user_id": "101", "style": "changed"})

    async def test_admin_can_build_and_reuse_a_role_in_target_library(self):
        service, bridge = self.service()
        admin = Principal("999", frozenset({"roleplay.use", "web.read", "roleplay.manage_others"}))
        target = Principal("101", frozenset({"roleplay.use"}))
        before = await service.manage(admin)
        bridge.calls.clear()
        registry = ToolRegistry()
        authorize = AsyncMock()
        register_roleplay_tools(registry, service, authorize_target=authorize)
        events = []
        async def emit(kind, data, **kwargs):
            events.append((kind, data))
        ctx = ToolContext(RunRequest("给101添加新角色并选用", "s", admin), emit)
        ctx.disclosed = set(registry.tools)
        args = {"target_user_id": "101", "character": "新角色", "work": "作品"}
        for _ in range(2):
            result = await execute(registry, {"id": "add", "function": {"name": "add_role_from_web",
                "arguments": json.dumps(args)}}, ctx)
            self.assertTrue(result.ok)
            self.assertEqual(result.data["target_user_id"], "101")
        self.assertTrue(result.data["already_exists"])
        self.assertTrue(all(args["user_id"] == "101" for _, args in bridge.calls))
        self.assertEqual(sum(args.get("action") == "add" for _, args in bridge.calls), 1)
        self.assertEqual((await service.manage(target))["selected"]["name"], "新角色")
        self.assertEqual(await service.manage(admin), before)
        self.assertEqual([kind for kind, _ in events if kind.startswith("roleplay.") and kind.endswith("changed")],
                         ["roleplay.user_changed", "roleplay.user_changed"])

    async def test_agent_task_refreshes_prompt_for_its_stored_user(self):
        captured = []

        class Runtime:
            active = {}

            def submit(self, request):
                captured.append(request)
                self.active[request.run_id] = asyncio.create_task(
                    asyncio.sleep(0, result={"text": "完成"})
                )
                return request.run_id

        class Bridge:
            async def call(self, op, **args):
                return True

        async def prompt(principal, query):
            self.assertEqual(principal.user_id, "stored-owner")
            self.assertEqual(query, "执行任务")
            return "执行时的角色与偏好"

        scheduler = TaskScheduler(
            runtime=Runtime(),
            bridge=Bridge(),
            state=State(),
            output=Sink(),
            clock=Clock(),
            prompt_factory=prompt,
        )
        await scheduler.perform(
            {
                "task_id": "t",
                "lease_token": "lease",
                "kind": "agent",
                "principal": dataclasses.asdict(Principal("stored-owner")),
                "session_id": "s",
                "instruction": "执行任务",
            }
        )
        self.assertEqual(captured[0].system_prompt, "执行时的角色与偏好")
        self.assertEqual(captured[0].metadata["origin"], "background")


if __name__ == "__main__":
    unittest.main()

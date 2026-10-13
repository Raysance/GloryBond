import asyncio
import copy
import dataclasses
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from agent_runtime import Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
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
        service, _ = self.service()
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
        self.assertEqual(await service.context(Principal("legacy-task-user")), "")

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

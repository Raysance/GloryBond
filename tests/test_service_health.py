"""No real API calls or QQ deliveries: exercise probes, isolation and routing."""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from local_debugger import import_hok_module


API = import_hok_module("api_adapters.service_health")
BUSINESS = import_hok_module("business.service_health")
FUNCS = import_hok_module("zfunc")
ZAPI = import_hok_module("zapi")
ZDB = import_hok_module("zdb")
ZFILE = import_hok_module("zfile")
QQ = import_hok_module("utils.qq_profiles")
RULES = import_hok_module("event_rules")
with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module("utils.message_sender")
CLIENT = httpx.AsyncClient


class HTTPProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_socks_proxy_listener_uses_tcp_and_closes_connection(self):
        writer = MagicMock(wait_closed=AsyncMock())
        with patch.object(API.asyncio, "open_connection", AsyncMock(return_value=(None, writer))) as connect:
            status, _ = await API.service_health_http(dict(url="socks5h://127.0.0.1:7891", check="proxy"), 1)
        self.assertEqual(status, "reachable")
        connect.assert_awaited_once_with("127.0.0.1", 7891)
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def probe(self, response, **options):
        self.requests, self.clients = [], []

        def transport(request):
            self.requests.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        def client(**kwargs):
            self.clients.append(kwargs)
            return CLIENT(**kwargs, transport=httpx.MockTransport(transport))

        target = dict(url="https://provider.test/v1/models", check="models", api_key="secret-test",
                      model="configured-model", proxy="", **options)
        with patch.object(API.httpx, "AsyncClient", side_effect=client):
            return await API.service_health_http(target, 2)

    async def test_models_checks_auth_and_exact_configured_model_without_generation(self):
        status, detail = await self.probe(httpx.Response(200, json={"data": [{"id": "configured-model"}]}))
        self.assertEqual(status, "ok")
        self.assertIn("生成未测试", detail)
        request = self.requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.headers["Authorization"], "Bearer secret-test")
        self.assertEqual(request.url.path, "/v1/models")
        self.assertFalse(self.clients[0]["trust_env"])
        self.assertFalse(self.clients[0]["follow_redirects"])

    async def test_no_false_positive_for_missing_model_auth_denial_or_server_error(self):
        for response, expected in [(httpx.Response(200, json={"data": []}), "warn"),
                                   (httpx.Response(401), "warn"), (httpx.Response(403), "warn"),
                                   (httpx.Response(429), "warn"), (httpx.Response(503), "error"),
                                   (httpx.Response(200, text="login page"), "warn")]:
            with self.subTest(response=response):
                status, detail = await self.probe(response)
                self.assertEqual(status, expected)
                self.assertNotIn("secret-test", detail)

    async def test_head_is_reachability_only_and_does_not_follow_redirect(self):
        target = dict(url="https://provider.test/", check="reachability", proxy="")
        with patch.object(API.httpx, "AsyncClient", return_value=CLIENT(transport=httpx.MockTransport(
                lambda request: httpx.Response(302, headers={"Location": "https://other.test/"})))):
            status, detail = await API.service_health_http(target, 2)
        self.assertEqual(status, "reachable")
        self.assertIn("业务未验证", detail)

    async def test_disabled_missing_credentials_and_missing_proxy_make_no_requests(self):
        for options in ({"enabled": False}, {"api_key": ""}, {"requires_proxy": True}):
            target = dict(url="https://provider.test/", check="models", api_key="key", proxy="")
            target.update(options)
            with patch.object(API.httpx, "AsyncClient") as client:
                status, _ = await API.service_health_http(target, 2)
            self.assertIn(status, {"skip", "warn"})
            client.assert_not_called()

    async def test_budget_and_unknown_json_structure_are_not_healthy(self):
        for response in (httpx.Response(200, content=b" " * 262145), httpx.Response(200, json=[])):
            self.assertEqual((await self.probe(response))[0], "warn")

    async def test_steam_uses_proxy_and_minimal_read_query(self):
        target = dict(url="https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/",
                      check="steam", api_key="steam-key", proxy="http://proxy.test:7890", requires_proxy=True)
        requests = []

        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"response": {"players": []}})

        def client(**kwargs):
            self.assertEqual(kwargs.pop("proxy"), "http://proxy.test:7890")
            return CLIENT(**kwargs, transport=httpx.MockTransport(transport))

        with patch.object(API.httpx, "AsyncClient", side_effect=client):
            self.assertEqual((await API.service_health_http(target, 2))[0], "ok")
        self.assertEqual(dict(requests[0].url.params), {"key": "steam-key", "steamids": ""})

    async def test_real_web_health_degraded_is_not_healthy(self):
        for reported, expected in (("ok", "ok"), ("degraded", "warn"), ("down", "error")):
            target = dict(url="http://127.0.0.1/health", proxy="", check="web_health")
            with patch.object(API.httpx, "AsyncClient", return_value=CLIENT(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"status": reported})))):
                self.assertEqual((await API.service_health_http(target, 2))[0], expected)


class ServiceCheckTests(unittest.IsolatedAsyncioTestCase):
    async def run_check(self, http_probe=None):
        targets = [dict(name="正常API", category="外部服务"), dict(name="故障API", category="外部服务")]

        async def http(target, timeout):
            if target["name"] == "故障API":
                raise RuntimeError("https://private.test/?key=do-not-disclose")
            return "ok", "最小 API 通过"

        with patch.object(FUNCS, "service_health_config", {"timeout_seconds": 1, "concurrency": 2}), \
             patch.object(FUNCS, "clash_proxy_url", ""), \
             patch.object(FUNCS, "service_health_redis", return_value=("ok", "PING")), \
             patch.object(ZDB, "service_health_ping", return_value=("ok", "SELECT 1")), \
             patch.object(QQ, "service_health_status", AsyncMock(return_value=("ok", "QQ在线"))), \
             patch.object(FUNCS.dmc, "qq_agent_service", None), \
             patch.object(ZFILE, "service_health_systemd", return_value=[("hok-nbot.service", "ok", "active")]), \
             patch.object(BUSINESS, "http_targets", return_value=targets), \
             patch.object(ZAPI, "service_health_http", side_effect=http_probe or http):
            return await FUNCS.service_health_check()

    async def test_failure_isolation_secret_redaction_and_all_categories_survive(self):
        report = "\n".join(await self.run_check())
        for text in ("Redis", "PostgreSQL 业务身份", "PostgreSQL 聊天只读身份", "QQ在线", "正常API", "故障API", "hok-nbot.service"):
            self.assertIn(text, report)
        self.assertIn("RuntimeError", report)
        self.assertNotIn("do-not-disclose", report)
        self.assertNotIn("private.test", report)
        self.assertFalse(FUNCS.dmc.service_health_lock.locked())

    async def test_concurrent_checks_do_not_duplicate_work(self):
        FUNCS.dmc.service_health_lock.acquire()
        try:
            result = await FUNCS.service_health_check()
            self.assertIn("正在进行", result[0])
        finally:
            FUNCS.dmc.service_health_lock.release()

    async def test_timeout_is_reported_and_other_items_complete(self):
        async def timeout(target, seconds):
            raise TimeoutError("secret")

        report = "\n".join(await self.run_check(timeout))
        self.assertIn("超时", report)
        self.assertIn("SELECT 1", report)
        self.assertNotIn("secret", report)

    async def test_cancellation_releases_lock(self):
        entered = asyncio.Event()

        async def paused(target, seconds):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(self.run_check(paused))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(FUNCS.dmc.service_health_lock.locked())

    async def test_total_budget_keeps_completed_results_and_marks_unfinished(self):
        async def slow(target, seconds):
            await asyncio.sleep(10)

        original_wait = asyncio.wait

        async def short_wait(tasks, *, timeout):
            return await original_wait(tasks, timeout=0.05)

        with patch.object(FUNCS.asyncio, "wait", side_effect=short_wait):
            report = "\n".join(await self.run_check(slow))
        self.assertIn("总检查时间已到", report)
        self.assertIn("SELECT 1", report)
        self.assertFalse(FUNCS.dmc.service_health_lock.locked())

    async def test_qq_real_status_and_account_guard(self):
        bot = SimpleNamespace(self_id=str(QQ.confs["QQBot"]["bot_qid"]),
                              call_api=AsyncMock(return_value={"online": True, "good": True}))
        with patch.object(QQ.nonebot, "get_bot", return_value=bot):
            self.assertEqual((await QQ.service_health_status())[0], "ok")
            bot.call_api.assert_awaited_once_with("get_status")
            bot.call_api.return_value = {"online": False, "good": True}
            self.assertEqual((await QQ.service_health_status())[0], "error")
            bot.self_id = "other-bot"
            bot.call_api.reset_mock()
            self.assertEqual((await QQ.service_health_status())[0], "error")
            bot.call_api.assert_not_awaited()

    async def test_only_explicit_admin_command_routes_to_handler(self):
        tree = ast.parse((Path(__file__).parents[1] / "hok/zevent.py").read_text())
        declaration = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == "_service_health" for target in node.targets))
        self.assertEqual(declaration.func.id, "on_fullmatch")
        self.assertEqual(next(x.value.id for x in declaration.keywords if x.arg == "rule"), "judge_super_command")
        commands = ast.literal_eval(declaration.args[0])
        self.assertIn("##health", commands)
        self.assertNotIn("#介绍##health", commands)
        event = SimpleNamespace(get_plaintext=lambda: "##health", get_user_id=lambda: "not-admin")
        self.assertFalse(await RULES.judge_super_command(event))


class SystemProbeTests(unittest.TestCase):
    def test_redis_uses_existing_db0_settings_with_independent_no_retry_pool(self):
        source = SimpleNamespace(connection_class=object, connection_kwargs={"host": "db.test", "db": 0})
        pool, client = MagicMock(), MagicMock()
        client.__enter__.return_value.ping.return_value = True
        with patch.object(FUNCS.dmc, "redis_deamon", SimpleNamespace(connection_pool=source)), \
             patch("redis.ConnectionPool", return_value=pool) as factory, \
             patch("redis.Redis", return_value=client):
            self.assertEqual(FUNCS.service_health_redis(2)[0], "ok")
        self.assertEqual(factory.call_args.kwargs["db"], 0)
        self.assertEqual(factory.call_args.kwargs["socket_timeout"], 2)
        self.assertEqual(factory.call_args.kwargs["socket_connect_timeout"], 2)
        self.assertFalse(factory.call_args.kwargs["retry_on_timeout"])
        pool.disconnect.assert_called_once()

    def test_systemd_reads_only_bot_units_without_host_enumeration(self):
        result = SimpleNamespace(returncode=0, stdout="Id=hok-nbot.service\nLoadState=loaded\nActiveState=active\nSubState=running\n\nId=missing.service\nLoadState=not-found\nActiveState=inactive\nSubState=dead\n")
        with patch("shutil.which", return_value="/bin/systemctl"), patch("subprocess.run", return_value=result) as run:
            report = ZFILE.service_health_systemd(["hok-nbot.service", "missing.service"])
        self.assertEqual({name: status for name, status, _ in report},
                         {"hok-nbot.service": "ok", "missing.service": "warn"})
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["systemctl", "show", "--no-pager",
            "--property=Id,Names,LoadState,ActiveState,SubState", "--", "hok-nbot.service", "missing.service"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_empty_bot_unit_list_does_not_query_host_services(self):
        with patch("shutil.which", return_value="/bin/systemctl"), patch("subprocess.run") as run:
            self.assertEqual(ZFILE.service_health_systemd([]), [])
        run.assert_not_called()

    def test_default_inventory_contains_only_bot_dependencies(self):
        config = FUNCS.confs["ServiceHealth"]
        self.assertEqual(set(config["systemd_units"]), {"hok-nbot.service", "hok-napcat.service",
            "hok-web.service", "hok-temp-files-cleanup.timer", "clash.service", "nginx.service",
            "redis.service", "postgresql-16.service"})
        targets = BUSINESS.http_targets(FUNCS.confs, {}, {}, "", {})
        server_targets = [row for row in targets if row["category"] == "服务器接口"]
        self.assertTrue(any(row["name"] == "HOK 本机 Web" for row in server_targets))
        self.assertFalse(any("个人网站" in row["name"] or "OAuth" in row["name"] for row in targets))

    def test_systemd_unavailable_and_rejects_shell_input(self):
        with patch("shutil.which", return_value=None):
            self.assertEqual(ZFILE.service_health_systemd(["hok-nbot.service"])[0][1], "skip")
        with self.assertRaises(ValueError):
            ZFILE.service_health_systemd(["--all; touch /tmp/bad"])

    def test_postgres_probe_is_readonly_and_bounded(self):
        connection = MagicMock()
        connection.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        with patch("psycopg.connect", return_value=connection) as connect:
            self.assertEqual(ZDB.service_health_ping(timeout=2)[0], "ok")
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], 2)
        self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])
        connection.__enter__.return_value.cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")

    def test_inventory_uses_resolved_endpoints_and_real_proxy_routes(self):
        config = {"Steam": {"api_key": "key"}, "WebService": {"server_domain": "example.test"}}
        targets = BUSINESS.http_targets(config, {"base_url": "https://resolved.test", "proxy_url": "http://modelproxy.test", "api_key": "k", "model": "m"}, {}, "http://clash.test", {})
        by_name = {row["name"]: row for row in targets}
        self.assertEqual(by_name["聊天模型"]["url"], "https://resolved.test/models")
        self.assertEqual(by_name["聊天模型"]["proxy"], "http://modelproxy.test")
        self.assertEqual(by_name["Steam"]["proxy"], "http://clash.test")
        self.assertEqual(by_name["王者营地"]["proxy"], "")
        self.assertEqual(by_name["阿里云搜索"]["proxy"], "")
        self.assertTrue(by_name["APIMart 图片服务"]["requires_proxy"])


class HealthReportTests(unittest.IsolatedAsyncioTestCase):
    def test_report_separates_unverified_and_healthy_into_exactly_two_nodes(self):
        rows = [dict(name=f"服务-{status}", category="依赖", status=status, detail="结果", ms=1)
                for status in ("ok", "error", "warn", "reachable", "skip")]
        nodes = BUSINESS.format_report(rows, 1.2)
        self.assertEqual(len(nodes), 2)
        for status in ("error", "warn", "reachable", "skip"):
            self.assertIn(f"服务-{status}", nodes[0])
            self.assertNotIn(f"服务-{status}", nodes[1])
        self.assertIn("服务-ok", nodes[1])
        self.assertNotIn("服务-ok", nodes[0])
        self.assertIn("不代表已确认故障", nodes[0])

    def test_empty_sections_remain_and_large_reports_are_not_split_or_truncated(self):
        nodes = BUSINESS.format_report([], 0)
        self.assertEqual(len(nodes), 2)
        self.assertIn("无。", nodes[0])
        rows = [dict(name=f"服务{i}", category="依赖", status="ok", detail="正常" * 50) for i in range(60)]
        nodes = BUSINESS.format_report(rows, 1)
        self.assertEqual(len(nodes), 2)
        self.assertIn("服务59", nodes[1])
        self.assertGreater(len(nodes[1]), 2800)

    async def test_health_entry_queues_one_forward_with_two_ordered_nodes(self):
        tree = ast.parse((Path(__file__).parents[1] / "hok/zevent.py").read_text())
        handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "f_service_health")
        handler.decorator_list = []
        namespace = {"__package__": "hok", "MessageEvent": object, "add_msg": MagicMock(), "log_message": MagicMock()}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "health-handler", "exec"), namespace)
        command = import_hok_module("event_handlers.service_health")
        event = SimpleNamespace(group_id=123, user_id=456)
        with patch.object(command, "command_reply", AsyncMock(return_value=["问题服务", "正常服务"])), \
             patch.object(SENDER, "add_forward_msg") as forward:
            await namespace["f_service_health"](event)
        forward.assert_called_once_with(["问题服务", "正常服务"], event=event, title="Bot 服务检查")
        self.assertEqual(namespace["add_msg"].call_count, 1)  # Only the initial progress notice.

    async def test_private_forward_queue_is_consumed_as_chat_records(self):
        queue = MagicMock()
        payload = {"kind": "private_forward", "type": "private", "toid": 456, "messages": []}
        queue.rpop.side_effect = [json.dumps(payload), asyncio.CancelledError()]
        bot = SimpleNamespace(send_private_forward_msg=AsyncMock(return_value={"message_id": 1}))
        with patch.object(SENDER.dmc, "MessageQueue", queue), \
             patch.object(SENDER.dmc, "last_msg_send_ts", 0, create=True), \
             patch.object(SENDER, "MESSAGE_SEND_INTERVAL", 0), \
             patch.object(SENDER.nonebot, "get_bot", return_value=bot):
            with self.assertRaises(asyncio.CancelledError):
                await SENDER.message_sender_loop()
        bot.send_private_forward_msg.assert_awaited_once_with(user_id=456, messages=[])

    async def test_group_and_private_forwards_preserve_destination_and_node_order(self):
        for event, kind, target in ((SimpleNamespace(group_id=123, user_id=456), "group", 123),
                                    (SimpleNamespace(user_id=456), "private", 456)):
            with self.subTest(kind=kind), patch.object(SENDER, "_enqueue_payload") as queue:
                SENDER.add_forward_msg(["问题服务", "正常服务"], event=event, title="Bot 服务检查")
                payload = queue.call_args.args[0]
                self.assertEqual((payload["type"], payload["toid"]), (kind, target))
                self.assertEqual([node["data"]["content"][0]["data"]["text"] for node in payload["messages"]],
                                 ["问题服务", "正常服务"])
                bot = SimpleNamespace(send_group_forward_msg=AsyncMock(return_value={"message_id": 1}),
                                      send_private_forward_msg=AsyncMock(return_value={"message_id": 2}))
                await SENDER._handle_forward_msg(bot, payload)
                sender = getattr(bot, f"send_{kind}_forward_msg")
                sender.assert_awaited_once_with(**{f"{'group' if kind == 'group' else 'user'}_id": target},
                    messages=payload["messages"], source="Bot 服务检查", prompt="Bot 服务检查")
                getattr(bot, f"send_{'private' if kind == 'group' else 'group'}_forward_msg").assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

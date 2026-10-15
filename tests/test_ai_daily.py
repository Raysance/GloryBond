import ast
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from local_debugger import import_hok_module


API = import_hok_module("api_adapters.aihot")
BUSINESS = import_hok_module("business.ai_daily")
FACADE = import_hok_module("zfunc")
ZAPI = import_hok_module("zapi")
with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    SENDER = import_hok_module("utils.message_sender")


def report_fixture():
    item = {"title": "新模型上线", "summary": "支持更长上下文。\n\n仍需关注使用限制。",
            "source": {"name": "官方博客"},
            "links": {"aihot": "https://aihot.news/items/example", "original": "https://example.com/new-model"}}
    return {"date": "2026-10-15", "generatedAt": "2026-10-15T00:00:30Z",
            "windowStart": "2026-10-14T00:00:00Z", "windowEnd": "2026-10-15T00:00:00Z",
            "links": {"aihot": "https://aihot.news/daily/2026-10-15"},
            "lead": {"title": "今日重点", "leadParagraph": "模型、产品与研究更新。"},
            "sections": [{"label": "模型发布/更新", "items": [item]}],
            "flashes": [{"title": "开源框架更新", "source": {"name": "项目博客"},
                         "links": {"original": "https://example.com/framework", "aihot": None},
                         "publishedAt": "2026-10-14T18:30:00Z"}]}


class AihotAdapterTests(unittest.TestCase):
    def test_real_schema_and_transport_with_no_credentials_or_environment_proxy(self):
        session = MagicMock()
        session.__enter__.return_value = session
        response = session.get.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({"schemaVersion": 1, "report": report_fixture()}).encode()]
        with patch.object(API.requests, "Session", return_value=session):
            report = API.aihot_latest_daily()
        self.assertEqual(report["date"], "2026-10-15")
        self.assertFalse(session.trust_env)
        kwargs = session.get.call_args.kwargs
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertTrue(session.get.call_args.args[0].endswith("/api/v1/dailies/latest"))

    def test_rate_limits_and_oversized_responses_do_not_retry(self):
        for status in (429, 503, 302, 404, 200):
            with self.subTest(status=status):
                session = MagicMock()
                session.__enter__.return_value = session
                response = session.get.return_value.__enter__.return_value
                response.status_code = status
                response.headers = {"Retry-After": "120"}
                response.iter_content.return_value = [b"x" * 33]
                with patch.object(API.requests, "Session", return_value=session), \
                     patch.dict(API.ai_daily_config, max_response_bytes=32):
                    with self.assertRaises((RuntimeError, ValueError)):
                        API.aihot_latest_daily()
                session.get.assert_called_once()

    def test_rejects_partial_or_changed_schema_and_inverted_window(self):
        report = report_fixture()
        for key in ("date", "windowStart", "sections", "flashes", "links"):
            bad = copy.deepcopy(report)
            bad.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                API._validate_report({"schemaVersion": 1, "report": bad})
        bad = copy.deepcopy(report)
        bad["sections"][0]["items"][0].pop("summary")
        with self.assertRaises(ValueError):
            API._validate_report({"schemaVersion": 1, "report": bad})
        bad = copy.deepcopy(report)
        bad["windowEnd"] = bad["windowStart"]
        with self.assertRaises(ValueError):
            API._validate_report({"schemaVersion": 1, "report": bad})
        with self.assertRaises(ValueError):
            API._validate_report({"schemaVersion": 2, "report": report})


class DailyLayoutTests(unittest.TestCase):
    def test_first_node_summarizes_every_following_point_with_matching_numbers(self):
        nodes = BUSINESS.build_daily_nodes(report_fixture())
        self.assertTrue(nodes[0].startswith("AI 日报 · 2026-10-15\n\n今日要点"))
        self.assertIn("01｜新模型上线", nodes[0])
        self.assertIn("02｜开源框架更新", nodes[0])
        self.assertTrue(nodes[1].startswith("01｜新模型上线"))
        self.assertTrue(nodes[2].startswith("02｜开源框架更新"))
        self.assertIn("支持更长上下文。", nodes[1])
        self.assertIn("原文：https://example.com/new-model", nodes[1])
        self.assertEqual(len(nodes), 3)
        for metadata in ("AIHOT", "aihot.news", "统计区间", "日报生成", "阅读顺序", "来源：", "发布时间", "今日导读"):
            self.assertNotIn(metadata, "\n".join(nodes))

    def test_duplicate_news_is_not_repeated_as_flash_and_empty_issue_is_explicit(self):
        report = report_fixture()
        report["flashes"].append(copy.deepcopy(report["sections"][0]["items"][0]))
        nodes = BUSINESS.build_daily_nodes(report)
        self.assertEqual(nodes[0].count("01｜"), 1)
        self.assertEqual(nodes[0].count("02｜"), 1)
        self.assertNotIn("03｜", nodes[0])
        self.assertEqual(len(nodes), 3)
        report.update(sections=[], flashes=[], lead=None)
        self.assertEqual(BUSINESS.build_daily_nodes(report), ["AI 日报 · 2026-10-15\n\n今日要点\n\n本期无新增资讯。"])

    def test_large_overview_stays_in_first_node_and_covers_every_full_detail(self):
        report = report_fixture()
        report["flashes"] = []
        item = report["sections"][0]["items"][0]
        report["sections"][0]["items"] = [dict(item, title=f"第{index}项研究" + "完整描述" * 40,
                                                   links={"original": f"https://example.com/{index}"})
                                                  for index in range(1, 21)]
        with patch.dict(BUSINESS.ai_daily_config, node_max_chars=400):
            nodes = BUSINESS.build_daily_nodes(report)
        self.assertLessEqual(len(nodes[0]), 400)
        self.assertEqual(nodes[0].count("｜"), 20)
        self.assertIn("20｜第20项研究", nodes[0])
        for index, item in enumerate(report["sections"][0]["items"], 1):
            self.assertTrue(nodes[index].startswith(f"{index:02d}｜{item['title']}"))

    def test_long_content_splits_without_losing_body_or_silently_exceeding_budget(self):
        report = report_fixture()
        body = "数据资料" * 1000 + "尾部仍需保留"
        report["sections"][0]["items"][0]["summary"] = body
        with patch.dict(BUSINESS.ai_daily_config, node_max_chars=300):
            nodes = BUSINESS.build_daily_nodes(report)
            self.assertTrue(all(len(text) <= 300 for text in nodes))
            self.assertIn(body, "".join(nodes))
        with patch.dict(BUSINESS.ai_daily_config, max_nodes=2), self.assertRaises(ValueError):
            BUSINESS.build_daily_nodes(report)


class DailyWorkflowTests(unittest.TestCase):
    def setUp(self):
        patches = [patch.object(BUSINESS, "current_epoch_seconds", return_value=1792026000),
                   patch.object(FACADE, "forward_delivery_status", return_value=None),
                   patch.object(ZAPI, "aihot_latest_daily", return_value=report_fixture()),
                   patch.object(SENDER, "add_group_forward_msg", return_value=1)]
        self.clock, self.status, self.api, self.enqueue = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def test_today_is_queued_once_as_one_forward_to_configured_group(self):
        result = BUSINESS.ai_daily_check_and_push()
        self.assertEqual(result["status"], "queued")
        self.enqueue.assert_called_once()
        self.assertEqual(self.enqueue.call_args.kwargs["group_qid"], BUSINESS.confs["QQBot"]["group_qid"])
        self.assertTrue(self.enqueue.call_args.kwargs["delivery_id"].endswith(":2026-10-15"))
        self.assertEqual(len(self.enqueue.call_args.args[0]), 3)

    def test_queued_sent_or_failed_edition_is_not_refetched_after_restart(self):
        for status in ("queued", "sent", "failed"):
            self.status.return_value = status
            self.assertEqual(BUSINESS.ai_daily_check_and_push()["status"], "duplicate")
        self.api.assert_not_called()
        self.enqueue.assert_not_called()

    def test_stale_or_future_issue_does_not_send(self):
        for date in ("2026-10-14", "2026-10-16"):
            self.api.return_value = dict(report_fixture(), date=date)
            with self.assertRaisesRegex(ValueError, "AI_DAILY_STALE"):
                BUSINESS.ai_daily_check_and_push()
        self.enqueue.assert_not_called()

    def test_disabled_does_not_read_state_or_network_and_queue_failure_propagates(self):
        with patch.dict(BUSINESS.ai_daily_config, enabled=False):
            self.assertEqual(BUSINESS.ai_daily_check_and_push()["status"], "disabled")
        self.api.assert_not_called()
        self.status.assert_not_called()
        self.enqueue.side_effect = RuntimeError("redis unavailable")
        with self.assertRaisesRegex(RuntimeError, "redis unavailable"):
            BUSINESS.ai_daily_check_and_push()

    def test_concurrent_reservation_loser_is_reported_as_duplicate(self):
        self.enqueue.return_value = 0
        self.assertEqual(BUSINESS.ai_daily_check_and_push()["status"], "duplicate")


class ForwardDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def test_external_cq_is_only_text_and_sender_is_configured_bot(self):
        text = "内容[CQ:at,qq=all][CQ:image,file=https://untrusted.example/a.png]"
        with patch.object(SENDER, "_enqueue_payload", return_value=1) as queue:
            SENDER.add_group_forward_msg([text], group_qid="123")
        node = queue.call_args.args[0]["messages"][0]["data"]
        self.assertEqual(node["uin"], str(SENDER.confs["QQBot"]["bot_qid"]))
        self.assertEqual(node["content"], [{"type": "text", "data": {"text": text}}])

    async def test_records_only_confirmed_success_and_contains_adapter_failures(self):
        for response in ({"message_id": 123}, {}, RuntimeError("QQ rejected")):
            bot = SimpleNamespace(send_group_forward_msg=AsyncMock())
            if isinstance(response, Exception):
                bot.send_group_forward_msg.side_effect = response
            else:
                bot.send_group_forward_msg.return_value = response
            with patch.object(FACADE, "finish_forward_delivery") as finish, patch.object(SENDER, "add_msg") as notice:
                await SENDER._handle_group_forward(bot, {"toid": 123, "messages": [], "delivery_id": "test"})
                expected = "sent" if response == {"message_id": 123} else "failed"
                finish.assert_called_once_with("test", expected)
                self.assertEqual(notice.call_count, 0 if expected == "sent" else 1)

    async def test_state_or_admin_notice_failure_never_resends_or_escapes(self):
        bot = SimpleNamespace(send_group_forward_msg=AsyncMock(side_effect=TimeoutError("unknown outcome")))
        with patch.object(FACADE, "finish_forward_delivery", side_effect=RuntimeError("redis unavailable")), \
             patch.object(SENDER, "add_msg", side_effect=RuntimeError("queue unavailable")):
            await SENDER._handle_group_forward(bot, {"toid": 123, "messages": [], "delivery_id": "test"})
        bot.send_group_forward_msg.assert_awaited_once()

    async def test_failed_forward_does_not_block_the_next_ordinary_message(self):
        bot = SimpleNamespace(send_group_forward_msg=AsyncMock(side_effect=RuntimeError("QQ rejected")),
                              send_group_msg=AsyncMock())
        queue = MagicMock()
        queue.rpop.side_effect = [json.dumps({"kind": "group_forward", "toid": 123, "messages": [], "delivery_id": "test"}),
                                 json.dumps({"type": "group", "toid": 123, "content": "后续消息"}),
                                 asyncio.CancelledError()]
        with patch.object(SENDER.dmc, "MessageQueue", queue), \
             patch.object(SENDER.dmc, "last_msg_send_ts", 0, create=True), \
             patch.object(SENDER, "MESSAGE_SEND_INTERVAL", 0), \
             patch.object(SENDER.nonebot, "get_bot", return_value=bot), \
             patch.object(FACADE, "finish_forward_delivery"), patch.object(SENDER, "add_msg"):
            with self.assertRaises(asyncio.CancelledError):
                await SENDER.message_sender_loop()
        bot.send_group_msg.assert_awaited_once()
        self.assertEqual(str(bot.send_group_msg.call_args.kwargs["message"]), "后续消息")

    def test_reservation_and_message_are_one_atomic_db0_operation(self):
        store = MagicMock()
        with patch.object(FACADE.dmc, "redis_deamon", store):
            FACADE.enqueue_forward_message({"kind": "group_forward"}, delivery_id="ai_daily:123:2026-10-15", ttl=604800)
        store.eval.assert_called_once()
        args = store.eval.call_args.args
        self.assertEqual(args[1], 2)
        self.assertEqual(args[2], "hok:message:forward:delivery:ai_daily:123:2026-10-15")
        self.assertEqual(args[3], "hok:queue:message:outbound")
        self.assertEqual(json.loads(args[4]), {"kind": "group_forward"})

    async def test_scheduler_registers_single_beijing_cron_and_runs_business_off_loop(self):
        source = Path("hok/zscheduler.py").read_text()
        tree = ast.parse(source)
        job = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "ai_daily_push")
        from apscheduler.triggers.cron import CronTrigger
        registered = []
        def register(*args, **kwargs):
            registered.append((args, kwargs))
            return lambda fn: fn
        scope = {"__package__": "hok", "ai_daily_config": BUSINESS.ai_daily_config,
                 "scheduler": SimpleNamespace(scheduled_job=register), "asyncio": asyncio,
                 "confs": BUSINESS.confs, "log_message": MagicMock(), "add_msg": MagicMock()}
        exec(compile(ast.Module(body=[job], type_ignores=[]), "hok/zscheduler.py", "exec"), scope)
        args, kwargs = registered[0]
        trigger = CronTrigger(hour=kwargs["hour"], minute=kwargs["minute"], timezone=kwargs["timezone"])
        self.assertEqual(str(trigger.timezone), "Asia/Shanghai")
        self.assertIn("hour='9'", str(trigger))
        self.assertEqual(args, ("cron",))
        self.assertEqual(kwargs["max_instances"], 1)
        self.assertEqual(kwargs["id"], "ai_daily_push")
        with patch.object(asyncio, "to_thread", new_callable=AsyncMock, return_value={"status": "queued"}) as run:
            await scope["ai_daily_push"]()
            run.assert_awaited_once_with(FACADE.ai_daily_check_and_push)
        with patch.object(asyncio, "to_thread", new_callable=AsyncMock, side_effect=RuntimeError("upstream offline")):
            await scope["ai_daily_push"]()
        self.assertEqual(scope["add_msg"].call_args.kwargs["msg_type"], "private")
        self.assertEqual(scope["add_msg"].call_args.kwargs["to_id"], BUSINESS.confs["QQBot"]["super_qid"])


if __name__ == "__main__":
    unittest.main()

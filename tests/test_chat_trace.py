import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from local_debugger import import_hok_module

CHAT = import_hok_module("zchat")
TRACE = import_hok_module("business.chat_trace")
HANDLER = import_hok_module("event_handlers.chat")
FILES = import_hok_module("zfile")
FUNC = import_hok_module("zfunc")
MEMORY = import_hok_module("zmemory")


class Registry:
    artifacts = []

    def schemas(self):
        return []

    def execute(self, name, arguments):
        if name == "fail":
            raise ValueError("query failed")
        return {"observations": [{"ok": True, "rows": [{"score": 9}]}, {"ok": False, "error": "bad SQL"}]}


class TraceTests(unittest.TestCase):
    def run_chat(self, model, **kwargs):
        return CHAT.chat_process(user_text="对比战绩", user_id="1", nickname="A", use_memory=False,
                                 model_caller=model, tool_registry=Registry(), return_artifacts=True, **kwargs)

    def test_batch_errors_private_reasoning_and_budget_are_recorded(self):
        requests = []
        def model(messages, **kwargs):
            requests.append(list(messages))
            if len(requests) > 1:
                self.assertEqual(kwargs["tool_choice"], "none")
                self.assertEqual(len([item for item in messages if item.get("type") == "function_call_output"]), 3)
                return {"content": "已比较", "tool_calls": []}
            calls = [{"call_id": str(n), "name": name, "arguments": '{}'}
                     for n, name in enumerate(["query_game_database", "fail", "skipped"])]
            return {"tool_calls": calls, "reasoning_content": "PRIVATE_REASONING",
                    "output_items": [{"role": "assistant", "reasoning_content": "PRIVATE_REASONING"}]}
        with patch.object(CHAT.dmc, "ChatToolBudget", 2):
            trace = self.run_chat(model)["trace"]
        self.assertEqual(trace["summary"], {"model_calls": 2, "tool_calls": 2, "skipped_calls": 1, "tool_errors": 2})
        self.assertEqual([call["status"] for call in trace["rounds"][0]["tools"]], ["partial", "error", "skipped"])
        self.assertEqual(trace["rounds"][0]["tools"][0]["observation"]["data"]["observations"][0]["rows"][0]["score"], 9)
        self.assertNotIn("PRIVATE_REASONING", json.dumps(trace))
        self.assertIn("PRIVATE_REASONING", json.dumps(requests[-1]))

    def test_round_limit_adds_one_final_request(self):
        calls = []
        def model(messages, **kwargs):
            calls.append(kwargs)
            return {"content": "结束", "tool_calls": [] if kwargs["tool_choice"] == "none" else
                    [{"call_id": str(len(calls)), "name": "lookup", "arguments": '{}'}]}
        with patch.object(CHAT.dmc, "ChatMaxRounds", 2):
            trace = self.run_chat(model)["trace"]
        self.assertEqual(len(calls), 3)
        self.assertEqual(trace["stop_reason"], "round_limit")

    def test_model_error_keeps_previous_observation(self):
        def model(messages, **kwargs):
            if any(item.get("type") == "function_call_output" for item in messages):
                raise RuntimeError("private server /srv/config sk-testsecret11111")
            return {"tool_calls": [{"call_id": "one", "name": "fail", "arguments": 'not JSON'}]}
        with self.assertRaises(CHAT.ChatRunError) as raised:
            self.run_chat(model)
        trace = raised.exception.trace
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["rounds"][0]["tools"][0]["observation"]["error"], "JSONDecodeError")
        self.assertEqual(trace["rounds"][1]["status"], "error")
        self.assertNotIn("sk-testsecret", json.dumps(trace))

    def test_private_tool_contents_and_credentials_are_hidden(self):
        for name in TRACE.PRIVATE_TOOLS:
            value = TRACE.tool_record({"name": name}, {"content": "MEMORYSECRET"},
                                      {"ok": True, "data": "GROUPSECRET"}, start_ms=0, duration_ms=1, executed=True)
            self.assertNotIn("SECRET", json.dumps(value))
        data = TRACE.public_value({"reasoning_content": "THOUGHT", "value": "sk-testsecret111 /srv/config/file PRIVATEKEY"}, secrets=("PRIVATEKEY",))
        self.assertNotIn("THOUGHT", json.dumps(data))
        self.assertNotIn("sk-testsecret", json.dumps(data))
        self.assertNotIn("/srv", json.dumps(data))
        self.assertNotIn("PRIVATEKEY", json.dumps(data))

    def test_expiring_publish_and_failed_storage(self):
        trace = {"kind": "chat_trace", "version": 1, "rounds": [], "question": "你好"}
        with patch.object(FUNC.dmc.redis_deamon, "set", return_value=True) as save:
            url = FUNC.chat_publish_trace(trace)
        token = url.rsplit("=", 1)[1]
        self.assertRegex(token, r"^[a-f0-9]{48}$")
        self.assertIn("/chat-trace?key=", url)
        self.assertEqual(save.call_args.kwargs["ex"], 604800)
        with patch.object(FUNC.dmc.redis_deamon, "set", return_value=False):
            result = FUNC.chat_prepare_reply({"text": "已回答", "trace": trace, "artifacts": []})
        self.assertEqual(result["text"], "已回答")
        self.assertEqual(result["trace_error"], "RuntimeError")


class QuoteTests(unittest.TestCase):
    def event(self, reply=None, group_id=2):
        return SimpleNamespace(reply=reply, group_id=group_id, self_id=10, get_user_id=lambda: "1",
                               original_message=[{"type": "reply", "data": {"id": "9"}}])

    def reply(self, **kwargs):
        return {"message_id": 9, "message_type": "group", "sender": {"user_id": 3, "card": "队友"},
                "message": [{"type": "text", "data": {"text": "这局表现如何"}},
                            {"type": "image", "data": {"url": "https://private-image/"}}], **kwargs}

    def test_adapter_reply_and_fallback_have_same_text_without_media_urls(self):
        adapter = HANDLER.normalize_quoted_message(self.event(self.reply()))
        fallback = HANDLER.normalize_quoted_message(self.event(), self.reply())
        self.assertEqual(adapter, fallback)
        self.assertTrue(adapter["available"])
        self.assertIn("这局表现如何", adapter["text"])
        self.assertIn("image消息", adapter["text"])
        self.assertNotIn("https://", adapter["text"])

    def test_missing_mismatched_or_cross_group_reply_is_unavailable(self):
        for reply in [None, self.reply(group_id=88), self.reply(message_type="private")]:
            self.assertFalse(HANDLER.normalize_quoted_message(self.event(), reply)["available"])
        self.assertFalse(HANDLER.normalize_quoted_message(self.event(), self.reply(message_id=8))["available"])

    def test_quote_is_only_in_current_model_context_not_memory_or_trace(self):
        seen = []
        quote = HANDLER.normalize_quoted_message(self.event(self.reply()))
        def model(messages, **kwargs):
            seen.extend(messages)
            return {"content": "结论"}
        with patch.object(MEMORY.instance, "load_active_chat", return_value=""), \
                patch.object(MEMORY.instance, "save_active_chat") as save:
            result = CHAT.chat_process(user_text="分析引用", user_id="1", nickname="A", quoted_message=quote,
                                       model_caller=model, tool_registry=Registry(), return_artifacts=True)
        self.assertIn("这局表现如何", json.dumps(seen, ensure_ascii=False))
        save.assert_called_once_with("1", "分析引用", "结论")
        self.assertNotIn("这局表现如何", json.dumps(result["trace"], ensure_ascii=False))


class CollageTests(unittest.TestCase):
    def test_multiple_charts_become_one_bounded_png_and_originals_survive(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(FILES, "temp_path", directory):
            artifacts = []
            for number, size in enumerate([(1600, 900), (800, 1200), (1456, 900)]):
                path = Path(directory) / f"chat_plot_{number:032x}.png"
                Image.new("RGB", size, (number * 80, 100, 100)).save(path)
                artifacts.append({"path": str(path)})
            result = FILES.combine_chat_plot_images(artifacts)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["source_count"], 3)
            with Image.open(result[0]["path"]) as image:
                self.assertEqual(image.width, 2400)
                self.assertLess(image.height, 3700)
            self.assertTrue(all(Path(item["path"]).exists() for item in artifacts))
            self.assertTrue(FILES.chat_plot_public_path(result[0]["path"]).startswith("/file_transfer/"))
            self.assertEqual(FILES.chat_plot_public_path("/etc/passwd"), "")


class ChatMessageTests(unittest.TestCase):
    def test_text_chart_and_footer_enqueue_exactly_one_message(self):
        from nonebot.adapters.onebot.v11 import Message

        with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda function: function)):
            sender = import_hok_module("utils.message_sender")
        event = SimpleNamespace(group_id=2)
        with patch.object(sender, "_enqueue_payload") as enqueue:
            sender.add_chat_result_msg({"text": "分析 [CQ:image,file=untrusted]",
                                        "artifacts": [{"path": "/tmp/trusted.png"}],
                                        "trace_url": "https://hok.example.com/chat-trace?key=abc"}, event=event)
        enqueue.assert_called_once()
        payload = enqueue.call_args.args[0]
        message = Message(payload["content"])
        self.assertEqual([part.type for part in message], ["text", "image", "text"])
        self.assertIn("untrusted", message[0].data["text"])
        self.assertIn("运行记录：https://", message[-1].data["text"])
        self.assertEqual(payload["toid"], 2)


if __name__ == "__main__":
    unittest.main()

"""Bilibili input, cache, download bounds and subscription delivery regressions."""

import json
from pathlib import Path
import subprocess
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from local_debugger import import_hok_module

API = import_hok_module("api_adapters.bili_media")
WORKER = import_hok_module("api_adapters.bili_media_worker")
HANDLERS = import_hok_module("event_handlers.bili_video")
RULES = import_hok_module("event_rules")
FILES = import_hok_module("zfile")
ZAPI = import_hok_module("zapi")
ZFUNC = import_hok_module("zfunc")
BUSINESS = import_hok_module("business.bili_video")
BV = "BV1xx411c7mD"
URL = "https://www.bilibili.com/video/" + BV


def event(segments, text="", *, group_id=20001, user_id=10001):
    return SimpleNamespace(original_message=segments, group_id=group_id, self_id=10,
                           get_user_id=lambda: str(user_id), get_plaintext=lambda: text)


def segment(kind, **data):
    return {"type": kind, "data": data}


class BiliReferenceTests(unittest.TestCase):
    def test_text_urls_ids_and_pages_are_normalized_and_deduplicated(self):
        text = f"看这个 {URL}?p=2&share_source=copy，还有 {BV}。https://m.bilibili.com/video/{BV}/"
        self.assertEqual(API.video_references(text), [URL + "?p=2", URL])
        self.assertEqual(API.normalize_video_reference("http://b23.tv/abcd123?share=1"), "https://b23.tv/abcd123")
        self.assertEqual(API.normalize_video_reference("av170001"), "https://www.bilibili.com/video/av170001")

    def test_foreign_urls_credentials_ports_and_invalid_pages_are_rejected(self):
        for value in [f"https://bilibili.com.evil.test/video/{BV}", f"https://evil.test/{BV}",
                      f"https://user:password@www.bilibili.com/video/{BV}", URL + "?p=0",
                      URL + "?p=-1", URL + "?p=1001", URL.replace(".com", ".com:443"),
                      "file:///tmp/" + BV]:
            self.assertIsNone(API.normalize_video_reference(value))
        self.assertEqual(API.video_references(f"https://evil.test/video/{BV}"), [])

    def test_cards_read_only_url_fields_and_ignore_quote_or_forward_content(self):
        card = json.dumps({"meta": {"detail_1": {"qqdocurl": "https://b23.tv/abcd123", "title": BV}}})
        source = event([segment("json", data=card), segment("text", text=URL),
                        segment("reply", id="1", text="BV1aa411c7mD"),
                        segment("forward", content=URL + "?p=3")])
        self.assertEqual(HANDLERS.share_references(source), ["https://b23.tv/abcd123", URL])
        source.original_message = [segment("json", data=json.dumps({"title": BV})),
                                   segment("xml", data=f'<msg url="{URL}?p=2&amp;x=1"/>')]
        self.assertEqual(HANDLERS.share_references(source), [URL + "?p=2"])

    def test_malformed_or_oversized_cards_do_not_crash(self):
        source = event([segment("json", data="{"), segment("xml", data="<!DOCTYPE x><x/>")])
        self.assertEqual(HANDLERS.share_references(source), [])
        source.original_message = [segment("json", data=" " * 33000 + URL)]
        self.assertEqual(HANDLERS.share_references(source), [])

    def test_short_link_redirect_is_checked_before_following(self):
        session = Mock()
        response = Mock(status_code=302, headers={"Location": URL + "?p=2"})
        session.get.return_value.__enter__ = Mock(return_value=response)
        session.get.return_value.__exit__ = Mock(return_value=False)
        with patch.object(API.requests, "Session") as factory:
            factory.return_value.__enter__.return_value = session
            self.assertEqual(API.resolve_video_reference("https://b23.tv/abcd123"), URL + "?p=2")
        session.get.assert_called_once()
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        response.headers["Location"] = "http://127.0.0.1/private"
        with patch.object(API.requests, "Session") as factory:
            factory.return_value.__enter__.return_value = session
            with self.assertRaises(API.BiliVideoError):
                API.resolve_video_reference("https://b23.tv/abcd123")
        self.assertEqual(session.get.call_count, 2)


class BiliCacheTests(unittest.TestCase):
    def test_cache_reuses_completed_video_and_discards_partial_failure(self):
        with TemporaryDirectory() as root, patch.object(FILES, "data_root", root):
            calls = []
            def download(reference, directory, **kwargs):
                calls.append(reference)
                path = Path(directory) / "video.mp4"
                path.write_bytes(b"synthetic video")
                return path
            with patch.object(ZAPI, "download_bili_video", side_effect=download):
                first = FILES.cached_bili_video(URL)
                second = FILES.cached_bili_video(URL)
            self.assertEqual(first, second)
            self.assertEqual(calls, [URL])
            with patch.object(ZAPI, "download_bili_video", side_effect=API.BiliVideoError("timeout")):
                with self.assertRaises(API.BiliVideoError):
                    FILES.cached_bili_video(URL + "?p=2")
            self.assertEqual([path.resolve() for path in (Path(root) / "bili_videos").iterdir()], [first])

    def test_timeout_kills_worker_process_group(self):
        process = Mock(pid=123, returncode=-9)
        process.communicate.side_effect = [subprocess.TimeoutExpired("worker", 1), ("", "")]
        with TemporaryDirectory() as root, patch.object(API.subprocess, "Popen") as popen, \
             patch.object(API.os, "killpg") as kill:
            popen.return_value.__enter__.return_value = process
            with self.assertRaises(API.BiliVideoError) as caught:
                API.download_bili_video(URL, root, timeout_seconds=1)
        self.assertEqual(caught.exception.code, "timeout")
        kill.assert_called_once_with(123, API.signal.SIGKILL)

    def test_download_error_does_not_expose_provider_text(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ('{"ok":false,"code":"https://private.invalid/token"}', None)
        with TemporaryDirectory() as root, patch.object(API.subprocess, "Popen") as popen:
            popen.return_value.__enter__.return_value = process
            with self.assertRaises(API.BiliVideoError) as caught:
                API.download_bili_video(URL, root)
        self.assertNotIn("private.invalid", str(caught.exception))


class BiliCompressionTests(unittest.IsolatedAsyncioTestCase):
    def test_five_minute_budget_is_ten_decimal_megabytes(self):
        request = {"max_size_mb": 90, "max_size_mb_per_5min": 10}
        self.assertEqual(WORKER.video_budget(300, request), 10_000_000)
        self.assertEqual(WORKER.video_budget(150, request), 5_000_000)
        for duration in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                WORKER.video_budget(duration, request)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    async def test_compression_meets_budget_resolution_and_keeps_audio(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
                "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                "-c:a", "aac", str(source)], check=True, timeout=30, capture_output=True)
            request = {"directory": directory, "max_size_mb": 90, "max_height": 480,
                       "max_size_mb_per_5min": 10}
            result = await WORKER.prepare_video(source, request)
            self.assertTrue(result["ok"])
            output = Path(directory) / "video.mp4"
            self.assertLessEqual(output.stat().st_size, 200_000)
            self.assertLess(output.stat().st_size, source.stat().st_size)
            info = json.loads(await WORKER.run_media_command("ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,codec_name,height", "-of", "json", str(output)))
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            self.assertEqual(video["codec_name"], "h264")
            self.assertLessEqual(video["height"], 480)
            self.assertTrue(any(s["codec_type"] == "audio" and s["codec_name"] == "aac" for s in info["streams"]))


class BiliRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_parse_respects_disable_sleep_and_repair(self):
        source = event([segment("text", text=URL)], URL)
        with patch.object(RULES, "check_sleep", new=AsyncMock(return_value=False)), \
             patch.object(RULES.dmc, "repair", False), \
             patch.object(ZFUNC, "get_battle_invisible_disabled_qids", return_value=[]):
            self.assertTrue(await RULES.judge_bili_share(source))
            with patch.object(ZFUNC, "get_battle_invisible_disabled_qids", return_value=["10001"]):
                self.assertFalse(await RULES.judge_bili_share(source))
            with patch.object(RULES, "check_sleep", new=AsyncMock(return_value=True)):
                self.assertFalse(await RULES.judge_bili_share(source))
            with patch.object(RULES.dmc, "repair", True), patch.object(RULES, "judge_unsuper", new=AsyncMock(return_value=True)):
                self.assertFalse(await RULES.judge_bili_share(source))
            with patch.dict(RULES.confs, {"BiliVideo": {"enabled": False}}):
                self.assertFalse(await RULES.judge_bili_share(source))

    async def test_self_and_prefixed_commands_do_not_trigger_download(self):
        self.assertFalse(await RULES.judge_bili_share(event([segment("text", text=URL)], URL, user_id=10)))
        self.assertFalse(await RULES.judge_bili_share(event([segment("text", text=URL)], "#订阅 " + URL)))

    async def test_share_binds_actual_destination_and_reports_safe_failure(self):
        source = event([segment("text", text=URL)], URL)
        with patch.object(ZFUNC, "bili_video_share_message", return_value="[CQ:video,file=file:///tmp/a.mp4]") as download:
            replies = [reply async for reply in HANDLERS.iter_share_replies(source)]
        self.assertEqual(replies, ["[CQ:video,file=file:///tmp/a.mp4]"])
        download.assert_called_once_with(URL, scope="10:group:20001")
        with patch.object(ZFUNC, "bili_video_share_message", side_effect=API.BiliVideoError("size")):
            replies = [reply async for reply in HANDLERS.iter_share_replies(source)]
        self.assertEqual(replies, [API.BiliVideoError.MESSAGES["size"]])


class BiliSubscriptionVideoTests(unittest.TestCase):
    def test_duplicate_share_is_scoped_and_failed_download_can_be_retried(self):
        from tests.test_bili_video_subscription import FakeRedis
        redis = FakeRedis()
        def evaluate(script, count, key, token):
            if redis.get(key) == token and "'del'" in script:
                redis.delete(key)
            return 1
        redis.eval = evaluate
        with patch.object(ZFUNC.dmc, "redis_deamon", redis), \
             patch.object(ZFUNC, "bili_video_download_message", return_value="video") as download:
            self.assertEqual(ZFUNC.bili_video_share_message(URL, scope="group:1"), "video")
            self.assertIsNone(ZFUNC.bili_video_share_message(BV, scope="group:1"))
            self.assertEqual(ZFUNC.bili_video_share_message(URL, scope="group:2"), "video")
            self.assertEqual(download.call_count, 2)
            download.side_effect = API.BiliVideoError("timeout")
            with self.assertRaises(API.BiliVideoError):
                ZFUNC.bili_video_share_message(URL, scope="group:3")
            download.side_effect = None
            self.assertEqual(ZFUNC.bili_video_share_message(URL, scope="group:3"), "video")

    def test_native_video_message_contains_no_cover_or_link(self):
        from nonebot.adapters.onebot.v11 import Message
        with patch.object(FILES, "cached_bili_video", return_value=Path("/tmp/video.mp4")):
            message = Message(ZFUNC.bili_video_download_message(URL))
        self.assertEqual([segment.type for segment in message], ["video"])
        self.assertEqual(message[0].data["file"], "file:///tmp/video.mp4")

    def test_failed_download_or_rejected_queue_keeps_subscription_pending(self):
        from tests.test_bili_video_subscription import FakeRedis
        redis = FakeRedis()
        redis.sadd("hok:bili:seen:123", "old")
        with patch.object(ZFUNC.dmc, "redis_deamon", redis), \
             patch.object(ZFUNC.dmc, "BiliVideoPushEnabled", True, create=True), \
             patch.object(BUSINESS, "_bili_video_subscribers_by_up", return_value={
                 "mid:123": {"up_mid": "123", "up_name": "Test", "subscribers": ["10001"]}}), \
             patch.object(ZAPI, "bilibili_get_user_card", return_value={}), \
             patch.object(ZAPI, "bilibili_search_videos_by_mid", return_value=[{"bvid": BV, "pubdate": 100}]), \
             patch.object(ZFUNC, "_bili_video_send_group_message", return_value=0) as send:
            with patch.object(ZFUNC, "bili_video_download_message", side_effect=API.BiliVideoError("size")):
                result = BUSINESS.bili_video_check_and_push()
            self.assertEqual(result["pushed"], 0)
            send.assert_not_called()
            self.assertFalse(redis.sismember("hok:bili:seen:123", BV))
            with patch.object(ZFUNC, "bili_video_download_message", return_value="video"):
                result = BUSINESS.bili_video_check_and_push()
            self.assertEqual(result["pushed"], 0)
            self.assertFalse(redis.sismember("hok:bili:seen:123", BV))
            self.assertNotIn("hok:lock:bili:video_push", redis.values)

    def test_multiple_latest_videos_are_separate_messages(self):
        with patch.object(ZFUNC, "_bili_video_get_subscriptions", return_value={"1": [
                {"up_mid": "10", "up_name": "First"}, {"up_mid": "20", "up_name": "Second"}]}), \
             patch.object(BUSINESS, "_bili_video_latest_for_item", side_effect=["video1", "video2"]):
            self.assertEqual(BUSINESS.bili_video_latest_for_user("1"), ["video1", "video2"])


if __name__ == "__main__":
    unittest.main()

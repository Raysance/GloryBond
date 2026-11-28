"""Bilibili input, cache, download bounds and subscription delivery regressions."""

import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import asyncio
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tools.debugger import import_project_module

API = import_project_module("glorybond.integrations.bili_media")
WORKER = import_project_module("glorybond.integrations.bili_media_worker")
HANDLERS = import_project_module("glorybond.apps.qq.handlers.bili_video")
RULES = import_project_module("glorybond.apps.qq.rules")
FILES = import_project_module("glorybond.storage.files")
ZAPI = import_project_module("glorybond.integrations.api")
ZFUNC = import_project_module("glorybond.features.facade")
BUSINESS = import_project_module("glorybond.features.subscriptions.bilibili")
BV = "BV1xx411c7mD"
URL = "https://www.bilibili.com/video/" + BV
METADATA = {"title": "标题 [CQ:at,qq=all]", "author": "示例UP", "published_at": 1704067200,
            "duration": 301, "page": 1, "page_count": 1, "part": "正片"}


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
    def test_oversize_verdict_is_reused_expires_and_respects_changed_limits(self):
        with TemporaryDirectory() as root, patch.object(FILES, "data_root", root), \
             patch.object(ZAPI, "download_bili_video", side_effect=API.BiliVideoError("size")) as download:
            for _ in range(2):
                with self.assertRaises(API.BiliVideoError) as caught:
                    FILES.cached_bili_video(URL)
                self.assertEqual(caught.exception.code, "size")
            self.assertEqual(download.call_count, 1)
            marker = next((Path(root) / "bili_videos").glob("*.size-*.json"))
            stamp = marker.stat().st_mtime
            with self.assertRaises(API.BiliVideoError):
                FILES.cached_bili_video(URL)
            self.assertEqual(marker.stat().st_mtime, stamp)
            os.utime(marker, (stamp - 86401, stamp - 86401))
            with self.assertRaises(API.BiliVideoError):
                FILES.cached_bili_video(URL)
            self.assertEqual(download.call_count, 2)
            for config in ({"max_output_size_mb": 60}, {"max_size_mb": 100}):
                with self.assertRaises(API.BiliVideoError):
                    FILES.cached_bili_video(URL, **config)
            self.assertEqual(download.call_count, 4)
            self.assertFalse(list((Path(root) / "bili_videos").glob(".download-*")))

    def test_cache_reuses_completed_video_and_discards_partial_failure(self):
        with TemporaryDirectory() as root, patch.object(FILES, "data_root", root):
            calls = []
            def download(reference, directory, **kwargs):
                calls.append(reference)
                path = Path(directory) / "video.mp4"
                path.write_bytes(b"synthetic video")
                (Path(directory) / "metadata.json").write_text(json.dumps(METADATA))
                return path
            with patch.object(ZAPI, "download_bili_video", side_effect=download):
                first = FILES.cached_bili_video(URL)
                second = FILES.cached_bili_video(URL)
            self.assertEqual(first, second)
            self.assertEqual(calls, [URL])
            self.assertEqual(FILES.read_bili_video_metadata(first), METADATA)
            with patch.object(ZAPI, "download_bili_video", side_effect=API.BiliVideoError("timeout")):
                with self.assertRaises(API.BiliVideoError):
                    FILES.cached_bili_video(URL + "?p=2")
            self.assertEqual(set(path.resolve() for path in (Path(root) / "bili_videos").iterdir()), {first, first.with_suffix(".json")})

    def test_missing_metadata_does_not_publish_an_incomplete_cache_entry(self):
        with TemporaryDirectory() as root, patch.object(FILES, "data_root", root):
            def download(reference, directory, **kwargs):
                path = Path(directory) / "video.mp4"
                path.write_bytes(b"synthetic video")
                return path
            with patch.object(ZAPI, "download_bili_video", side_effect=download), self.assertRaises(API.BiliVideoError):
                FILES.cached_bili_video(URL)
            self.assertEqual(list((Path(root) / "bili_videos").iterdir()), [])

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
    def test_duration_target_never_exceeds_per_video_limit(self):
        request = {"max_size_mb": 90, "target_size_mb_per_5min": 10, "max_output_size_mb": 20}
        self.assertEqual(WORKER.video_budget(300, request), 10_000_000)
        self.assertEqual(WORKER.video_budget(150, request), 5_000_000)
        self.assertEqual(WORKER.video_budget(1200, request), 20_000_000)
        for duration in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                WORKER.video_budget(duration, request)

    async def test_worker_metadata_matches_the_selected_page_and_uses_public_video_object(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"synthetic video")
            credential = asyncio.get_running_loop().create_future()
            credential.set_result(None)
            stream = SimpleNamespace(url="https://cdn.example/video", backup_url=[])
            parser = SimpleNamespace(credential=credential, headers={}, aclose=AsyncMock(),
                                     get_download_streams=AsyncMock(return_value=(stream, None)))
            downloader = SimpleNamespace(head_size=AsyncMock(return_value=15), aclose=AsyncMock(),
                                         download_video=AsyncMock(return_value=source))
            item = SimpleNamespace(get_info=AsyncMock(return_value=SimpleNamespace(
                arc=SimpleNamespace(title="实际标题", author=SimpleNamespace(name="实际作者"), pubdate=1704067200),
                pages=[SimpleNamespace(page=SimpleNamespace(part="第一集", duration=100)),
                       SimpleNamespace(page=SimpleNamespace(part="第二集", duration=301))])))
            video = Mock(return_value=item)
            modules = {
                "nonebot_plugin_parser_lite": SimpleNamespace(configure=Mock()),
                "nonebot_plugin_parser_lite.parsers.bilibili": SimpleNamespace(BilibiliParser=lambda: parser),
                "nonebot_plugin_parser_lite.download": SimpleNamespace(StreamDownloader=lambda: downloader),
                "nonebot_plugin_parser_lite.exception": SimpleNamespace(SizeLimitException=type("SizeLimitException", (Exception,), {})),
                "nonebot_plugin_parser_lite.utils.bilibili.video": SimpleNamespace(Video=video),
            }
            request = {"url": "https://www.bilibili.com/video/av170001?p=2", "directory": directory,
                       "max_height": 480, "max_size_mb": 90, "max_output_size_mb": 50}
            with patch.dict(sys.modules, modules), patch.object(WORKER, "prepare_video", return_value={"ok": True}):
                result = await WORKER.download(request)
            self.assertTrue(result["ok"])
            video.assert_called_once_with(aid=170001, credential=None)
            parser.get_download_streams.assert_awaited_once_with(video=item, page_index=1)
            metadata = json.loads((Path(directory) / "metadata.json").read_text())
            self.assertEqual(metadata, {"title": "实际标题", "author": "实际作者", "published_at": 1704067200,
                                        "duration": 301, "page": 2, "page_count": 2, "part": "第二集"})
            parser.aclose.assert_awaited_once()
            downloader.aclose.assert_awaited_once()

    async def test_size_preflight_skips_bodies_and_unknown_sizes_are_checked_after_download(self):
        for sizes, actual_size, should_download, expected in [
                ([40_000_000, 15_000_000], 1, False, {"ok": False, "code": "size"}),
                ([None, None], 50_000_001, True, {"ok": False, "code": "size"}),
                ([49_000_000, 1_000_000], 50_000_000, True, {"ok": True}),
                ([None, None], 0, True, {"ok": False, "code": "unavailable"})]:
            with self.subTest(sizes=sizes), TemporaryDirectory() as directory:
                source = Path(directory) / "source.mp4"
                with source.open("wb") as file:
                    file.truncate(actual_size)
                credential = asyncio.get_running_loop().create_future()
                credential.set_result(None)
                stream = SimpleNamespace(url="https://cdn.example/video", backup_url=[])
                parser = SimpleNamespace(credential=credential, headers={}, aclose=AsyncMock(),
                    get_download_streams=AsyncMock(return_value=(stream, stream)))
                downloader = SimpleNamespace(head_size=AsyncMock(side_effect=sizes), aclose=AsyncMock(),
                    download_av_and_merge=AsyncMock(return_value=source))
                item = SimpleNamespace(get_info=AsyncMock(return_value=SimpleNamespace(
                    arc=SimpleNamespace(title="Test", author=SimpleNamespace(name="Test"), pubdate=1),
                    pages=[SimpleNamespace(page=SimpleNamespace(part="Test", duration=100))])))
                configure = Mock()
                modules = {
                    "nonebot_plugin_parser_lite": SimpleNamespace(configure=configure),
                    "nonebot_plugin_parser_lite.parsers.bilibili": SimpleNamespace(BilibiliParser=lambda: parser),
                    "nonebot_plugin_parser_lite.download": SimpleNamespace(StreamDownloader=lambda: downloader),
                    "nonebot_plugin_parser_lite.exception": SimpleNamespace(SizeLimitException=type("SizeLimitException", (Exception,), {})),
                    "nonebot_plugin_parser_lite.utils.bilibili.video": SimpleNamespace(Video=lambda **kwargs: item),
                }
                request = {"url": URL, "directory": directory, "max_height": 480,
                           "max_size_mb": 90, "max_output_size_mb": 50}
                with patch.dict(sys.modules, modules), \
                     patch.object(WORKER, "prepare_video", new=AsyncMock(return_value={"ok": True})) as prepare:
                    self.assertEqual(await WORKER.download(request), expected)
                self.assertEqual(prepare.await_count, int(expected["ok"]))
                self.assertEqual(downloader.download_av_and_merge.await_count, int(should_download))
                self.assertEqual(configure.call_args.kwargs["plite_max_size"], 48)
                parser.aclose.assert_awaited_once()
                downloader.aclose.assert_awaited_once()

    async def test_oversized_source_is_not_probed_or_transcoded(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            with source.open("wb") as file:
                file.truncate(50_000_001)
            with patch.object(WORKER, "run_media_command", new=AsyncMock()) as run:
                self.assertEqual(await WORKER.prepare_video(source, {"max_output_size_mb": 50}),
                                 {"ok": False, "code": "size"})
            run.assert_not_awaited()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    async def test_compression_reduces_size_caps_resolution_and_keeps_audio(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
                "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                "-c:a", "aac", str(source)], check=True, timeout=30, capture_output=True)
            request = {"directory": directory, "max_size_mb": 90, "max_height": 480,
                       "target_size_mb_per_5min": 10, "max_output_size_mb": 20}
            result = await WORKER.prepare_video(source, request)
            self.assertTrue(result["ok"])
            output = Path(directory) / "video.mp4"
            self.assertLessEqual(output.stat().st_size, 20_000_000)
            self.assertLess(output.stat().st_size, source.stat().st_size)
            info = json.loads(await WORKER.run_media_command("ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,codec_name,height", "-of", "json", str(output)))
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            self.assertEqual(video["codec_name"], "h264")
            self.assertLessEqual(video["height"], 480)
            self.assertTrue(any(s["codec_type"] == "audio" and s["codec_name"] == "aac" for s in info["streams"]))

    async def test_compatible_source_above_soft_target_does_not_need_transcoding(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            with source.open("wb") as stream:
                stream.truncate(26_800_000)
            request = {"directory": directory, "max_size_mb": 90, "max_height": 480,
                       "target_size_mb_per_5min": 10, "max_output_size_mb": 50}
            info = {"format": {"duration": "300"}, "streams": [
                {"codec_type": "video", "codec_name": "h264", "height": 480, "width": 854},
                {"codec_type": "audio", "codec_name": "aac"}]}
            with patch.object(WORKER, "run_media_command", new=AsyncMock(return_value=json.dumps(info))) as run:
                self.assertTrue((await WORKER.prepare_video(source, request))["ok"])
            self.assertEqual(run.await_count, 1)  # Probe only; no unnecessary encode.
            self.assertEqual((Path(directory) / "video.mp4").stat().st_size, 26_800_000)

    async def test_encoded_video_can_exceed_target_but_never_output_limit(self):
        for encoded_size, expected_ok, expected_encodes in [(11_000_000, True, 1), (20_000_001, False, 2)]:
            with self.subTest(encoded_size=encoded_size), TemporaryDirectory() as directory:
                source = Path(directory) / "source.mp4"
                source.write_bytes(b"synthetic input")
                request = {"directory": directory, "max_size_mb": 90, "max_height": 480,
                           "target_size_mb_per_5min": 10, "max_output_size_mb": 20}
                info = {"format": {"duration": "300"}, "streams": [
                    {"codec_type": "video", "codec_name": "h264", "height": 720, "width": 1280}]}
                async def run(*args):
                    if args[0] == "ffprobe":
                        return json.dumps(info)
                    with Path(args[-1]).open("wb") as stream:
                        stream.truncate(encoded_size)
                    return b""
                with patch.object(WORKER, "run_media_command", new=AsyncMock(side_effect=run)) as media:
                    self.assertEqual((await WORKER.prepare_video(source, request))["ok"], expected_ok)
                self.assertEqual(media.await_count, 1 + expected_encodes)
                self.assertEqual((Path(directory) / "video.mp4").exists(), expected_ok)


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
            download.side_effect = API.BiliVideoError("size")
            self.assertIn(URL, ZFUNC.bili_video_share_message(URL, scope="group:4"))
            self.assertIsNone(ZFUNC.bili_video_share_message(URL, scope="group:4"))

    def test_native_video_keeps_metadata_separate_without_cover_or_link(self):
        from nonebot.adapters.onebot.v11 import Message
        with patch.dict(ZFUNC.confs, {"BiliVideo": {}}), \
             patch.object(FILES, "cached_bili_video", return_value=Path("/tmp/video.mp4")) as download, \
             patch.object(FILES, "read_bili_video_metadata", return_value=METADATA):
            result = ZFUNC.bili_video_download_message(URL)
            message = Message(result.video)
        self.assertEqual([segment.type for segment in message], ["video"])
        self.assertEqual(message[0].data["file"], "file:///tmp/video.mp4")
        self.assertIn("标题：" + METADATA["title"], result.text)
        self.assertIn("作者：示例UP", result.text)
        self.assertIn("发布时间：2024-01-01 08:00:00\n", result.text)
        self.assertNotIn("北京时间", result.text)
        self.assertEqual(download.call_args.kwargs["max_output_size_mb"], 50)
        self.assertIn("时长：5:01", result.text)

    def test_missing_publication_time_stays_unknown_and_pages_are_identified(self):
        text = BUSINESS.format_video_metadata({**METADATA, "published_at": 0, "page": 2, "page_count": 3, "part": "第二集"})
        self.assertIn("发布时间：未知", text)
        self.assertIn("分P：2/3 · 第二集", text)
        self.assertNotIn("1970", text)

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
            with patch.object(ZFUNC, "bili_video_download_message", side_effect=API.BiliVideoError("timeout")):
                report = Mock()
                result = BUSINESS.bili_video_check_and_push(on_error=report)
                report.assert_called_once()
                self.assertIsInstance(report.call_args.args[0], API.BiliVideoError)
            self.assertEqual(result["pushed"], 0)
            send.assert_not_called()
            self.assertFalse(redis.sismember("hok:bili:seen:123", BV))
            with patch.object(ZFUNC, "bili_video_download_message", return_value="video"):
                result = BUSINESS.bili_video_check_and_push()
            self.assertEqual(result["pushed"], 0)
            self.assertFalse(redis.sismember("hok:bili:seen:123", BV))
            self.assertNotIn("hok:lock:bili:video_push", redis.values)

    def test_oversize_link_is_marked_seen_only_after_queue_acceptance(self):
        from nonebot.adapters.onebot.v11 import Message
        from tests.test_bili_video_subscription import FakeRedis
        redis = FakeRedis()
        redis.sadd("hok:bili:seen:123", "old")
        row = {"bvid": BV, "pubdate": 100, "title": "Title [CQ:at,qq=all]", "pic": "https://cdn.example/cover.jpg"}
        with patch.object(ZFUNC.dmc, "redis_deamon", redis), \
             patch.object(ZFUNC.dmc, "BiliVideoPushEnabled", True, create=True), \
             patch.object(BUSINESS, "_bili_video_subscribers_by_up", return_value={
                 "mid:123": {"up_mid": "123", "up_name": "Test", "subscribers": ["10001"]}}), \
             patch.object(ZAPI, "bilibili_get_user_card", return_value={}), \
             patch.object(ZAPI, "bilibili_search_videos_by_mid", return_value=[row]), \
             patch.object(BUSINESS, "_bili_video_page_link", return_value="https://example.test/video"), \
             patch.object(ZFUNC, "bili_video_download_message", side_effect=API.BiliVideoError("size")) as download, \
             patch.object(ZFUNC, "_bili_video_send_group_message", side_effect=[0, 1]) as send:
            failed = Mock()
            self.assertEqual(BUSINESS.bili_video_check_and_push(on_error=failed)["pushed"], 0)
            self.assertFalse(redis.sismember("hok:bili:seen:123", BV))
            self.assertIsInstance(failed.call_args.args[0], RuntimeError)
            failed.reset_mock()
            self.assertEqual(BUSINESS.bili_video_check_and_push(on_error=failed)["pushed"], 1)
            self.assertTrue(redis.sismember("hok:bili:seen:123", BV))
            self.assertEqual(BUSINESS.bili_video_check_and_push(on_error=failed)["pushed"], 0)
            failed.assert_not_called()
            self.assertEqual(download.call_count, 2)
            message = Message(send.call_args.args[0])
            self.assertEqual([part.type for part in message], ["text", "image", "text"])
            self.assertIn(row["title"], message.extract_plain_text())
            self.assertIn("https://example.test/video", message.extract_plain_text())
            self.assertNotIn("北京时间", message.extract_plain_text())

    def test_multiple_latest_videos_are_separate_messages(self):
        with patch.object(ZFUNC, "_bili_video_get_subscriptions", return_value={"1": [
                {"up_mid": "10", "up_name": "First"}, {"up_mid": "20", "up_name": "Second"}]}), \
             patch.object(BUSINESS, "_bili_video_latest_for_item", side_effect=["video1", "video2"]):
            self.assertEqual(BUSINESS.bili_video_latest_for_user("1"), ["video1", "video2"])

    def test_partial_latest_failure_keeps_success_and_reports_the_original_exception(self):
        error = API.BiliVideoError("size")
        report = Mock()
        with patch.object(ZFUNC, "_bili_video_get_subscriptions", return_value={"1": [
                {"up_mid": "10", "up_name": "First"}, {"up_mid": "20", "up_name": "Second"}]}), \
             patch.object(BUSINESS, "_bili_video_latest_for_item", side_effect=[error, "video2"]):
            self.assertEqual(BUSINESS.bili_video_latest_for_user("1", on_error=report), ["video2"])
        report.assert_called_once_with(error)


if __name__ == "__main__":
    unittest.main()

"""Media coverage, cache reuse, provider isolation and quoted-source authorization."""
import asyncio
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

import httpx
from agent_runtime import Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext

from glorybond.agent.media_inputs import MediaLimits, MediaReader, media_settings, prepare_media, media_command
from glorybond.agent.tools.media import ReadMediaArgs, read_local_media, register_media_tool
from glorybond.apps.qq.agent.media import read_qq_media
from tools.debugger import import_project_module

CHAT = import_project_module('glorybond.apps.qq.handlers.chat')

SETTINGS = {'api_key': 'test-secret', 'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash'}


def write_wave(path, seconds):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\0\0' * int(seconds * 16000))


class MediaInputTests(unittest.TestCase):
    def test_native_quoted_media_requires_its_actual_scope(self):
        event = Mock(group_id=10, self_id=30)
        event.reply = {'message_id': 4, 'message_type': 'group', 'sender': {'user_id': 20},
                       'message': [{'type': 'video', 'data': {'url': 'https://cdn.qq.com/video?secret=x',
                                                            'file': 'sent.mp4', 'file_size': '4'}}]}
        self.assertFalse(CHAT.normalize_quoted_message(event)['available'])
        self.assertFalse(CHAT.normalize_quoted_message(event, {**event.reply, 'group_id': 99})['available'])
        quote = CHAT.normalize_quoted_message(event, {**event.reply, 'group_id': 10})
        self.assertTrue(quote['available'])
        self.assertEqual(quote['media_sources'][0]['kind'], 'video')
        self.assertEqual(quote['media_sources'][0]['file_size'], '4')
        self.assertEqual(quote['text'], '[video消息，未读取内容]')
        self.assertEqual(CHAT.media_sources('[CQ:video,file=file:///private]'), [])

    def test_local_symlink_cannot_escape_authorized_directory(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            allowed = root / 'allowed'
            allowed.mkdir()
            secret = root / 'secret.mp4'
            secret.write_bytes(b'private')
            (allowed / 'video.mp4').symlink_to(secret)
            with self.assertRaises(PermissionError):
                read_local_media(str(allowed / 'video.mp4'), (allowed,), 1024)
            with self.assertRaises(ValueError):
                ReadMediaArgs(url='https://example.com/a', attachment_id='a' * 64, question='test')

    def test_official_media_key_is_independent_of_chat_and_vision_keys(self):
        remote = {'public': {'base_url': 'https://third-party.example'},
                  'private': {'api_key': 'chat', 'vision_api_key': 'vision', 'media_api_key': 'official'}}
        self.assertEqual(media_settings(remote)['api_key'], 'official')
        del remote['private']['media_api_key']
        self.assertIsNone(media_settings(remote))


class MediaAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.preparations = 0
        self.model = SimpleModel()
        self.reader = MediaReader(self.tmp.name, SETTINGS, model_factory=Mock(return_value=self.model))
        self.loader = AsyncMock(return_value=b'synthetic owned media')
        self.asr = AsyncMock(side_effect=[{'text': '第一段完整语音', 'duration_ms': 115000},
                                         {'text': '第二段完整语音', 'duration_ms': 9000}])
        self.reader._transcribe = self.asr

    async def prepare(self, source, directory, limits):
        self.preparations += 1
        (directory / 'frame-0000.jpg').write_bytes(b'fake jpeg')
        for i, duration in enumerate((115, 9)):
            write_wave(directory / f'audio-{i:04d}.wav', duration)
        return {'duration_seconds': 124, 'frame_interval_seconds': 10,
                'frames': [{'timestamp': 0, 'file': 'frame-0000.jpg'}],
                'audio_chunks': [{'start': 0, 'duration': 115, 'file': 'audio-0000.wav'},
                                 {'start': 115, 'duration': 9, 'file': 'audio-0001.wav'}],
                'audio_duration_seconds': 124, 'has_audio': True, 'has_video': True}

    async def test_full_transcript_and_frames_go_to_flash_once_across_repeated_questions(self):
        with patch('glorybond.agent.media_inputs.prepare_media', side_effect=self.prepare):
            first, second = await asyncio.gather(*[self.reader.read(source_key='source', loader=self.loader, question='概要') for _ in range(2)])
            followup = await self.reader.read(source_key='source', loader=self.loader, question='详细解释')
        self.loader.assert_awaited_once()
        self.assertEqual(self.preparations, 1)
        self.assertEqual(self.asr.await_count, 2)
        self.assertEqual(self.model.calls, 2)
        self.assertFalse(first['cache_hit'])
        self.assertTrue(second['cache_hit'])
        self.assertEqual(first['new_asr_seconds'], 124)
        self.assertEqual(second['new_asr_seconds'], 0)
        self.assertEqual(second['new_model_usage'], {})
        self.assertEqual(followup['new_asr_seconds'], 0)
        content = self.model.messages[0]['content']
        self.assertIn('第一段完整语音', content[0]['text'])
        self.assertIn('第二段完整语音', content[0]['text'])
        self.assertEqual(content[-1]['type'], 'image_url')
        self.assertEqual(self.reader.model_factory.call_args.kwargs['model'], 'deepseek-flash')
        # A new process/session reader reuses persisted transcripts and answers.
        restored = MediaReader(self.tmp.name, SETTINGS, model_factory=Mock())
        result = await restored.read(source_key='source', loader=AsyncMock(side_effect=AssertionError()), question='概要')
        self.assertTrue(result['cache_hit'])
        restored.model_factory.assert_not_called()

    async def test_failed_segment_never_claims_full_coverage_and_completed_work_is_reused(self):
        self.asr.side_effect = [{'text': '第一段', 'duration_ms': 115000}, ValueError('ASR unavailable')]
        with patch('glorybond.agent.media_inputs.prepare_media', side_effect=self.prepare):
            with self.assertRaises(ValueError):
                await self.reader.read(source_key='source', loader=self.loader, question='概要')
            self.assertEqual(self.model.calls, 0)
            self.asr.side_effect = [{'text': '第二段', 'duration_ms': 9000}]
            result = await self.reader.read(source_key='source', loader=self.loader, question='概要')
        self.assertEqual(self.asr.await_count, 3)
        self.loader.assert_awaited_once()
        self.assertTrue(result['audio_complete'])
        self.assertEqual(result['new_asr_seconds'], 9)

    async def test_independent_readers_share_locks_and_cached_analysis(self):
        other = MediaReader(self.tmp.name, SETTINGS, model_factory=Mock(return_value=self.model))
        other._transcribe = self.asr
        with patch('glorybond.agent.media_inputs.prepare_media', side_effect=self.prepare):
            results = await asyncio.gather(*[reader.read(source_key='same-source', loader=self.loader, question='概要')
                                            for reader in (self.reader, other)])
        self.loader.assert_awaited_once()
        self.assertEqual(self.preparations, 1)
        self.assertEqual(self.asr.await_count, 2)
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(sum(result['cache_hit'] for result in results), 1)

    async def test_all_six_segments_run_concurrently_and_keep_source_order(self):
        async def prepare(source, directory, limits):
            value = await self.prepare(source, directory, limits)
            value['duration_seconds'] = value['audio_duration_seconds'] = 600
            value['audio_chunks'] = [{'start': 115 * index, 'duration': 115 if index < 5 else 25,
                                      'file': f'audio-{index:04d}.wav'} for index in range(6)]
            return value
        started = 0
        all_started = asyncio.Event()
        async def transcribe(path):
            nonlocal started
            index = int(path.stem.split('-')[1])
            started += 1
            if started == 6:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), 1)
            await asyncio.sleep((5 - index) * 0.001)
            return {'text': f'segment{index}', 'duration_ms': 115000 if index < 5 else 25000}
        self.reader._transcribe = transcribe
        with patch('glorybond.agent.media_inputs.prepare_media', side_effect=prepare):
            result = await self.reader.read(source_key='parallel', loader=self.loader, question='概要')
        self.assertEqual(started, 6)
        self.assertEqual(result['new_asr_seconds'], 600)
        self.assertEqual(result['audio_segments'], 6)
        transcript = result['transcript']
        self.assertEqual([line.split()[-1] for line in transcript.splitlines()], [f'segment{i}' for i in range(6)])

    async def test_over_ten_minutes_is_rejected_before_extraction_or_api_requests(self):
        probe = {'format': {'duration': '600.01'}, 'streams': [{'codec_type': 'video'}]}
        with patch('glorybond.agent.media_inputs.media_command', AsyncMock(return_value=json.dumps(probe))) as command:
            with self.assertRaisesRegex(ValueError, '600 秒'):
                await prepare_media(Path('input.mp4'), Path(self.tmp.name), MediaLimits())
        command.assert_awaited_once()
        self.asr.assert_not_awaited()
        self.assertEqual(self.model.calls, 0)

    async def test_native_voice_conversion_requires_an_authorized_output(self):
        path = Path(self.tmp.name) / 'voice.wav'
        write_wave(path, 1)
        bot = Mock(get_record=AsyncMock(return_value={'file': str(path)}))
        fetcher = Mock(download=AsyncMock())
        source = {'kind': 'audio', 'file': 'native.silk'}
        result = await read_qq_media(source, bot=bot, fetcher=fetcher,
                                    max_bytes=100000, local_roots=(Path(self.tmp.name),))
        self.assertEqual(result, path.read_bytes())
        bot.get_record.assert_awaited_once_with(file='native.silk', out_format='wav')
        fetcher.download.assert_not_awaited()
        with self.assertRaises(PermissionError):
            await read_qq_media(source, bot=bot, fetcher=fetcher, max_bytes=100000, local_roots=())

    async def test_bot_video_uses_exact_local_file_instead_of_inconsistent_url(self):
        root = Path(self.tmp.name)
        (root / 'sent.mp4').write_bytes(b'correct-video')
        source = {'kind': 'video', 'file': 'sent.mp4', 'file_size': '13', 'url': 'https://qq.example/wrong'}
        fetcher = Mock(download=AsyncMock(return_value={'raw': b'wrong-video'}))
        result = await read_qq_media(source, fetcher=fetcher, max_bytes=100000,
                                    local_roots=(root,), prefer_cached_video=True)
        self.assertEqual(result, b'correct-video')
        fetcher.download.assert_not_awaited()
        # A different sender cannot select the bot's local file by its basename.
        with self.assertRaisesRegex(ValueError, '文件大小不一致'):
            await read_qq_media(source, fetcher=fetcher, max_bytes=100000, local_roots=(root,))
        fetcher.download.assert_awaited_once_with(source['url'], max_bytes=13)

    async def test_mismatched_download_cannot_enter_cache_or_reach_analysis(self):
        source = {'kind': 'video', 'file_size': 4, 'url': 'https://qq.example/media'}
        fetcher = Mock(download=AsyncMock(return_value={'raw': b'bad'}))
        async def load():
            return await read_qq_media(source, fetcher=fetcher, max_bytes=100000)
        with self.assertRaisesRegex(ValueError, '文件大小不一致'):
            await self.reader.read(source_key='mismatch', loader=load, question='概要')
        self.assertEqual(list(Path(self.tmp.name).glob('*/source.media')), [])
        self.assertEqual(self.model.calls, 0)
        self.asr.assert_not_awaited()
        fetcher.download.return_value = {'raw': b'good'}
        self.assertEqual(await load(), b'good')

    async def test_local_video_replacement_and_path_escape_are_rejected(self):
        root = Path(self.tmp.name)
        allowed = root / 'allowed'
        allowed.mkdir()
        (allowed / 'sent.mp4').write_bytes(b'changed-size')
        source = {'kind': 'video', 'file': 'sent.mp4', 'file_size': '4'}
        fetcher = Mock(download=AsyncMock())
        with self.assertRaisesRegex(ValueError, '文件大小不一致'):
            await read_qq_media(source, fetcher=fetcher, max_bytes=100000,
                                local_roots=(allowed,), prefer_cached_video=True)
        outside = root / 'outside.mp4'
        outside.write_bytes(b'good')
        (allowed / 'sent.mp4').unlink()
        (allowed / 'sent.mp4').symlink_to(outside)
        with self.assertRaises(PermissionError):
            await read_qq_media(source, fetcher=fetcher, max_bytes=100000,
                                local_roots=(allowed,), prefer_cached_video=True)
        fetcher.download.assert_not_awaited()

    async def test_cancellation_terminates_media_decoder(self):
        started = asyncio.Event()
        process = Mock(returncode=None)
        async def communicate():
            if process.returncode is None:
                started.set()
                await asyncio.Event().wait()
            return b'', b''
        process.communicate = communicate
        process.kill.side_effect = lambda: setattr(process, 'returncode', -9)
        with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=process)):
            task = asyncio.create_task(media_command('ffmpeg'))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        process.kill.assert_called_once()

    async def test_attachment_is_opaque_scoped_and_not_downloaded_before_tool_call(self):
        load = AsyncMock(return_value=b'synthetic owned media')
        entries = self.reader.bind(scope='chat:1', message_id=10,
            sources=[{'kind': 'video', 'url': 'https://qq.example/signed?secret=x'}], reader=load)
        self.assertNotIn('secret', json.dumps(entries))
        load.assert_not_awaited()
        with self.assertRaises(PermissionError):
            await self.reader.read_attachment(entries[0]['attachment_id'], 'chat:2', '概要')
        load.assert_not_awaited()
        with patch('glorybond.agent.media_inputs.prepare_media', side_effect=self.prepare):
            result = await self.reader.read_attachment(entries[0]['attachment_id'], 'chat:1', '概要')
        self.assertTrue(result['audio_complete'])
        self.assertEqual(result['attachment_id'], entries[0]['attachment_id'])
        self.assertEqual(result['source_message_id'], '10')
        load.assert_awaited_once()

    async def test_tool_is_discovered_normally_and_exposes_actual_usage(self):
        registry = ToolRegistry()
        register_media_tool(registry, media=self.reader, fetcher=Mock(download=AsyncMock(return_value={'raw': b'media'})))
        tool = registry.tools['read_media']
        self.assertFalse(tool.initially_visible)
        ctx = ToolContext(RunRequest('test', 'chat:1', Principal('u', frozenset({'web.read'}))), AsyncMock())
        with patch('glorybond.agent.media_inputs.prepare_media', side_effect=self.prepare):
            result = await tool.handler(ReadMediaArgs(url='https://example.com/a.mp4', question='概要'), ctx)
        self.assertTrue(result['audio_complete'])
        self.assertFalse(result['transcript_truncated'])
        self.assertEqual(result['new_model_usage'], {'prompt_tokens': 100, 'completion_tokens': 20})

    async def test_asr_uses_official_endpoint_and_does_not_expose_failure_body(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(503, text='signed_url=private')
        self.reader.client_factory = lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond))
        path = Path(self.tmp.name) / 'a.wav'
        write_wave(path, 1)
        with self.assertRaisesRegex(ValueError, 'HTTP 503') as caught:
            await MediaReader._transcribe(self.reader, path)
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(str(requests[0].url), 'https://api.deepseek.com/v1/tools/asr')
        self.assertEqual(requests[0].headers['authorization'], 'Bearer test-secret')


class SimpleModel:
    def __init__(self):
        self.calls = 0
        self.messages = []

    async def complete(self, messages, tools, on_delta):
        self.calls += 1
        self.messages = messages
        await asyncio.sleep(0)
        return {'message': {'content': '基于完整转写与采样帧的分析'}, 'model': 'deepseek-flash',
                'finish_reason': 'stop', 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class MediaDecodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_audio_is_partitioned_without_dropping_the_tail(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'input.wav'
            write_wave(source, 235.5)
            destination = root / 'decoded'
            destination.mkdir()
            result = await prepare_media(source, destination, MediaLimits())
            self.assertEqual(len(result['audio_chunks']), 3)
            self.assertEqual(result['frames'], [])
            self.assertAlmostEqual(result['audio_duration_seconds'], 235.5, places=3)
            for chunk in result['audio_chunks']:
                self.assertLessEqual(chunk['duration'], 120)
                self.assertLess((destination / chunk['file']).stat().st_size, 8 * 1024 * 1024)

    async def test_video_sampling_preserves_timestamps_and_audio(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'input.mp4'
            await media_command('ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=2',
                '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '12', '-c:v', 'libx264', '-preset', 'ultrafast',
                '-c:a', 'aac', str(source))
            destination = root / 'decoded'
            destination.mkdir()
            result = await prepare_media(source, destination, MediaLimits())
            self.assertEqual([f['timestamp'] for f in result['frames']], [0, 10])
            self.assertTrue(result['has_audio'])
            self.assertAlmostEqual(result['audio_duration_seconds'], 12, delta=0.1)
            self.assertTrue(all((destination / f['file']).is_file() for f in result['frames']))

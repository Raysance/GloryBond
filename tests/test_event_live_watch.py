import asyncio
import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, patch

from hok_camp_client import CampError
from tools.debugger import import_project_module
from glorybond.integrations import camp

WATCH = import_project_module('glorybond.apps.qq.handlers.live_watch')
ZFUNC = import_project_module('glorybond.features.facade')
ZFILE = import_project_module('glorybond.storage.files')
ADAPTER = import_project_module('glorybond.integrations.wzry')


class Event:
    def __init__(self, text): self.text = text
    def get_plaintext(self): return self.text
    def get_user_id(self): return '1001'


class LiveWatchEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for obj, name, value in [(WATCH,'userlist',{'alice':11}), (WATCH,'roleidlist',{'alice':22}),
            (WATCH,'namenick',{'alice':'Alice'}), (ZFUNC,'qid2realname',Mock(return_value='alice')),
            (ZFUNC,'extract_name',Mock(side_effect=lambda value, **kw: 'alice' if value=='昵称' else None))]:
            item=patch.object(obj,name,value);item.start();self.addCleanup(item.stop)

    def test_target_resolution_and_explicit_command_boundaries(self):
        for text in ('#观战alice','＃观战 昵称','#观战我','#我的观战'):
            with self.subTest(text=text):
                result=WATCH.prepare_watch_request(Event(text))
                self.assertEqual((result['userid'],result['roleid']), (11,22))
        self.assertIsNone(WATCH.watch_target('我要观战alice'))
        self.assertIsNone(WATCH.watch_target('#介绍观战功能'))
        self.assertEqual(WATCH.prepare_watch_request(Event('#观战'))['kind'],'text')
        self.assertEqual(WATCH.prepare_watch_request(Event('#观战unknown'))['kind'],'text')

    async def test_image_is_saved_and_safe_result_contains_no_stream_details(self):
        prepared=WATCH.prepare_watch_request(Event('#观战我'))
        with patch.object(ADAPTER,'wzry_watch_frame',return_value={'state':'ready','jpeg':b'JPEG'}) as call, \
             patch.object(ZFILE,'save_watch_frame',return_value='/tmp/watch.jpg') as save:
            result=await WATCH.run_watch_request(prepared)
        call.assert_called_once_with(11,22)
        save.assert_called_once_with(b'JPEG')
        self.assertEqual(result['kind'],'image')
        self.assertEqual(result['image_path'],'/tmp/watch.jpg')

    async def test_unavailable_and_timeout_do_not_retry_or_echo_server_text(self):
        prepared=WATCH.prepare_watch_request(Event('#观战我'))
        for error in (CampError('watch_unavailable','PRIVATE',response={'reason':'not_gaming'}),
                      CampError('video_decode','rtmp://private'), OSError('PRIVATE')):
            with patch.object(ADAPTER,'wzry_watch_frame',side_effect=error) as call:
                result=await WATCH.run_watch_request(prepared)
            call.assert_called_once()
            self.assertEqual(result['kind'],'text')
            self.assertNotIn('PRIVATE',str(result))
            self.assertNotIn('rtmp',str(result))
        with patch.object(ADAPTER,'wzry_watch_frame',return_value={'state':'pending'}):
            self.assertIn('超时',(await WATCH.run_watch_request(prepared))['text'])

    async def test_slow_lineup_does_not_block_stream_but_precedes_reply(self):
        prepared = WATCH.prepare_watch_request(Event('#观战我'))
        order = []
        rendering = threading.Event()
        stream_ready = threading.Event()
        finish_rendering = threading.Event()
        raw = {'battleID': 'synthetic-battle', 'camp1': [{'roleId': 22, 'heroName': '赵云',
                                                       'roleInfo': {'roleName': '玩家'}}], 'camp2': []}
        def capture(*args, on_battle_info):
            on_battle_info(raw)
            self.assertTrue(rendering.wait(2))
            # Simulates the SDK processing a ready notification after callback.
            order.append('stream_ready')
            stream_ready.set()
            return {'state': 'ready', 'jpeg': b'JPEG'}
        def lineup(data):
            self.assertEqual(data['battle_id'], 'synthetic-battle')
            rendering.set()
            self.assertTrue(finish_rendering.wait(4))
            order.append('lineup')
        errors = Mock()
        with patch.object(ADAPTER, 'wzry_watch_frame', side_effect=capture), \
             patch.object(ZFILE, 'save_watch_frame', return_value='/tmp/watch.jpg'):
            request = asyncio.create_task(WATCH.run_watch_request(prepared, on_lineup=lineup, on_error=errors))
            try:
                self.assertTrue(await asyncio.to_thread(stream_ready.wait, 2))
                self.assertFalse(request.done())
                self.assertEqual(order, ['stream_ready'])
            finally:
                finish_rendering.set()
                result = await request
        order.append('reply')
        self.assertEqual(order, ['stream_ready', 'lineup', 'reply'])
        self.assertEqual(result['kind'], 'image')
        errors.assert_not_called()

    async def test_rendering_failure_keeps_frame_and_worker_finishes_on_timeout(self):
        prepared = WATCH.prepare_watch_request(Event('#观战我'))
        raw = {'battleID': 'synthetic-battle', 'camp1': [], 'camp2': []}
        def capture(*args, on_battle_info):
            on_battle_info(raw)
            return {'state': 'ready', 'jpeg': b'JPEG'}
        errors = Mock()
        with patch.object(ADAPTER, 'wzry_watch_frame', side_effect=capture), \
             patch.object(ZFILE, 'save_watch_frame', return_value='/tmp/watch.jpg'), \
             patch('glorybond.features.game.watch_lineup.prepare_watch_lineup', return_value={'battle_id': 'synthetic-battle'}):
            result = await WATCH.run_watch_request(prepared, on_lineup=Mock(side_effect=OSError('PRIVATE')),
                                                   on_error=errors)
        self.assertEqual(result['kind'], 'image')
        errors.assert_called_once()
        self.assertNotIn('PRIVATE', str(errors.call_args))

        for failure in ({'state': 'pending'}, CampError('im_login', 'PRIVATE')):
            done = threading.Event()
            def fail_capture(*args, on_battle_info):
                on_battle_info(raw)
                if isinstance(failure, Exception):
                    raise failure
                return failure
            with patch.object(ADAPTER, 'wzry_watch_frame', side_effect=fail_capture) as call, \
                 patch('glorybond.features.game.watch_lineup.prepare_watch_lineup', return_value={'battle_id': 'synthetic-battle'}):
                result = await WATCH.run_watch_request(prepared, on_lineup=lambda _: done.set())
            self.assertTrue(done.is_set())
            self.assertEqual(result['kind'], 'text')
            call.assert_called_once()

    def test_pending_diagnostic_keeps_private_metadata_out(self):
        raw = {'state': 'pending', 'reason': 'stream_wait_timeout', 'battle_info': {'private': 'PRIVATE'}}
        with patch.object(ADAPTER, 'capture_watch_frame', return_value=raw), \
             patch.object(ADAPTER, 'monotonic', side_effect=[10, 35]), \
             patch.object(ADAPTER, 'log_message') as log:
            self.assertIs(ADAPTER.wzry_watch_frame(11, 22), raw)
        self.assertEqual(log.call_args.args[0],
                         'WATCH_FRAME_RESULT state=pending reason=stream_wait_timeout reused=False elapsed=25.000')
        self.assertNotIn('PRIVATE', str(log.call_args))

    def test_unique_artifact_names(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ZFILE,'temp_path',directory):
            first,second=ZFILE.save_watch_frame(b'JPEG'),ZFILE.save_watch_frame(b'JPEG')
            self.assertNotEqual(first,second)
            self.assertEqual(Path(first).read_bytes(),b'JPEG')


class WatchSdkBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client=Mock()
        self.client.capture_watch_frame.return_value={'state':'ready','jpeg':b'JPEG','stream_url':'rtmp://PRIVATE'}
        self.patcher=patch.object(camp,'_get_client',return_value=self.client)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def test_capture_delegates_reuse_and_keeps_session_open(self):
        result=camp.capture_watch_frame('/private/session.json',11,22)
        self.assertEqual(result,{'state':'ready','jpeg':b'JPEG'})
        self.client.capture_watch_frame.assert_called_once_with(11,22,wait_timeout=60)
        callback = Mock()
        result = camp.capture_watch_frame('/private/session.json',11,22,on_battle_info=callback)
        self.client.capture_watch_frame.assert_called_with(11,22,wait_timeout=60,on_battle_info=callback)
        self.client.close.assert_not_called()
        self.client.close_watch_stream.assert_not_called()
        self.client.capture_watch_frame.side_effect=CampError('video_decode','PRIVATE')
        with self.assertRaises(CampError):
            camp.capture_watch_frame('/private/session.json',11,22)
        self.assertTrue(camp._watch_lock.acquire(blocking=False))
        camp._watch_lock.release()

    def test_pending_and_concurrent_request_do_not_read_media_or_queue_login(self):
        self.client.capture_watch_frame.return_value={'state':'pending','reason':'stream_wait_timeout','stream_url':'PRIVATE'}
        self.assertEqual(camp.capture_watch_frame('/private/session.json',11,22),
                         {'state':'pending','reason':'stream_wait_timeout'})
        self.client.capture_watch_frame.reset_mock()
        with camp._watch_lock:
            with self.assertRaises(CampError) as caught:
                camp.capture_watch_frame('/private/session.json',11,22)
        self.assertEqual(caught.exception.code,'watch_active')
        self.client.capture_watch_frame.assert_not_called()

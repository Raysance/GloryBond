import tempfile
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

    def test_unique_artifact_names(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ZFILE,'temp_path',directory):
            first,second=ZFILE.save_watch_frame(b'JPEG'),ZFILE.save_watch_frame(b'JPEG')
            self.assertNotEqual(first,second)
            self.assertEqual(Path(first).read_bytes(),b'JPEG')


class WatchSdkBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client=Mock()
        self.live=MagicMock()
        self.live.__enter__.return_value=self.live
        self.live.result={'state':'ready','stream_url':'rtmp://PRIVATE'}
        self.client.open_watch_stream.return_value=self.live
        self.frames=MagicMock()
        self.frames.__next__.return_value=b'JPEG'
        self.live.frames.return_value=self.frames
        self.patcher=patch.object(camp,'_get_client',return_value=self.client)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def test_first_frame_and_failure_close_all_resources(self):
        result=camp.capture_watch_frame('/private/session.json',11,22)
        self.assertEqual(result,{'state':'ready','jpeg':b'JPEG'})
        self.client.open_watch_stream.assert_called_once_with(11,22,wait_timeout=60)
        self.frames.close.assert_called_once()
        self.live.__exit__.assert_called_once()
        self.frames.__next__.side_effect=CampError('video_decode','PRIVATE')
        with self.assertRaises(CampError):
            camp.capture_watch_frame('/private/session.json',11,22)
        self.assertEqual(self.live.__exit__.call_count,2)
        self.assertEqual(self.frames.close.call_count,2)

    def test_pending_and_concurrent_request_do_not_read_media_or_queue_login(self):
        self.live.result={'state':'pending','reason':'stream_wait_timeout','stream_url':'PRIVATE'}
        self.assertEqual(camp.capture_watch_frame('/private/session.json',11,22),
                         {'state':'pending','reason':'stream_wait_timeout'})
        self.live.frames.assert_not_called()
        self.client.open_watch_stream.reset_mock()
        with camp._watch_lock:
            with self.assertRaises(CampError) as caught:
                camp.capture_watch_frame('/private/session.json',11,22)
        self.assertEqual(caught.exception.code,'watch_active')
        self.client.open_watch_stream.assert_not_called()

import json
import unittest
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

from local_debugger import import_hok_module


ZAPI = import_hok_module("zapi")
ZFUNC = import_hok_module("zfunc")
BUSINESS = import_hok_module("business.x_subscription")
HANDLERS = import_hok_module("event_handlers.x_subscription")
RULES = import_hok_module("event_rules")
RENDER = import_hok_module("tools.gen_x_post")


class Event:
    def __init__(self, text):
        self.text = text

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return "10001"


class MemoryState:
    def __init__(self):
        self.records, self.cursors, self.seen, self.sent = [], {}, set(), []

    @contextmanager
    def _x_lock(self):
        yield "token"

    def _x_refresh_lock(self, token):
        pass

    def _x_subscriptions(self):
        return deepcopy(self.records)

    def _x_cursor(self, account):
        return deepcopy(self.cursors.get(account))

    def _x_save_cursor(self, account, cursor):
        self.cursors[account] = deepcopy(cursor)

    def _x_save_subscription(self, row):
        self.records.append(row)

    def _x_delete_subscription(self, user, account):
        self.records = [r for r in self.records if (r['user_qid'], r['id']) != (str(user), account)]

    def _x_seen(self, account, post):
        return (account, post) in self.seen

    def _x_mark_seen(self, account, post):
        self.seen.add((account, post))

    def _x_send_message(self, message):
        self.sent.append(message)

    def _x_render_message(self, bundle):
        return json.dumps(bundle, ensure_ascii=False)


class XBusinessTests(unittest.TestCase):
    def setUp(self):
        self.state = MemoryState()
        self.user = {"id": "1", "username": "example", "name": "Example"}
        self.records = [dict(self.user, user_qid="10001")]
        self.state.records = deepcopy(self.records)
        self.state.cursors["1"] = {"since_id": "10", "start_time": "2026-10-01T00:00:00Z"}
        patches = [patch.object(BUSINESS, "_facade", return_value=self.state),
                   patch.dict(BUSINESS.x_subscription_config, auth_token="test", ct0="test-csrf", enabled=True),
                   patch.object(ZAPI, "x_get_replies", return_value={"replies": [], "sample_size": 0})]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_first_subscription_baselines_old_posts_and_second_does_not_consume_pending(self):
        self.state.records = []
        with patch.object(ZAPI, "x_get_user", return_value=self.user), \
             patch.object(ZAPI, "x_get_posts", return_value=[{"id": "20", "text": "old"}]):
            self.assertIn("订阅成功", BUSINESS.x_subscribe_user("10001", "example"))
            self.assertEqual(self.state.cursors['1']['since_id'], "20")
        with patch.object(ZAPI, "x_get_user", return_value=self.user), \
             patch.object(ZAPI, "x_get_posts", return_value=[{"id": "21", "text": "pending"}]):
            BUSINESS.x_subscribe_user("10002", "example")
        self.assertEqual(self.state.cursors['1']['since_id'], "20")
        self.assertEqual(len(self.state.records), 2)

    def test_push_once_for_shared_account_in_oldest_order(self):
        self.state.records.append(dict(self.user, user_qid="10002"))
        posts = [{"id": "12", "text": "second"}, {"id": "11", "text": "first"}]
        with patch.object(ZAPI, "x_get_posts", return_value=posts) as request:
            result = BUSINESS.x_check_and_push()
        self.assertEqual(result['pushed'], 2)
        self.assertEqual(request.call_count, 1)
        self.assertEqual([json.loads(m)['post']['id'] for m in self.state.sent], ['11', '12'])
        self.assertEqual(self.state.cursors['1']['since_id'], '12')

    def test_enqueue_failure_keeps_cursor_and_other_account_still_runs(self):
        self.state.records.append({"id":"2", "username":"other", "name":"Other", "user_qid":"10001"})
        self.state.cursors['2'] = {'since_id':'10'}
        with patch.object(ZAPI, "x_get_posts", return_value=[{'id':'11','text':'new'}]), \
             patch.object(self.state, "_x_send_message", side_effect=[RuntimeError("queue unavailable"), None]):
            result = BUSINESS.x_check_and_push()
        self.assertEqual(result['pushed'], 1)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(self.state.cursors['1']['since_id'], '10')
        self.assertNotIn(('1', '11'), self.state.seen)
        self.assertEqual(self.state.cursors['2']['since_id'], '11')

    def test_fresh_post_waits_for_replies_without_advancing_cursor(self):
        time = import_hok_module('ztime')
        with patch.object(ZAPI, "x_get_posts", return_value=[{'id':'11', 'text':'fresh', 'created_at':time.utc_timestamp_text()}]):
            result = BUSINESS.x_check_and_push()
        self.assertEqual(result['pushed'], 0)
        self.assertEqual(self.state.cursors['1']['since_id'], '10')

    def test_replies_and_translation_are_in_card_and_failures_are_visible(self):
        replies = {'replies':[{'id':'9','text':'Great','lang':'en','likes':3}], 'sample_size':50}
        with patch.object(ZAPI, 'x_get_replies', return_value=replies), \
             patch.object(ZAPI, 'ai_api', return_value='{"11":"你好", "9":"很棒"}') as translate:
            card = json.loads(BUSINESS.post_card(self.user, {'id':'11','text':'Hello','lang':'en'}))
        self.assertEqual(translate.call_args.kwargs['response_format'], {'type': 'json_object'})
        self.assertEqual(card['post']['translation'], '你好')
        self.assertEqual(card['replies'][0]['translation'], '很棒')
        self.assertIn('50', card['note'])
        with patch.object(ZAPI, 'x_get_replies', side_effect=RuntimeError()), \
             patch.object(ZAPI, 'ai_api', return_value='invalid'):
            card = json.loads(BUSINESS.post_card(self.user, {'id':'11','text':'Hello','lang':'en'}))
        self.assertEqual(card['post']['translation'], '翻译暂不可用')
        self.assertIn('暂不可用', card['note'])

    def test_unsubscribe_does_not_remove_other_users_record(self):
        self.state.records.append(dict(self.user, user_qid="10002"))
        BUSINESS.x_unsubscribe_user('10001', '@example')
        self.assertEqual([r['user_qid'] for r in self.state.records], ['10002'])

    def test_cursor_write_failure_does_not_duplicate_already_queued_post_on_retry(self):
        with patch.object(ZAPI, 'x_get_posts', return_value=[{'id':'11','text':'new'}]):
            with patch.object(self.state, '_x_save_cursor', side_effect=RuntimeError('write failed')):
                self.assertEqual(len(BUSINESS.x_check_and_push()['errors']), 1)
            self.assertEqual(BUSINESS.x_check_and_push()['pushed'], 0)
        self.assertEqual(len(self.state.sent), 1)
        self.assertEqual(self.state.cursors['1']['since_id'], '11')

    def test_lost_lock_stops_send_even_after_image_has_been_generated(self):
        with patch.object(ZAPI, 'x_get_posts', return_value=[{'id':'11','text':'new'}]), \
             patch.object(self.state, '_x_refresh_lock', side_effect=[None,None,RuntimeError('lost lock')]):
            result = BUSINESS.x_check_and_push()
        self.assertEqual(result['pushed'], 0)
        self.assertEqual(self.state.sent, [])
        self.assertEqual(self.state.cursors['1']['since_id'], '10')


class RedisStub:
    def __init__(self):
        self.lock = None
        self.hashes = {}

    def set(self, key, value, **kwargs):
        if self.lock:
            return False
        self.lock = value
        return True

    def eval(self, script, count, key, token, *args):
        if self.lock != token:
            return 0
        if 'expire' in script:
            return 1
        self.lock = None
        return 1

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value.encode()

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hvals(self, key):
        return list(self.hashes.get(key, {}).values())


class XStorageTests(unittest.TestCase):
    def test_subscription_hash_keeps_simultaneous_users_and_cursor_roundtrips(self):
        with patch.object(ZFUNC.dmc, 'redis_deamon', RedisStub()):
            for user in ('1','2'):
                ZFUNC._x_save_subscription({'id':'10','user_qid':user,'username':'test'})
            self.assertEqual(len(ZFUNC._x_subscriptions()), 2)
            ZFUNC._x_save_cursor('10', {'since_id':'9007199254740993'})
            self.assertEqual(ZFUNC._x_cursor('10')['since_id'], '9007199254740993')

    def test_expired_owner_cannot_release_successor_lock(self):
        redis = RedisStub()
        with patch.object(ZFUNC.dmc, 'redis_deamon', redis):
            with ZFUNC._x_lock() as token:
                ZFUNC._x_refresh_lock(token)
                redis.lock = 'successor'
                with self.assertRaises(RuntimeError):
                    ZFUNC._x_refresh_lock(token)
            self.assertEqual(redis.lock, 'successor')


class XRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_x_commands_do_not_match_bili_or_unprefixed_chat(self):
        for text in ('#订阅X @example', '＃订阅x https://x.com/example', '#取消订阅X example', '#我的X订阅', '#X最新内容'):
            self.assertTrue(await RULES.judge_x_subscription(Event(text)))
            self.assertFalse(await RULES.judge_bili_video_subscribe(Event(text)))
            self.assertFalse(await RULES.judge_bili_video_unsubscribe(Event(text)))
        self.assertFalse(await RULES.judge_x_subscription(Event('订阅X @example')))
        self.assertFalse(await RULES.judge_x_subscription(Event('##x check')))
        self.assertTrue(await RULES.judge_x_subscription_admin(Event('##x check')))

    async def test_handler_binds_real_sender(self):
        with patch.object(ZFUNC, 'x_subscribe_user', return_value='ok') as subscribe:
            self.assertEqual(await HANDLERS.command_reply(Event('＃订阅x @example')), 'ok')
        subscribe.assert_called_once_with('10001', '@example')

    def test_render_long_bilingual_content_paginates_and_preserves_media(self):
        from PIL import Image
        bundle = {'post':{'id':'11','username':'example','name':'测试作者','text':'Hello\n你好世界'*300,
                          'translation':'中文译文'}, 'note':'采样 100 条，按点赞数选取',
                  'replies':[{'id':'12', 'text':'A good reply', 'translation':'一条好回复','likes':30}]}
        images = RENDER.render_x_post_images(bundle, [Image.new('RGB',(600,200),'red')])
        self.assertGreater(len(images), 1)
        self.assertTrue(all(image.width == 1080 and image.height <= 8000 for image in images))

    def test_card_keeps_source_translation_and_sampling_without_redundant_copy(self):
        from PIL import Image, ImageDraw
        original_text = ImageDraw.ImageDraw.text
        drawn = []
        def capture(draw, xy, text, *args, **kwargs):
            drawn.append(text)
            return original_text(draw, xy, text, *args, **kwargs)
        bundle = {'post':{'id':'11','username':'example','name':'Tibo',
                          'text':'Original text https://t.co/media https://example.com',
                          'translation':'中文译文 https://t.co/media',
                          'media_short_urls':['https://t.co/media']},
                  'replies':[{'id':'12','username':'reader','name':'Reader','text':'A reply','likes':5}],
                  'sample_size':50,'note':'This is metadata, not card copy'}
        with patch.object(ImageDraw.ImageDraw, 'text', new=capture):
            RENDER.render_x_post_images(bundle, [Image.new('RGB',(300,100),'white')])
        text = '\n'.join(drawn)
        self.assertIn('中文译文',text)
        self.assertIn('Original text',text)
        self.assertIn('https://example.com',text)
        self.assertIn('采样 50 条',text)
        for redundant in ('X 关注动态','中文翻译（AI）','https://t.co/media',bundle['note'],'x.com/reader/status'):
            self.assertNotIn(redundant,text)

    def test_reply_media_link_is_kept_until_the_attachment_is_rendered(self):
        from PIL import Image, ImageDraw
        original_text = ImageDraw.ImageDraw.text
        drawn = []
        def capture(draw, xy, text, *args, **kwargs):
            drawn.append(text)
            return original_text(draw, xy, text, *args, **kwargs)
        bundle = {'post':{'id':'11','username':'author','name':'Author','text':'Post'},
                  'replies':[{'id':'12','username':'reader','name':'Reader','text':'See https://t.co/photo',
                              'media_short_urls':['https://t.co/photo']}]}
        with patch.object(ImageDraw.ImageDraw, 'text', new=capture):
            RENDER.render_x_post_images(bundle)
            self.assertIn('https://t.co/photo','\n'.join(drawn))
            drawn.clear()
            RENDER.render_x_post_images(bundle, reply_media_images={'12':[Image.new('RGB',(300,100),'white')]})
            self.assertNotIn('https://t.co/photo','\n'.join(drawn))

    def test_bundled_card_font_is_resolved_from_project_root(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import os
        files = import_hok_module('zfile')
        previous = os.getcwd()
        try:
            with TemporaryDirectory() as directory:
                os.chdir(directory)
                path = files.x_card_font_path()
                self.assertTrue(Path(path).is_absolute())
                self.assertTrue(Path(path).is_file())
                self.assertIn('NotoSansSC',str(path))
        finally:
            os.chdir(previous)


if __name__ == '__main__':
    unittest.main()

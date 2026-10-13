"""Emoji input moves to scoped archives; no passive chat cache is needed."""
import unittest
from unittest.mock import Mock, patch
from local_debugger import import_hok_module

FUNCS=import_hok_module('zfunc')
DB=import_hok_module('zdb')
GEN=import_hok_module('tools.gen_emoji_image')


class EmojiContextTests(unittest.TestCase):
    def test_archive_read_is_bound_to_user_group_and_skips_commands(self):
        rows=[{'group_id':'200','user_id':'101','message_id':'1','timestamp':1,'text':'今天赢了'},
              {'group_id':'200','user_id':'102','message_id':'2','timestamp':2,'text':'other user'},
              {'group_id':'200','user_id':'101','message_id':'3','timestamp':3,'text':'#查询'}]
        with patch.object(DB,'load_group_chat_messages',return_value=rows) as load, patch.object(FUNCS,'_load_group_chat_history_redis',return_value=[]):
            result=FUNCS.recent_emoji_messages('101','200')
        load.assert_called_once_with('200',limit=100,user_id='101')
        self.assertEqual([r['text'] for r in result],['今天赢了'])
        with patch.object(DB,'load_group_chat_messages') as load:
            self.assertEqual(FUNCS.recent_emoji_messages('101',None),[])
        load.assert_not_called()
    def test_picker_uses_emoji_only_context_and_retains_deduplication(self):
        context=Mock()
        context.recent.return_value=[{'text':'今天赢了'}]
        context.get_action.return_value={'action':'use','text':'今天赢了'}
        context.used.return_value=False
        with patch.object(import_hok_module('tools.emoji_context'),'EmojiContext',return_value=context) as factory:
            result=GEN._emoji_pick_one_refined_message('101','200')
        factory.assert_called_once_with('101','200')
        self.assertEqual(result['text'],'今天赢了')
        context.mark_used.assert_called_once_with(result['hash'])

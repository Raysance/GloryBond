import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from bs4 import BeautifulSoup

from local_debugger import import_hok_module


API = import_hok_module('api_adapters.x')
TRANSACTION = import_hok_module('api_adapters.x_transaction')


def user(account='1', **extra):
    return {'rest_id':account, 'legacy':{'screen_name':f'author{account}', 'name':f'Author {account}'}, **extra}


def tweet(post_id, *, author='1', likes=0, reply_to=None, conversation=None, **extra):
    return {'__typename':'Tweet', 'rest_id':str(post_id),
            'core':{'user_results':{'result':user(author)}},
            'legacy':{'full_text':f'Post {post_id}', 'created_at':'Thu Oct 15 04:00:00 +0000 2026',
                      'lang':'en', 'favorite_count':likes, 'in_reply_to_status_id_str':reply_to,
                      'conversation_id_str':conversation or str(post_id)}, **extra}


def entry(post, *, name=None):
    return {'entryId':name or f"tweet-{post['rest_id']}",
            'content':{'itemContent':{'tweet_results':{'result':post}}}}


def page(entries=(), cursor=None, *, detail=False, pinned=None):
    items=deepcopy(list(entries))
    if cursor:
        items.append({'entryId':'cursor-bottom-0', 'content':{'cursorType':'Bottom','value':cursor}})
    instructions=[{'type':'TimelineAddEntries','entries':items}]
    if pinned:
        instructions.insert(0, {'type':'TimelinePinEntry','entry':entry(pinned)})
    timeline={'instructions':instructions}
    if detail:
        return {'data':{'threaded_conversation_with_injections_v2':timeline}}
    return {'data':{'user':{'result':{'timeline_v2':{'timeline':timeline}}}}}


class XWebApiTests(unittest.TestCase):
    def setUp(self):
        configs=patch.dict(API.x_subscription_config, auth_token='session-secret',ct0='csrf-secret')
        configs.start()
        self.addCleanup(configs.stop)
        self.client=SimpleNamespace(prepare=AsyncMock(), http=SimpleNamespace(aclose=AsyncMock()),
                                    gql=SimpleNamespace(user_tweets=AsyncMock(),user_tweets_and_replies=AsyncMock(),
                                                        user_by_screen_name=AsyncMock(),tweet_detail=AsyncMock()))
        factory=patch.object(API,'XWebClient',return_value=self.client)
        factory.start()
        self.addCleanup(factory.stop)

    def test_username_supports_profile_links_and_rejects_other_hosts(self):
        for text in ('@Example','Example','https://x.com/Example?lang=en','https://twitter.com/Example/'):
            self.assertEqual(API.x_username(text),'Example')
        for text in ('https://evil.test/Example','https://x.com/Example/status/1','显示昵称',''):
            with self.assertRaises(ValueError):
                API.x_username(text)

    def test_user_lookup_uses_website_gql_and_closes_session(self):
        self.client.gql.user_by_screen_name.return_value=({'data':{'user':{'result':user()}}},None)
        self.assertEqual(API.x_get_user('@author1')['id'],'1')
        self.client.gql.user_by_screen_name.assert_awaited_once_with('author1')
        self.client.http.aclose.assert_awaited_once()

    def test_missing_cookies_or_proxy_fails_before_network(self):
        with patch.dict(API.x_subscription_config,auth_token=''):
            with self.assertRaisesRegex(ValueError,'HOK_X_AUTH_TOKEN'):
                API.x_get_user('example')
        with patch.object(API,'clash_proxy_url',''):
            with self.assertRaisesRegex(ValueError,'Proxy.clash_url'):
                API.x_get_user('example')
        self.client.prepare.assert_not_awaited()

    def test_private_accounts_are_rejected(self):
        result=user()
        result['legacy']['protected']=True
        self.client.gql.user_by_screen_name.return_value=({'data':{'user':{'result':result}}},None)
        with self.assertRaisesRegex(RuntimeError,'公开账号'):
            API.x_get_user('author1')

    def test_current_core_user_fields_are_normalized(self):
        self.assertEqual(API._user({'rest_id':'1','core':{'screen_name':'newname','name':'New'}})['username'],'newname')

    def test_pagination_stops_at_cutoff_deduplicates_and_ignores_pin(self):
        self.client.gql.user_tweets.side_effect=[
            (page([entry(tweet('13')),entry(tweet('12'))],'next',pinned=tweet('2')),None),
            (page([entry(tweet('12')),entry(tweet('11')),entry(tweet('10'))],'more'),None)]
        rows=API.x_get_posts('1',since_id='10')
        self.assertEqual([r['id'] for r in rows],['13','12','11'])
        self.assertEqual(self.client.gql.user_tweets.await_count,2)
        self.assertEqual(self.client.gql.user_tweets.await_args_list[1].args[-1],'next')

    def test_start_bound_for_initial_empty_account(self):
        old=tweet('10')
        old['legacy']['created_at']='Wed Oct 14 04:00:00 +0000 2026'
        self.client.gql.user_tweets.return_value=(page([entry(tweet('11')),entry(old)],'older'),None)
        rows=API.x_get_posts('1',since_id='0',start_time='2026-10-15T00:00:00Z')
        self.assertEqual([r['id'] for r in rows],['11'])

    def test_latest_skips_reposts_replies_ads_and_other_authors(self):
        repost=tweet('20')
        repost['legacy']['retweeted_status_result']={'result':tweet('19',author='2')}
        ad=entry(tweet('18'))
        ad['content']['itemContent']['promotedMetadata']={'advertiser':'x'}
        self.client.gql.user_tweets.side_effect=[
            (page([entry(repost),entry(tweet('19',reply_to='1')),ad,entry(tweet('17',author='2'))],'next'),None),
            (page([entry(tweet('16'))]),None)]
        self.assertEqual([r['id'] for r in API.x_get_posts('1',latest=True)],['16'])

    def test_old_conversation_root_does_not_prematurely_stop_new_post_scan(self):
        module={'entryId':'profile-conversation-1','content':{'items':[{'item':entry(tweet('2'))['content']}]}}
        self.client.gql.user_tweets.side_effect=[(page([module,entry(tweet('14'))],'next'),None),
                                                 (page([entry(tweet('13')),entry(tweet('10'))]),None)]
        self.assertEqual([r['id'] for r in API.x_get_posts('1',since_id='10')],['14','13'])

    def test_empty_timeline_is_valid_but_changed_structure_fails(self):
        self.client.gql.user_tweets.return_value=(page(),None)
        self.assertEqual(API.x_get_posts('1',latest=True),[])
        self.client.gql.user_tweets.return_value=({'data':{}},None)
        with self.assertRaisesRegex(RuntimeError,'结构变化'):
            API.x_get_posts('1',latest=True)

    def test_pagination_limit_never_returns_an_incomplete_batch(self):
        self.client.gql.user_tweets.return_value=(page([entry(tweet('12'))],'next'),None)
        with patch.dict(API.x_subscription_config,max_pages=1),self.assertRaisesRegex(RuntimeError,'max_pages'):
            API.x_get_posts('1',since_id='10')

    def test_repeated_cursor_cannot_loop_forever(self):
        self.client.gql.user_tweets.return_value=(page([entry(tweet('12'))],'next'),None)
        with self.assertRaisesRegex(RuntimeError,'游标重复'):
            API.x_get_posts('1',since_id='10')

    def test_long_post_visibility_wrapper_and_media_are_preserved(self):
        post=tweet('11')
        post['note_tweet']={'note_tweet_results':{'result':{'text':'Full long text'}}}
        post['legacy']['extended_entities']={'media':[{'media_url_https':'https://pbs.twimg.com/a.jpg'}]}
        result=API._post({'__typename':'TweetWithVisibilityResults','tweet':post})
        self.assertEqual(result['text'],'Full long text')
        self.assertEqual(result['media_urls'],['https://pbs.twimg.com/a.jpg'])
        self.assertEqual(result['created_at'],'2026-10-15T04:00:00Z')

    def test_replies_only_use_target_conversation_with_likes_ranking(self):
        root=tweet('10')
        low=tweet('11',author='2',likes=1,reply_to='10',conversation='10')
        high=tweet('12',author='3',likes=25,reply_to='11',conversation='10')
        unrelated=tweet('13',author='4',likes=1000,reply_to='9',conversation='9')
        self.client.gql.tweet_detail.return_value=(page([entry(root),entry(low),entry(high),entry(unrelated)],detail=True),None)
        result=API.x_get_replies('10')
        self.assertEqual(result['sample_size'],2)
        self.assertEqual([row['id'] for row in result['replies']],['12','11'])
        self.client.gql.tweet_detail.assert_awaited_once_with('10',None)

    def test_reply_sampling_obeys_limit_and_deduplicates_pages(self):
        posts=[entry(tweet(str(i),likes=i,reply_to='10',conversation='10')) for i in range(11,16)]
        self.client.gql.tweet_detail.side_effect=[(page(posts[:2],'next',detail=True),None),
                                                  (page(posts[1:],'more',detail=True),None)]
        with patch.dict(API.x_subscription_config,reply_sample_size=3):
            result=API.x_get_replies('10')
        self.assertEqual(result['sample_size'],3)
        self.assertEqual([r['id'] for r in result['replies']],['13','12','11'])

    def test_session_and_transport_errors_never_disclose_raw_cookie_or_payload(self):
        for error in (API.Unauthorized('session-secret csrf-secret'),ValueError('session-secret'),RuntimeError('csrf-secret')):
            with self.subTest(error=type(error).__name__):
                self.client.prepare.side_effect=error
                with self.assertRaises(RuntimeError) as raised:
                    API.x_get_user('author1')
                self.assertNotIn('session-secret',str(raised.exception))
                self.assertNotIn('csrf-secret',str(raised.exception))
        self.assertEqual(self.client.http.aclose.await_count,3)

    def test_media_download_obeys_byte_budget_and_has_no_cookie_header(self):
        response=SimpleNamespace(status_code=200,headers={'Content-Type':'image/png'},
                                 iter_content=lambda size:iter([b'1234',b'5678']),close=lambda:None)
        with patch.dict(API.x_subscription_config,max_media_bytes=5), \
             patch.object(API,'clash_request',return_value=response) as request, \
             patch.object(response,'close') as close,self.assertRaises(RuntimeError):
            API.x_get_media_bytes('https://pbs.twimg.com/a.png')
        self.assertNotIn('headers',request.call_args.kwargs)
        close.assert_called_once()
        with patch.object(API,'clash_request') as request:
            for url in ('http://pbs.twimg.com/a','https://evil.test/a','https://pbs.twimg.com@evil.test/a'):
                with self.assertRaises(ValueError):
                    API.x_get_media_bytes(url)
            request.assert_not_called()


class XWebTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config=patch.dict(API.x_subscription_config,auth_token='session-secret',ct0='csrf-secret')
        self.config.start()
        self.client=API.XWebClient()

    async def asyncTearDown(self):
        await self.client.http.aclose()
        self.config.stop()

    async def test_cookie_scope_survives_transaction_backup_and_duplicate_cleanup(self):
        self.client.set_cookies({'auth_token':'session-secret','ct0':'csrf-secret'},clear_cookies=True)
        self.client._remove_duplicate_ct0_cookie()
        for url,expected in [('https://x.com/i/api/graphql/test/UserTweets',True),
                             ('https://abs.twimg.com/main.js',False),('https://evil.test/',False)]:
            request=httpx.Request('GET',url)
            self.client.http.cookies.set_cookie_header(request)
            self.assertEqual('session-secret' in request.headers.get('cookie',''),expected)
        self.assertFalse(self.client.http.trust_env)
        self.assertFalse(self.client.http.follow_redirects)
        self.assertEqual(self.client.proxy, API.clash_proxy_url)

    async def test_only_readonly_website_operations_are_allowed(self):
        for method,url in [('POST','https://x.com/i/api/graphql/id/CreateTweet'),
                           ('GET','https://api.x.com/2/users/1/tweets'),
                           ('GET','https://evil.test/id/UserTweets')]:
            with self.assertRaises(ValueError):
                await self.client.request(method,url)

    async def test_current_query_discovery_and_explicit_override(self):
        html=BeautifulSoup('<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script>','html.parser')
        response=SimpleNamespace(raise_for_status=lambda:None,text='queryId:"new-id",operationName:"UserTweets"')
        self.client.client_transaction.home_page_response=html
        with patch.object(self.client.client_transaction,'init',new=AsyncMock()), \
             patch.object(self.client.http,'get',new=AsyncMock(return_value=response)), \
             patch.dict(API.x_subscription_config,web_query_ids={'TweetDetail':'override'}):
            await self.client.prepare()
        self.assertEqual(self.client.query_ids['UserTweets'],'new-id')
        self.assertEqual(self.client.query_ids['TweetDetail'],'override')

    async def test_request_rewrites_query_id_and_rejects_partial_graphql_errors(self):
        self.client.query_ids={'UserTweets':'current'}
        response=SimpleNamespace(status_code=200,json=lambda:{'data':{}})
        with patch.object(self.client.http,'request',new=AsyncMock(return_value=response)) as request, \
             patch.object(self.client.client_transaction,'generate_transaction_id',return_value='signature'):
            await self.client.request('GET','https://x.com/i/api/graphql/old/UserTweets',params={'features':'{}'})
        self.assertIn('/current/UserTweets',request.call_args.args[1])
        self.assertFalse(request.call_args.kwargs['follow_redirects'])
        self.assertEqual(request.call_args.kwargs['headers']['X-Client-Transaction-Id'],'signature')
        response.json=lambda:{'data':{},'errors':[{'message':'secret'}]}
        with patch.object(self.client.http,'request',new=AsyncMock(return_value=response)), \
             patch.object(self.client.client_transaction,'generate_transaction_id',return_value='signature'):
            with self.assertRaisesRegex(RuntimeError,'不完整'):
                await self.client.request('GET','https://x.com/i/api/graphql/old/UserTweets')

    async def test_web_status_errors_do_not_trigger_other_account_requests(self):
        self.client.query_ids={'UserTweets':'current'}
        for status,message in [(429,'限流'),(403,'会话'),(404,'HTTP 404')]:
            with patch.object(self.client.http,'request',new=AsyncMock(return_value=SimpleNamespace(status_code=status))) as request, \
                 patch.object(self.client.client_transaction,'generate_transaction_id',return_value='signature'):
                with self.assertRaisesRegex(RuntimeError,message):
                    await self.client.request('GET','https://x.com/i/api/graphql/old/UserTweets')
            request.assert_awaited_once()


class XTransactionBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_split_module_and_hash_maps(self):
        html=BeautifulSoup('<script>names={59924:"ondemand.s"};hashes={59924:"abcdef123"}</script>','html.parser')
        response=SimpleNamespace(status_code=200,text='parseInt(a[2],16)*parseInt(aa[12], 16)*parseInt(x[14],16)')
        session=SimpleNamespace(get=AsyncMock(return_value=response))
        transaction=TRANSACTION.XWebTransaction()
        self.assertEqual(await transaction.get_indices(html,session,{}),(2,[12,14]))
        self.assertEqual(session.get.call_args.args[0],'https://abs.twimg.com/responsive-web/client-web/ondemand.s.abcdef123a.js')

    async def test_previous_inline_mapping_still_supported(self):
        html=BeautifulSoup('<script>chunks={"ondemand.s":"abcdef"}</script>','html.parser')
        session=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(status_code=200,text='parseInt(a[2],16)*parseInt(a[9],16)')))
        self.assertEqual(await TRANSACTION.XWebTransaction().get_indices(html,session,{}),(2,[9]))

    async def test_initialization_uses_authenticated_home_instead_of_new_logged_out_app(self):
        response=SimpleNamespace(status_code=200,content=b'<html><meta name="twitter-site-verification" content="key"></html>')
        session=SimpleNamespace(get=AsyncMock(return_value=response))
        transaction=TRANSACTION.XWebTransaction()
        with patch.object(transaction,'get_indices',new=AsyncMock(return_value=(2,[9]))), \
             patch.object(transaction,'get_key',return_value='encoded-key'), \
             patch.object(transaction,'get_key_bytes',return_value=[1,2,3]), \
             patch.object(transaction,'get_animation_key',return_value='animation'):
            await transaction.init(session,{'User-Agent':'test'})
        session.get.assert_awaited_once_with('https://x.com/home',headers={'User-Agent':'test'})
        self.assertEqual(transaction.animation_key,'animation')

    async def test_missing_resource_mapping_or_indices_fails_closed(self):
        transaction=TRANSACTION.XWebTransaction()
        session=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(status_code=200,text='changed shape')))
        for html,message in [('<html></html>','资源映射'),('<script>{"ondemand.s":"abcdef"}</script>','索引结构变化')]:
            with self.subTest(html=html),self.assertRaisesRegex(RuntimeError,message):
                await transaction.get_indices(BeautifulSoup(html,'html.parser'),session,{})


if __name__=='__main__':
    unittest.main()

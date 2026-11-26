"""Synthetic contracts for the current x-web Relay reader; no live credentials."""

import json
import unittest
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from bs4 import BeautifulSoup

from tools.debugger import import_project_module

API = import_project_module('glorybond.integrations.x')
ASSETS = import_project_module('glorybond.integrations.x_web_assets')
TRANSACTION = import_project_module('glorybond.integrations.x_transaction')
AUTH_PROVIDER = '__relay_internal__pv__xclientsfeaturesappviewerisloggedinrelayprovider'
OPTIONAL_PROVIDER = '__relay_internal__pv__optionalpresentationrelayprovider'
STAMP = int(datetime(2026, 10, 15, 4, tzinfo=timezone.utc).timestamp() * 1000)


def post(post_id, *, author='1', reply_to=None, conversation=None):
    return {
        '__typename': 'Tweet', 'rest_id': str(post_id),
        'core': {'user_results': {'result': {
            'rest_id': author, 'core': {'screen_name': 'author' + author, 'name': 'Author ' + author},
            'privacy': {'protected': False},
        }}},
        'legacy': {'lang': 'en', 'conversation_id_str': conversation or str(post_id)},
        'details': {'created_at_ms': STAMP, 'full_text': 'Full &amp; current text'},
        'counts': {'favorite_count': 7, 'reply_count': 3},
        'reply_to_results': {'rest_id': reply_to} if reply_to else None,
        'media_entities2': [{'media_url_https': 'https://pbs.twimg.com/synthetic.jpg', 'url': 'https://t.co/synthetic'}],
    }


def entry(value, *, entry_id=None):
    return {'entry_id': entry_id or 'tweet-' + value['rest_id'], 'content': {
        '__typename': 'TimelineTimelineItem',
        'content': {'__typename': 'TimelineTweet', 'tweet_results': {'result': value}},
    }}


def timeline(entries=(), *, cursor=None, pinned=None, detail=False, with_replies=False):
    instructions = [{'__typename': 'TimelineClearCache'}]
    if pinned:
        instructions.append({'__typename': 'TimelinePinEntry', 'entry': entry(pinned)})
    rows = deepcopy(list(entries))
    if cursor is not None:
        rows.append({'entry_id': 'cursor-bottom', 'content': {
            '__typename': 'TimelineTimelineCursor', 'cursor_type': 'Bottom', 'value': cursor,
        }})
    instructions.append({'__typename': 'TimelineAddEntries', 'entries': rows})
    result = {'instructions': instructions}
    if detail:
        return {'data': {'threaded_conversation_with_injections_v2': result}}
    field = 'profile_with_replies_timeline_v2' if with_replies else 'profile_user_originals_timeline'
    return {'data': {'user_result_by_screen_name': {'result': {field: {'timeline': result}}}}}


class RelayParsingTests(unittest.TestCase):
    def test_current_fields_and_note_text_preserve_full_content(self):
        value = post('15', reply_to='10', conversation='10')
        normalized = API._post(value)
        self.assertEqual(normalized['created_at'], '2026-10-15T04:00:00Z')
        self.assertEqual(normalized['text'], 'Full & current text')
        self.assertEqual((normalized['likes'], normalized['reply_count']), (7, 3))
        self.assertEqual(normalized['media_urls'], ['https://pbs.twimg.com/synthetic.jpg'])
        self.assertEqual(normalized['media_short_urls'], ['https://t.co/synthetic'])
        self.assertEqual((normalized['author_id'], normalized['conversation_id'], normalized['reply']), ('1', '10', True))
        value['note_tweet'] = {'note_tweet_results': {'result': {'text': 'Long original. ' * 500 + 'TAIL'}}}
        self.assertTrue(API._post({'__typename': 'TweetWithVisibilityResults', 'tweet': value})['text'].endswith('TAIL'))
        value['retweeted_status_results'] = {'rest_id': '9', 'result': post('9')}
        self.assertTrue(API._post(value)['retweet'])

    def test_legacy_payload_fallback_retains_timestamp_counts_and_media(self):
        value = post('15')
        for key in ('details', 'counts', 'media_entities2', 'reply_to_results'):
            value.pop(key)
        value['legacy'].update(created_at='Thu Oct 15 04:00:00 +0000 2026', full_text='Legacy',
                               favorite_count=2, reply_count=1, in_reply_to_status_id_str='10',
                               extended_entities={'media': [{'media_url_https': 'https://pbs.twimg.com/old.jpg'}]})
        row = API._post(value)
        self.assertEqual((row['text'], row['likes'], row['reply']), ('Legacy', 2, True))
        self.assertEqual(row['created_at'], '2026-10-15T04:00:00Z')
        self.assertEqual(row['media_urls'], ['https://pbs.twimg.com/old.jpg'])

    def test_snake_case_timeline_excludes_pins_ads_and_embedded_quotes(self):
        normal = post('15')
        normal['quoted_status_result'] = {'result': post('2')}
        advertised = entry(post('16'))
        advertised['content']['content']['promoted_metadata'] = {'advertiser_id': '9'}
        module = {'entry_id': 'profile-originals-conversation-1', 'content': {
            '__typename': 'TimelineTimelineModule', 'items': [
                {'item': {'content': entry(post('3'))['content']['content']}}
            ],
        }}
        rows, cursor = API._timeline_page(timeline([entry(normal), advertised, module], cursor='next', pinned=post('1')))
        self.assertEqual([r['id'] for r in rows], ['15', '3'])
        self.assertEqual([r['_timeline_bound'] for r in rows], [True, False])
        self.assertEqual(cursor, 'next')
        for detail, with_replies in ((True, False), (False, True)):
            rows, _ = API._timeline_page(timeline([entry(post('15'))], detail=detail, with_replies=with_replies), detail=detail)
            self.assertEqual([r['id'] for r in rows], ['15'])

    def test_invalid_bottom_cursor_and_missing_instructions_fail_closed(self):
        for payload in (timeline(cursor=''), timeline(cursor=123), {'data': {}}):
            with self.subTest(payload=payload), self.assertRaises(API.XWebError):
                API._timeline_page(payload)
        self.assertEqual(API._timeline_page(timeline()), ([], None))

    def test_recognized_tweet_missing_result_is_not_an_empty_timeline(self):
        broken = entry(post('15'))
        broken['content']['content']['tweet_results'] = {}
        with self.assertRaises(API.XWebError):
            API._timeline_page(timeline([broken]))

    def test_incremental_scan_keeps_module_non_bound_and_stable_author_filter(self):
        module = {'entry_id': 'profile-originals-conversation-1', 'content': {
            '__typename': 'TimelineTimelineModule', 'items': [{'item': {'content': entry(post('2'))['content']['content']}}],
        }}
        gql = SimpleNamespace(user_tweets=AsyncMock(side_effect=[
            (timeline([module, entry(post('14')), entry(post('99', author='2'))], cursor='older'), None),
            (timeline([entry(post('13')), entry(post('10'))]), None),
        ]))
        client = SimpleNamespace(prepare=AsyncMock(), http=SimpleNamespace(aclose=AsyncMock()), gql=gql)
        with patch.object(API, 'XWebClient', return_value=client), \
             patch.dict(API.x_subscription_config, auth_token='session-secret', ct0='csrf-secret', exclude=['replies', 'retweets']):
            rows = API.x_get_posts('1', since_id='10')
        self.assertEqual([row['id'] for row in rows], ['14', '13'])
        self.assertEqual(gql.user_tweets.await_count, 2)
        client.http.aclose.assert_awaited_once()


class RelayRequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = patch.dict(API.x_subscription_config, auth_token='session-secret', ct0='csrf-secret')
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = API.XWebClient()
        self.addAsyncCleanup(self.client.http.aclose)
        self.client.client_transaction.assets = SimpleNamespace(query=AsyncMock(return_value=('current-query', [AUTH_PROVIDER, OPTIONAL_PROVIDER])))

    async def test_stable_id_redirect_resolves_renamed_profile_once(self):
        response = httpx.Response(307, headers={'location': '/renamed_author'})
        with patch.object(self.client.http, 'get', new=AsyncMock(return_value=response)) as get:
            self.assertEqual(await self.client._screen_name('123'), 'renamed_author')
            self.assertEqual(await self.client._screen_name('123'), 'renamed_author')
        get.assert_awaited_once_with('https://x.com/i/user/123', follow_redirects=False)

    async def test_untrusted_and_non_profile_redirects_are_rejected(self):
        locations = ['https://evil.test/profile', '//evil.test/profile', 'https://x.com@evil.test/profile',
                     'https://user@x.com/profile', 'https://x.com:444/profile', '/i/flow/login', '/home',
                     '/login', '/profile/status/123', '/profile?token=secret', '/profile#secret', '']
        for location in locations:
            with self.subTest(location=location), \
                 patch.object(self.client.http, 'get', new=AsyncMock(return_value=httpx.Response(307, headers={'location': location}))), \
                 self.assertRaises(API.XWebError):
                await self.client._screen_name('123')
        self.assertEqual(self.client._screen_names, {})

    async def test_logical_operations_map_to_current_relay_parameters(self):
        cases = [
            ('UserByScreenName', {'screen_name': 'author'}, 'UserByScreenName', {'screenName': 'author', 'withIdentity': True}),
            ('UserTweets', {'userId': '123', 'count': 20, 'cursor': 'next'}, 'UserOriginalsTimeline',
             {'screenName': 'renamed_author', 'count': 20, 'cursor': 'next', 'sortByMostLiked': False}),
            ('UserTweetsAndReplies', {'userId': '123', 'count': 20}, 'UserTweets',
             {'screenName': 'renamed_author', 'count': 20, 'cursor': None, 'sortByMostLiked': False}),
            ('TweetDetail', {'focalTweetId': '15'}, 'TweetDetail',
             {'focalTweetId': '15', 'cursor': None, 'rankingMode': 'Relevance', 'referrer': None, 'withFocalTweet': True}),
            ('TweetDetail', {'focalTweetId': '15', 'cursor': 'next'}, 'TweetDetail',
             {'focalTweetId': '15', 'cursor': 'next', 'rankingMode': 'Relevance', 'referrer': None, 'withFocalTweet': False}),
        ]
        with patch.object(self.client, '_screen_name', new=AsyncMock(return_value='renamed_author')):
            for logical, variables, wire, expected in cases:
                with self.subTest(operation=logical, cursor=variables.get('cursor')):
                    url, params = await self.client._relay_request(logical, {'variables': json.dumps(variables), 'features': '{}'})
                    self.assertEqual(url, f'https://api.x.com/graphql/current-query/{wire}')
                    self.assertEqual(set(params), {'variables'})
                    self.assertEqual(json.loads(params['variables']), {**expected, AUTH_PROVIDER: True, OPTIONAL_PROVIDER: False})
                    self.client.client_transaction.assets.query.assert_awaited_with(wire)

    async def test_request_signs_rewritten_api_path_and_sends_cookie_only_to_x(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={'data': {}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as session:
            session.cookies.set('auth_token', 'session-secret', domain='.x.com', path='/')
            session.cookies.set('ct0', 'csrf-secret', domain='.x.com', path='/')
            with patch.object(self.client, 'http', session), \
                 patch.object(self.client, 'relay', True), \
                 patch.object(self.client.client_transaction, 'generate_transaction_id', return_value='signature') as sign:
                await self.client.request('GET', 'https://x.com/i/api/graphql/stale/UserByScreenName',
                                          params={'variables': '{"screen_name":"author"}'})
                sign.assert_called_once_with(method='GET', path='/graphql/current-query/UserByScreenName')
                self.assertEqual(requests[-1].url.host, 'api.x.com')
                self.assertIn('session-secret', requests[-1].headers['cookie'])
                self.assertEqual(requests[-1].headers['X-Client-Transaction-Id'], 'signature')
                await session.get('https://abs.twimg.com/x-web/x-web/assets/public.js')
                self.assertNotIn('cookie', requests[-1].headers)


class RelayAssetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cache = patch.object(ASSETS, '_CACHE', OrderedDict())
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.base = 'https://abs.twimg.com/x-web/x-web/'
        self.seen = []
        self.sources = {
            'entry-test.js': 'import{boot}from"./assets/runtime-test.js";throw Error("must never execute");',
            'assets/runtime-test.js': (
                'function signature(){return import(`./signature-test.js`)};headers.set(`x-client-transaction-id`,sig);'
                'const component=()=>import(`./unused-test.js`),loader=()=>import(`./original-loader.js`);route(`/$username/_profile/`);'
                'const allLoader=()=>import(`./all-loader.js`);route(`/$username/_profile/all`);'
                'async function detail(){let{preloadConversation:p}=await import(`./detail-loader.js`)};'
                f'const q={{params:{{id:`user-id`,metadata:{{}},name:`UserByScreenName`,operationKind:`query`,text:null,providedVariables:{{{AUTH_PROVIDER}:a}}}}}};'
            ),
            'assets/signature-test.js': 'wrap(k[11],16)*wrap(k[25],16)*wrap(k[3],16)*wrap(k[45],16)',
            'assets/original-loader.js': 'export{q}from"./original-query.js";',
            'assets/original-query.js': f'var q={{params:{{id:`original-id`,metadata:{{}},name:`UserOriginalsTimeline`,operationKind:`query`,text:null,providedVariables:{{{AUTH_PROVIDER}:a,{OPTIONAL_PROVIDER}:b}}}}}};',
            'assets/all-loader.js': 'export{q}from"./all-query.js";',
            'assets/all-query.js': 'var q={params:{id:"all-id",metadata:{},name:"UserTweets",operationKind:"query",text:null}};',
            'assets/detail-loader.js': 'export{q as preloadConversation}from"./detail-query.js";',
            'assets/detail-query.js': 'var q={params:{id:"detail-id",metadata:{},name:"TweetDetail",operationKind:"query",text:null}};',
        }
        def respond(request):
            self.seen.append(request)
            path = str(request.url).removeprefix(self.base)
            value = self.sources.get(path)
            if isinstance(value, httpx.Response):
                return value
            return httpx.Response(200 if value is not None else 404, text=value or '')
        self.session = httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False, trust_env=False)
        self.session.cookies.set('auth_token', 'session-secret', domain='.x.com', path='/')
        self.addAsyncCleanup(self.session.aclose)
        self.assets = ASSETS.XWebAssets(self.base + 'entry-test.js', self.session, {'User-Agent': 'test'})

    async def test_discovers_public_signature_and_relay_queries_without_execution(self):
        await self.assets.bootstrap()
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(await self.assets.query('UserByScreenName'), ('user-id', [AUTH_PROVIDER]))
        self.assertIn('k[11]', await self.assets.signature_source())
        self.assertEqual(await self.assets.query('UserOriginalsTimeline'), ('original-id', [AUTH_PROVIDER, OPTIONAL_PROVIDER]))
        self.assertEqual(await self.assets.query('UserTweets'), ('all-id', []))
        self.assertEqual(await self.assets.query('TweetDetail'), ('detail-id', []))
        self.assertTrue(all('cookie' not in request.headers and 'authorization' not in request.headers for request in self.seen))
        self.assertFalse(any('unused-test.js' in str(request.url) for request in self.seen))
        self.assertTrue(all('session-secret' not in source for source in ASSETS._CACHE.values()))
        before = len(self.seen)
        other = ASSETS.XWebAssets(self.base + 'entry-test.js', self.session, {})
        await other.bootstrap()
        self.assertEqual(len(self.seen), before)

    async def test_signature_indices_support_obfuscated_wrappers_and_reject_changed_count(self):
        await self.assets.bootstrap()
        transaction = TRANSACTION.XWebTransaction()
        transaction.assets = self.assets
        self.assertEqual(await transaction.get_indices(BeautifulSoup('', 'html.parser'), self.session, {}), (11, [25, 3, 45]))
        with patch.object(self.assets, 'signature_source', new=AsyncMock(return_value='wrap(k[11],16)')):
            with self.assertRaisesRegex(API.XWebError, '索引结构变化'):
                await transaction.get_indices(BeautifulSoup('', 'html.parser'), self.session, {})

    async def test_rejects_external_paths_redirects_and_never_caches_failed_response(self):
        for url in ['https://evil.test/public.js', self.base + '../outside.js',
                    self.base + 'entry-test.js?secret=value', 'https://abs.twimg.com:444/x-web/x-web/a.js',
                    'https://user@abs.twimg.com/x-web/x-web/a.js', self.base + 'entry-test.js#fragment']:
            with self.subTest(url=url), self.assertRaises(API.XWebError):
                await self.assets.load(url)
        self.assertEqual(self.seen, [])
        self.sources['assets/redirect.js'] = httpx.Response(302, headers={'location': 'https://evil.test/script.js'})
        with self.assertRaisesRegex(API.XWebError, 'HTTP 302'):
            await self.assets.load(self.base + 'assets/redirect.js')
        self.assertEqual(len(self.seen), 1)
        self.assertNotIn(self.base + 'assets/redirect.js', ASSETS._CACHE)

    async def test_asset_discovery_and_download_have_hard_budgets(self):
        for index in range(25):
            self.sources[f'assets/bounded-{index}.js'] = '/* public */'
        for index in range(24):
            await self.assets.load(self.base + f'assets/bounded-{index}.js')
        with self.assertRaisesRegex(API.XWebError, '超过预算'):
            await self.assets.load(self.base + 'assets/bounded-24.js')
        self.assertEqual(len(self.seen), 24)
        oversized = ASSETS.XWebAssets(self.base + 'entry-test.js', self.session, {})
        self.sources['assets/oversized.js'] = 'x' * (4 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(API.XWebError, '超过大小预算'):
            await oversized.load(self.base + 'assets/oversized.js')
        self.assertNotIn(self.base + 'assets/oversized.js', ASSETS._CACHE)


if __name__ == '__main__':
    unittest.main()

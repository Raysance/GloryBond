"""Read X's website GraphQL through a cookie session; no developer API calls.

Twikit supplies the website protocol and transaction signatures. This module
owns operation discovery, read-only requests, parsing, filtering and pagination.
"""

import asyncio
import json
import re
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx
from twikit import Client
from twikit.errors import TooManyRequests, Unauthorized, Forbidden, AccountLocked, AccountSuspended

from .proxy import clash_request
from .x_transaction import XWebTransaction
from .x_web_assets import XWebError
from ..zstatic import clash_proxy_url, x_subscription_config
from ..ztime import parse_chat_time_bound, utc_timestamp_text


def x_username(value):
    text = str(value or "").strip()
    if text.startswith(("https://", "http://")):
        parsed = urlparse(text)
        if parsed.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            raise ValueError("请输入 X 用户名、@用户名或 x.com 账号主页链接")
        text = parsed.path.strip("/")
    text = text.removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", text):
        raise ValueError("请输入 X 用户名、@用户名或 x.com 账号主页链接，不支持显示昵称搜索")
    return text


class XWebClient(Client):
    """Expose only GET operations needed for public account subscriptions."""

    def __init__(self):
        super().__init__(language=x_subscription_config["language"], proxy=clash_proxy_url,
                         user_agent=x_subscription_config["user_agent"], trust_env=False,
                         timeout=x_subscription_config["timeout_seconds"], follow_redirects=False)
        self.query_ids = {}
        self.relay = False
        self._screen_names = {}
        self.client_transaction = XWebTransaction()
        self.set_cookies({key: x_subscription_config[key] for key in ("auth_token", "ct0")})

    def set_cookies(self, cookies, clear_cookies=False):
        if clear_cookies:
            self.http.cookies.clear()
        for name, value in cookies.items():
            # Transaction setup also fetches static assets; keep session cookies
            # scoped to X even when Twikit backs up and restores its cookie jar.
            self.http.cookies.set(name, value, domain=".x.com", path="/")

    def _remove_duplicate_ct0_cookie(self):
        cookies = {cookie.name: cookie.value for cookie in self.http.cookies.jar}
        self.set_cookies(cookies, clear_cookies=True)

    async def prepare(self):
        await self.client_transaction.init(self.http, {
            "User-Agent": x_subscription_config["user_agent"],
            "Accept-Language": x_subscription_config["language"],
        })
        page = self.client_transaction.home_page_response
        self.query_ids = dict(x_subscription_config.get("web_query_ids") or {})
        self.relay = getattr(self.client_transaction, "assets", None) is not None
        if self.relay:
            return
        scripts = [urljoin("https://x.com", tag.get("src", "")) for tag in page.select("script[src]")]
        main_urls = [url for url in scripts if urlparse(url).scheme == "https" and urlparse(url).hostname == "abs.twimg.com"
                     and re.search(r"/main\.[^/]+\.js$", urlparse(url).path)]
        if main_urls:
            response = await self.http.get(main_urls[0])
            response.raise_for_status()
            pattern = r'''["']?queryId["']?\s*:\s*["']([\w-]+)["']\s*,\s*["']?operationName["']?\s*:\s*["'](\w+)["']'''
            discovered = {name: query_id for query_id, name in re.findall(pattern, response.text)}
            self.query_ids = {**discovered, **self.query_ids}

    async def _screen_name(self, user_id):
        if not re.fullmatch(r"[0-9]{1,19}", str(user_id)):
            raise XWebError("无效的 X 用户 ID")
        if user_id not in self._screen_names:
            response = await self.http.get(f"https://x.com/i/user/{user_id}", follow_redirects=False)
            destination = urlparse(urljoin("https://x.com", response.headers.get("location", "")))
            if (response.status_code not in {301, 302, 303, 307, 308}
                    or destination.scheme != "https" or destination.netloc != "x.com"
                    or destination.query or destination.fragment
                    or not re.fullmatch(r"/[A-Za-z0-9_]{1,15}", destination.path)
                    or destination.path.lower() in {"/home", "/login", "/logout", "/explore", "/i"}):
                raise XWebError("X 网页账号 ID 解析失败，请检查会话或账号状态；本次保留游标")
            self._screen_names[user_id] = destination.path[1:]
        return self._screen_names[user_id]

    async def _relay_request(self, operation, params):
        variables = json.loads(params.get("variables") or "{}")
        if operation == "UserByScreenName":
            variables = {"screenName": variables["screen_name"], "withIdentity": True}
        elif operation in {"UserTweets", "UserTweetsAndReplies"}:
            name = await self._screen_name(variables["userId"])
            variables = {"screenName": name, "count": variables["count"],
                         "cursor": variables.get("cursor"), "sortByMostLiked": False}
            operation = "UserOriginalsTimeline" if operation == "UserTweets" else "UserTweets"
        else:
            variables = {"focalTweetId": variables["focalTweetId"], "cursor": variables.get("cursor"),
                         "rankingMode": "Relevance", "referrer": None, "withFocalTweet": not variables.get("cursor")}
        query_id, providers = await self.client_transaction.assets.query(operation)
        query_id = self.query_ids.get(operation, query_id)
        if not re.fullmatch(r"[\w-]+", query_id):
            raise XWebError("X 网页操作标识无效，本次保留游标")
        # Optional presentation features stay disabled; authentication reflects
        # this cookie-session reader. No scripts or provider functions execute.
        for provider in providers:
            variables[provider] = provider == "__relay_internal__pv__xclientsfeaturesappviewerisloggedinrelayprovider"
        return f"https://api.x.com/graphql/{query_id}/{operation}", {"variables": json.dumps(variables)}

    async def request(self, method, url, **kwargs):
        parsed = urlparse(url)
        operation = parsed.path.rsplit("/", 1)[-1]
        allowed = {"UserByScreenName", "UserTweets", "UserTweetsAndReplies", "TweetDetail"}
        if method.upper() != "GET" or parsed.scheme != "https" or parsed.hostname != "x.com" or operation not in allowed:
            raise ValueError("X 网页读取器拒绝非订阅读取请求")
        params = dict(kwargs.get("params") or {})
        if self.relay:
            url, params = await self._relay_request(operation, params)
        else:
            query_id = self.query_ids.get(operation)
            if not query_id or not re.fullmatch(r"[\w-]+", query_id):
                raise XWebError("X 网页操作标识缺失，请更新网页适配或 XSubscriptions.web_query_ids")
            url = f"https://x.com/i/api/graphql/{query_id}/{operation}"
            features = json.loads(params.get("features") or "{}")
            features.update(x_subscription_config.get("web_features") or {})
            params["features"] = json.dumps(features)
        kwargs["params"] = params
        headers = dict(kwargs.pop("headers", None) or self._base_headers)
        headers["X-Client-Transaction-Id"] = self.client_transaction.generate_transaction_id(method="GET", path=urlparse(url).path)
        response = await self.http.request("GET", url, headers=headers, follow_redirects=False, **kwargs)
        self._remove_duplicate_ct0_cookie()
        if response.status_code == 429:
            raise XWebError("X 网页请求被限流，请稍后重试")
        if response.status_code in {401, 403}:
            raise XWebError("X 网页会话不可用，请在浏览器确认登录状态并更新 auth_token 与 ct0")
        if response.status_code != 200:
            raise XWebError(f"X 网页接口 HTTP {response.status_code}，本次保留游标")
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise XWebError("X 网页未返回有效数据，本次保留游标") from None
        if not isinstance(payload, dict) or payload.get("errors"):
            raise XWebError("X 网页返回错误或不完整数据，本次保留游标")
        return payload, response


def _run(action):
    if not all(str(x_subscription_config.get(key) or "").strip() for key in ("auth_token", "ct0")):
        raise ValueError("X 网页会话尚未配置，请在现有 .env 设置 HOK_X_AUTH_TOKEN 和 HOK_X_CT0")
    if not clash_proxy_url:
        raise ValueError("X 网页读取需要配置现有 Proxy.clash_url")

    async def execute():
        client = XWebClient()
        try:
            async def work():
                await client.prepare()
                return await action(client)
            return await asyncio.wait_for(work(), timeout=x_subscription_config["operation_timeout_seconds"])
        finally:
            await client.http.aclose()

    try:
        return asyncio.run(execute())
    except XWebError:
        raise
    except TooManyRequests:
        raise XWebError("X 网页请求被限流，请稍后重试") from None
    except (Unauthorized, Forbidden, AccountLocked, AccountSuspended):
        raise XWebError("X 网页会话不可用，请在浏览器确认登录状态并更新 auth_token 与 ct0") from None
    except (TimeoutError, httpx.TimeoutException):
        raise XWebError("X 网页读取超时，请稍后重试；本次保留游标") from None
    except httpx.RequestError:
        raise XWebError("X 网页网络或代理连接失败，请稍后重试；本次保留游标") from None
    except Exception as exc:
        raise XWebError(f"X 网页适配失败（{type(exc).__name__}），请检查网页接口变化；本次保留游标") from None


def _user(result):
    if not isinstance(result, dict) or not re.fullmatch(r"[0-9]{1,19}", str(result.get("rest_id", ""))):
        raise XWebError("未找到可读取的公开 X 账号")
    legacy, core = result.get("legacy") or {}, result.get("core") or {}
    if legacy.get("protected") or (result.get("privacy") or {}).get("protected"):
        raise XWebError("X 订阅仅支持公开账号")
    username = x_username(core.get("screen_name") or legacy.get("screen_name"))
    return {"id": str(result["rest_id"]), "username": username,
            "name": str(core.get("name") or legacy.get("name") or username)}


def x_get_user(username):
    username = x_username(username)
    async def action(client):
        payload, _ = await client.gql.user_by_screen_name(username)
        data = payload.get("data") or {}
        return _user((data.get("user_result_by_screen_name") or data.get("user") or {}).get("result"))
    return _run(action)


def _post(result):
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}
    if result.get("__typename") in {"TweetTombstone", "TweetUnavailable"}:
        return None
    legacy = result.get("legacy")
    if not isinstance(legacy, dict):
        raise XWebError("X 网页帖子结构变化，本次保留游标")
    post_id = str(result.get("rest_id") or legacy.get("id_str") or "")
    details = result.get("details") or {}
    created_at = details.get("created_at_ms")
    if created_at is not None:
        created_epoch = float(created_at) / 1000
    else:
        created_epoch = parse_chat_time_bound(legacy["created_at"]) if legacy.get("created_at") else None
    if not re.fullmatch(r"[0-9]{1,19}", post_id) or created_epoch is None:
        raise XWebError("X 网页帖子缺少 ID 或发布时间，本次保留游标")
    user = _user(((result.get("core") or {}).get("user_results") or {}).get("result"))
    note = ((result.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}
    media = result.get("media_entities2") or (legacy.get("extended_entities") or {}).get("media") or []
    counts = result.get("counts") or legacy
    references = {"retweet": bool(legacy.get("retweeted_status_result") or result.get("retweeted_status_result")
                                  or result.get("retweeted_status_results")),
                  "reply": bool(legacy.get("in_reply_to_status_id_str") or (result.get("reply_to_results") or {}).get("rest_id"))}
    return {"id": post_id, "text": unescape(str(note.get("text") or details.get("full_text") or legacy.get("full_text") or "")),
            "created_at": utc_timestamp_text(created_epoch),
            "lang": legacy.get("lang"), "username": user["username"], "name": user["name"],
            "author_id": user["id"], "conversation_id": str(legacy.get("conversation_id_str") or post_id),
            "likes": int(counts.get("favorite_count") or 0), "reply_count": int(counts.get("reply_count") or 0),
            "media_urls": [row["media_url_https"] for row in media if row.get("media_url_https")],
            "media_short_urls": [row['url'] for row in media if row.get('url')],
            **references}


def _timeline_page(payload, *, detail=False):
    data = payload.get("data") or {}
    if detail:
        timeline = data.get("threaded_conversation_with_injections_v2") or data.get("threaded_conversation_with_injections") or {}
    else:
        user = (data.get("user_result_by_screen_name") or data.get("user") or {}).get("result") or {}
        timeline = (user.get("profile_user_originals_timeline") or user.get("profile_with_replies_timeline_v2")
                    or user.get("timeline_v2") or user.get("timeline") or {})
        timeline = timeline.get("timeline") or timeline
    instructions = timeline.get("instructions")
    if not isinstance(instructions, list):
        raise XWebError("X 网页时间线结构变化，本次保留游标")
    entries = []
    for instruction in instructions:
        if (instruction.get("type") or instruction.get("__typename")) == "TimelinePinEntry":
            continue
        entries.extend(instruction.get("entries") or instruction.get("moduleItems") or instruction.get("module_items") or [])
        if instruction.get("entry"):
            entries.append(instruction["entry"])
    posts, cursor = {}, None

    def read_content(content, can_bound=False):
        nonlocal cursor
        if not isinstance(content, dict) or content.get("promotedMetadata") or content.get("promoted_metadata"):
            return
        item = content.get("itemContent") or content.get("content") or content
        if item.get("promotedMetadata") or item.get("promoted_metadata"):
            return
        if (item.get("cursorType") or item.get("cursor_type")) == "Bottom":
            cursor = item.get("value")
            if not isinstance(cursor, str) or not cursor:
                raise XWebError("X 网页分页游标结构变化，本次保留游标")
        if item.get("__typename") == "TimelineTweet" and not isinstance(item.get("tweet_results"), dict):
            raise XWebError("X 网页帖子结构变化，本次保留游标")
        if isinstance(item.get("tweet_results"), dict):
            result = item["tweet_results"].get("result")
            if not isinstance(result, dict) or not result:
                raise XWebError("X 网页帖子结果缺失，本次保留游标")
            post = _post(result)
            if post:
                post["_timeline_bound"] = can_bound
                posts[post["id"]] = post
        for child in content.get("items") or []:
            read_content(child.get("item") or child)

    for entry in entries:
        entry_id = str(entry.get("entryId") or entry.get("entry_id") or "")
        if entry_id.startswith(("promoted", "tweetdetailrelatedtweets")):
            continue
        read_content(entry.get("content") or entry.get("item") or {},
                     can_bound=entry_id.startswith("tweet-"))
    return list(posts.values()), cursor


def x_get_posts(user_id, *, since_id=None, start_time=None, latest=False):
    if not re.fullmatch(r"[0-9]{1,19}", str(user_id)):
        raise ValueError("无效的 X 用户 ID")
    cutoff = int(since_id or 0)
    start_epoch = parse_chat_time_bound(start_time) if not cutoff and start_time else None
    async def action(client):
        posts, cursor, visited = {}, None, set()
        for _ in range(int(x_subscription_config["max_pages"])):
            method = client.gql.user_tweets if "replies" in x_subscription_config["exclude"] else client.gql.user_tweets_and_replies
            payload, _ = await method(str(user_id), int(x_subscription_config["page_size"]), cursor)
            rows, next_cursor = _timeline_page(payload)
            reached = False
            for row in rows:
                if row["author_id"] != str(user_id):
                    continue
                if ("replies" in x_subscription_config["exclude"] and row["reply"]) or ("retweets" in x_subscription_config["exclude"] and row["retweet"]):
                    continue
                if int(row["id"]) <= cutoff or (start_epoch is not None and parse_chat_time_bound(row["created_at"]) < start_epoch):
                    reached = reached or row["_timeline_bound"]
                    continue
                posts[row["id"]] = row
            if (latest and posts) or reached or not next_cursor:
                return sorted(posts.values(), key=lambda row: int(row["id"]), reverse=True)
            if next_cursor in visited:
                raise XWebError("X 网页分页游标重复，本次保留增量游标")
            visited.add(next_cursor)
            cursor = next_cursor
        raise XWebError("X 网页分页超过 max_pages，请增大预算；本次保留游标避免漏推")
    return _run(action)


def x_get_replies(post_id):
    if not re.fullmatch(r"[0-9]{1,19}", str(post_id)):
        raise ValueError("无效的 X 帖子 ID")
    async def action(client):
        samples, cursor, visited = {}, None, set()
        limit = int(x_subscription_config["reply_sample_size"])
        for _ in range(int(x_subscription_config["max_pages"])):
            payload, _ = await client.gql.tweet_detail(str(post_id), cursor)
            rows, next_cursor = _timeline_page(payload, detail=True)
            for row in rows:
                if row["id"] != str(post_id) and row["conversation_id"] == str(post_id) and row["reply"]:
                    samples.setdefault(row["id"], row)
                    if len(samples) >= limit:
                        break
            if len(samples) >= limit or not next_cursor or next_cursor in visited:
                break
            visited.add(next_cursor)
            cursor = next_cursor
        ranked = sorted(samples.values(), key=lambda row: (row["likes"], int(row["id"])), reverse=True)
        return {"replies": ranked[:int(x_subscription_config["reply_count"])], "sample_size": len(samples)}
    return _run(action)


def x_get_media_bytes(url):
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or parsed.hostname != "pbs.twimg.com" or parsed.username or parsed.password:
        raise ValueError("X 媒体仅允许 HTTPS pbs.twimg.com")
    limit = int(x_subscription_config["max_media_bytes"])
    try:
        response = clash_request("GET", url, timeout=x_subscription_config["timeout_seconds"],
                                 allow_redirects=False, stream=True)
        try:
            if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
                raise ValueError("not an image")
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError("image too large")
            return bytes(data)
        finally:
            response.close()
    except Exception:
        raise RuntimeError("X 原帖图片读取失败") from None

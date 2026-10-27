"""Read X's website GraphQL through a cookie session; no developer API calls.

Twikit supplies the website protocol and transaction signatures. This module
owns operation discovery, read-only requests, parsing, filtering and pagination.
"""

import asyncio
import json
import re
from html import unescape
from urllib.parse import urljoin, urlparse

from twikit import Client
from twikit.errors import TooManyRequests, Unauthorized, Forbidden, AccountLocked, AccountSuspended

from .proxy import clash_request
from .x_transaction import XWebTransaction
from ..zstatic import clash_proxy_url, x_subscription_config
from ..ztime import parse_chat_time_bound, utc_timestamp_text


class XWebError(RuntimeError):
    """A credential-free diagnostic safe for the QQ command boundary."""


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
        scripts = [urljoin("https://x.com", tag.get("src", "")) for tag in page.select("script[src]")]
        main_urls = [url for url in scripts if urlparse(url).scheme == "https" and urlparse(url).hostname == "abs.twimg.com"
                     and re.search(r"/main\.[^/]+\.js$", urlparse(url).path)]
        if main_urls:
            response = await self.http.get(main_urls[0])
            response.raise_for_status()
            pattern = r'''["']?queryId["']?\s*:\s*["']([\w-]+)["']\s*,\s*["']?operationName["']?\s*:\s*["'](\w+)["']'''
            discovered = {name: query_id for query_id, name in re.findall(pattern, response.text)}
            self.query_ids = {**discovered, **self.query_ids}

    async def request(self, method, url, **kwargs):
        parsed = urlparse(url)
        operation = parsed.path.rsplit("/", 1)[-1]
        allowed = {"UserByScreenName", "UserTweets", "UserTweetsAndReplies", "TweetDetail"}
        if method.upper() != "GET" or parsed.scheme != "https" or parsed.hostname != "x.com" or operation not in allowed:
            raise ValueError("X 网页读取器拒绝非订阅读取请求")
        query_id = self.query_ids.get(operation)
        if not query_id or not re.fullmatch(r"[\w-]+", query_id):
            raise XWebError("X 网页操作标识缺失，请更新网页适配或 XSubscriptions.web_query_ids")
        url = f"https://x.com/i/api/graphql/{query_id}/{operation}"
        params = dict(kwargs.get("params") or {})
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
    except Exception:
        raise XWebError("X 网页读取失败，请检查会话、代理或网页接口变化；本次保留游标") from None


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
        return _user(((payload.get("data") or {}).get("user") or {}).get("result"))
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
    if not re.fullmatch(r"[0-9]{1,19}", post_id) or not legacy.get("created_at"):
        raise XWebError("X 网页帖子缺少 ID 或发布时间，本次保留游标")
    user = _user(((result.get("core") or {}).get("user_results") or {}).get("result"))
    note = ((result.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}
    media = (legacy.get("extended_entities") or {}).get("media") or []
    references = {"retweet": bool(legacy.get("retweeted_status_result") or result.get("retweeted_status_result")),
                  "reply": bool(legacy.get("in_reply_to_status_id_str"))}
    return {"id": post_id, "text": unescape(str(note.get("text") or legacy.get("full_text") or "")),
            "created_at": utc_timestamp_text(parse_chat_time_bound(legacy["created_at"])),
            "lang": legacy.get("lang"), "username": user["username"], "name": user["name"],
            "author_id": user["id"], "conversation_id": str(legacy.get("conversation_id_str") or post_id),
            "likes": int(legacy.get("favorite_count") or 0), "reply_count": int(legacy.get("reply_count") or 0),
            "media_urls": [row["media_url_https"] for row in media if row.get("media_url_https")],
            "media_short_urls": [row['url'] for row in media if row.get('url')],
            **references}


def _timeline_page(payload, *, detail=False):
    data = payload.get("data") or {}
    if detail:
        timeline = data.get("threaded_conversation_with_injections_v2") or data.get("threaded_conversation_with_injections") or {}
    else:
        user = (data.get("user") or {}).get("result") or {}
        timeline = user.get("timeline_v2") or user.get("timeline") or {}
        timeline = timeline.get("timeline") or timeline
    instructions = timeline.get("instructions")
    if not isinstance(instructions, list):
        raise XWebError("X 网页时间线结构变化，本次保留游标")
    entries = []
    for instruction in instructions:
        if instruction.get("type") == "TimelinePinEntry":
            continue
        entries.extend(instruction.get("entries") or instruction.get("moduleItems") or [])
        if instruction.get("entry"):
            entries.append(instruction["entry"])
    posts, cursor = {}, None

    def read_content(content, can_bound=False):
        nonlocal cursor
        if not isinstance(content, dict) or content.get("promotedMetadata"):
            return
        item = content.get("itemContent") or content
        if item.get("promotedMetadata"):
            return
        if item.get("cursorType") == "Bottom":
            cursor = item.get("value")
        if isinstance(item.get("tweet_results"), dict):
            result = item["tweet_results"].get("result")
            if result:
                post = _post(result)
                if post:
                    post["_timeline_bound"] = can_bound
                    posts[post["id"]] = post
        for child in content.get("items") or []:
            read_content(child.get("item") or child)

    for entry in entries:
        if str(entry.get("entryId", "")).startswith(("promoted", "tweetdetailrelatedtweets")):
            continue
        read_content(entry.get("content") or entry.get("item") or {},
                     can_bound=str(entry.get("entryId", "")).startswith("tweet-"))
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

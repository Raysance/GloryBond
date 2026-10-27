"""Bilibili esports and video API adapters."""

import hashlib
import re
import urllib.parse

import requests

from ..ztime import current_timestamp

class BilibiliEsportsAPI:
    API_BASE = "https://api.bilibili.com/x/esports"
    REQUEST_HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bilibili.com/v/game/match/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }

    @classmethod
    def get_json(cls, path_or_url, *, params=None):
        """Request and validate a Bilibili esports JSON response."""
        url = str(path_or_url or "")
        if url.startswith("/"):
            url = f"{cls.API_BASE}{url}"
        url = url.replace("http://", "https://", 1)
        response = requests.get(url, params=params, headers=cls.REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise Exception(f"bilibili_esports_api_error: non-dict response url={url} params={params}")
        if payload.get("code") not in (0, "0", None):
            raise Exception(
                f"bilibili_esports_api_error: url={url} params={params} "
                f"code={payload.get('code')} message={payload.get('message')!r}"
            )
        return payload

    @classmethod
    def get_bytes(cls, url):
        """Fetch a binary asset referenced by Bilibili esports JSON."""
        url = str(url or "").replace("http://", "https://", 1)
        if not url:
            raise ValueError("bilibili_esports_asset_error: empty url")
        response = requests.get(url, headers=cls.REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
        return response.content


def bilibili_esports_get_json(path_or_url, *, params=None):
    return BilibiliEsportsAPI.get_json(path_or_url, params=params)


def bilibili_esports_get_bytes(url):
    return BilibiliEsportsAPI.get_bytes(url)


class BilibiliVideoAPI:
    API_BASE = "https://api.bilibili.com"
    REQUEST_HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bilibili.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }
    MIXIN_KEY_ENC_TAB = [
        46, 47, 18, 2, 53, 8, 23, 32,
        15, 50, 10, 31, 58, 3, 45, 35,
        27, 43, 5, 49, 33, 9, 42, 19,
        29, 28, 14, 39, 12, 38, 41, 13,
        37, 48, 7, 16, 24, 55, 40, 61,
        26, 17, 0, 1, 60, 51, 30, 4,
        22, 25, 54, 21, 56, 59, 6, 63,
        57, 62, 11, 36, 20, 34, 44, 52,
    ]
    _wbi_keys = None
    _wbi_keys_ts = 0

    @classmethod
    def _request_json(cls, path_or_url, *, params=None, headers=None):
        url = str(path_or_url or "")
        if url.startswith("/"):
            url = f"{cls.API_BASE}{url}"
        request_headers = dict(cls.REQUEST_HEADERS)
        request_headers.update(headers or {})
        response = requests.get(url, params=params, headers=request_headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise Exception(f"bilibili_video_api_error: non-dict response url={url} params={params}")
        code = payload.get("code")
        if code not in (0, "0", -101):
            raise Exception(
                f"bilibili_video_api_error: url={url} params={params} "
                f"code={code} message={payload.get('message')!r}"
            )
        return payload

    @classmethod
    def _get_wbi_keys(cls):
        now = current_timestamp()
        if cls._wbi_keys and now - cls._wbi_keys_ts < 12 * 60 * 60:
            return cls._wbi_keys
        payload = cls._request_json("/x/web-interface/nav")
        wbi_img = ((payload.get("data") or {}).get("wbi_img") or {})
        img_url = str(wbi_img.get("img_url") or "")
        sub_url = str(wbi_img.get("sub_url") or "")
        img_key = img_url.rsplit("/", 1)[-1].split(".", 1)[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".", 1)[0]
        if not img_key or not sub_key:
            raise Exception(f"bilibili_video_wbi_error: empty wbi keys payload={payload}")
        cls._wbi_keys = (img_key, sub_key)
        cls._wbi_keys_ts = now
        return cls._wbi_keys

    @classmethod
    def _wbi_sign(cls, params):
        img_key, sub_key = cls._get_wbi_keys()
        raw_key = img_key + sub_key
        mixin_key = "".join(raw_key[index] for index in cls.MIXIN_KEY_ENC_TAB)[:32]
        signed = {str(key): str(value) for key, value in (params or {}).items()}
        signed["wts"] = str(round(current_timestamp()))
        clean = {
            key: "".join(ch for ch in value if ch not in "!'()*")
            for key, value in sorted(signed.items())
        }
        query = urllib.parse.urlencode(clean)
        clean["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
        return clean

    @staticmethod
    def _strip_html(text):
        return re.sub(r"<.*?>", "", str(text or "")).strip()

    @classmethod
    def search_users(cls, query, *, page_size=10):
        query = str(query or "").strip()
        if not query:
            raise ValueError("bilibili_user_search_error: empty query")
        params = cls._wbi_sign({
            "search_type": "bili_user",
            "keyword": query,
            "page": 1,
            "user_type": 0,
        })
        payload = cls._request_json("/x/web-interface/wbi/search/type", params=params)
        rows = ((payload.get("data") or {}).get("result") or [])[:int(page_size or 10)]
        users = []
        for row in rows:
            mid = str(row.get("mid") or "").strip()
            name = cls._strip_html(row.get("uname") or row.get("title"))
            if not mid or not name:
                continue
            official = row.get("official_verify") or {}
            users.append({
                "mid": mid,
                "name": name,
                "fans": int(row.get("fans") or 0),
                "videos": int(row.get("videos") or 0),
                "official_desc": str(official.get("desc") or ""),
                "official_type": official.get("type"),
            })
        return users

    @classmethod
    def get_user_card(cls, mid):
        mid = str(mid or "").strip()
        if not mid:
            raise ValueError("bilibili_user_card_error: empty mid")
        payload = cls._request_json("/x/web-interface/card", params={"mid": mid})
        card = ((payload.get("data") or {}).get("card") or {})
        name = cls._strip_html(card.get("name"))
        return {
            "mid": str(card.get("mid") or mid),
            "name": name,
            "fans": int(card.get("fans") or 0),
        }

    @classmethod
    def _video_from_search_row(cls, row):
        author = cls._strip_html(row.get("author"))
        bvid = str(row.get("bvid") or "").strip()
        if not bvid:
            return None
        title = cls._strip_html(row.get("title"))
        pubdate = row.get("pubdate") or row.get("senddate") or 0
        arcurl = str(row.get("arcurl") or "").replace("http://", "https://", 1)
        if not arcurl:
            arcurl = f"https://www.bilibili.com/video/{bvid}"
        return {
            "up_name": author,
            "up_mid": str(row.get("mid") or row.get("uid") or "").strip(),
            "aid": str(row.get("aid") or row.get("id") or "").strip(),
            "bvid": bvid,
            "title": title,
            "pubdate": int(pubdate or 0),
            "url": arcurl,
            "pic": str(row.get("pic") or ""),
        }

    @classmethod
    def search_videos(cls, keyword, *, page_size=20, page=1):
        keyword = str(keyword or "").strip()
        if not keyword:
            raise ValueError("bilibili_video_search_error: empty keyword")
        params = cls._wbi_sign({
            "search_type": "video",
            "keyword": keyword,
            "order": "pubdate",
            "page": max(1, int(page or 1)),
            "duration": 0,
            "tids": 0,
        })
        payload = cls._request_json("/x/web-interface/wbi/search/type", params=params)
        rows = ((payload.get("data") or {}).get("result") or [])[:int(page_size or 20)]
        videos = []
        for row in rows:
            video = cls._video_from_search_row(row)
            if video:
                videos.append(video)
        videos.sort(key=lambda item: int(item.get("pubdate") or 0), reverse=True)
        return videos

    @classmethod
    def search_videos_by_exact_author(cls, up_name, *, page_size=20):
        up_name = str(up_name or "").strip()
        return [
            video for video in cls.search_videos(up_name, page_size=page_size)
            if video.get("up_name") == up_name
        ]

    @classmethod
    def _search_videos_by_mid_from_keyword(cls, mid, up_name, page_size):
        up_name = str(up_name or "").strip()
        if not up_name:
            return []
        videos_by_bvid = {}
        target_count = max(1, int(page_size or 20))
        for page in range(1, 8):
            for video in cls.search_videos(up_name, page_size=20, page=page):
                if str(video.get("up_mid") or "") == mid:
                    videos_by_bvid[video["bvid"]] = video
            if len(videos_by_bvid) >= target_count:
                break
        videos = list(videos_by_bvid.values())
        videos.sort(key=lambda item: int(item.get("pubdate") or 0), reverse=True)
        return videos[:target_count]

    @classmethod
    def _space_video_rows(cls, mid, page_size):
        headers = {
            "Referer": f"https://space.bilibili.com/{mid}/video",
            "Origin": "https://space.bilibili.com",
        }
        attempts = [
            (
                "/x/space/arc/search",
                {
                    "mid": mid,
                    "pn": 1,
                    "ps": page_size,
                    "order": "pubdate",
                    "jsonp": "jsonp",
                },
            ),
            (
                "/x/space/wbi/arc/search",
                lambda: cls._wbi_sign({
                    "mid": mid,
                    "pn": 1,
                    "ps": page_size,
                    "order": "pubdate",
                    "platform": "web",
                    "web_location": "1550101",
                }),
            ),
        ]
        last_error = None
        for path, params in attempts:
            try:
                if callable(params):
                    params = params()
                payload = cls._request_json(path, params=params, headers=headers)
                return (((payload.get("data") or {}).get("list") or {}).get("vlist") or [])
            except Exception as error:
                last_error = error
        raise last_error

    @classmethod
    def search_videos_by_mid(cls, mid, *, up_name=None, page_size=20):
        mid = str(mid or "").strip()
        if not mid:
            raise ValueError("bilibili_video_search_error: empty mid")
        current_name = str(up_name or "").strip()
        size = max(1, min(int(page_size or 20), 50))
        try:
            rows = cls._space_video_rows(mid, size)[:size]
        except Exception:
            return cls._search_videos_by_mid_from_keyword(mid, current_name, size)
        videos = []
        for row in rows:
            bvid = str(row.get("bvid") or "").strip()
            if not bvid:
                continue
            author = cls._strip_html(row.get("author")) or current_name
            title = cls._strip_html(row.get("title"))
            pubdate = row.get("created") or row.get("pubdate") or row.get("senddate") or 0
            videos.append({
                "up_name": author,
                "up_mid": str(row.get("mid") or mid).strip(),
                "aid": str(row.get("aid") or row.get("id") or "").strip(),
                "bvid": bvid,
                "title": title,
                "pubdate": int(pubdate or 0),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "pic": str(row.get("pic") or ""),
            })
        videos.sort(key=lambda item: int(item.get("pubdate") or 0), reverse=True)
        return videos


def bilibili_search_videos_by_exact_author(up_name, *, page_size=20):
    return BilibiliVideoAPI.search_videos_by_exact_author(up_name, page_size=page_size)


def bilibili_search_users(query, *, page_size=10):
    return BilibiliVideoAPI.search_users(query, page_size=page_size)


def bilibili_get_user_card(mid):
    return BilibiliVideoAPI.get_user_card(mid)


def bilibili_search_videos_by_mid(mid, *, up_name=None, page_size=20):
    return BilibiliVideoAPI.search_videos_by_mid(mid, up_name=up_name, page_size=page_size)

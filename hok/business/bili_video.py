"""Pure Bilibili subscription normalization and presentation helpers."""

import difflib


def _zfunc_attr(name):
    from .. import zfunc

    return getattr(zfunc, name)


def qid2nick(*args, **kwargs):
    return _zfunc_attr("qid2nick")(*args, **kwargs)


def _web_artifacts():
    return _zfunc_attr("WebArtifacts")


def log_message(*args, **kwargs):
    return _zfunc_attr("log_message")(*args, **kwargs)

def _bili_video_normalize_subscription_item(item):
    if isinstance(item, dict):
        up_name = str(item.get("up_name") or "").strip()
        up_mid = str(item.get("up_mid") or item.get("mid") or "").strip()
        query = str(item.get("query") or up_name).strip()
        subscribed_at = str(item.get("subscribed_at") or "")
    else:
        up_name = str(item or "").strip()
        up_mid = ""
        query = up_name
        subscribed_at = ""
    if not up_name and not up_mid:
        return None
    return {
        "up_mid": up_mid,
        "up_name": up_name,
        "query": query,
        "subscribed_at": subscribed_at,
    }


def _bili_video_normalize_subscriptions(subscriptions):
    if not isinstance(subscriptions, dict):
        subscriptions = {}
    normalized = {}
    for user_qid, item in subscriptions.items():
        user_qid = str(user_qid)
        if isinstance(item, list):
            items = [
                normalized_item
                for normalized_item in (_bili_video_normalize_subscription_item(row) for row in item)
                if normalized_item
            ]
            if not items:
                continue
            normalized[user_qid] = items
        else:
            normalized_item = _bili_video_normalize_subscription_item(item)
            if not normalized_item:
                continue
            normalized[user_qid] = [normalized_item]
    return normalized

def _bili_video_subscription_items_for_user(subscriptions, user_qid):
    item = (subscriptions or {}).get(str(user_qid))
    if isinstance(item, list):
        return [row for row in item if isinstance(row, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def _bili_video_set_subscription_items_for_user(subscriptions, user_qid, items):
    user_qid = str(user_qid)
    items = [
        normalized_item
        for normalized_item in (_bili_video_normalize_subscription_item(row) for row in items)
        if normalized_item
    ]
    if not items:
        subscriptions.pop(user_qid, None)
    else:
        subscriptions[user_qid] = items
    return subscriptions


def _bili_video_iter_subscription_items(subscriptions):
    for user_qid in sorted((subscriptions or {}).keys()):
        for index, item in enumerate(_bili_video_subscription_items_for_user(subscriptions, user_qid)):
            yield str(user_qid), index, item


def _bili_video_identity_key(up_mid, up_name=""):
    up_mid = str(up_mid or "").strip()
    if up_mid:
        return f"mid:{up_mid}"
    return f"name:{str(up_name).strip()}"


def _bili_video_seen_key(up_mid, up_name=""):
    identity = _bili_video_identity_key(up_mid, up_name)
    if identity.startswith("mid:"):
        identity = identity[len("mid:"):]
    return f"hok:bili:seen:{identity}"

def _bili_video_subscribed_at_epoch(item):
    from ..ztime import str_to_time

    subscribed_at = str((item or {}).get("subscribed_at") or "").strip()
    if not subscribed_at:
        return 0
    try:
        return int(str_to_time(subscribed_at).timestamp())
    except Exception as error:
        log_message(f"BILI_VIDEO_SUBSCRIBED_AT_PARSE_ERROR: subscribed_at={subscribed_at} error={repr(error)}")
        return 0

def _bili_video_format_subscriber_list(user_qids):
    formatted = []
    for user_qid in user_qids:
        nick = qid2nick(str(user_qid))
        if nick:
            formatted.append(f"{nick}({user_qid})")
        else:
            formatted.append(str(user_qid))
    return "、".join(formatted)


def _bili_video_format_subscription_label(item):
    return f"{item.get('up_name') or item.get('query') or '未知UP'}({item.get('up_mid') or '未知mid'})"


def _bili_video_find_matching_items(items, query_text):
    query = str(query_text or "").strip().lower()
    if not query:
        return []
    matches = []
    for index, item in enumerate(items):
        up_mid = str(item.get("up_mid") or "").strip().lower()
        up_name = str(item.get("up_name") or "").strip().lower()
        saved_query = str(item.get("query") or "").strip().lower()
        if query == up_mid or query == up_name or query == saved_query:
            matches.append((index, item, 3))
        elif query and ((up_name and query in up_name) or (saved_query and query in saved_query)):
            matches.append((index, item, 2))
        elif query and ((up_name and up_name in query) or (saved_query and saved_query in query)):
            matches.append((index, item, 1))
    if not matches:
        return []
    best_score = max(score for _, _, score in matches)
    return [(index, item) for index, item, score in matches if score == best_score]


def _bili_video_app_url(aid):
    aid = str(aid or "").strip()
    return f"bilibili://video/{aid}?page=0" if aid else ""


def _bili_video_mobile_url(bvid):
    bvid = str(bvid or "").strip()
    return f"https://m.bilibili.com/video/{bvid}" if bvid else ""


def _bili_video_pic_url(video):
    pic_url = str((video or {}).get("pic") or "").strip()
    if pic_url.startswith("//"):
        return "https:" + pic_url
    if pic_url.startswith("http://"):
        return pic_url.replace("http://", "https://", 1)
    return pic_url


def _cq_escape(value):
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace(",", "&#44;")
    )


def _bili_video_pic_message_segment(video):
    pic_url = _bili_video_pic_url(video)
    if not pic_url:
        return "暂无"
    return f"[CQ:image,file={_cq_escape(pic_url)}]"


def _bili_video_page_link(up_name, video):
    from ..ztime import epoch_to_text

    pubdate_text = epoch_to_text(video.get("pubdate")) or "未知"
    bvid = str(video.get("bvid") or "").strip()
    aid = str(video.get("aid") or video.get("avid") or "").strip()
    video_url = video.get("url") or (f"https://www.bilibili.com/video/{bvid}" if bvid else "")
    up_mid = str(video.get("up_mid") or "").strip()
    return _web_artifacts().bili_video_route_link({
        "up_name": up_name,
        "up_mid": up_mid,
        "up_url": f"https://space.bilibili.com/{up_mid}" if up_mid else "",
        "aid": aid,
        "bvid": bvid,
        "title": video.get("title") or "无标题",
        "pubdate": int(video.get("pubdate") or 0),
        "pubdate_text": pubdate_text,
        "url": video_url,
        "pic": video.get("pic") or "",
        "app_url": _bili_video_app_url(aid),
        "mobile_url": _bili_video_mobile_url(bvid),
    })


def _bili_video_format_video_message(up_name, video):
    from ..ztime import epoch_to_text

    pubdate_text = epoch_to_text(video.get("pubdate")) or "未知"
    page_link = _bili_video_page_link(up_name, video)
    return (
        "B站订阅视频推送\n"
        f"【{video.get('title') or '无标题'}】\n"
        f"{up_name} · {pubdate_text}\n\n"
        f"{_bili_video_pic_message_segment(video)}\n\n"
        f"{page_link}"
    )


def _bili_video_format_push_message(up_name, video, subscribers):
    return _bili_video_format_video_message(up_name, video)


def _bili_video_format_latest_message(up_name, video):
    return _bili_video_format_video_message(up_name, video)



def _bili_video_similarity(query, candidate_name):
    query = str(query or "").strip().lower()
    candidate_name = str(candidate_name or "").strip().lower()
    if not query or not candidate_name:
        return 0
    if query == candidate_name:
        return 240
    score = int(difflib.SequenceMatcher(None, query, candidate_name).ratio() * 100)
    if query in candidate_name:
        score += 120
    if candidate_name in query:
        score += 80
    return score

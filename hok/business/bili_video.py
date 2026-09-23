"""Pure Bilibili subscription normalization and presentation helpers."""

import difflib
import math


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


def _bili_video_subscribers_by_up():
    subscriptions = _zfunc_attr("_bili_video_get_subscriptions")()
    grouped = {}
    for user_qid, _, item in _bili_video_iter_subscription_items(subscriptions):
        identity = _bili_video_identity_key(item.get("up_mid"), item.get("up_name"))
        if identity not in grouped:
            grouped[identity] = {
                "up_mid": item.get("up_mid") or "",
                "up_name": item.get("up_name") or "",
                "query": item.get("query") or item.get("up_name") or "",
                "subscribers": [],
                "subscribed_at_epochs": [],
            }
        grouped[identity]["subscribers"].append(user_qid)
        subscribed_at_epoch = _bili_video_subscribed_at_epoch(item)
        if subscribed_at_epoch:
            grouped[identity]["subscribed_at_epochs"].append(subscribed_at_epoch)
    for item in grouped.values():
        item["subscribers"].sort()
        subscribed_at_epochs = item.pop("subscribed_at_epochs", [])
        item["latest_subscribed_at_epoch"] = (
            max(subscribed_at_epochs) if subscribed_at_epochs else 0
        )
    return grouped


def _bili_video_update_subscription_identity(identity, *, up_mid=None, up_name=None):
    get_subscriptions = _zfunc_attr("_bili_video_get_subscriptions")
    save_subscriptions = _zfunc_attr("_bili_video_save_subscriptions")
    subscriptions = get_subscriptions()
    changed = False
    for user_qid in list(subscriptions.keys()):
        user_items = _bili_video_subscription_items_for_user(subscriptions, user_qid)
        user_changed = False
        for item in user_items:
            if _bili_video_identity_key(item.get("up_mid"), item.get("up_name")) != identity:
                continue
            if up_mid and item.get("up_mid") != str(up_mid):
                item["up_mid"] = str(up_mid)
                changed = True
                user_changed = True
            if up_name and item.get("up_name") != str(up_name):
                item["up_name"] = str(up_name)
                changed = True
                user_changed = True
        if user_changed:
            _bili_video_set_subscription_items_for_user(
                subscriptions,
                user_qid,
                user_items,
            )
    if changed:
        save_subscriptions(subscriptions)
    return changed


def _bili_video_resolve_best_up(query):
    from ..zapi import bilibili_search_users

    query = str(query or "").strip()
    candidates = bilibili_search_users(query, page_size=10)
    if not candidates:
        return None, []
    ranked = []
    for candidate in candidates:
        text_score = _bili_video_similarity(query, candidate.get("name"))
        fans = int(candidate.get("fans") or 0)
        videos = int(candidate.get("videos") or 0)
        popularity_bonus = min(int(math.log10(max(fans, 1)) * 18), 140)
        video_bonus = min(videos // 20, 25)
        official_bonus = 50 if candidate.get("official_type") in {0, 1} else 0
        total_score = text_score + popularity_bonus + video_bonus + official_bonus
        ranked.append((total_score, text_score, fans, videos, candidate))
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    best = dict(ranked[0][4])
    best["match_score"] = ranked[0][0]
    return best, [dict(item[4], match_score=item[0]) for item in ranked]


def bili_video_subscribe_user(user_qid, up_name):
    from .. import zdynamic as dmc
    from ..zapi import bilibili_search_videos_by_mid
    from ..ztime import time_r, time_to_str

    user_qid = str(user_qid)
    up_name = str(up_name or "").strip()
    if not up_name:
        return "参数错误，格式：#订阅 UP昵称"

    subscriptions = _zfunc_attr("_bili_video_get_subscriptions")()
    current_items = _bili_video_subscription_items_for_user(subscriptions, user_qid)
    best_up, _ = _bili_video_resolve_best_up(up_name)
    if not best_up:
        return f"未找到可匹配的 B站 UP：{up_name}"

    resolved_mid = str(best_up.get("mid") or "").strip()
    resolved_name = str(best_up.get("name") or "").strip()
    for item in current_items:
        if _bili_video_identity_key(
            item.get("up_mid"), item.get("up_name")
        ) == _bili_video_identity_key(resolved_mid, resolved_name):
            return f"你已经订阅了 {resolved_name}({resolved_mid})"

    try:
        videos = bilibili_search_videos_by_mid(
            resolved_mid,
            up_name=resolved_name,
            page_size=getattr(dmc, "BiliVideoApiPageSize", 20),
        )
    except Exception as error:
        return (
            f"B站视频接口暂时不可用：{resolved_name}({resolved_mid})，"
            f"错误：{repr(error)}"
        )
    if not videos:
        return (
            f"已匹配到 {resolved_name}({resolved_mid})，"
            "但未找到该 UP 的公开视频，订阅未保存"
        )

    current_items.append(
        {
            "up_mid": resolved_mid,
            "up_name": resolved_name,
            "query": up_name,
            "subscribed_at": time_to_str(time_r()),
        }
    )
    _bili_video_set_subscription_items_for_user(subscriptions, user_qid, current_items)
    _zfunc_attr("_bili_video_save_subscriptions")(subscriptions)
    _zfunc_attr("_bili_video_mark_seen")(
        resolved_mid,
        resolved_name,
        [video.get("bvid") for video in videos],
    )
    latest = videos[0]
    prefix = f"订阅成功：{resolved_name}({resolved_mid})\n当前订阅数：{len(current_items)}"
    return f"{prefix}\n\n{_bili_video_format_latest_message(resolved_name, latest)}"


def bili_video_unsubscribe_user(user_qid, query_text=""):
    user_qid = str(user_qid)
    subscriptions = _zfunc_attr("_bili_video_get_subscriptions")()
    current_items = _bili_video_subscription_items_for_user(subscriptions, user_qid)
    if not current_items:
        return "你当前没有 B站 UP 订阅"

    query_text = str(query_text or "").strip()
    if not query_text and len(current_items) > 1:
        lines = ["你当前订阅了多个 UP，请指定要取消哪一个："]
        for index, item in enumerate(current_items, 1):
            lines.append(f"{index}. {_bili_video_format_subscription_label(item)}")
        lines.append("格式：#取消订阅 UP昵称 或 #取消订阅 mid")
        return "\n".join(lines)
    if not query_text:
        removed = current_items[0]
        _bili_video_set_subscription_items_for_user(subscriptions, user_qid, [])
        _zfunc_attr("_bili_video_save_subscriptions")(subscriptions)
        return f"已取消订阅：{_bili_video_format_subscription_label(removed)}"

    matches = _bili_video_find_matching_items(current_items, query_text)
    if not matches:
        known = "、".join(
            _bili_video_format_subscription_label(item) for item in current_items
        )
        return f"未找到匹配的 B站 UP 订阅：{query_text}\n当前订阅：{known}"
    if len(matches) > 1:
        matched = "、".join(
            _bili_video_format_subscription_label(item) for _, item in matches
        )
        return f"匹配到多个订阅，请输入更完整的 UP 昵称或 mid：{matched}"
    remove_index, removed = matches[0]
    current_items.pop(remove_index)
    _bili_video_set_subscription_items_for_user(subscriptions, user_qid, current_items)
    _zfunc_attr("_bili_video_save_subscriptions")(subscriptions)
    return f"已取消订阅：{_bili_video_format_subscription_label(removed)}"


def bili_video_my_subscription(user_qid):
    items = _bili_video_subscription_items_for_user(
        _zfunc_attr("_bili_video_get_subscriptions")(),
        str(user_qid),
    )
    if not items:
        return "你当前没有 B站 UP 订阅"
    if len(items) == 1:
        return f"你的 B站 UP 订阅：{_bili_video_format_subscription_label(items[0])}"
    lines = ["你的 B站 UP 订阅："]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. {_bili_video_format_subscription_label(item)}")
    return "\n".join(lines)


def _bili_video_latest_for_item(item):
    from .. import zdynamic as dmc
    from ..zapi import bilibili_get_user_card, bilibili_search_videos_by_mid

    identity = _bili_video_identity_key(item.get("up_mid"), item.get("up_name"))
    up_mid = item.get("up_mid") or ""
    up_name = item.get("up_name") or item.get("query") or ""
    if not up_mid:
        best_up, _ = _bili_video_resolve_best_up(up_name)
        if not best_up:
            return f"未能解析你订阅的 UP：{up_name}"
        up_mid = str(best_up.get("mid") or "")
        up_name = str(best_up.get("name") or up_name)
        _bili_video_update_subscription_identity(
            identity,
            up_mid=up_mid,
            up_name=up_name,
        )

    try:
        current_card = bilibili_get_user_card(up_mid)
        if current_card.get("name"):
            up_name = current_card["name"]
            _bili_video_update_subscription_identity(identity, up_name=up_name)
    except Exception as error:
        log_message(f"BILI_VIDEO_LATEST_CARD_ERROR: mid={up_mid} error={repr(error)}")

    videos = bilibili_search_videos_by_mid(
        up_mid,
        up_name=up_name,
        page_size=getattr(dmc, "BiliVideoApiPageSize", 20),
    )
    if not videos:
        return f"暂未查询到 {up_name}({up_mid}) 的公开视频"
    return _bili_video_format_latest_message(up_name, videos[0])


def bili_video_latest_for_user(user_qid):
    items = _bili_video_subscription_items_for_user(
        _zfunc_attr("_bili_video_get_subscriptions")(),
        str(user_qid),
    )
    if not items:
        return "你当前没有订阅 UP，格式：#订阅 UP昵称"
    if len(items) == 1:
        return _bili_video_latest_for_item(items[0])
    messages = []
    for item in items:
        try:
            messages.append(_bili_video_latest_for_item(item))
        except Exception as error:
            label = _bili_video_format_subscription_label(item)
            messages.append(f"{label} 最新视频查询失败：{repr(error)}")
    return "\n\n——\n\n".join(messages)


def bili_video_list_subscriptions():
    grouped = _bili_video_subscribers_by_up()
    if not grouped:
        return "当前没有 B站 UP 订阅"
    lines = ["B站 UP 订阅列表："]
    for identity in sorted(grouped):
        item = grouped[identity]
        label = f"{item.get('up_name') or identity}({item.get('up_mid') or '未知mid'})"
        lines.append(
            f"{label}：{_bili_video_format_subscriber_list(item['subscribers'])}"
        )
    return "\n".join(lines)


def bili_video_check_and_push(*, debug=False):
    from .. import zdynamic as dmc
    from ..zapi import bilibili_get_user_card, bilibili_search_videos_by_mid

    if not getattr(dmc, "BiliVideoPushEnabled", True):
        return {
            "checked": 0,
            "pushed": 0,
            "debug": "BILI_VIDEO_PUSH paused by BiliVideoPushEnabled=false",
        }

    grouped = _bili_video_subscribers_by_up()
    if not grouped:
        return {"checked": 0, "pushed": 0, "debug": "BILI_VIDEO_PUSH no subscriptions"}
    if not _zfunc_attr("_bili_video_acquire_push_lock")():
        return {"checked": 0, "pushed": 0, "debug": "BILI_VIDEO_PUSH locked"}

    checked = 0
    pushed = 0
    debug_lines = []
    try:
        for identity in sorted(grouped):
            checked += 1
            item = grouped[identity]
            up_mid = item.get("up_mid") or ""
            up_name = item.get("up_name") or item.get("query") or identity
            subscribers = item["subscribers"]
            subscription_cutoff_epoch = int(
                item.get("latest_subscribed_at_epoch") or 0
            )

            if not up_mid:
                best_up, _ = _bili_video_resolve_best_up(up_name)
                if not best_up:
                    debug_lines.append(f"BILI_VIDEO_SKIP unresolved={up_name}")
                    continue
                up_mid = str(best_up.get("mid") or "")
                up_name = str(best_up.get("name") or up_name)
                if _bili_video_update_subscription_identity(
                    identity,
                    up_mid=up_mid,
                    up_name=up_name,
                ):
                    debug_lines.append(
                        f"BILI_VIDEO_MIGRATED identity={identity} mid={up_mid} up={up_name}"
                    )

            try:
                current_card = bilibili_get_user_card(up_mid)
                if current_card.get("name"):
                    up_name = current_card["name"]
                    if _bili_video_update_subscription_identity(identity, up_name=up_name):
                        debug_lines.append(
                            f"BILI_VIDEO_NAME_UPDATED mid={up_mid} up={up_name}"
                        )
            except Exception as error:
                debug_lines.append(
                    f"BILI_VIDEO_CARD_ERROR mid={up_mid} error={repr(error)}"
                )

            videos = bilibili_search_videos_by_mid(
                up_mid,
                up_name=up_name,
                page_size=getattr(dmc, "BiliVideoApiPageSize", 20),
            )
            debug_lines.append(
                f"BILI_VIDEO_UP mid={up_mid} up={up_name} "
                f"videos={len(videos)} subscribers={len(subscribers)}"
            )
            if not videos:
                continue

            if not _zfunc_attr("_bili_video_seen_initialized")(up_mid, up_name):
                _zfunc_attr("_bili_video_mark_seen")(
                    up_mid,
                    up_name,
                    [video.get("bvid") for video in videos],
                )
                debug_lines.append(
                    f"BILI_VIDEO_INIT_SEEN mid={up_mid} up={up_name} count={len(videos)}"
                )
                continue

            unseen_videos = [
                video
                for video in videos
                if video.get("bvid")
                and not _zfunc_attr("_bili_video_seen_exists")(
                    up_mid,
                    up_name,
                    video.get("bvid"),
                )
            ]
            old_unseen_videos = [
                video
                for video in unseen_videos
                if subscription_cutoff_epoch
                and int(video.get("pubdate") or 0) <= subscription_cutoff_epoch
            ]
            if old_unseen_videos:
                _zfunc_attr("_bili_video_mark_seen")(
                    up_mid,
                    up_name,
                    [video.get("bvid") for video in old_unseen_videos],
                )
                debug_lines.append(
                    f"BILI_VIDEO_MARK_OLD_SEEN mid={up_mid} up={up_name} "
                    f"count={len(old_unseen_videos)}"
                )
            new_videos = [
                video
                for video in unseen_videos
                if (not subscription_cutoff_epoch)
                or int(video.get("pubdate") or 0) > subscription_cutoff_epoch
            ]
            new_videos.sort(key=lambda item: int(item.get("pubdate") or 0))
            for video in new_videos:
                message = _bili_video_format_push_message(up_name, video, subscribers)
                _zfunc_attr("_bili_video_send_group_message")(message)
                _zfunc_attr("_bili_video_mark_seen")(
                    up_mid,
                    up_name,
                    [video.get("bvid")],
                )
                pushed += 1
                debug_lines.append(
                    f"BILI_VIDEO_PUSHED mid={up_mid} up={up_name} bvid={video.get('bvid')}"
                )
        return {"checked": checked, "pushed": pushed, "debug": "\n".join(debug_lines)}
    finally:
        _zfunc_attr("_bili_video_release_push_lock")()


def bili_video_admin_command(raw_msg):
    raw_msg = str(raw_msg or "").strip()
    args = raw_msg.replace("##bili", "", 1).strip().split()
    action = args[0].lower() if args else "list"
    if action == "list":
        return bili_video_list_subscriptions()
    if action == "check":
        result = bili_video_check_and_push(debug=True)
        return (
            f"B站订阅检查完成：checked={result.get('checked')} "
            f"pushed={result.get('pushed')}\n{result.get('debug') or ''}"
        ).strip()
    return "参数错误，支持：##bili list / ##bili check"

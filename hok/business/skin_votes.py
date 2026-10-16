"""Normalize skin-return votes and compose a text summary plus source-style card."""

import math

from .. import zapi, zfile, ztime
from ..zstatic import skin_votes_config
from ..zutil import log_message


def _number(value, *, rank=False):
    if value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0
            or (rank and (value < 1 or int(value) != value))):
        raise ValueError("skin_votes_invalid_number")
    return int(value) if rank else value


def _stamp(value, pattern="%Y-%m-%d %H:%M:%S"):
    if not value:
        return "未知"
    return ztime.epoch_to_text(ztime.parse_chat_time_bound(value), pattern,
                              timezone_name="Asia/Shanghai")


def normalize_skin_votes(payload):
    """Preserve published ranks and nulls; never derive a fake current snapshot."""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("skin_votes_invalid_payload")
    series, times = payload.get("series"), payload.get("times")
    if not isinstance(series, list) or not isinstance(times, list):
        raise ValueError("skin_votes_invalid_series_or_times")
    epochs = [ztime.parse_chat_time_bound(value) for value in times]
    if any(value is None for value in epochs) or any(a >= b for a, b in zip(epochs, epochs[1:])):
        raise ValueError("skin_votes_invalid_times")
    rows, ids = [], set()
    for item in series:
        if not isinstance(item, dict) or not item.get("skinId"):
            raise ValueError("skin_votes_invalid_skin")
        skin_id = str(item["skinId"])
        if skin_id in ids:
            raise ValueError("skin_votes_duplicate_skin")
        ids.add(skin_id)
        votes = item.get("votes")
        if not isinstance(votes, list) or len(votes) != len(times):
            raise ValueError("skin_votes_misaligned_history")
        votes = [_number(value) for value in votes]
        latest = _number(item.get("latestVotes"))
        first = next((value for value in votes if value is not None), None)
        rows.append({
            "skin_id": skin_id,
            "hero": str(item.get("heroName") or "未知英雄"),
            "skin": str(item.get("skinName") or "未知皮肤"),
            "icon": str(item.get("icon") or ""),
            "rank": _number(item.get("latestRank"), rank=True),
            "votes": latest, "speed": _number(item.get("latestAddNum")),
            "growth": latest - first if latest is not None and first is not None else None,
            "history": votes,
        })
    rows.sort(key=lambda row: (row["rank"] is None, row["rank"] or 0))
    previous = None
    for row in rows:
        row["gap"] = None
        if (previous and row["rank"] is not None and previous["rank"] == row["rank"] - 1
                and previous["votes"] is not None and row["votes"] is not None):
            row["gap"] = previous["votes"] - row["votes"]
        previous = row
    return {
        "rows": rows, "times": epochs,
        "time_labels": [_stamp(value, "%m-%d %H:%M") for value in times],
        "updated": _stamp(payload.get("updatedAt")),
        "hours": int(skin_votes_config["hours"]),
    }


def skin_votes_query_process():
    data = normalize_skin_votes(zapi.tianyuanzhiyi_skin_votes_api())
    rows = data["rows"]
    if not rows:
        return {"text": "皮肤返场投票排行\n暂无榜单数据，请稍后重试。",
                "image_path": None}
    count = max(1, min(10, int(skin_votes_config["text_top"])))
    lines = ["皮肤返场投票排行", f"更新时间：{data['updated']}（北京时间）"]
    for row in rows[:count]:
        votes = f"{row['votes']:,.0f}票" if row["votes"] is not None else "票数未知"
        rank = str(row["rank"]) if row["rank"] is not None else "?"
        lines.append(f"{rank}. {row['hero']}·{row['skin']}  {votes}")
    lines.append("票数约有百票精度误差。")
    text = "\n".join(lines)
    try:
        from ..tools.gen_skin_votes import render_skin_votes_image

        image_rows = rows[:max(1, min(30, int(skin_votes_config["image_top"])))]
        icons = zapi.tianyuanzhiyi_skin_icons_api(image_rows)
        image = render_skin_votes_image(data, image_rows, icons)
        image_path = zfile.save_skin_votes_image(image)
    except Exception as error:
        log_message(f"SKIN_VOTES_IMAGE_ERROR: {error!r}")
        return {"text": text + f"\n返场排行图片生成失败：location=business.skin_votes "
                f"params={{'hours': {data['hours']}}} error={error!r}", "image_path": None}
    return {"text": text, "image_path": image_path}

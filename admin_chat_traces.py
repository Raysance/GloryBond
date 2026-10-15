"""Bounded admin listing of QQ traces without loading full model payloads."""

import datetime
import json
import time

from chat_trace import valid_trace_key


TRACE_INDEX_KEY = "hok:chat:traces"
PAGE_SIZE = 25


def list_chat_traces(store, *, max_records=1000, page=1, query="", status="", group_id=""):
    rows = []
    now = time.time()
    for raw in store.lrange(TRACE_INDEX_KEY, 0, max(1, min(int(max_records), 10000)) - 1):
        try:
            row = json.loads(raw)
            if not isinstance(row, dict) or not valid_trace_key(row.get("key")) or float(row.get("expires_at", 0)) <= now:
                continue
            created_at = float(row["created_at"])
            row["time_text"] = datetime.datetime.fromtimestamp(created_at,
                datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            continue
        if status and row.get("status") != status:
            continue
        if group_id and str(row.get("group_id") or "") != group_id:
            continue
        haystack = " ".join(str(row.get(key) or "") for key in ("question", "run_id", "session_id", "user_id", "model"))
        if query.casefold() not in haystack.casefold():
            continue
        row["detail_url"] = "/admin/funcs/chat-traces/" + row["key"]
        rows.append(row)
    rows.sort(key=lambda row: float(row["created_at"]), reverse=True)
    total = len(rows)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, pages))
    return {"records": rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], "total": total, "page": page, "pages": pages}

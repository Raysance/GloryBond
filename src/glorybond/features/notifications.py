"""Daily report message assembly without transport concerns."""

import traceback

from glorybond import time as ztime


def _runtime():
    from glorybond.features import facade as zfunc

    return zfunc


def notify_msg_impl():
    runtime = _runtime()
    runtime.log_message("NOTIFY" + ztime.date_r())
    try:
        report = runtime.rnk_process(
            rcv_msg="",
            caller=None,
            show_zero=True,
        )
    except Exception:
        return [traceback.format_exc()]

    messages = [(report["text"], report["image_path"])] if report["image_path"] else [report["text"]]
    if report["error_report"]:
        messages.append({"admin_error": report["error_report"]})
    try:
        representative = runtime.get_daily_representative_battle()
        if representative:
            match_text, battle_image, best_battle = representative
            messages.append(
                (
                    match_text,
                    battle_image,
                    best_battle.get("AiCommentary"),
                )
            )
    except Exception:
        runtime.log_message(
            "GET_REPRESENTATIVE_BATTLE_ERROR: "
            f"target_date=auto error={traceback.format_exc()}"
        )
    return messages

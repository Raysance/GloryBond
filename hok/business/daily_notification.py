"""Daily report message assembly without transport concerns."""

import traceback

from .. import ztime


def _runtime():
    from .. import zfunc

    return zfunc


def notify_msg_impl():
    runtime = _runtime()
    runtime.log_message("NOTIFY" + ztime.date_r())
    report_text = "今日王者战报(每日23:30推送)：\n"
    try:
        report_text += runtime.rnk_process(
            rcv_msg="",
            caller=None,
            show_zero=False,
            show_analyze=True,
        )[0]
    except Exception:
        return [traceback.format_exc()]

    messages = [report_text]
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

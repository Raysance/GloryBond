"""Bot configuration/logging boundary for the private Camp SDK."""
import logging
from time import monotonic

from hok_camp_client import CampError, download_battle_image
from glorybond.integrations.camp import query, capture_watch_frame, session_path

from glorybond.storage.files import append_hok_exception_log, refresh_login_credentials
from glorybond.config.settings import data_root
from glorybond.common import log_message


def wzry_battle_image_bytes(url, *, timeout=10):
    return download_battle_image(url, timeout=timeout)


class WzryOfficialAPI:
    LOW_PRIORITY_PERIOD_SECONDS = 5

    @staticmethod
    def _get_official_impl(reqtype, userid=-1, roleid=0, gameseq=-1, gameSvrId=-1,
                           relaySvrId=-1, pvptype=-1, heroid=-1, rankId=-1, rankSegment=-1,
                           battle_id=-1, honor_adcode=156, *, last_time=0):
        refresh_login_credentials()
        try:
            return query(session_path(data_root), reqtype, userid, roleid, gameseq, gameSvrId,
                         relaySvrId, pvptype, heroid, rankId, rankSegment, battle_id,
                         honor_adcode, last_time=last_time)
        except Exception as exc:
            details = {"reqtype": reqtype, "error_type": type(exc).__name__}
            if isinstance(exc, CampError):
                details["code"] = exc.code
            try:
                append_hok_exception_log("Camp request failed", details)
            except Exception:
                log_message("HOK_EXCEPTION_LOG_WRITE_ERROR", logging.ERROR)
            raise


def wzry_watch_frame(userid, roleid, *, on_battle_info=None):
    started = monotonic()
    try:
        options = {"on_battle_info": on_battle_info} if on_battle_info is not None else {}
        result = capture_watch_frame(session_path(data_root), userid, roleid, **options)
        state = result.get("state")
        state = state if state in {"ready", "pending", "ended", "unavailable"} else "unknown"
        reason = "stream_wait_timeout" if result.get("reason") == "stream_wait_timeout" else "other"
        log_message(f"WATCH_FRAME_RESULT state={state} reason={reason} "
                    f"reused={result.get('reused') is True} elapsed={monotonic() - started:.3f}",
                    logging.WARNING if state == "pending" else logging.INFO)
        return result
    except Exception as exc:
        log_message("WATCH_FRAME_ERROR type=" + type(exc).__name__, logging.WARNING)
        raise


def wzry_get_official(reqtype, userid=-1, roleid=0, gameseq=-1, gameSvrId=-1,
                      relaySvrId=-1, pvptype=-1, heroid=-1, rankId=-1, rankSegment=-1,
                      battle_id=-1, priority="normal", honor_adcode=156, *, last_time=0):
    return WzryOfficialAPI._get_official_impl(reqtype, userid, roleid, gameseq, gameSvrId,
        relaySvrId, pvptype, heroid, rankId, rankSegment, battle_id, honor_adcode, last_time=last_time)

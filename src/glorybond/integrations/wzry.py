"""Bot configuration/logging boundary for the private Camp SDK."""
import logging

from hok_camp_client import CampError, download_battle_image
from glorybond.integrations.camp import query, capture_watch_frame, session_path

from glorybond.storage.files import append_hok_exception_log, refresh_login_credentials
from glorybond.config.settings import data_root
from glorybond.common import log_message


def wzry_battle_image_bytes(url):
    return download_battle_image(url)


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


def wzry_watch_frame(userid, roleid):
    try:
        return capture_watch_frame(session_path(data_root), userid, roleid)
    except Exception as exc:
        log_message("WATCH_FRAME_ERROR type=" + type(exc).__name__, logging.WARNING)
        raise


def wzry_get_official(reqtype, userid=-1, roleid=0, gameseq=-1, gameSvrId=-1,
                      relaySvrId=-1, pvptype=-1, heroid=-1, rankId=-1, rankSegment=-1,
                      battle_id=-1, priority="normal", honor_adcode=156, *, last_time=0):
    return WzryOfficialAPI._get_official_impl(reqtype, userid, roleid, gameseq, gameSvrId,
        relaySvrId, pvptype, heroid, rankId, rankSegment, battle_id, honor_adcode, last_time=last_time)

"""Application call-name compatibility; all Camp protocol work belongs to the SDK."""
import atexit
import threading
from pathlib import Path

from hok_camp_client import CampClient, CampError

_lock = threading.RLock()
_client = None
_client_path = None
_watch_lock = threading.Lock()


def session_path(data_dir):
    """Only the private file location crosses the application/SDK boundary."""
    return Path(data_dir) / "account_sessions" / "camp-session.json"


def _get_client(state_file):
    global _client, _client_path
    path = Path(state_file).resolve()
    if _client is None or path != _client_path:
        if _client is not None:
            _client.close()
        _client = CampClient(state_file=path, timeout=30, trust_env=False)
        _client_path = path
    else:
        _client.reload_session()
    return _client


def close():
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None


atexit.register(close)


def query(state_file, reqtype, userid=-1, roleid=0, gameseq=-1, gameSvrId=-1,
          relaySvrId=-1, pvptype=-1, heroid=-1, rankId=-1, rankSegment=-1,
          battle_id=-1, honor_adcode=156, *, last_time=0):
    """Reuse the SDK-owned session; the host never reads account credentials."""
    with _lock:
        _get_client(state_file)
        match reqtype:
            case "btlist" | "btlist_url":
                return _client.get_battle_list(userid, roleid, last_time=last_time)
            case "btldetail":
                return _client.get_battle_detail(roleid, gameseq, gameSvrId, relaySvrId, pvptype)
            case "profile":
                return _client.get_player_profile(userid, roleid)
            case "season":
                return _client.get_current_season(roleid)
            case "heropower":
                return _client.get_hero_power(userid, roleid)
            case "allhero":
                return _client.get_heroes(roleid)
            case "herostatistics":
                return _client.get_hero_statistics(roleid, heroid)
            case "heroranklist":
                return _client.get_hero_rankings(rankId, rankSegment)
            case "honorranklist":
                return _client.get_honor_rankings(roleid, heroid, adcode=honor_adcode)
            case "watchbattle":
                return _client.get_watch_battle_info(userid, battle_id, roleid)
            case _:
                raise ValueError(f"unsupported wzry reqtype: {reqtype}")


def capture_watch_frame(state_file, userid, roleid, *, wait_timeout=60):
    """One screenshot through public SDK APIs; never expose the stream URL."""
    if not _watch_lock.acquire(blocking=False):
        raise CampError("watch_active", "A screenshot request is already running")
    try:
        with _lock:
            client = _get_client(state_file)
            with client.open_watch_stream(userid, roleid, wait_timeout=wait_timeout) as live:
                result = live.result
                if result["state"] != "ready":
                    return {"state": result["state"], "reason": result.get("reason")}
                frames = live.frames()
                try:
                    jpeg = next(frames)
                except StopIteration:
                    raise CampError("video_decode", "No video frame received") from None
                finally:
                    frames.close()
                return {"state": "ready", "jpeg": jpeg}
    finally:
        _watch_lock.release()

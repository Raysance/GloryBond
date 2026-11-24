"""Application call-name compatibility; all Camp protocol work belongs to the SDK."""
import atexit
import threading

from hok_camp_client import CampClient

_lock = threading.RLock()
_client = None


def close():
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None


atexit.register(close)


def query(config, reqtype, userid=-1, roleid=0, gameseq=-1, gameSvrId=-1,
          relaySvrId=-1, pvptype=-1, heroid=-1, rankId=-1, rankSegment=-1,
          battle_id=-1, honor_adcode=156, *, last_time=0):
    """Delegate business names to SDK APIs; reuse the process client and cooldown."""
    global _client
    with _lock:
        if _client is None:
            _client = CampClient.from_config(config, timeout=30, trust_env=False)
        else:
            _client.update_config(config)
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

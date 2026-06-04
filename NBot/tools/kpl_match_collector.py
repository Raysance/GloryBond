"""
kpl_match_collector

提供 B 站赛事中心赛程与单场数据的获取接口，供 qbot 业务层直接调用。

对外推荐接口：
- `get_full_match_list(...)`: 获取赛程并按 finished/ongoing/upcoming 分组
- `get_match_content(...)`: 根据 cid 获取单场的选手评分/热评/英雄/KDA 等内容
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

import requests

API_BASE = "https://api.bilibili.com"
API_ENDPOINTS = {
    "schedule_list": f"{API_BASE}/x/esports/matchs/list",
    "match_grade": f"{API_BASE}/x/esports/grade/info",
}

DEFAULTS: Dict[str, Any] = {
    "mid": 214,
    "ps": 50,
    "schedule_url_template": "https://www.bilibili.com/v/game/match/schedule?mid={mid}&time={time_ms}",
}

MatchStatus = Literal["upcoming", "ongoing", "finished"]


def _ensure_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _to_epoch_seconds(dt: datetime, *, default_tz: str = "Asia/Shanghai") -> int:
    if dt.tzinfo is not None:
        return int(dt.timestamp())
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(default_tz)
        return int(dt.replace(tzinfo=tz).timestamp())
    except Exception:
        return int(dt.replace(tzinfo=timezone.utc).timestamp())


def _dt_from_ts(ts: Optional[int], tz_name: str = "Asia/Shanghai") -> Optional[str]:
    if not ts:
        return None
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz).isoformat()


def _classify_match(now_sec: int, stime: Optional[int], etime: Optional[int]) -> MatchStatus:
    if stime is None:
        return "upcoming"
    if now_sec < stime:
        return "upcoming"
    if etime is not None and now_sec >= etime:
        return "finished"
    return "ongoing"


@dataclass
class BiliClient:
    """
    B 站接口请求客户端（requests.Session 封装）。

    - `create()` 构造带常用 headers 的 session
    - `get_json()` 统一处理 code/message 并在异常时抛出
    """
    session: requests.Session

    @staticmethod
    def create() -> "BiliClient":
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
                "Accept-Encoding": "identity",
            }
        )
        return BiliClient(session=s)

    def get_json(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("code") not in (0, "0", None):
            raise RuntimeError(f"API error: code={data.get('code')} message={data.get('message')}")
        return data


def fetch_schedule(
    client: BiliClient,
    *,
    mid: int,
    time_ms: int,
    pn: int = 1,
    ps: int = 50,
) -> Dict[str, Any]:
    """
    获取赛程分页列表。

    返回：
    - items: 标准化后的 contest 列表（包含队伍/比分/时间等）
    - raw: 原始接口响应（便于业务侧排查字段变更）
    """
    url = API_ENDPOINTS["schedule_list"]
    payload = client.get_json(url, params={"mid": mid, "time": time_ms, "pn": pn, "ps": ps})
    contests = (payload.get("data") or {}).get("list") or []
    out: List[Dict[str, Any]] = []
    for c in contests:
        home = c.get("home_team") or {}
        away = c.get("away_team") or {}
        out.append(
            {
                "contest_id": c.get("id"),
                "title": c.get("title"),
                "season_title": (c.get("season") or {}).get("title"),
                "game_stage": c.get("game_stage"),
                "start_time": c.get("stime"),
                "start_time_iso": _dt_from_ts(_ensure_int(c.get("stime"))),
                "end_time": c.get("etime"),
                "end_time_iso": _dt_from_ts(_ensure_int(c.get("etime"))),
                "home_team": {"id": c.get("home_id"), "name": home.get("title") or home.get("name"), "logo": home.get("logo")},
                "away_team": {"id": c.get("away_id"), "name": away.get("title") or away.get("name"), "logo": away.get("logo")},
                "score": {"home": c.get("home_score"), "away": c.get("away_score")},
                "raw": c,
            }
        )
    return {
        "mid": mid,
        "time": time_ms,
        "pn": pn,
        "ps": ps,
        "items": out,
        "raw": payload,
    }


def fetch_match_grade(client: BiliClient, *, cid: int) -> Dict[str, Any]:
    """
    获取单场内容（选手评分/热评/英雄/KDA 等）。

    关键字段来源：
    - data.teams[].player_grade_detail[] 提供选手评分与热评等信息

    返回：
    - score: 系列赛总比分（home/away）
    - teams: 队伍基础信息（name/logo 等，原样透传，可能为空）
    - players: 单局维度的选手列表（当前 bo 的英雄/KDA/热评等；来源 player_grade_detail）
    - global_players: 系列赛维度的选手评分列表（来源 global_grade_info；不包含英雄/KDA）
    - raw: 原始接口响应
    """
    url = API_ENDPOINTS["match_grade"]
    payload = client.get_json(url, params={"cid": cid})
    data = payload.get("data") or {}

    home_team = data.get("home_team") or {}
    away_team = data.get("away_team") or {}

    teams = data.get("teams") or []
    if not teams and (home_team or away_team):
        teams = [{"name": home_team.get("name")}, {"name": away_team.get("name")}]

    score = data.get("score") or {
        "home": data.get("home_score"),
        "away": data.get("away_score"),
    }

    players_out: List[Dict[str, Any]] = []
    for team in (data.get("teams") or []):
        team_name = team.get("name")
        team_id = team.get("team_id") or team.get("id")
        player_list = team.get("player_grade_detail") or []
        for p in player_list:
            if not isinstance(p, dict):
                continue
            hero_photo = p.get("hero_photo") or ""
            hero_id = None
            if hero_photo:
                m = re.search(r"/(\d+)\.(?:png|jpg|jpeg|webp)$", str(hero_photo))
                hero_id = int(m.group(1)) if m else None
            players_out.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "player_id": p.get("player_id"),
                    "player_name": p.get("nickname"),
                    "position": p.get("position"),
                    "avg_grade": p.get("avg_grade"),
                    "grade_users": p.get("grade_users"),
                    "kda": {"kill": p.get("kill"), "death": p.get("death"), "assist": p.get("assist")},
                    "hero": {"hero_id": hero_id, "hero_photo": hero_photo},
                    "hot_comment": p.get("hot_remark") or "",
                    "raw": p,
                }
            )

    global_players: List[Dict[str, Any]] = []
    global_grade = data.get("global_grade_info") or {}
    for side in ["home_team", "away_team"]:
        side_info = global_grade.get(side) or {}
        for p in side_info.get("players") or []:
            if not isinstance(p, dict):
                continue
            global_players.append(
                {
                    "side": side,
                    "player_id": p.get("player_id"),
                    "player_name": p.get("nickname"),
                    "position": p.get("place"),
                    "avg_grade": p.get("avg_grade"),
                    "raw": p,
                }
            )

    return {
        "cid": cid,
        "match_name": data.get("match_name") or data.get("title"),
        "season": data.get("season") or {},
        "game_stage": data.get("game_stage"),
        "current_bo": data.get("current_bo"),
        "bo_status": data.get("bo_status"),
        "start_time": _ensure_int(data.get("stime")) or _ensure_int(data.get("start_time")),
        "start_time_iso": _dt_from_ts(_ensure_int(data.get("stime")) or _ensure_int(data.get("start_time"))),
        "end_time": _ensure_int(data.get("etime")) or _ensure_int(data.get("end_time")),
        "end_time_iso": _dt_from_ts(_ensure_int(data.get("etime")) or _ensure_int(data.get("end_time"))),
        "teams": teams,
        "score": score,
        "players": players_out,
        "global_players": global_players,
        "raw": payload,
    }


def _normalize_contest_item(contest: Dict[str, Any], *, now_sec: int) -> Dict[str, Any]:
    stime_i = int(contest["stime"]) if isinstance(contest.get("stime"), int) else None
    etime_i = int(contest["etime"]) if isinstance(contest.get("etime"), int) else None

    home = contest.get("home_team") or {}
    away = contest.get("away_team") or {}

    status = _classify_match(now_sec, stime_i, etime_i)
    return {
        "cid": contest.get("id"),
        "mid": contest.get("mid"),
        "season_id": contest.get("sid") or contest.get("season_id") or (contest.get("season") or {}).get("id"),
        "season_title": (contest.get("season") or {}).get("title"),
        "title": contest.get("title"),
        "game_stage": contest.get("game_stage"),
        "stime": stime_i,
        "etime": etime_i,
        "home": {"id": contest.get("home_id"), "name": home.get("title") or home.get("name"), "logo": home.get("logo")},
        "away": {"id": contest.get("away_id"), "name": away.get("title") or away.get("name"), "logo": away.get("logo")},
        "score": {"home": contest.get("home_score"), "away": contest.get("away_score")},
        "status": status,
        "raw": contest,
    }


def get_full_match_list(
    *,
    mid: int,
    time_ms: int,
    now: datetime,
    ps: int = 50,
    tz_name: str = "Asia/Shanghai",
) -> Dict[str, Any]:
    now_sec = _to_epoch_seconds(now, default_tz=tz_name)
    client = BiliClient.create()

    first = fetch_schedule(client, mid=mid, time_ms=time_ms, pn=1, ps=ps)
    raw_first = first.get("raw") or {}
    page = (raw_first.get("data") or {}).get("page") or {}
    total = page.get("total") if isinstance(page.get("total"), int) else None
    size = page.get("size") if isinstance(page.get("size"), int) else ps

    contests: List[Dict[str, Any]] = []
    contests.extend((raw_first.get("data") or {}).get("list") or [])

    if total is not None and total > len(contests):
        last_pn = math.ceil(total / max(int(size), 1))
        for pn in range(2, last_pn + 1):
            p = fetch_schedule(client, mid=mid, time_ms=time_ms, pn=pn, ps=ps)
            raw = p.get("raw") or {}
            contests.extend((raw.get("data") or {}).get("list") or [])

    normalized = [_normalize_contest_item(c, now_sec=now_sec) for c in contests]
    normalized.sort(key=lambda x: (x.get("stime") or -1), reverse=True)

    groups: Dict[str, List[Dict[str, Any]]] = {"finished": [], "ongoing": [], "upcoming": []}
    for it in normalized:
        groups[it["status"]].append(it)

    return {
        "mid": mid,
        "time": time_ms,
        "now_epoch": now_sec,
        "ps": ps,
        "counts": {
            "total": len(normalized),
            "finished": len(groups["finished"]),
            "ongoing": len(groups["ongoing"]),
            "upcoming": len(groups["upcoming"]),
        },
        "groups": groups,
        "list": normalized,
    }


def get_match_content(match_params: Dict[str, Any]) -> Dict[str, Any]:
    cid = match_params.get("cid")
    if cid is None:
        raise ValueError("match_params 缺少必要字段 cid")
    client = BiliClient.create()
    return fetch_match_grade(client, cid=int(cid))

def get_series_summary(match_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    获取系列赛（大场/整场 BO）维度信息。

    返回字段（JSON 可序列化）：
    - cid
    - match_name / game_stage / start_time_iso / end_time_iso
    - teams: [{"name": str, "score": int|None, "players": [{"name": str, "pos": str|None, "score": str|None}]}]
      其中 players 来源于 global_grade_info，不包含英雄/KDA/热评
    - raw: 原始接口响应
    """
    content = get_match_content(match_params)
    raw = content.get("raw") or {}
    data = raw.get("data") or {}
    home_team = data.get("home_team") or {}
    away_team = data.get("away_team") or {}
    home_name = home_team.get("name") or ""
    away_name = away_team.get("name") or ""
    home_score = data.get("home_score")
    away_score = data.get("away_score")

    pos_map = {"TOP": "对抗路", "JUG": "打野", "MID": "中路", "AD": "发育路", "SUP": "游走"}
    teams_out = []
    grade = data.get("global_grade_info") or {}
    for side, name, score in [("home_team", home_name, home_score), ("away_team", away_name, away_score)]:
        if not name:
            continue
        players = []
        for p in (grade.get(side) or {}).get("players") or []:
            if not isinstance(p, dict):
                continue
            place = p.get("place")
            players.append({"name": p.get("nickname"), "pos": pos_map.get(str(place), place), "score": p.get("avg_grade")})
        teams_out.append({"name": name, "score": score, "players": players})

    return {
        "cid": content.get("cid"),
        "match_name": content.get("match_name"),
        "game_stage": content.get("game_stage"),
        "start_time_iso": content.get("start_time_iso"),
        "end_time_iso": content.get("end_time_iso"),
        "teams": teams_out,
        "raw": raw,
    }

def get_current_map_detail(match_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    获取当前小局（地图/bo）维度信息。

    说明：bilibili `x/esports/grade/info` 在 `teams[].player_grade_detail` 中包含英雄/KDA/热评等，
    其语义更接近“当前 bo 的单局数据”。目前未发现可稳定指定 bo 序号的参数接口，因此仅提供当前数据读取。

    返回字段（JSON 可序列化）：
    - cid
    - current_bo / bo_status
    - score: 系列赛总比分
    - teams: 队伍基础信息
    - players: 单局维度选手信息（英雄/KDA/热评）
    - raw: 原始接口响应
    """
    content = get_match_content(match_params)
    return {
        "cid": content.get("cid"),
        "current_bo": content.get("current_bo"),
        "bo_status": content.get("bo_status"),
        "score": content.get("score"),
        "teams": content.get("teams"),
        "players": content.get("players"),
        "raw": content.get("raw"),
    }

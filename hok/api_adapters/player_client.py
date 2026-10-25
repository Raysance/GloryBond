"""Read-only game adapter with external, account-wide pacing and circuit breaks."""

OPERATIONS = frozenset({
    "homepage", "profile", "history", "heroes", "game", "hero_assets",
    "collections", "displayed_skins", "hero_road_brief", "hero_detail", "hero_titles", "search",
    "matches", "game_statistics", "hero_honors", "profile_summary",
    "friends", "friend_states", "friend_state",
})


class PlayerClientRateLimited(RuntimeError):
    def __init__(self, retry_after, reason="interval"):
        self.retry_after, self.reason = retry_after, reason
        super().__init__("Player client requests are cooling down")


def player_client_error_info(error):
    """Log only types, protocol IDs and counts, never account material or payloads."""
    from hok_research import QueryTimeout

    info = {"type": type(error).__name__}
    for field in ("code", "command", "message_id"):
        value = getattr(error, field, None)
        if type(value) is int:
            info[field] = value
    control = getattr(error, "error", None)
    if isinstance(control, dict):
        for field in ("code", "detail"):
            if type(control.get(field)) is int:
                info["control_" + field] = control[field]
    if isinstance(error, QueryTimeout):
        info["response_chunks"] = len(error.partial_chunks)
        info["response_records"] = len(error.partial_records)
    return info


def player_client_artwork_api(items, settings):
    """Bounded public artwork GETs, with no account cookies or environment proxy."""
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlsplit
    from .tianyuanzhiyi import _skin_votes_get_bytes

    def fetch(item):
        url = item["avatarUrl"]
        if urlsplit(url).hostname != "game.gtimg.cn" or not url.startswith("https://"):
            return None
        try:
            return str(item["heroId"]), _skin_votes_get_bytes(url,
                float(settings["artwork_timeout_seconds"]), int(settings["artwork_max_bytes"]))
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        return dict(value for value in pool.map(fetch, items) if value)


class PlayerClientAdapter:
    """One connection, serialized by zfunc; never silently log in or retry again."""
    def __init__(self, *, paths, settings, gate, on_error):
        from hok_research import HokClient, MsdkSession

        self.settings, self.gate, self.on_error = settings, gate, on_error
        self.client = HokClient.from_resources(
            paths["resources"], installation_path=paths["installation"],
            timeout=float(settings["timeout_seconds"]),
            query_interval=float(settings["query_interval_seconds"]))
        try:
            self.client.use_msdk_session(MsdkSession.load(paths["session"]))
            # One login group covers directory selection and game authentication.
            gate("login")
            self.client.servers(platform_id=int(settings["platform_id"]))
            self.client.login(server_id=settings.get("server_id"), tree_index=int(settings.get("tree_index", 0)))
        except Exception as error:
            self.client.close()
            from ..zutil import log_message
            log_message(f"PLAYER_CLIENT_LOGIN_FAILED: info={player_client_error_info(error)}")
            on_error(error, login=True)
            raise

    def close(self):
        self.client.close()
        if hasattr(self, "_cache"):
            self._cache.clear()

    def heartbeat(self):
        try:
            self.client.heartbeat()
        except Exception as error:
            # Idle polling can receive the same server stop as a business read.
            # Apply its cooldown before the facade discards this connection.
            self.on_error(error, login=False)
            raise

    def _read(self, method, *args, **options):
        from collections import OrderedDict
        from copy import deepcopy
        from .. import ztime
        from ..zutil import log_message

        cacheable = method in {"profile", "game", "hero_titles", "hero_extra_statistics", "hero_road_brief", "hero_detail"}
        if not hasattr(self, "_cache"):
            self._cache = OrderedDict()
        key = (method, args, tuple(sorted(options.items())))
        ttl = float(self.settings.get("query_cache_ttl_seconds", 60))
        now = ztime.monotonic_seconds()
        cached = self._cache.get(key) if cacheable else None
        if cached is not None:
            if now < cached[0]:
                self._cache.move_to_end(key)
                log_message(f"PLAYER_CLIENT_READ_TIMING: operation={method} cached=true gate_ms=0 request_ms=0")
                return deepcopy(cached[1])
            del self._cache[key]
        # The server pushes the complete roster at login and then sends deltas.
        # Reading it does not emit a game request; pace only actual wire reads.
        if method != "friends":
            self.gate("query")
        admitted = ztime.monotonic_seconds()
        try:
            result = getattr(self.client, method)(*args, timeout=float(self.settings["timeout_seconds"]), **options)
        except Exception as error:
            log_message(f"PLAYER_CLIENT_REQUEST_FAILED: operation={method} info={player_client_error_info(error)} "
                        f"gate_ms={round((admitted-now)*1000)} "
                        f"request_ms={round((ztime.monotonic_seconds()-admitted)*1000)} "
                        f"timeout_ms={round(float(self.settings['timeout_seconds'])*1000)}")
            self.on_error(error, login=False)
            raise
        log_message(f"PLAYER_CLIENT_READ_TIMING: operation={method} cached=false "
                    f"gate_ms={round((admitted-now)*1000)} request_ms={round((ztime.monotonic_seconds()-admitted)*1000)}")
        if cacheable and ttl > 0:
            self._cache[key] = (ztime.monotonic_seconds() + ttl, deepcopy(result))
            self._cache.move_to_end(key)
            while len(self._cache) > int(self.settings.get("query_cache_max_entries", 16)):
                self._cache.popitem(last=False)
        return result

    def _statistics_result(self, profile, *, scope="season", mode="all", branch=None):
        from hok_research.player_pages import battle_display
        from hok_research.profile_data import json_value

        result = profile.game.statistics(scope=scope, mode=mode, branch=branch).to_json_value()
        result["player_name"] = json_value(profile.raw.get("szAcntName"))
        rows = (result.get("display") or {}).get("source_rows") or []
        result["branch_statistics"] = ([{"branch": key, "display": battle_display([row])}
            for key, row in zip(("top", "mid", "bot", "jungle", "assist"), rows)] if branch is None else [])
        return result

    def _hero_page(self, target, *, hero_id=None):
        """Compose only the requested page sources, gating every real request."""
        from hok_research import PlayerHomepage, QueryRejected

        profile = self._read("profile", target)
        values, errors, details = {}, {}, {}
        sources = [("hero_titles", "hero_titles"), ("hero_extra_statistics", "hero_extra_statistics"),
                   ("hero_road_brief", "hero_road_brief")]
        for field, method in sources:
            try:
                values[field] = self._read(method, profile.player)
            except PlayerClientRateLimited:
                errors[field] = {"reason": "rate_limited"}
                # The same gate would reject subsequent requests too.
                break
            except QueryRejected as error:
                if error.code not in self.settings["rate_limit"]["privacy_codes"]:
                    raise
                errors[field] = {"code": error.code}
        if hero_id is not None and not any(error.get("reason") == "rate_limited" for error in errors.values()):
            try:
                details[int(hero_id)] = self._read("hero_detail", profile.player, int(hero_id))
            except PlayerClientRateLimited:
                errors["hero_detail"] = {"reason": "rate_limited"}
            except QueryRejected as error:
                if error.code not in self.settings["rate_limit"]["privacy_codes"]:
                    raise
                errors["hero_detail"] = {"code": error.code}
        return PlayerHomepage(profile, errors=errors, hero_details=details, **values)

    def query(self, operation, *, player=None, name=None, platform=None, scope="all", hero_id=None,
              mode="all", branch=None):
        from hok_research import PlayerRef, ResourceCatalog, PlayerHomepage, QueryRejected
        from hok_research.profile_data import json_value

        if operation not in OPERATIONS:
            raise ValueError("Unsupported player query")
        if operation == "search":
            if platform is None:
                from hok_research import PlayerSearchResult

                # The upstream aggregate makes two requests; gate both individually.
                results = [self._read("search_players", name, platform=value) for value in (1, 2)]
                return PlayerSearchResult.combine(results).to_json_value()
            return self._read("search_players", name, platform=platform).to_json_value()
        if operation in {"friends", "friend_states"}:
            if player is not None:
                raise ValueError("Game friends belong to the current logged-in role")
            from hok_research import GameplayCatalog

            catalog = GameplayCatalog.bundled()
            snapshot = self._read("friends")
            if operation == "friends":
                return snapshot.to_json_value(gameplay_catalog=catalog)
            if any(state.online is True for state in snapshot.players):
                snapshot = self._read("refresh_friend_states", snapshot)
            states = snapshot.players
            return {"complete": snapshot.complete, "total": len(states),
                    "players": [state.to_json_value(gameplay_catalog=catalog) for state in states]}
        if not player:
            raise ValueError("An explicitly configured target player is required")
        target = PlayerRef(**{key: int(player[key]) for key in ("uid", "logic_world_id", "fake_description_id")})
        if operation == "friend_state":
            from hok_research import GameplayCatalog

            snapshot = self._read("friends")
            state = snapshot.by_player(target)
            if state is not None and state.online is True:
                state = self._read("refresh_friend_states", snapshot).by_player(target)
            return {"found": state is not None,
                    "state": state.to_json_value(gameplay_catalog=GameplayCatalog.bundled()) if state is not None else None}
        if operation == "profile_summary":
            from hok_research.player_pages import branch_page

            profile = self._read("profile", target)
            radar = profile.raw.get("stStatistic", {}).get("stRadarDetail", {})
            statistics = (self._statistics_result(profile)
                          if "stCurSeason" in radar else None)
            return {"profile": profile.to_json_value(), "statistics": statistics,
                    "branches": branch_page(profile, catalog=ResourceCatalog.bundled())}
        if operation == "homepage":
            # Compose outside the module so each actual data request passes the gate.
            profile = self._read("profile", target)
            history, errors = None, {}
            try:
                history = self._read("history", profile.player)
            except QueryRejected as error:
                if error.code not in self.settings["rate_limit"]["privacy_codes"]:
                    raise
                errors["history"] = {"code": error.code}
            result = PlayerHomepage(profile, history, errors=errors)
        elif operation == "matches":
            from hok_research import GameplayCatalog
            return self._read("matches", target).to_json_value(
                catalog=ResourceCatalog.bundled(), gameplay_catalog=GameplayCatalog.bundled())
        elif operation == "game_statistics":
            profile = self._read("profile", target)
            return self._statistics_result(profile, scope=scope, mode=mode, branch=branch)
        elif operation == "hero_honors":
            page = self._hero_page(target, hero_id=hero_id)
            result = page.hero_honors(int(hero_id), scope=scope).to_json_value(catalog=ResourceCatalog.bundled())
            result["errors"] = page.errors
            result["player_name"] = json_value(page.profile.raw.get("szAcntName"))
            return result
        elif operation == "heroes":
            page = self._hero_page(target)
            result = page.hero_page(scope=scope, sort_by="highest_fight_value").to_json_value(catalog=ResourceCatalog.bundled())
            return {"scope": scope, "heroes": result["cards"], "branches": result["branches"], "errors": page.errors,
                    "player_name": json_value(page.profile.raw.get("szAcntName"))}
        elif operation == "hero_detail":
            result = self._read(operation, target, int(hero_id))
        else:
            result = self._read(operation, target)
        if hasattr(result, "to_json_value"):
            return result.to_json_value()
        return json_value(result.raw if hasattr(result, "raw") else result)

"""Read-only game adapter with external, account-wide pacing and circuit breaks."""

OPERATIONS = frozenset({
    "homepage", "profile", "history", "heroes", "game", "hero_assets",
    "collections", "displayed_skins", "hero_road_brief", "hero_detail", "hero_titles", "search",
    "matches", "game_statistics", "hero_honors",
})


class PlayerClientRateLimited(RuntimeError):
    def __init__(self, retry_after, reason="interval"):
        self.retry_after, self.reason = retry_after, reason
        super().__init__("Player client requests are cooling down")


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
            on_error(error, login=True)
            raise

    def close(self):
        self.client.close()

    def _read(self, method, *args, **options):
        self.gate("query")
        try:
            return getattr(self.client, method)(*args, timeout=float(self.settings["timeout_seconds"]), **options)
        except Exception as error:
            self.on_error(error, login=False)
            raise

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
        if not player:
            raise ValueError("An explicitly configured target player is required")
        target = PlayerRef(**{key: int(player[key]) for key in ("uid", "logic_world_id", "fake_description_id")})
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
            game = self._read("game", target)
            return game.statistics(scope=scope, mode=mode, branch=branch).to_json_value()
        elif operation == "hero_honors":
            page = self._hero_page(target, hero_id=hero_id)
            result = page.hero_honors(int(hero_id), scope=scope).to_json_value(catalog=ResourceCatalog.bundled())
            result["errors"] = page.errors
            return result
        elif operation == "heroes":
            page = self._hero_page(target)
            result = page.hero_page(scope=scope, sort_by="highest_fight_value").to_json_value(catalog=ResourceCatalog.bundled())
            return {"scope": scope, "heroes": result["cards"], "branches": result["branches"], "errors": page.errors}
        elif operation == "hero_detail":
            result = self._read(operation, target, int(hero_id))
        else:
            result = self._read(operation, target)
        if hasattr(result, "to_json_value"):
            return result.to_json_value()
        return json_value(result.raw if hasattr(result, "raw") else result)

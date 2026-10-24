"""Read-only game adapter with external, account-wide pacing and circuit breaks."""

OPERATIONS = frozenset({
    "homepage", "profile", "history", "heroes", "game", "hero_assets",
    "collections", "displayed_skins", "hero_road_brief", "hero_detail", "hero_titles", "search",
})


class PlayerClientRateLimited(RuntimeError):
    def __init__(self, retry_after, reason="interval"):
        self.retry_after, self.reason = retry_after, reason
        super().__init__("Player client requests are cooling down")


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

    def query(self, operation, *, player=None, name=None, platform=1, scope="all", hero_id=None):
        from hok_research import PlayerRef, ResourceCatalog, PlayerHomepage, QueryRejected
        from hok_research.profile_data import json_value

        if operation not in OPERATIONS:
            raise ValueError("Unsupported player query")
        if operation == "search":
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
        elif operation == "heroes":
            result = self._read("heroes", target, scope=scope)
            return {"scope": scope, "heroes": [row.to_json_value(catalog=ResourceCatalog.bundled())
                                              for row in result.player_heroes()]}
        elif operation == "hero_detail":
            result = self._read(operation, target, int(hero_id))
        else:
            result = self._read(operation, target)
        if hasattr(result, "to_json_value"):
            return result.to_json_value()
        return json_value(result.raw if hasattr(result, "raw") else result)

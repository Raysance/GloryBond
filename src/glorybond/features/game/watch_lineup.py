"""Render only facts present in the watch response using the strength template."""
import math
from urllib.parse import urlsplit


def _text(value):
    return value.strip()[:200] if isinstance(value, str) and value.strip() else None


def _asset(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        from ipaddress import ip_address
        try:
            if not ip_address(parsed.hostname).is_global:
                return None
        except ValueError:
            if parsed.hostname == "localhost":
                return None
        return value
    except ValueError:
        pass
    return None


def _number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0 or (integer and not number.is_integer()):
        return None
    return int(number) if integer else number


def _win_rate(value):
    percent = isinstance(value, str) and value.strip().endswith("%")
    number = _number(value.strip()[:-1] if percent else value)
    if number is None or number > 100:
        return None
    return number / 100 if percent or number > 1 else number


def prepare_watch_lineup(battle_info, *, role_id):
    if not isinstance(battle_info, dict):
        return None
    battle_id = battle_info.get("battleID")
    if type(battle_id) not in (str, int) or not str(battle_id).strip() or str(battle_id) == "0":
        return None
    teams = []
    for camp in (1, 2):
        rows = battle_info.get(f"camp{camp}") or []
        if not isinstance(rows, list) or len(rows) > 10:
            raise ValueError("Unsupported watch lineup structure")
        players = []
        for raw in rows:
            raw = raw if isinstance(raw, dict) else {}
            role = raw.get("roleInfo") if isinstance(raw.get("roleInfo"), dict) else {}
            hero_id = raw.get("heroId")
            players.append({"name": _text(role.get("roleName")), "hero_name": _text(raw.get("heroName")),
                            "hero_id": str(hero_id) if type(hero_id) in (str, int) else None,
                            "hero_icon": _asset(raw.get("heroIcon")), "role_icon": _asset(role.get("roleIcon")),
                            "wins": _number(raw.get("win"), integer=True),
                            "losses": _number(raw.get("lost"), integer=True),
                            "win_rate": _win_rate(raw.get("winRate")),
                            "hero_power": _number(raw.get("heroFightValue"), integer=True),
                            "is_target": bool(role_id) and str(raw.get("roleId")) == str(role_id)})
        teams.append({"camp": camp, "players": players})
    if not any(team["players"] for team in teams):
        return None
    return {"battle_id": str(battle_id), "map_name": _text(battle_info.get("mapName")), "teams": teams}


def available_metric_score(player):
    """Color-only comparison: average observed metrics, excluding missing terms."""
    terms = []
    if player["hero_power"] is not None:
        power = player["hero_power"]
        terms.append((2.0, power / (power + 5000)))
    if player["wins"] is not None and player["losses"] is not None:
        matches = player["wins"] + player["losses"]
        terms.append((1.3, matches / (matches + 100)))
    if player["win_rate"] is not None:
        terms.append((2.0, player["win_rate"]))
    return 100 * sum(weight * value for weight, value in terms) / sum(weight for weight, _ in terms) if terms else None


def render_watch_lineup_file(data):
    from glorybond.rendering.gen_coplayer_analyses import PlayerInfo, render_player_strength_image
    from glorybond.storage.files import load_watch_lineup_images, save_watch_lineup_image

    teams = list(data["teams"])
    target_teams = [team for team in teams if any(player["is_target"] for player in team["players"])]
    labels = ("阵营1", "阵营2")
    if len(target_teams) == 1:
        teams.sort(key=lambda team: team is not target_teams[0])
        labels = ("我方", "对方")
    players = [PlayerInfo(
        name=player["name"] or "", hero_name=player["hero_name"],
        avatar_path=player["role_icon"], hero_avatar_url=player["hero_icon"],
        hero_power=player["hero_power"], wins=player["wins"], losses=player["losses"],
        win_rate=player["win_rate"], score=available_metric_score(player), side="my" if index == 0 else "op",
    ) for index, team in enumerate(teams) for player in team["players"]]
    image = render_player_strength_image(
        players, title="本局双方阵容", subtitle=data["map_name"],
        partial_data=True, images=load_watch_lineup_images(data), team_labels=labels,
    )
    return save_watch_lineup_image(image)

"""Trusted HOK identity policy of the local adapter, separate from role logic."""

from agent_runtime import Principal


LOCAL_SCOPES = frozenset(
    {
        "chat.read",
        "chat.cross_group",
        "game.read",
        "web.read",
        "python.execute",
        "image.generate",
        "memory.use",
        "task.use",
        "reference.read",
        "roleplay.use",
    }
)


def local_principal(snapshot, player_key):
    records = snapshot["context"]["catalogs"].get("players", [])
    matches = [r for r in records if r.get("player_key") == player_key]
    if len(matches) != 1 or len(matches[0].get("qq", [])) != 1:
        raise ValueError("本地默认玩家必须在权威映射中唯一对应QQ")
    player = matches[0]
    return Principal(
        user_id=player["qq"][0],
        scopes=LOCAL_SCOPES,
        attributes={
            "chat": {"all_groups": True},
            "identity": {"player_key": player_key, "name": player["name"]},
        },
    )

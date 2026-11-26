"""Identify the exact watched battle using the response's existing detail route."""
from urllib.parse import parse_qsl, urlsplit


def battle_reference(battle_info, *, role_id):
    if not isinstance(battle_info, dict) or not battle_info.get("battleID"):
        return None
    route = battle_info.get("battleDetailUrl")
    if not isinstance(route, str) or len(route) > 8192:
        return None
    try:
        parsed = urlsplit(route)
        if (parsed.scheme, parsed.netloc, parsed.path) != ("smobagamehelper", "hippy", ""):
            return None
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=80)
        fields = dict(pairs)
        if len(fields) != len(pairs) or fields.get("modulename") != "battledetail":
            return None
        names = ("gameSvrId", "relaySvrId", "gameSeq", "pvpType", "toAppRoleId")
        if any(not fields.get(key, "").isascii() or not fields.get(key, "").isdecimal()
               or len(fields[key]) > 30 for key in names):
            return None
        if fields["toAppRoleId"] != str(role_id) or int(fields["gameSeq"]) <= 0:
            return None
        return {"battle_id": str(battle_info["battleID"]), "params": {
            "gameseq": fields["gameSeq"], "gameSvrId": fields["gameSvrId"],
            "relaySvrId": fields["relaySvrId"], "pvptype": int(fields["pvpType"]),
        }}
    except (ValueError, TypeError):
        return None


def completed_battle(page, params):
    """A matching history row proves completion; elapsed time never does."""
    if not isinstance(page, dict) or not isinstance(page.get("list"), list):
        raise ValueError("战绩列表格式无效")
    if page.get("invisible") is True:
        raise PermissionError("该玩家战绩不可见，本次结束推送已停止")
    fields = {"gameSeq": "gameseq", "gameSvrId": "gameSvrId",
              "relaySvrId": "relaySvrId", "pvpType": "pvptype"}
    return any(isinstance(row, dict) and row.get("isGaming") is not True
               and all(str(row.get(source)) == str(params[target]) for source, target in fields.items())
               for row in page["list"])

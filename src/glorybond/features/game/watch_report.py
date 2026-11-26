"""Identify the exact watched battle using the response's existing detail route."""
from urllib.parse import parse_qsl, urlsplit


def _relay_server_id(value):
    """Compare the same 32-bit ID in signed history and unsigned watch form."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = str(value)
    digits = text[1:] if text.startswith("-") else text
    if not digits.isascii() or not digits.isdecimal() or len(digits) > 10:
        return None
    number = int(text)
    return number % (1 << 32) if -(1 << 31) <= number < (1 << 32) else None


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
        names = ("gameSvrId", "gameSeq", "pvpType", "toAppRoleId")
        if any(not fields.get(key, "").isascii() or not fields.get(key, "").isdecimal()
               or len(fields[key]) > 30 for key in names):
            return None
        if _relay_server_id(fields.get("relaySvrId")) is None:
            return None
        if fields["toAppRoleId"] != str(role_id) or int(fields["gameSeq"]) <= 0:
            return None
        return {"battle_id": str(battle_info["battleID"]), "params": {
            "gameseq": fields["gameSeq"], "gameSvrId": fields["gameSvrId"],
            "relaySvrId": fields["relaySvrId"], "pvptype": int(fields["pvpType"]),
        }}
    except (ValueError, TypeError):
        return None


def completed_battle_params(page, params):
    """Match all identifiers, accounting for the relay's signed representation."""
    if not isinstance(page, dict) or not isinstance(page.get("list"), list):
        raise ValueError("战绩列表格式无效")
    if page.get("invisible") is True:
        raise PermissionError("该玩家战绩不可见，本次结束推送已停止")
    expected_relay = _relay_server_id(params.get("relaySvrId"))
    if expected_relay is None:
        return None
    fields = {"gameSeq": "gameseq", "gameSvrId": "gameSvrId", "pvpType": "pvptype"}
    for row in page["list"]:
        if not isinstance(row, dict) or row.get("isGaming") in (True, 1, "1", "true"):
            continue
        if not all(str(row.get(source)) == str(params[target]) for source, target in fields.items()):
            continue
        if _relay_server_id(row.get("relaySvrId")) != expected_relay:
            continue
        return {**params, "relaySvrId": str(row["relaySvrId"])}
    return None

"""Application result projections; SQL row shapes are not kernel contracts."""


def project_sql_result(value, max_chars):
    data = value.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("observations"), list):
        return value
    observations = []
    for item in data["observations"]:
        projected = dict(item)
        if "rows" in projected:
            projected["rows"] = projected["rows"][:3]
            projected["context_truncated"] = True
        observations.append(projected)
    return {**value, "data": {**data, "observations": observations}}

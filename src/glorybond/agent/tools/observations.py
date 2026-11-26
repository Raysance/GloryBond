"""Application result projections; SQL row shapes are not kernel contracts."""

from decimal import Decimal, InvalidOperation


def numeric_column_totals(observation):
    """Exact arithmetic on returned rows, never infer population or denominators."""
    totals = {}
    rows = observation.get("rows", [])
    for column in observation.get("columns", []):
        values = [row.get(column) for row in rows if row.get(column) is not None]
        if not values or any(type(value) not in {int, float, Decimal} for value in values):
            continue
        try:
            decimals = [Decimal(str(value)) for value in values]
            if not all(value.is_finite() for value in decimals):
                continue
            total = sum(decimals, Decimal(0))
        except InvalidOperation:
            continue
        totals[column] = {"sum": format(total, "f"), "non_null_rows": len(values)}
    return {"basis": "returned_rows", "complete": not observation.get("truncated", False), "columns": totals}


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

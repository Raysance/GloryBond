"""Portable read-only KPLLL protocol adapter, outside the agent engine."""
import datetime
import json
import re
from urllib.parse import urlencode, urlsplit

import requests


def validate_kpl_config(config):
    keys = {"enabled", "api_base_url", "site_url", "timeout_seconds", "max_response_bytes",
            "max_rows", "max_nested_items", "max_observation_chars"}
    if not isinstance(config, dict) or set(config) != keys or type(config["enabled"]) is not bool:
        raise ValueError("AgentKPL 必须使用完整的公开配置，不能包含凭据或额外字段")
    for key in ("api_base_url", "site_url"):
        parsed = urlsplit(config[key])
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError(f"AgentKPL.{key} 必须为无凭据的 HTTPS 地址")
    for key, maximum in (("max_response_bytes", 8388608), ("max_rows", 200),
                         ("max_nested_items", 100), ("max_observation_chars", 64000)):
        if type(config[key]) is not int or not 1 <= config[key] <= maximum:
            raise ValueError(f"AgentKPL.{key} 超出允许范围")
    if type(config["timeout_seconds"]) not in (int, float) or not 0 < config["timeout_seconds"] <= 60:
        raise ValueError("AgentKPL.timeout_seconds 超出允许范围")
    return dict(config)


def validate_kpl_params(catalog, action, params):
    if action not in catalog["actions"] or not isinstance(params, dict):
        raise ValueError("未知 KPL 查询或参数格式无效，请查看 kpl 目录")
    spec = catalog["actions"][action]
    definitions = {name: catalog["parameters"][kind] for name, kind in spec.get("params", {}).items()}
    if set(params) - set(definitions):
        raise ValueError("KPL 查询包含不支持的参数：" + ", ".join(sorted(set(params) - set(definitions))))
    missing = set(spec.get("required", [])) - set(params)
    if missing:
        raise ValueError("KPL 查询缺少参数：" + ", ".join(sorted(missing)))
    for name, value in params.items():
        definition = definitions[name]
        if definition["type"] == "integer":
            if type(value) is not int or not definition.get("min", 1) <= value <= definition.get("max", 10**16):
                raise ValueError(f"KPL 参数 {name} 必须是允许范围内的整数")
        elif not isinstance(value, str) or not value.strip() or len(value) > definition.get("max_length", 80):
            raise ValueError(f"KPL 参数 {name} 必须是有效文字")
        if "enum" in definition and value not in definition["enum"]:
            raise ValueError(f"KPL 参数 {name} 必须取 {definition['enum']}")
        if "pattern" in definition and not re.fullmatch(definition["pattern"], str(value)):
            raise ValueError(f"KPL 参数 {name} 格式无效")
    if any(params[left] == params[right] for left, right in spec.get("distinct_params", [])):
        raise ValueError("KPL 英雄组合的两个位置必须不同")
    return spec


def _path_value(value, path):
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ValueError("KPL 接口响应结构已变化，请检查共享目录")
        value = value[key]
    return value


def _names(value, fields):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in fields and isinstance(item, str):
                yield item.casefold()
            elif isinstance(item, (dict, list)):
                yield from _names(item, fields)
    elif isinstance(value, list):
        for item in value:
            yield from _names(item, fields)


def _compact(value, excluded, nested_limit, omissions, path="data"):
    if isinstance(value, dict):
        return {key: _compact(item, excluded, nested_limit, omissions, path + "." + key)
                for key, item in value.items() if key not in excluded}
    if isinstance(value, list):
        if len(value) > nested_limit:
            omissions.append({"path": path, "total": len(value), "returned": nested_limit})
        return [_compact(item, excluded, nested_limit, omissions, path + f"[{index}]")
                for index, item in enumerate(value[:nested_limit])]
    return value


def query_kpl_data(catalog, config, args, *, transport=None):
    """One fixed-origin GET; HTTP settings never come from model arguments."""
    config = validate_kpl_config(config)
    if not config["enabled"]:
        raise ValueError("KPL 查询当前未启用")
    action, params = args["action"], args.get("params", {})
    spec = validate_kpl_params(catalog, action, params)
    offset, limit = args.get("offset", 0), args.get("limit", 20)
    nested_limit = args.get("nested_limit", 20)
    if type(offset) is not int or not 0 <= offset <= 100000:
        raise ValueError("KPL offset 超出允许范围")
    if type(limit) is not int or not 1 <= limit <= config["max_rows"]:
        raise ValueError("KPL limit 超出允许范围")
    if type(nested_limit) is not int or not 1 <= nested_limit <= config["max_nested_items"]:
        raise ValueError("KPL nested_limit 超出允许范围")
    search = args.get("search", "")
    fields = args.get("fields", [])
    bounds = {}
    for name in ("date_from", "date_to"):
        if args.get(name) is not None:
            try:
                bounds[name] = datetime.date.fromisoformat(args[name])
            except (ValueError, TypeError) as exc:
                raise ValueError("KPL 日期必须为有效 YYYY-MM-DD") from exc
    if len(bounds) == 2 and bounds["date_from"] > bounds["date_to"]:
        raise ValueError("KPL 开始日期不得晚于结束日期")
    if bounds and not spec.get("date_field"):
        raise ValueError("该查询不支持日期筛选；赛程请使用 matches")
    if not isinstance(search, str) or len(search) > 100:
        raise ValueError("KPL search 格式无效")
    if not isinstance(fields, list) or len(fields) > 40 or any(not isinstance(f, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", f) for f in fields):
        raise ValueError("KPL fields 格式无效")
    if not spec.get("collection") and (search or offset):
        raise ValueError("search/offset 仅用于列表查询；详情可用 fields 与 nested_limit")
    path_params = set(re.findall(r"\{([A-Za-z][A-Za-z0-9]*)\}", spec["path"]))
    route = spec["path"].format(**params)
    base = config["api_base_url"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("AgentKPL.api_base_url 必须为无凭据的 HTTPS API 地址")
    url = base + route
    query = {name: value for name, value in params.items() if name not in path_params}
    # Only the already-inspected paginated ranking endpoint accepts pagination.
    server_page = None
    if spec.get("server_pagination"):
        if search:
            raise ValueError("分页榜单不能用 search 过滤，否则会误解全榜范围")
        server_page = offset // limit + 1
        if offset % limit:
            raise ValueError("该榜单 offset 必须是 limit 的整数倍")
        query.update(page=server_page, pageSize=limit)
    with requests.Session() as session:
        session.trust_env = False
        request = transport or session.get
        try:
            with request(url, params=query, timeout=config["timeout_seconds"], stream=True,
                         allow_redirects=False, headers={"Accept": "application/json", "Accept-Encoding": "identity"}) as response:
                if response.status_code != 200:
                    raise ValueError(f"KPL 网站返回 HTTP {response.status_code}，未取得数据")
                if "json" not in response.headers.get("Content-Type", "").lower():
                    raise ValueError("KPL 网站返回非 JSON 内容，未取得数据")
                raw = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    raw.extend(chunk)
                    if len(raw) > config["max_response_bytes"]:
                        raise ValueError("KPL 响应超过体积上限，请缩小查询范围")
                payload = json.loads(raw)
        except requests.RequestException as exc:
            raise ValueError("KPL 网站连接或读取失败，请稍后重试") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("KPL 网站返回无效 JSON，未取得数据") from exc
    data = _path_value(payload, spec.get("data_path", ["data"]))
    if data is None or not isinstance(data, (list, dict)):
        raise ValueError("KPL 返回缺失数据或异常结构，不能作为查询证据")
    omissions = []
    total, filtered_total, next_offset = None, None, None
    if spec.get("collection"):
        if not isinstance(data, list):
            raise ValueError("KPL 列表响应结构已变化")
        total = len(data) if server_page is None else _path_value(payload, spec["total_path"])
        if type(total) is not int or total < 0:
            raise ValueError("KPL 列表总量格式异常")
        if search:
            data = [row for row in data if any(search.casefold() in name for name in _names(row, catalog["search_fields"]))]
        if bounds:
            selected = []
            for row in data:
                value = row.get(spec["date_field"])
                if not value:
                    continue
                try:
                    timestamp = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                except (TypeError, ValueError) as exc:
                    raise ValueError("KPL 赛程日期格式已变化，不能可靠筛选") from exc
                # Zoned times use the user's Shanghai calendar; naive API times
                # retain their source date without pretending to know a zone.
                day = timestamp.astimezone(datetime.timezone(datetime.timedelta(hours=8))).date() if timestamp.tzinfo else timestamp.date()
                if (("date_from" not in bounds or day >= bounds["date_from"])
                        and ("date_to" not in bounds or day <= bounds["date_to"])):
                    selected.append(row)
            data = selected
        filtered_total = len(data) if server_page is None else total
        if server_page is None:
            data = data[offset:offset + limit]
            if offset + len(data) < filtered_total:
                next_offset = offset + len(data)
        elif offset + len(data) < total:
            next_offset = offset + len(data)
        # Top-level paging is distinct from nested arrays in each returned row.
        data = [_compact(row, set(catalog["exclude_fields"]), nested_limit, omissions, f"data[{i}]") for i, row in enumerate(data)]
    else:
        data = _compact(data, set(catalog["exclude_fields"]), nested_limit, omissions)
    if fields:
        rows = data if isinstance(data, list) else [data]
        available = {key for row in rows if isinstance(row, dict) for key in row}
        if any(not isinstance(row, dict) for row in rows) or (rows and set(fields) - available):
            raise ValueError("KPL fields 包含不存在的字段，请采用返回数据中的字段名")
        projected = [{name: row.get(name) for name in fields} for row in rows]
        data = projected if isinstance(data, list) else projected[0]
    if len(json.dumps(data, ensure_ascii=False)) > config["max_observation_chars"]:
        raise ValueError("KPL 结果过大，请减小 limit/nested_limit 或用 fields 选择需要的字段")
    source_url = config["site_url"].rstrip("/") + spec["source_path"].format(**params)
    returned = len(data) if isinstance(data, list) else 1
    return {"source": catalog["source"], "source_url": source_url,
            "api_url": url + ("?" + urlencode(query) if query else ""), "action": action, "params": params,
            "retrieved_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
            "local_filters": {"search": search, **{name: value.isoformat() for name, value in bounds.items()}},
            "data": data, "row_count": returned, "offset": offset, "total": total,
            "filtered_total": filtered_total, "next_offset": next_offset,
            "truncated": bool(offset or next_offset is not None or omissions), "nested_truncations": omissions,
            "server_page": server_page, "notice": catalog["notice"]}

"""Declarative reference tools, kept outside the ReAct kernel."""

import hashlib
import json


def _strings(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _unique(values):
    return list(dict.fromkeys(values))


def account_id_binding(key, identifiers, sameuser):
    """Use an explicit ID first, then the unique sameuser owner's ID.

    A sameuser key is the main account; its values are related accounts. Never
    borrow IDs from siblings or choose between conflicting main accounts.
    """
    seen = set()
    while key not in seen:
        seen.add(key)
        direct = _unique(value.strip() for value in _strings(identifiers.get(key)) if value.strip())
        if direct:
            return direct, key
        owners = [str(owner) for owner, members in sameuser.items()
                  if str(owner) != key and key in _strings(members)]
        if len(owners) != 1:
            break
        key = owners[0]
    return [], None


class ReferenceData:
    """Build records using only explicitly declared source fields.

    IDs remain strings and retain their namespace. Collisions are returned as
    multiple matches; aliases and account relations never grant permissions.
    """

    def __init__(self, manifest, values, *, source):
        self.source = source
        self.catalogs = {}
        for spec in manifest["catalogs"]:
            records = self._build(spec, values)
            self.catalogs[spec["name"]] = {"spec": spec, "records": records}
        serialized = json.dumps(self.catalogs, ensure_ascii=False, sort_keys=True)
        self.version = hashlib.sha256(serialized.encode()).hexdigest()[:16]

    @staticmethod
    def _build(spec, values):
        def mapping(field):
            value = values.get(field, {})
            if not isinstance(value, dict):
                raise ValueError(f"Reference source {field} must be a mapping")
            return value

        if spec.get("kind", "entities") == "mapping":
            result = []
            for key, value in mapping(spec["field"]).items():
                if spec.get("orientation") == "name_to_id":
                    result.append({"id": str(value), "name": str(key), "aliases": []})
                else:
                    result.append(
                        {
                            "id": str(key),
                            "name": str(key),
                            "aliases": [],
                            "value": value,
                        }
                    )
            return result

        fields = (
            spec.get("names", [])
            + spec.get("aliases", [])
            + [f for sources in spec.get("ids", {}).values() for f in sources]
        )
        keys = _unique(str(key) for field in fields for key in mapping(field))
        records = {
            key: {"id": key, "name": key, "aliases": [], "ids": {}} for key in keys
        }
        for field in reversed(spec.get("names", [])):
            for key, name in mapping(field).items():
                records[str(key)]["name"] = str(name)
        for field in spec.get("aliases", []):
            for key, aliases in mapping(field).items():
                records[str(key)]["aliases"].extend(_strings(aliases))
        for field in spec.get("reverse_aliases", []):
            for alias, key in mapping(field).items():
                if str(key) in records:
                    records[str(key)]["aliases"].append(str(alias))
        for namespace, sources in spec.get("ids", {}).items():
            for field in sources:
                for key, value in mapping(field).items():
                    identifiers = records[str(key)]["ids"].setdefault(namespace, [])
                    identifiers.extend(_strings(value))
        for namespace, field in spec.get("id_fallbacks", {}).items():
            identifiers = {key: record["ids"].get(namespace, []) for key, record in records.items()}
            for key, record in records.items():
                ids, owner = account_id_binding(key, identifiers, mapping(field))
                if ids:
                    record["ids"][namespace] = ids
                if owner and owner != key:
                    record.setdefault("id_sources", {})[namespace] = owner
        for relation, sources in spec.get("relations", {}).items():
            for field in sources:
                for owner, members in mapping(field).items():
                    group = _unique([str(owner), *_strings(members)])
                    for key in group:
                        if key in records:
                            related = (
                                records[key]
                                .setdefault("relations", {})
                                .setdefault(relation, [])
                            )
                            related.extend(item for item in group if item != key)
        for record in records.values():
            record["aliases"] = _unique(record["aliases"])
            record["ids"] = {key: _unique(ids) for key, ids in record["ids"].items()}
            if "relations" in record:
                record["relations"] = {
                    k: _unique(v) for k, v in record["relations"].items()
                }
        return list(records.values())

    def directory(self):
        return {
            "source": self.source,
            "version": self.version,
            "catalogs": [
                {
                    "name": name,
                    "description": entry["spec"]["description"],
                    "id_namespace": entry["spec"]["id_namespace"],
                    "field_usage": entry["spec"].get("field_usage", {}),
                    "record_count": len(entry["records"]),
                }
                for name, entry in self.catalogs.items()
            ],
            "rules": [
                "ID 均为带命名空间的字符串，不同类型不能混用。",
                "名称和别名只是匹配线索；多条匹配均返回，不猜测唯一身份。",
                "参考数据提供名称对应关系，不提供消息统计、游戏战绩或权限。",
            ],
        }

    def context(self):
        catalogs = {}
        for name, entry in self.catalogs.items():
            spec = entry["spec"]
            if not spec.get("context"):
                continue
            records = []
            for item in entry["records"]:
                projected = {
                    spec["id_namespace"]: item["id"],
                    "name": item["name"],
                    "aliases": item["aliases"],
                }
                projected.update(
                    {
                        ns: ids
                        for ns, ids in item.get("ids", {}).items()
                        if ns in spec.get("context_namespaces", [])
                    }
                )
                sources = {ns: key for ns, key in item.get("id_sources", {}).items()
                           if ns in spec.get("context_namespaces", [])}
                if sources:
                    projected["id_sources"] = sources
                records.append(projected)
            catalogs[name] = records
        return {"source": self.source, "version": self.version, "catalogs": catalogs}

    def lookup(
        self,
        *,
        catalogs=(),
        terms=(),
        namespace=None,
        match="exact",
        offset=0,
        limit=50,
    ):
        selected = list(catalogs) or list(self.catalogs)
        unknown = set(selected) - self.catalogs.keys()
        if unknown:
            raise ValueError("未知参考目录：" + ", ".join(sorted(unknown)))
        if match not in {"exact", "contains"} or offset < 0 or not 1 <= limit <= 100:
            raise ValueError("无效的匹配方式或分页参数")
        known_namespaces = {
            ns
            for name in selected
            for ns in [
                self.catalogs[name]["spec"]["id_namespace"],
                *self.catalogs[name]["spec"].get("ids", {}),
            ]
        }
        if namespace is not None and namespace not in known_namespaces:
            raise ValueError("所选目录没有此 ID 命名空间：" + namespace)
        matches = []
        matched_terms = set()
        for name in selected:
            entry = self.catalogs[name]
            primary = entry["spec"]["id_namespace"]
            for record in entry["records"]:
                if namespace is None:
                    candidates = [record["id"], record["name"], *record["aliases"]]
                    candidates.extend(_strings(record.get("value")))
                    candidates.extend(
                        value for ids in record.get("ids", {}).values() for value in ids
                    )
                elif namespace == primary:
                    candidates = [record["id"]]
                else:
                    candidates = record.get("ids", {}).get(namespace, [])
                hits = [
                    term
                    for term in terms
                    if any(
                        str(term).casefold() == value.casefold()
                        if match == "exact"
                        else str(term).casefold() in value.casefold()
                        for value in candidates
                    )
                ]
                if terms and not hits:
                    continue
                matched_terms.update(hits)
                matches.append(
                    {
                        "catalog": name,
                        "id_namespace": primary,
                        "matched_terms": hits,
                        **record,
                    }
                )
        return {
            "source": self.source,
            "version": self.version,
            "matches": matches[offset : offset + limit],
            "total_matches": len(matches),
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(matches) else None,
            "unmatched_terms": [term for term in terms if term not in matched_terms],
            "field_usage": {
                name: self.catalogs[name]["spec"].get("field_usage", {})
                for name in selected
            },
        }

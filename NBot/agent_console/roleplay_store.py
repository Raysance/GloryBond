"""Owner-bound Redis persistence, called only by the external SSH worker."""

import hashlib
import json

from agent_console.roleplay_models import ReplyPreferences, RoleDefinition


def roleplay_operation(store, *, user_id, action, builtins, default_role, **args):
    if not user_id:
        raise ValueError("缺少可信用户身份")
    owner = hashlib.sha256(user_id.encode()).hexdigest()
    prefix = "hok:agent_runtime:console:roleplay:" + owner + ":"
    roles = {
        item.role_id: item
        for item in (RoleDefinition.model_validate(value) for value in builtins)
    }
    for raw in store.hvals(prefix + "roles"):
        item = RoleDefinition.model_validate_json(raw)
        roles[item.role_id] = item

    def resolve(identifier):
        if identifier in roles:
            return roles[identifier]
        matches = [r for r in roles.values() if r.name == identifier]
        if len(matches) != 1:
            raise ValueError("角色不存在或名称不唯一，请先读取目录并传 role_id")
        return matches[0]

    if action == "add":
        role = RoleDefinition.model_validate(args["role"])
        if (
            role.kind != "web"
            or not role.sources
            or not role.role_id.startswith("web_")
        ):
            raise ValueError("联网角色必须有真实来源和独立 web_ 标识")
        if role.role_id in roles:
            raise ValueError("角色标识已存在")
        # Atomic capacity enforcement also covers concurrent web builders.
        script = """
        if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 1 then return 0 end
        if redis.call('HLEN', KEYS[1]) >= 50 then return -1 end
        redis.call('HSET', KEYS[1], ARGV[1], ARGV[2]); return 1
        """
        saved = store.eval(
            script, 1, prefix + "roles", role.role_id, role.model_dump_json()
        )
        if saved != 1:
            raise ValueError("角色已存在或自定义角色已到50个上限")
        roles[role.role_id] = role
        if args.get("select", True):
            store.set(prefix + "selected", role.role_id)
    elif action == "select":
        role = resolve(args["role_id"])
        store.set(prefix + "selected", role.role_id)
    elif action == "preferences":
        patch = args["preferences"]
        if not patch:
            raise ValueError("至少提供一项回复偏好")
        unknown = set(patch) - set(ReplyPreferences.model_fields)
        if unknown:
            raise ValueError("未知回复偏好字段")
        validated = ReplyPreferences.model_validate(patch).model_dump()
        store.hset(
            prefix + "preferences", mapping={key: validated[key] for key in patch}
        )
    elif action != "list":
        raise ValueError("未知角色管理动作")

    selected = store.get(prefix + "selected") or default_role
    if selected not in roles:
        raise ValueError("默认角色未注册，请检查 LocalAgent.default_role")
    preferences = ReplyPreferences.model_validate(store.hgetall(prefix + "preferences"))
    return {
        "selected": roles[selected].model_dump(),
        "roles": [r.model_dump() for r in roles.values()],
        "preferences": preferences.model_dump(),
    }

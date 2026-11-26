"""Normalize the explicit public fields of a verified QQ group member."""


def normalize_group_member_profile(record, group_id, user_id):
    if not isinstance(record, dict) or str(record.get("group_id")) != str(group_id) or str(record.get("user_id")) != str(user_id):
        raise ValueError("QQ 返回的群成员身份与请求不一致")

    def text(field):
        value = record.get(field)
        return value[:500] if isinstance(value, str) and value else None

    def integer(field):
        value = record.get(field)
        return value if type(value) is int and value > 0 else None

    return {
        "group_id": str(group_id), "user_id": str(user_id),
        "nickname": text("nickname"), "group_card": text("card"),
        "role": record.get("role") if record.get("role") in {"owner", "admin", "member"} else None,
        "title": text("title"), "level": text("level"), "area": text("area"),
        "sex": record.get("sex") if record.get("sex") in {"male", "female"} else None,
        "age": integer("age"), "joined_at": integer("join_time"),
        "last_sent_at": integer("last_sent_time"),
        "title_expires_at": integer("title_expire_time"),
        "title_permanent": record.get("title_expire_time") == -1 if text("title") else None,
    }

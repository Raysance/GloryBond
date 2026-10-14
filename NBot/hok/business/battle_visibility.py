"""Pure battle-history visibility state transitions."""


def resolve_visibility_qids(user_name, same_user_map, qid_map):
    related_names = {user_name}
    for main_name, alias_names in (same_user_map or {}).items():
        aliases = set(alias_names if isinstance(alias_names, list) else [])
        aliases.add(main_name)
        if user_name in aliases:
            related_names.update(aliases)

    target_qids = []
    missing_names = []
    for name in sorted(related_names):
        user_qid = (qid_map or {}).get(name)
        if not user_qid:
            missing_names.append(name)
            continue
        user_qid = str(user_qid)
        if user_qid not in target_qids:
            target_qids.append(user_qid)
    return target_qids, missing_names


def update_disabled_qids(disabled_qids, target_qids, *, visible):
    normalized_disabled = [str(item) for item in disabled_qids]
    normalized_targets = [str(item) for item in target_qids]
    target_qid_set = set(normalized_targets)

    if visible:
        changed_qids = [
            user_qid
            for user_qid in normalized_targets
            if user_qid in normalized_disabled
        ]
        updated_qids = [
            user_qid
            for user_qid in normalized_disabled
            if user_qid not in target_qid_set
        ]
        return updated_qids, changed_qids

    updated_qids = list(normalized_disabled)
    changed_qids = []
    for user_qid in normalized_targets:
        if user_qid not in updated_qids:
            updated_qids.append(user_qid)
            changed_qids.append(user_qid)
    return updated_qids, changed_qids

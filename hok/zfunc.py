
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc

_BATTLE_INVISIBLE_DISABLED_QIDS_REDIS_KEY = "hok:battle:invisible_disabled_qids"
_GROUP_CHAT_HISTORY_REDIS_PREFIX = "hok:chat:group:"


def _forward_delivery_key(delivery_id):
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", str(delivery_id or "")):
        raise ValueError("Invalid forward delivery ID")
    return REDIS_KEY_FORWARD_DELIVERY_PREFIX + delivery_id


def forward_delivery_status(delivery_id):
    return dmc.redis_deamon.get(_forward_delivery_key(delivery_id))


def enqueue_forward_message(payload, *, delivery_id, ttl):
    """Atomically reserve an edition and persist its entire outbound message in DB0."""
    key = _forward_delivery_key(delivery_id)
    if int(ttl) <= 0:
        raise ValueError("Forward delivery TTL must be positive")
    return dmc.redis_deamon.eval(
        "if redis.call('exists', KEYS[1]) == 1 then return 0 end "
        "redis.call('lpush', KEYS[2], ARGV[1]); "
        "redis.call('set', KEYS[1], 'queued', 'EX', ARGV[2]); return 1",
        2, key, REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, json.dumps(payload, ensure_ascii=False), int(ttl),
    )


def finish_forward_delivery(delivery_id, status):
    """Record the real adapter outcome; a failed/unknown send is not replayed blindly."""
    if status not in {"sent", "failed"}:
        raise ValueError("Invalid forward delivery status")
    return dmc.redis_deamon.eval(
        "if redis.call('get', KEYS[1]) == 'queued' then "
        "return redis.call('set', KEYS[1], ARGV[1], 'KEEPTTL') end return 0",
        1, _forward_delivery_key(delivery_id), status,
    )


def ai_daily_check_and_push():
    from .business.ai_daily import ai_daily_check_and_push as impl
    return impl()


def _redis_get_json(key, default=None):
    raw = dmc.redis_deamon.get(key)
    if not raw:
        return default
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def recent_emoji_messages(user_id, group_id, limit=8):
    """Read only this speaker's recent speech in the trusted source group."""
    user, group = str(user_id), str(group_id or "")
    if not group:
        return []
    if not user.isascii() or not user.isdecimal() or not group.isascii() or not group.isdecimal() or int(group) <= 0:
        raise ValueError("Emoji context requires trusted QQ and group IDs")
    try:
        from . import zdb
        rows = zdb.load_group_chat_messages(group, limit=100, user_id=user)
    except Exception as error:
        log_message(f"EMOJI_HISTORY_READ_FALLBACK: error={type(error).__name__}", level=logging.ERROR)
        rows = []
    try:
        pending = _load_group_chat_history_redis(group)
    except Exception:
        pending = []
    merged = {str(row["message_id"]): row for row in [*pending, *rows]
              if str(row.get("user_id")) == user and row.get("message_id") is not None}
    records = sorted(merged.values(), key=lambda row: int(row.get("timestamp") or 0))
    return [row for row in records if str(row.get("text") or "").strip()
            and not str(row["text"]).lstrip().startswith(("#", "＃"))
            and not ("战力" in row["text"] and "查询" in row["text"])][-max(1, min(40, int(limit))):]


def emoji_message_state(user_id, group_id, action, message_hash, value=None):
    """Read/write regenerable emoji decisions, isolated by group and speaker."""
    user, group = str(user_id), str(group_id or "private")
    if not user.isascii() or not user.isdecimal() or (group != "private" and not group.isdecimal()):
        raise ValueError("Invalid emoji identity")
    if not re.fullmatch(r"[a-f0-9]{40}", message_hash):
        raise ValueError("Invalid emoji message hash")
    root = REDIS_KEY_EMOJI_PREFIX + group + ":" + user
    store = dmc.redis_deamon
    if action == "get":
        raw = store.hget(root + ":actions", message_hash)
        return json.loads(raw) if raw else None
    if action == "used":
        return bool(store.sismember(root + ":used", message_hash))
    with store.pipeline(transaction=True) as pipe:
        if action == "set":
            key = root + ":actions"
            pipe.hset(key, message_hash, json.dumps(value, ensure_ascii=False))
        elif action == "mark":
            key = root + ":used"
            pipe.sadd(key, message_hash)
        else:
            raise ValueError("Unknown emoji state operation")
        pipe.expire(key, 172800)
        pipe.execute()


def _redis_set_json(key, value):
    dmc.redis_deamon.set(key, json.dumps(value, ensure_ascii=False))


def _wait_official_low_priority_turn():
    """Yield background official-API work to interactive web queues."""
    from .ztime import current_timestamp, sleep_seconds

    while True:
        now = current_timestamp()
        active_until = getattr(dmc, "OfficialForegroundActiveUntil", 0)
        if now < active_until:
            sleep_seconds(min(active_until - now, 3))
            continue
        try:
            if dmc.redis_deamon.llen(REDIS_KEY_BATTLE_SHARE_QUEUE):
                sleep_seconds(3)
                continue
            if dmc.redis_deamon.llen(REDIS_KEY_BATTLE_ANALYZE_QUEUE):
                sleep_seconds(3)
                continue
        except Exception as error:
            log_message(f"OFFICIAL_LOW_PRIORITY_QUEUE_CHECK_ERROR: {error}")
        wait_seconds = (
            getattr(dmc, "OfficialLowPriorityLastVisitAt", 0)
            + 5
            - current_timestamp()
        )
        if wait_seconds > 0:
            sleep_seconds(wait_seconds)
            continue
        dmc.OfficialLowPriorityLastVisitAt = current_timestamp()
        return


def wzry_get_official(*args, priority="normal", **kwargs):
    """Apply business priority rules, then call the stateless API adapter."""
    from . import zapi
    from .ztime import current_timestamp

    if priority == "low":
        _wait_official_low_priority_turn()
    else:
        dmc.OfficialForegroundActiveUntil = current_timestamp() + 5
    return zapi.wzry_get_official(*args, **kwargs)


def get_battle_invisible_disabled_qids():
    try:
        value = _redis_get_json(_BATTLE_INVISIBLE_DISABLED_QIDS_REDIS_KEY, default=[])
    except Exception as error:
        log_message(f"BATTLE_VISIBILITY_REDIS_READ_ERROR: {repr(error)}")
        value = []
    if not isinstance(value, list):
        value = []
    return sorted({str(item) for item in value if str(item or "").strip()})


def save_battle_invisible_disabled_qids(disabled_qids):
    disabled_qids = sorted({str(item) for item in disabled_qids if str(item or "").strip()})
    _redis_set_json(_BATTLE_INVISIBLE_DISABLED_QIDS_REDIS_KEY, disabled_qids)
    return disabled_qids


def _battle_visibility_qids(realname):
    from .business.battle_visibility import resolve_visibility_qids

    target_qids, missing_names = resolve_visibility_qids(
        realname,
        globals().get("sameuser", {}),
        qid,
    )
    for name in missing_names:
        log_message(f"WZRY_VISIBILITY_QID_NOT_FOUND: {name}")
    return target_qids


def sync_battle_visibility_state(realname, visible):
    from .business.battle_visibility import update_disabled_qids
    from .utils.message_sender import BATTLE_INVISIBLE_MUTE_SECONDS
    from .utils.message_sender import add_group_ban_task

    target_qids = _battle_visibility_qids(realname)
    if not target_qids:
        log_message(f"WZRY_VISIBILITY_QID_NOT_FOUND: {realname}")
        return []

    disabled_qids, changed_qids = update_disabled_qids(
        get_battle_invisible_disabled_qids(),
        target_qids,
        visible=visible,
    )
    action = "ENABLE" if visible else "DISABLE"
    for user_qid in changed_qids:
        log_message(f"WZRY_VISIBILITY_{action}_QID: {realname} {user_qid}")

    if changed_qids:
        save_battle_invisible_disabled_qids(disabled_qids)
        duration = 0 if visible else BATTLE_INVISIBLE_MUTE_SECONDS
        source = f"battle_visibility:{realname}:{'visible' if visible else 'invisible'}"
        for user_qid in target_qids:
            add_group_ban_task(user_qid, duration=duration, source=source)
    return changed_qids


def _today_hero_cached(realname, current_date, *, ignore_limit=False):
    if ignore_limit:
        return None
    raw = dmc.TodayHeroPool.get(f"{REDIS_KEY_HERO_TODAY_PREFIX}{realname}")
    if not raw:
        return None
    payload = json.loads(raw)
    if payload.get("date") != current_date:
        return None
    return payload


def _today_hero_store(realname, payload):
    current_date = payload["date"]
    dmc.TodayHeroPool.set(
        f"{REDIS_KEY_HERO_TODAY_PREFIX}{realname}",
        json.dumps(payload),
    )
    history_key = f"{REDIS_KEY_HERO_HISTORY_PREFIX}{realname}"
    history_entry = {
        "date": current_date,
        "heroname": payload.get("heroname"),
        "skinname": payload.get("skinname"),
        "selectinfo": payload.get("selectinfo"),
    }
    history_items = dmc.TodayHeroPool.lrange(history_key, 0, -1)
    for index, raw in enumerate(history_items):
        if json.loads(raw).get("date") == current_date:
            dmc.TodayHeroPool.lset(history_key, index, json.dumps(history_entry))
            return payload
    dmc.TodayHeroPool.rpush(history_key, json.dumps(history_entry))
    return payload


def _group_chat_history_key(group_id):
    return f"{_GROUP_CHAT_HISTORY_REDIS_PREFIX}{str(group_id)}"


def _record_group_chat_message_redis(record):
    """Emergency/legacy Redis writer retained until migration is verified."""
    key = _group_chat_history_key(record["group_id"])
    redis_client = dmc.redis_deamon
    redis_client.rpush(key, json.dumps(record, ensure_ascii=False))
    max_messages = int(getattr(dmc, "ChatHistoryMaxMessages", 0) or 0)
    if max_messages > 0:
        redis_client.ltrim(key, -max_messages, -1)


def _load_group_chat_history_redis(group_id):
    """Read the legacy DB0 list without trusting embedded group metadata."""
    records = []
    for raw in dmc.redis_deamon.lrange(_group_chat_history_key(group_id), 0, -1):
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            record = json.loads(raw)
        except Exception:
            continue
        if isinstance(record, dict):
            records.append({**record, "group_id": str(group_id)})
    return records


def _list_group_chat_history_groups_redis():
    groups = {}
    for key in dmc.redis_deamon.scan_iter(match=f"{_GROUP_CHAT_HISTORY_REDIS_PREFIX}*"):
        key = key.decode("utf-8") if isinstance(key, bytes) else key
        group_id = key[len(_GROUP_CHAT_HISTORY_REDIS_PREFIX):]
        if not group_id.isascii() or not group_id.isdecimal() or int(group_id) <= 0:
            continue
        count = dmc.redis_deamon.llen(key)
        if count:
            groups[group_id] = {"group_id": group_id, "message_count": count}
    return groups


def record_group_chat_message(group_id, user_id, text, *, message_id=None, reply_to_message_id=None):
    """Persist one inbound group message to PostgreSQL, with Redis fallback."""
    from .ztime import current_datetime_text, current_epoch_seconds

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return None
    if message_id in (None, ""):
        message_id = f"{current_epoch_seconds()}:{user_id}"
    record = {
        "group_id": str(group_id),
        "user_id": str(user_id),
        "message_id": str(message_id),
        "reply_to_message_id": str(reply_to_message_id) if reply_to_message_id not in (None, "") else None,
        "time": current_datetime_text(),
        "timestamp": current_epoch_seconds(),
        "text": normalized_text,
    }
    try:
        from . import zdb
        zdb.upsert_group_chat_message(record, trusted_group_id=group_id)
    except Exception as error:
        log_message(
            f"GROUP_CHAT_POSTGRES_WRITE_FALLBACK: group_id={group_id} "
            f"message_id={message_id} error={type(error).__name__}",
            level=logging.ERROR,
        )
        _record_group_chat_message_redis(record)
    return record


def load_group_chat_history(group_id, limit=None, time_start=None, time_end=None):
    """Read SQL history plus any not-yet-migrated Redis records."""
    try:
        legacy = _load_group_chat_history_redis(group_id)
    except Exception as error:
        log_message(
            f"GROUP_CHAT_REDIS_LEGACY_READ_SKIPPED: group_id={group_id} error={type(error).__name__}",
            level=logging.ERROR,
        )
        legacy = []
    try:
        from . import zdb
        sql_records = zdb.load_group_chat_messages(
            str(group_id), time_start=time_start, time_end=time_end)
    except Exception as error:
        log_message(
            f"GROUP_CHAT_POSTGRES_READ_FALLBACK: group_id={group_id} error={type(error).__name__}",
            level=logging.ERROR,
        )
        sql_records = []

    # SQL is authoritative for duplicate (group_id, message_id) records.  Redis
    # remains readable during rollout so messages written by an older process
    # between backup and deployment are not lost.
    merged = {}
    for position, record in enumerate([*legacy, *sql_records]):
        if not isinstance(record, dict):
            continue
        message_id = str(record.get("message_id") or "").strip()
        if not message_id:
            continue
        merged[message_id] = ({**record, "group_id": str(group_id)}, position)
    records = [item for item, _ in sorted(
        merged.values(),
        key=lambda pair: (int(pair[0].get("timestamp") or 0), pair[1]),
    )]
    if time_start is not None:
        records = [record for record in records if int(record.get("timestamp") or 0) >= int(time_start)]
    if time_end is not None:
        records = [record for record in records if int(record.get("timestamp") or 0) <= int(time_end)]
    if limit is not None:
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be a positive integer") from exc
        records = records[-limit:]
    return records


def list_chat_history_groups():
    """List SQL groups, including any legacy Redis-only messages during migration."""
    try:
        redis_groups = _list_group_chat_history_groups_redis()
    except Exception as error:
        log_message(f"GROUP_CHAT_REDIS_GROUPS_SKIPPED: error={type(error).__name__}", level=logging.ERROR)
        redis_groups = {}
    try:
        from . import zdb
        sql_groups = {item["group_id"]: item for item in zdb.list_group_chat_history_groups()}
    except Exception as error:
        log_message(f"GROUP_CHAT_POSTGRES_GROUPS_FALLBACK: error={type(error).__name__}", level=logging.ERROR)
        sql_groups = {}
    groups = {**redis_groups, **sql_groups}
    for group_id in redis_groups.keys() & sql_groups.keys():
        groups[group_id] = {"group_id": group_id,
                            "message_count": len(load_group_chat_history(group_id))}
    return [groups[group_id] for group_id in sorted(groups, key=int)]


from .business import hero_tier as _hero_tier_business


def _to_pinyin(value):
    return _hero_tier_business.to_pinyin(value)


def safe_hero_name(hero_id, default=None):
    return _hero_tier_business.safe_hero_name(hero_id, default=default)


def hero_tier_query_process():
    return _hero_tier_business.hero_tier_query_process()


from .business import battle_matchup as _battle_matchup_business


def _battle_matchup_composition(detail_list):
    return _battle_matchup_business.battle_matchup_composition(detail_list)


def hero_matchup_process(my_detail, op_detail, matchup_api=None):
    return _battle_matchup_business.hero_matchup_process(
        my_detail,
        op_detail,
        matchup_api=matchup_api,
    )


def _battle_lineup_items(detail_list):
    return _battle_matchup_business.battle_lineup_items(detail_list)


def _format_battle_lineup_ai_text(value):
    return _battle_matchup_business.format_battle_lineup_ai_text(value)


def battle_lineup_ai_process(my_lineup, op_lineup, ai_func=None):
    return _battle_matchup_business.battle_lineup_ai_process(
        my_lineup,
        op_lineup,
        ai_func=ai_func,
    )


def _compact_report_value(value, max_len=220):
    return _rankings_business.compact_report_value(value, max_len=max_len)


def _build_traversal_error(source, realname, params, error):
    return _rankings_business.build_traversal_error(
        source,
        realname,
        params,
        error,
    )


def format_traversal_error_report(title, errors):
    return _rankings_business.format_traversal_error_report(title, errors)


def peak_rank_process(player_names=None):
    return _rankings_business.peak_rank_process(player_names=player_names)


from .business import player_data as _player_data_business


def wzry_data(
    realname,
    savepath=None,
    target_userid=None,
    target_roleid=None,
    target_date=None,
    sync_battle_visibility=False,
):
    return _player_data_business.wzry_data(
        realname,
        savepath=savepath,
        target_userid=target_userid,
        target_roleid=target_roleid,
        target_date=target_date,
        sync_battle_visibility=sync_battle_visibility,
    )


def _enrich_battle_list_skills_from_cache(payload, roleid):
    return _player_data_business.enrich_battle_list_skills_from_cache(
        payload,
        roleid,
    )


def dump_specific_user(userid, roleid, target_date):
    return _player_data_business.dump_specific_user(
        userid,
        roleid,
        target_date,
    )
from .business import ai_prompts as _ai_prompts_business


def ai_parser(user_query, msg_type, network=False):
    return _ai_prompts_business.ai_parser(
        user_query,
        msg_type,
        network=network,
    )

def chat_prepare_reply(result):
    """Combine plots and publish the trace without losing a successful answer."""
    from .zfile import combine_chat_plot_images
    from .ztime import monotonic_seconds

    result = dict(result)
    result["trace"] = dict(result["trace"])
    begin = monotonic_seconds()
    originals = result.get("artifacts", [])
    delivery = {"source_images": len(originals), "merged": False}
    if len(originals) > 1:
        try:
            result["artifacts"] = combine_chat_plot_images(originals)
            delivery["merged"] = True
        except Exception as error:
            delivery["error"] = type(error).__name__
            result["text"] += f"\n图表合并失败（{type(error).__name__}），以下保留原图。"
    delivery["duration_ms"] = round((monotonic_seconds() - begin) * 1000, 2)
    result["trace"]["delivery"] = delivery
    result["trace"]["duration_ms"] = result["trace"].get("duration_ms", 0) + delivery["duration_ms"]
    try:
        result["trace_url"] = chat_publish_trace(result["trace"], originals)
    except Exception as error:
        result["trace_error"] = type(error).__name__
    return result


async def agent_set_bot_avatar(image_bytes):
    from .utils.qq_profiles import set_bot_avatar
    return await set_bot_avatar(image_bytes)


async def agent_read_generated_image(identifier):
    from .zfile import load_agent_artifact_image
    return await asyncio.to_thread(load_agent_artifact_image, identifier)


async def agent_read_group_member_profile(*, group_id, user_id, include_avatar=True):
    """QQBot owns live member lookup and avatar retrieval; the agent receives a snapshot."""
    from .utils.qq_profiles import load_group_member_profile
    from .business.qq_profiles import normalize_group_member_profile
    from .zapi import qq_avatar_bytes

    record = await load_group_member_profile(group_id, user_id)
    profile = normalize_group_member_profile(record, group_id, user_id)
    result = {"profile": profile, "avatar_bytes": None, "avatar_error": None}
    if include_avatar:
        try:
            result["avatar_bytes"] = await asyncio.to_thread(qq_avatar_bytes, user_id, config=qq_profile_config)
        except Exception as exc:
            result["avatar_error"] = f"头像读取失败（{type(exc).__name__}），文字资料仍可用"
    return result


async def agent_runtime_start():
    """Bind QQ IO to the shared, externally maintained ReAct runtime."""
    from qq_agent import QQAgentService
    from .zfile import store_agent_artifact
    from .tools.chat_text import normalize_qq_text, format_chat_reply
    from .utils.message_sender import add_chat_result_msg

    if dmc.qq_agent_service is not None:
        await dmc.qq_agent_service.start()
        return dmc.qq_agent_service
    config = dict(confs.get("QQAgent", {}))
    if not config.get("enabled", True):
        raise RuntimeError("QQ Agent is disabled in config.yaml")
    if config.get("log_directory", "log/qq_agent") == "log/qq_agent":
        config["log_directory"] = os.path.join(log_root, "qq_agent")
    if config.get("image_directory", "data/agent_inputs") == "data/agent_inputs":
        config["image_directory"] = os.path.join(data_root, "agent_inputs")

    async def send(packet, delivery):
        return add_chat_result_msg({**packet, "text": format_text(packet["text"])}, destination=delivery)

    async def prepare(packet):
        return await asyncio.to_thread(chat_prepare_reply, packet)

    async def store(identifier, raw):
        return await asyncio.to_thread(store_agent_artifact, identifier, raw)

    def format_text(text):
        names = {player: namenick.get(player) or "该玩家" for player in dict.fromkeys([*namenick, *qid, *userlist, *roleidlist])}
        identities = {str(identity): names[player] for mapping in (qid, userlist, roleidlist)
                      for player, identity in mapping.items() if identity}
        return format_chat_reply(normalize_qq_text(text), player_names=names,
                                 identity_names=identities, aliases=[a for values in nameref.values() for a in values])

    service = QQAgentService(root=project_root, config=config, admin_id=confs["QQBot"]["super_qid"],
                             bot_id=confs["QQBot"]["bot_qid"],
                             sender=send, prepare_reply=prepare, store_artifact=store, formatter=format_text,
                             member_profile_reader=agent_read_group_member_profile,
                             bot_avatar_setter=agent_set_bot_avatar,
                             generated_image_reader=agent_read_generated_image)
    dmc.qq_agent_service = service
    try:
        await service.start()
    except BaseException:
        dmc.qq_agent_service = None
        raise
    return service


async def agent_chat(**request):
    service = await agent_runtime_start()
    return await service.chat(**request)


async def agent_clear_memory(user_id, group_id=None):
    service = await agent_runtime_start()
    return await service.clear_memory(user_id, group_id)


async def agent_task_tick():
    if dmc.qq_agent_service is not None:
        await dmc.qq_agent_service.tick()


async def agent_runtime_stop():
    if dmc.qq_agent_service is not None:
        await dmc.qq_agent_service.close()
        dmc.qq_agent_service = None


def agent_register_tool(**spec):
    if dmc.qq_agent_service is None:
        raise RuntimeError("Register agent tools after runtime startup")
    dmc.qq_agent_service.runtime.registry.register(**spec)


def chat_publish_trace(trace, artifacts=()):
    """Store an admin-only execution record and its bounded discovery index."""
    from .business.chat_trace import public_value, trace_index_entry
    from .zfile import chat_plot_public_path
    from .ztime import current_epoch_seconds

    token = WebArtifacts.make_hash()
    payload = public_value(trace, secrets=(chat_api_config.get("api_key"), chat_readonly_dsn))
    payload["artifacts"] = [
        {"artifact_id": str(item.get("artifact_id", "")), "url": url}
        for item in artifacts if (url := chat_plot_public_path(item.get("path", "")))
    ]
    payload["expires_in_seconds"] = max(60, int(getattr(dmc, "ChatTraceExpireSeconds", 604800)))
    payload["visibility"] = "admin"
    serialized = json.dumps(payload, ensure_ascii=False)
    entry = trace_index_entry(payload, token, current_epoch_seconds())
    with dmc.redis_deamon.pipeline(transaction=True) as pipe:
        pipe.set(f"{REDIS_KEY_WEB_ARTIFACT_PREFIX}{token}", serialized, ex=payload["expires_in_seconds"])
        pipe.lpush(REDIS_KEY_CHAT_TRACE_INDEX, json.dumps(entry, ensure_ascii=False))
        pipe.ltrim(REDIS_KEY_CHAT_TRACE_INDEX, 0, max(1, int(getattr(dmc, "ChatTraceMaxRecords", 1000))) - 1)
        pipe.expire(REDIS_KEY_CHAT_TRACE_INDEX, payload["expires_in_seconds"])
        saved = pipe.execute()
    if not saved or not saved[0]:
        raise RuntimeError("chat_trace_publish_failed")
    return WebArtifacts.route_url("chat_trace", token)


class WebArtifacts:
    @staticmethod
    def make_hash(seed=None):
        """Create a short stable hash from seed or a random token."""
        from .business.web_artifacts import make_hash

        return make_hash(seed)

    @staticmethod
    def history_json_path(filename_hashed):
        """Build the public history JSON path."""
        from .zfile import web_history_json_path

        return web_history_json_path(filename_hashed)

    @staticmethod
    def history_artifact(seed=None):
        """Create a public history JSON filename and path pair."""
        filename_hashed=WebArtifacts.make_hash(seed)
        return filename_hashed,WebArtifacts.history_json_path(filename_hashed)

    @staticmethod
    def route_url(sitetype,hash_key):
        """Build a public route URL for a stored web payload."""
        from .business.web_artifacts import route_url

        return route_url(sitetype, hash_key, confs["WebService"]["server_domain"])

    @staticmethod
    def create_route_link(contents,sitetype):
        """Store route contents in Redis and return the public URL."""
        hash_key=WebArtifacts.make_hash()
        redis_key = f"{REDIS_KEY_WEB_ARTIFACT_PREFIX}{hash_key}"
        dmc.redis_deamon.set(redis_key,contents,ex=REDIS_TEXT_EXPIRE_SECONDS)
        return WebArtifacts.route_url(sitetype,hash_key)

    @staticmethod
    def history_route_link(filename_hashed,sitetype,caller="",time_text="",extra=None):
        """Create a route link for a history JSON artifact."""
        from .business.web_artifacts import history_route_payload

        payload = history_route_payload(filename_hashed, caller, time_text, extra)
        return WebArtifacts.create_route_link(json.dumps(payload,ensure_ascii=False),sitetype)

    @staticmethod
    def publish_history_json_route(payload,sitetype):
        """Publish a JSON payload to the history JSON path, then return a route URL."""
        from .zfile import write_web_history_payload

        filename_hashed = WebArtifacts.make_hash()
        write_web_history_payload(filename_hashed, payload)
        return WebArtifacts.route_url(sitetype,filename_hashed)

    @staticmethod
    def bili_video_route_link(payload):
        """Publish a Bilibili video payload to Redis and return its public detail page."""
        return WebArtifacts.create_route_link(json.dumps(payload,ensure_ascii=False),"bili_video")

from .business import online_status as _online_status_business


def online_process():
    return _online_status_business.online_process()
from .business import rankings as _rankings_business


def rnk_process(rcv_msg, caller=None, show_zero=True, show_analyze=False, debug=False):
    return _rankings_business.rnk_process(
        rcv_msg,
        caller=caller,
        show_zero=show_zero,
        show_analyze=show_analyze,
        debug=debug,
    )
from .business import player_report as _player_report_business


def single_process(rcv_msg):
    return _player_report_business.single_process(rcv_msg)
from .business import battle_detail as _battle_detail_business


def view_process(rcv_msg, time_gap=analyze_time_gap):
    return _battle_detail_business.view_process(rcv_msg, time_gap=time_gap)


def btldetail_process(
    gameSvrId,
    relaySvrId,
    gameseq,
    pvptype,
    roleid,
    gen_image=False,
    show_profile=False,
    from_web=False,
    individual_show=False,
    strict_filter=True,
):
    return _battle_detail_business.btldetail_process(
        gameSvrId,
        relaySvrId,
        gameseq,
        pvptype,
        roleid,
        gen_image=gen_image,
        show_profile=show_profile,
        from_web=from_web,
        individual_show=individual_show,
        strict_filter=strict_filter,
    )
from .business import hero_profiles as _hero_profiles_business


def heropower_process(realname):
    return _hero_profiles_business.heropower_process(realname)


from .business import hero_statistics as _hero_statistics_business
from .business import honor_power as _honor_power_business


def _honor_hero_from_query(query_text):
    return _honor_power_business._honor_hero_from_query(query_text)


def _honor_region_name_without_suffix(region_name):
    return _honor_power_business._honor_region_name_without_suffix(region_name)


def _honor_district_entries(district_payload):
    return _honor_power_business._honor_district_entries(district_payload)


def resolve_honor_district(region_query, district_payload=None):
    return _honor_power_business.resolve_honor_district(
        region_query, district_payload=district_payload
    )


def _honor_rank_percentile_points(rank_list):
    return _honor_power_business._honor_rank_percentile_points(rank_list)


def honor_power_query_process(realname, query_text):
    return _honor_power_business.honor_power_query_process(realname, query_text)


def single_player_single_hero_process(
    username, heroid, heroname, this_season=True
):
    return _hero_statistics_business.single_player_single_hero_process(
        username, heroid, heroname, this_season=this_season
    )


def single_player_mult_hero_process(
    username, days=30, top_n=3, min_games=2, this_season=False
):
    return _hero_statistics_business.single_player_mult_hero_process(
        username,
        days=days,
        top_n=top_n,
        min_games=min_games,
        this_season=this_season,
    )


def mult_player_mult_hero_process(
    days=30, top_n=5, min_games=5, this_season=False
):
    return _hero_statistics_business.mult_player_mult_hero_process(
        days=days,
        top_n=top_n,
        min_games=min_games,
        this_season=this_season,
    )


def mult_player_single_hero_process(
    hero_id, hero_name, days=30, min_games=3, top_n=5, this_season=False
):
    return _hero_statistics_business.mult_player_single_hero_process(
        hero_id,
        hero_name,
        days=days,
        min_games=min_games,
        top_n=top_n,
        this_season=this_season,
    )

from .business import today_hero as _today_hero_business


def todayhero_process(realname, ignore_limit=False, ai_comment=True):
    return _today_hero_business.todayhero_process(
        realname,
        ignore_limit=ignore_limit,
        ai_comment=ai_comment,
    )
def allhero_process(realname):
    return _hero_profiles_business.allhero_process(realname)
from .business import player_visuals as _player_visuals_business


def gradeanalyze_process(realname):
    return _player_visuals_business.gradeanalyze_process(realname)


def watchbattle_process(realname):
    return _player_visuals_business.watchbattle_process(realname)
from .business import battle_watch as _battle_watch_business


def watchbattleinfo_to_coplayer_res(watchbattle_json, roleid=None, game_result=None):
    return _battle_watch_business.watchbattleinfo_to_coplayer_res(
        watchbattle_json,
        roleid=roleid,
        game_result=game_result,
    )
def spoiler_process(battle_id,roleid,userid):
    return _battle_watch_business.spoiler_process(battle_id, roleid, userid)
from .business import battle_power as _battle_power_business

BattlePowerHistory = _battle_power_business.BattlePowerHistory


def record_battle_evaluator(record):
    redis_client = dmc.BtlAnalyzeEvaluatorPool
    redis_client.rpush(
        REDIS_KEY_BATTLE_EVALUATOR_RECORDS,
        json.dumps(record, ensure_ascii=False),
    )
    max_records = max(
        1,
        int(getattr(dmc, "BtlAnalyzeEvaluatorMaxRecords", 10000)),
    )
    redis_client.ltrim(REDIS_KEY_BATTLE_EVALUATOR_RECORDS, -max_records, -1)


def coplayer_process(
    gameSvrId,
    relaySvrId,
    gameseq,
    pvptype,
    roleid,
    spoiler_info,
    from_web=False,
    return_power_data=False,
    official_priority="normal",
    save_power_history=False,
    with_ai_analysis=False,
):
    return _battle_power_business.coplayer_process(
        gameSvrId,
        relaySvrId,
        gameseq,
        pvptype,
        roleid,
        spoiler_info,
        from_web=from_web,
        return_power_data=return_power_data,
        official_priority=official_priority,
        save_power_history=save_power_history,
        with_ai_analysis=with_ai_analysis,
    )

def mark_battle_power_failed(gameseq, reason, candidate=None):
    return _battle_power_business.mark_battle_power_failed(
        gameseq,
        reason,
        candidate,
    )


def battle_power_process(
    gameSvrId,
    relaySvrId,
    gameseq,
    pvptype,
    roleid,
    spoiler_info=None,
    from_web=False,
    official_priority="normal",
    save_power_history=True,
    gen_image=True,
    with_ai_analysis=False,
):
    return _battle_power_business.battle_power_process(
        gameSvrId,
        relaySvrId,
        gameseq,
        pvptype,
        roleid,
        spoiler_info=spoiler_info,
        from_web=from_web,
        official_priority=official_priority,
        save_power_history=save_power_history,
        gen_image=gen_image,
        with_ai_analysis=with_ai_analysis,
    )


def evaluate_battle_power_history(game_params, roleid, official_priority="low"):
    return _battle_power_business.evaluate_battle_power_history(
        game_params,
        roleid,
        official_priority=official_priority,
    )


def find_pending_battle_power_candidate(
    days=7,
    excluded_gameseqs=None,
    start_date_str=None,
):
    return _battle_power_business.find_pending_battle_power_candidate(
        days=days,
        excluded_gameseqs=excluded_gameseqs,
        start_date_str=start_date_str,
    )


def recent_power_process(realname, days=7):
    return _battle_power_business.recent_power_process(realname, days=days)


def power_rank_process(days=7):
    return _battle_power_business.power_rank_process(days=days)

from .business import history_data as _history_data_business


def fetch_history(
    userid=None,
    start_date=None,
    end_date=None,
    filter_official=True,
):
    return _history_data_business.fetch_history(
        userid=userid,
        start_date=start_date,
        end_date=end_date,
        filter_official=filter_official,
    )

from .business import game_activity as _game_activity_business


def recentgames_process(realname):
    return _game_activity_business.recentgames_process(realname)


def gametime_rank_process(days=14):
    return _game_activity_business.gametime_rank_process(days=days)

from .business import battle_history as _battle_history_business

Analyses = _battle_history_business.Analyses


def fetch_battle(gameseq, roleid=0):
    return _battle_history_business.fetch_battle(gameseq, roleid=roleid)

from .business import user_helpers as _user_helpers_business


def generate_greeting():
    return _user_helpers_business.generate_greeting()


def qid2nick(userqid):
    return _user_helpers_business.qid2nick(userqid)


def qid2realname(userqid):
    return _user_helpers_business.qid2realname(userqid)


def get_emoji(txt):
    return _user_helpers_business.get_emoji(txt)


def get_emoji_url(index):
    return _user_helpers_business.get_emoji_url(index)


def _x_subscriptions():
    return [json.loads(raw) for raw in dmc.redis_deamon.hvals(REDIS_KEY_X_SUBSCRIPTIONS)]


def _x_save_subscription(item):
    field = f"{item['user_qid']}:{item['id']}"
    return dmc.redis_deamon.hset(REDIS_KEY_X_SUBSCRIPTIONS, field, json.dumps(item, ensure_ascii=False))


def _x_delete_subscription(user_qid, account_id):
    return dmc.redis_deamon.hdel(REDIS_KEY_X_SUBSCRIPTIONS, f"{user_qid}:{account_id}")


def _x_cursor(account_id):
    raw = dmc.redis_deamon.hget(REDIS_KEY_X_CURSORS, str(account_id))
    return json.loads(raw) if raw else None


def _x_save_cursor(account_id, cursor):
    return dmc.redis_deamon.hset(REDIS_KEY_X_CURSORS, str(account_id), json.dumps(cursor))


def _x_seen(account_id, post_id):
    return bool(dmc.redis_deamon.sismember(REDIS_KEY_X_SEEN_PREFIX + str(account_id), str(post_id)))


def _x_mark_seen(account_id, post_id):
    return dmc.redis_deamon.sadd(REDIS_KEY_X_SEEN_PREFIX + str(account_id), str(post_id))


def _x_lock():
    from contextlib import contextmanager
    import uuid

    @contextmanager
    def locked():
        token = uuid.uuid4().hex
        if not dmc.redis_deamon.set(REDIS_KEY_X_PUSH_LOCK, token, nx=True, ex=int(x_subscription_config['lock_seconds'])):
            raise RuntimeError("X 订阅正在检查或更新，请稍后重试")
        try:
            yield token
        finally:
            dmc.redis_deamon.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                1, REDIS_KEY_X_PUSH_LOCK, token,
            )
    return locked()


def _x_refresh_lock(token):
    renewed = dmc.redis_deamon.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
        1, REDIS_KEY_X_PUSH_LOCK, token, int(x_subscription_config['lock_seconds']),
    )
    if not renewed:
        raise RuntimeError("X 推送锁已失效，本次停止发送并保留游标")


def _x_render_message(bundle):
    from .business.x_subscription import post_text_preview
    from .tools.gen_x_post import render_x_post_images
    from .zfile import save_x_post_images, pil_image_from_bytes
    from .zapi import x_get_media_bytes
    from .ztime import epoch_to_text, parse_chat_time_bound, time_ago_text
    from nonebot.adapters.onebot.v11 import MessageSegment

    images = []
    reply_images = {}
    media_budget = int(x_subscription_config['max_media_images'])
    for url in bundle['post'].get('media_urls', [])[:int(x_subscription_config['max_media_images'])]:
        media_budget -= 1
        try:
            media = pil_image_from_bytes(x_get_media_bytes(url), max_pixels=int(x_subscription_config['max_media_pixels']))
            images.append(media.convert('RGB'))
        except Exception:
            bundle = dict(bundle, media_unavailable=True)
    for reply in bundle.get('replies', []):
        for url in reply.get('media_urls', [])[:max(0, media_budget)]:
            media_budget -= 1
            try:
                media = pil_image_from_bytes(x_get_media_bytes(url), max_pixels=int(x_subscription_config['max_media_pixels']))
                reply_images.setdefault(reply['id'], []).append(media.convert('RGB'))
            except Exception:
                pass
    paths = save_x_post_images(render_x_post_images(bundle, images, reply_images))
    post = bundle['post']
    name = post.get('name') or post['username']
    published = post.get('created_at')
    if published:
        timestamp = parse_chat_time_bound(published)
        stamp = epoch_to_text(timestamp, timezone_name='Asia/Shanghai') + f'（{time_ago_text(timestamp)}）'
    else:
        stamp = '时间未知'
    preview = post_text_preview(post.get('text'), x_subscription_config['message_preview_max_chars'],
                                translation=post.get('translation'))
    text = f"{name} · {stamp}\n{preview}\n"
    pictures = '\n'.join(str(MessageSegment.image(f"file://{path}")) for path in paths)
    link = f"\nhttps://x.com/{post['username']}/status/{post['id']}"
    return str(MessageSegment.text(text)) + pictures + str(MessageSegment.text(link))


def _x_send_message(message):
    from .utils.message_sender import add_msg
    return add_msg(message, msg_type="group", to_id=confs["QQBot"]["group_qid"])


def x_subscribe_user(user_qid, query):
    from .business.x_subscription import x_subscribe_user as impl
    return impl(user_qid, query)


def x_unsubscribe_user(user_qid, query=""):
    from .business.x_subscription import x_unsubscribe_user as impl
    return impl(user_qid, query)


def x_my_subscription(user_qid):
    from .business.x_subscription import x_my_subscription as impl
    return impl(user_qid)


def x_latest_for_user(user_qid):
    from .business.x_subscription import x_latest_for_user as impl
    return impl(user_qid)


def x_check_and_push():
    from .business.x_subscription import x_check_and_push as impl
    return impl()


def x_admin_command(raw):
    from .business.x_subscription import x_admin_command as impl
    return impl(raw)


_BILI_VIDEO_SUBSCRIPTIONS_REDIS_KEY = "hok:bili:subscriptions"


from .business import bili_video as _bili_video_business


def _bili_video_normalize_subscription_item(item):
    return _bili_video_business._bili_video_normalize_subscription_item(item)


def _bili_video_normalize_subscriptions(subscriptions):
    return _bili_video_business._bili_video_normalize_subscriptions(subscriptions)


def _bili_video_get_subscriptions():
    try:
        subscriptions = _bili_video_normalize_subscriptions(
            _redis_get_json(_BILI_VIDEO_SUBSCRIPTIONS_REDIS_KEY, default={})
        )
        return subscriptions
    except Exception as error:
        log_message(f"BILI_VIDEO_SUBSCRIPTION_REDIS_READ_ERROR: {repr(error)}")
        return {}


def _bili_video_save_subscriptions(subscriptions):
    subscriptions = _bili_video_normalize_subscriptions(subscriptions)
    _redis_set_json(_BILI_VIDEO_SUBSCRIPTIONS_REDIS_KEY, subscriptions)


def _bili_video_subscription_items_for_user(subscriptions, user_qid):
    return _bili_video_business._bili_video_subscription_items_for_user(
        subscriptions, user_qid
    )


def _bili_video_set_subscription_items_for_user(subscriptions, user_qid, items):
    return _bili_video_business._bili_video_set_subscription_items_for_user(
        subscriptions, user_qid, items
    )


def _bili_video_iter_subscription_items(subscriptions):
    return _bili_video_business._bili_video_iter_subscription_items(subscriptions)


def _bili_video_identity_key(up_mid, up_name=""):
    return _bili_video_business._bili_video_identity_key(up_mid, up_name)


def _bili_video_seen_key(up_mid, up_name=""):
    return _bili_video_business._bili_video_seen_key(up_mid, up_name)


def _bili_video_seen_exists(up_mid, up_name, bvid):
    return bool(dmc.redis_deamon.sismember(_bili_video_seen_key(up_mid, up_name), str(bvid)))


def _bili_video_mark_seen(up_mid, up_name, bvids):
    clean_bvids = [str(bvid).strip() for bvid in bvids if str(bvid or "").strip()]
    if not clean_bvids:
        return 0
    return dmc.redis_deamon.sadd(_bili_video_seen_key(up_mid, up_name), *clean_bvids)


def _bili_video_seen_initialized(up_mid, up_name):
    return bool(dmc.redis_deamon.exists(_bili_video_seen_key(up_mid, up_name)))


def _bili_video_acquire_push_lock():
    from .ztime import current_epoch_seconds

    return bool(
        dmc.redis_deamon.set(
            "hok:lock:bili:video_push",
            str(current_epoch_seconds()),
            nx=True,
            ex=600,
        )
    )


def _bili_video_release_push_lock():
    return dmc.redis_deamon.delete("hok:lock:bili:video_push")


def _bili_video_send_group_message(message):
    from .utils.message_sender import add_msg

    return add_msg(message, msg_type="group", to_id=confs["QQBot"]["group_qid"])


def _bili_video_subscribed_at_epoch(item):
    return _bili_video_business._bili_video_subscribed_at_epoch(item)


def _bili_video_subscribers_by_up():
    return _bili_video_business._bili_video_subscribers_by_up()


def _bili_video_update_subscription_identity(identity, *, up_mid=None, up_name=None):
    return _bili_video_business._bili_video_update_subscription_identity(
        identity,
        up_mid=up_mid,
        up_name=up_name,
    )


def _bili_video_format_subscriber_list(user_qids):
    return _bili_video_business._bili_video_format_subscriber_list(user_qids)


def _bili_video_format_subscription_label(item):
    return _bili_video_business._bili_video_format_subscription_label(item)


def _bili_video_find_matching_items(items, query_text):
    return _bili_video_business._bili_video_find_matching_items(items, query_text)


def _bili_video_app_url(aid):
    return _bili_video_business._bili_video_app_url(aid)


def _bili_video_mobile_url(bvid):
    return _bili_video_business._bili_video_mobile_url(bvid)


def _bili_video_pic_url(video):
    return _bili_video_business._bili_video_pic_url(video)


def _cq_escape(value):
    return _bili_video_business._cq_escape(value)


def _bili_video_pic_message_segment(video):
    return _bili_video_business._bili_video_pic_message_segment(video)


def _bili_video_page_link(up_name, video):
    return _bili_video_business._bili_video_page_link(up_name, video)


def _bili_video_format_video_message(up_name, video):
    return _bili_video_business._bili_video_format_video_message(up_name, video)


def _bili_video_format_push_message(up_name, video, subscribers):
    return _bili_video_business._bili_video_format_push_message(
        up_name, video, subscribers
    )


def _bili_video_format_latest_message(up_name, video):
    return _bili_video_business._bili_video_format_latest_message(up_name, video)


def _bili_video_similarity(query, candidate_name):
    return _bili_video_business._bili_video_similarity(query, candidate_name)


def _bili_video_resolve_best_up(query):
    return _bili_video_business._bili_video_resolve_best_up(query)


def bili_video_subscribe_user(user_qid, up_name):
    return _bili_video_business.bili_video_subscribe_user(user_qid, up_name)


def bili_video_unsubscribe_user(user_qid, query_text=""):
    return _bili_video_business.bili_video_unsubscribe_user(user_qid, query_text)


def bili_video_my_subscription(user_qid):
    return _bili_video_business.bili_video_my_subscription(user_qid)


def _bili_video_latest_for_item(item):
    return _bili_video_business._bili_video_latest_for_item(item)


def bili_video_latest_for_user(user_qid):
    return _bili_video_business.bili_video_latest_for_user(user_qid)


def bili_video_list_subscriptions():
    return _bili_video_business.bili_video_list_subscriptions()


def bili_video_check_and_push(*, debug=False):
    return _bili_video_business.bili_video_check_and_push(debug=debug)


def bili_video_admin_command(raw_msg):
    return _bili_video_business.bili_video_admin_command(raw_msg)


def generate_user_emoji_image(*, user_qid: str, size=None):
    from .tools.gen_emoji_image import generate_user_emoji_image as _impl
    return _impl(user_qid=user_qid, size=size)
def extract_url_params(url):
    return _user_helpers_business.extract_url_params(url)


def get_peak_alter_list(details, processed, reverse=1):
    return _user_helpers_business.get_peak_alter_list(
        details,
        processed,
        reverse=reverse,
    )


def extract_name(from_text, precise=False):
    return _user_helpers_business.extract_name(from_text, precise=precise)
from .business import battle_metrics as _battle_metrics_business


def merge_crossday_gamedata(gamedata):
    return _battle_metrics_business.merge_crossday_gamedata(gamedata)


def calculate_official_battle_average(details):
    return _battle_metrics_business.calculate_official_battle_average(details)


def _battle_all_roles(battle_detail):
    return _battle_metrics_business._battle_all_roles(battle_detail)


def _find_battle_role(battle_detail, roleid=None, userid=None):
    return _battle_metrics_business._find_battle_role(
        battle_detail, roleid=roleid, userid=userid
    )


def _battle_role_has_assist_equip(role):
    return _battle_metrics_business._battle_role_has_assist_equip(role)


def calculate_battle_contribution_factor(
    battle_detail, roleid=None, userid=None, role=None
):
    return _battle_metrics_business.calculate_battle_contribution_factor(
        battle_detail,
        roleid=roleid,
        userid=userid,
        role=role,
    )


def calculate_official_battle_contribution_average(details, roleid):
    return _battle_metrics_business.calculate_official_battle_contribution_average(
        details, roleid
    )


def check_btl_official(btlname):
    return _battle_metrics_business.check_btl_official(btlname)


def check_btl_official_only_rank(btlname):
    return _battle_metrics_business.check_btl_official_only_rank(btlname)


def check_btl_official_with_matching(btlname):
    return _battle_metrics_business.check_btl_official_with_matching(btlname)


def check_btl_official_with_matching_with_entertain(btlname):
    return _battle_metrics_business.check_btl_official_with_matching_with_entertain(
        btlname
    )
def export_btldetail(gameinfo, roleid):
    return _player_data_business.export_battle_details(gameinfo, roleid)

from .business import daily_notification as _daily_notification_business


def notify_msg_impl():
    return _daily_notification_business.notify_msg_impl()

_KPL_PUSH_LOCK_KEY = "hok:lock:kpl:push"
_KPL_PUSH_PENDING_KEY = "hok:kpl:push_pending"
_KPL_PUSHED_CIDS_KEY = "hok:kpl:pushed_cids"


from .business import kpl as _kpl_business


def _kpl_acquire_push_lock():
    from .ztime import current_epoch_seconds

    return bool(
        dmc.redis_deamon.set(
            _KPL_PUSH_LOCK_KEY,
            str(current_epoch_seconds()),
            nx=True,
            ex=600,
        )
    )


def _kpl_release_push_lock():
    return dmc.redis_deamon.delete(_KPL_PUSH_LOCK_KEY)


def _kpl_mark_push_pending():
    return dmc.redis_deamon.set(_KPL_PUSH_PENDING_KEY, "1", ex=3600)


def _kpl_take_push_pending():
    pending = dmc.redis_deamon.get(_KPL_PUSH_PENDING_KEY)
    if pending:
        dmc.redis_deamon.delete(_KPL_PUSH_PENDING_KEY)
        return True
    return False


def _kpl_was_pushed(cid):
    return bool(dmc.redis_deamon.sismember(_KPL_PUSHED_CIDS_KEY, str(cid)))


def _kpl_mark_pushed(cid):
    return dmc.redis_deamon.sadd(_KPL_PUSHED_CIDS_KEY, str(cid))


def _kpl_save_push_image(image_url, cid, date_text):
    from .zfile import save_kpl_push_image

    return save_kpl_push_image(image_url, cid, date_text)


def _kpl_send_push_message(text, image_path, event=None):
    from .utils.message_sender import add_text_image_msg

    return add_text_image_msg(
        text,
        image_path,
        event=event,
        msg_type="group",
        to_id=confs["QQBot"]["group_qid"],
    )


def kpl_check_and_push(
    *,
    debug: bool = False,
    event=None,
    force: bool = False,
    preview_only: bool = False,
):
    return _kpl_business.kpl_check_and_push(
        debug=debug,
        event=event,
        force=force,
        preview_only=preview_only,
    )


def kpl_match_image_generate(*, match_content: dict, size: str, resolution: str):
    return _kpl_business.kpl_match_image_generate(
        match_content=match_content,
        size=size,
        resolution=resolution,
    )


def kpl_build_match_image_prompt(*, match_content: dict):
    return _kpl_business.kpl_build_match_image_prompt(match_content=match_content)


from .business import history_query as _history_query_business
from .business import representative_battle as _representative_battle_business


def _build_representative_battle_text(best_battle, title_date):
    return _representative_battle_business._build_representative_battle_text(
        best_battle, title_date
    )


def get_daily_representative_battle(target_date=None, candidates_only=False):
    return _representative_battle_business.get_daily_representative_battle(
        target_date=target_date,
        candidates_only=candidates_only,
    )


def representative_battle_query_impl(query_text):
    return _representative_battle_business.representative_battle_query_impl(query_text)


def _build_representative_category_leader_text(category_label, candidate):
    return _representative_battle_business._build_representative_category_leader_text(
        category_label, candidate
    )


def get_representative_battle_category_leaders(target_date):
    return _representative_battle_business.get_representative_battle_category_leaders(
        target_date
    )


def representative_battle_range_debug_impl(query_text):
    return _representative_battle_business.representative_battle_range_debug_impl(
        query_text
    )


def extract_heroname(origin_text, precise=False):
    return _history_query_business.extract_heroname(origin_text, precise=precise)


def txt_contain(x, y, precise, is_origin):
    return _history_query_business.txt_contain(x, y, precise, is_origin)


def history_query_handler(rcv_msg):
    return _history_query_business.history_query_handler(rcv_msg)


def format_history_query_prefix(query_desc, stats):
    return _history_query_business.format_history_query_prefix(query_desc, stats)


def history_query_single_match(detail, realname):
    return btldetail_process(
        **detail["Params"],
        roleid=roleidlist[realname],
        gen_image=True,
        individual_show=True,
    )


def history_query_multiple_matches_link(query_target, matches):
    from .zfile import write_web_history_payload
    from .ztime import current_datetime_text, current_timestamp

    now_time = current_datetime_text()
    packed_data = _history_query_business.pack_history_query_matches(
        matches,
        roleidlist,
        fetch_battle,
    )
    filename_hashed = WebArtifacts.make_hash(round(current_timestamp() * 1000000))
    write_web_history_payload(filename_hashed, packed_data)
    return WebArtifacts.history_route_link(
        filename_hashed,
        "query_select",
        query_target,
        now_time,
    )

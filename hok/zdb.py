"""PostgreSQL data access for structured HOK history data."""

from .zutil import *
from .zstatic import postgres_dsn


def _connect():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise RuntimeError("PostgreSQL driver is unavailable; install psycopg[binary]") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)


def _jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _as_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_text(value):
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def ping():
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            return cursor.fetchone()["ok"] == 1


def execute_schema(schema_sql):
    if not str(schema_sql or "").strip():
        raise ValueError("database schema is empty")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema_sql)


def import_archive_payload(descriptor, payload):
    kind = descriptor["kind"]
    source_path = descriptor["source_path"]
    if kind == "history":
        return replace_history_date(descriptor["date"], payload, source_path)
    if kind == "battle":
        return upsert_battle_detail(descriptor["game_seq"], payload, source_path)
    if kind == "personal":
        return upsert_personal_snapshot(descriptor["date"], descriptor["user_id"], payload, source_path)
    if kind == "power":
        return upsert_battle_power(descriptor["game_seq"], payload, source_path)
    if kind == "hero_tier":
        return replace_hero_tier_date(descriptor["date"], payload, source_path)
    if kind == "hero_rank":
        return replace_hero_rank_date(descriptor["date"], payload, source_path)
    raise ValueError(f"unsupported archive kind: {kind}")


def replace_history_date(snapshot_date, players, source_path=None):
    """Atomically replace one daily aggregate and its normalized battle rows."""
    if not isinstance(players, list):
        raise ValueError("history payload must be a list")
    snapshot_date = _date_text(snapshot_date)
    player_count = 0
    battle_count = 0
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM hok.history_players WHERE snapshot_date = %s", (snapshot_date,))
            for player_index, player in enumerate(players):
                if not isinstance(player, dict):
                    continue
                player_key = str(player.get("key") or player.get("id") or f"unknown-{player_index}")
                user_id = _as_int(player.get("id"))
                role_id = _as_int(player.get("roleid"))
                cursor.execute(
                    """
                    INSERT INTO hok.history_players (
                        snapshot_date, player_key, player_index, user_id, role_id, nickname,
                        rank_name, rank_star, star, star_up, today_num, total_num, visible,
                        map_count, peak_up, gaming_info, payload, source_path, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, now()
                    )
                    """,
                    (
                        snapshot_date,
                        player_key,
                        player_index,
                        user_id,
                        role_id,
                        player.get("nickname"),
                        player.get("rank_name") or player.get("rank"),
                        _as_int(player.get("rank_star")),
                        _as_int(player.get("star")),
                        _as_int(player.get("star_up")),
                        _as_int(player.get("today_num")),
                        _as_int(player.get("total_num")),
                        player.get("visible") if isinstance(player.get("visible"), bool) else None,
                        _jsonb(player.get("map_cnt") or {}),
                        _jsonb(player.get("peak_up") or []),
                        _jsonb(player.get("gaming_info") or {}),
                        _jsonb(player),
                        source_path,
                    ),
                )
                player_count += 1
                details = player.get("details") or []
                if not isinstance(details, list):
                    continue
                for detail_index, detail in enumerate(details):
                    if not isinstance(detail, dict):
                        continue
                    cursor.execute(
                        """
                        INSERT INTO hok.battle_records (
                            snapshot_date, player_key, player_index, detail_index, user_id, role_id,
                            game_seq, game_time_label, game_time_epoch, hero_name, map_name,
                            map_type, star_after_game, peak_grade_after, peak_grade_before,
                            kill_count, death_count, assist_count, result, game_grade,
                            duration_seconds, params, others, payload
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        """,
                        (
                            snapshot_date,
                            player_key,
                            player_index,
                            detail_index,
                            user_id,
                            role_id,
                            _as_int(detail.get("GameSeq")),
                            detail.get("GameTime"),
                            _as_int(detail.get("GameTime_Timestamp")),
                            detail.get("HeroName"),
                            detail.get("MapName"),
                            _as_int(detail.get("MapType")),
                            _as_int(detail.get("StarAfterGame")),
                            _as_int(detail.get("PeakGradeAfterGame")),
                            _as_int(detail.get("PeakGradeBeforeGame")),
                            _as_int(detail.get("KillCnt")),
                            _as_int(detail.get("DeadCnt")),
                            _as_int(detail.get("AssistCnt")),
                            detail.get("Result"),
                            _as_float(detail.get("GameGrade")),
                            _as_int(detail.get("Duration_Second")),
                            _jsonb(detail.get("Params") or {}),
                            _jsonb(detail.get("Others")) if detail.get("Others") is not None else None,
                            _jsonb(detail),
                        ),
                    )
                    battle_count += 1
    return {"players": player_count, "battles": battle_count}


def read_history_date(snapshot_date):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT payload
                FROM hok.history_players
                WHERE snapshot_date = %s
                ORDER BY player_index
                """,
                (_date_text(snapshot_date),),
            )
            return [row["payload"] for row in cursor.fetchall()]


def list_history_dates_descending(start_date=None):
    query = "SELECT DISTINCT snapshot_date FROM hok.history_players"
    params = []
    if start_date:
        query += " WHERE snapshot_date >= %s"
        params.append(_date_text(start_date))
    query += " ORDER BY snapshot_date DESC"
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [row["snapshot_date"].isoformat() for row in cursor.fetchall()]


def fetch_history(userid=None, start_date=None, end_date=None, filter_official=True):
    """Return the legacy {player_key: [battle]} shape using indexed rows."""
    conditions = ["snapshot_date BETWEEN %s AND %s"]
    params = [_date_text(start_date), _date_text(end_date)]
    if userid is not None:
        conditions.append("user_id = %s")
        params.append(_as_int(userid))
    if filter_official:
        conditions.append("map_name ~ '(排位|巅峰|战队)'")
        conditions.append("lower(coalesce(map_name, '')) !~ '(1v1|2v2|3v3)'")
    where_sql = " AND ".join(conditions)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(DISTINCT snapshot_date) AS duration
                FROM hok.history_players
                WHERE snapshot_date BETWEEN %s AND %s
                """,
                (_date_text(start_date), _date_text(end_date)),
            )
            duration = int(cursor.fetchone()["duration"] or 0)
            cursor.execute(
                f"""
                SELECT player_key, payload
                FROM hok.battle_records
                WHERE {where_sql}
                ORDER BY snapshot_date DESC, player_key, detail_index DESC
                """,
                params,
            )
            histories = {}
            for row in cursor.fetchall():
                histories.setdefault(row["player_key"], []).append(row["payload"])
    return histories, duration


def latest_rank_star_before(user_id, before_date):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT star_after_game
                FROM hok.battle_records
                WHERE user_id = %s
                  AND snapshot_date <= %s
                  AND map_type = 1
                  AND star_after_game IS NOT NULL
                ORDER BY snapshot_date DESC, detail_index DESC
                LIMIT 1
                """,
                (_as_int(user_id), _date_text(before_date)),
            )
            row = cursor.fetchone()
            return row["star_after_game"] if row else None


def upsert_battle_detail(game_seq, payload, source_path=None):
    if not isinstance(payload, dict):
        raise ValueError("battle detail payload must be an object")
    game_seq = _as_int(game_seq)
    if game_seq is None:
        raise ValueError("battle detail is missing game_seq")
    battle = payload.get("battle") or {}
    roles = list(payload.get("redRoles") or []) + list(payload.get("blueRoles") or [])
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO hok.battle_details (
                    game_seq, game_type, map_name, event_time_label, start_time_label,
                    duration_seconds, payload, source_path, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (game_seq) DO UPDATE SET
                    game_type = EXCLUDED.game_type,
                    map_name = EXCLUDED.map_name,
                    event_time_label = EXCLUDED.event_time_label,
                    start_time_label = EXCLUDED.start_time_label,
                    duration_seconds = EXCLUDED.duration_seconds,
                    payload = EXCLUDED.payload,
                    source_path = EXCLUDED.source_path,
                    updated_at = now()
                """,
                (
                    game_seq,
                    _as_int(battle.get("gameType")),
                    battle.get("mapName"),
                    battle.get("dtEventTime"),
                    battle.get("startTime"),
                    _as_int(battle.get("usedTime")),
                    _jsonb(payload),
                    source_path,
                ),
            )
            cursor.execute("DELETE FROM hok.battle_participants WHERE game_seq = %s", (game_seq,))
            for participant_index, role in enumerate(roles):
                if not isinstance(role, dict):
                    continue
                basic = role.get("basicInfo") or {}
                stats = role.get("battleStats") or {}
                records = role.get("battleRecords") or {}
                hero = records.get("usedHero") or {}
                cursor.execute(
                    """
                    INSERT INTO hok.battle_participants (
                        game_seq, participant_index, camp, role_id, user_id, role_name,
                        hero_id, hero_name, kill_count, death_count, assist_count,
                        game_grade, gold, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        game_seq,
                        participant_index,
                        str(basic.get("acntCamp")) if basic.get("acntCamp") is not None else None,
                        _as_int(basic.get("roleId")),
                        _as_int(basic.get("userId")),
                        basic.get("roleName"),
                        _as_int(hero.get("heroId")),
                        hero.get("heroName"),
                        _as_int(stats.get("killCnt")),
                        _as_int(stats.get("deadCnt")),
                        _as_int(stats.get("assistCnt")),
                        _as_float(stats.get("gradeGame")),
                        _as_int(stats.get("money")),
                        _jsonb(role),
                    ),
                )
    return {"battle_details": 1, "participants": len(roles)}


def read_battle_detail(game_seq):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM hok.battle_details WHERE game_seq = %s",
                (_as_int(game_seq),),
            )
            row = cursor.fetchone()
            return row["payload"] if row else None


def battle_detail_exists(game_seq):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM hok.battle_details WHERE game_seq = %s) AS found",
                (_as_int(game_seq),),
            )
            return bool(cursor.fetchone()["found"])


def upsert_personal_snapshot(snapshot_date, user_id, payload, source_path=None):
    if not isinstance(payload, dict):
        raise ValueError("personal snapshot payload must be an object")
    btlist = payload.get("btlist") or {}
    profile = payload.get("profile") or {}
    target_role_id = profile.get("targetRoleId")
    if target_role_id is None:
        roles = profile.get("roleList") or []
        target_role_id = roles[0].get("roleId") if roles and isinstance(roles[0], dict) else None
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO hok.personal_snapshots (
                    snapshot_date, user_id, target_role_id, invisible, is_gaming,
                    battle_count, payload, source_path, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (snapshot_date, user_id) DO UPDATE SET
                    target_role_id = EXCLUDED.target_role_id,
                    invisible = EXCLUDED.invisible,
                    is_gaming = EXCLUDED.is_gaming,
                    battle_count = EXCLUDED.battle_count,
                    payload = EXCLUDED.payload,
                    source_path = EXCLUDED.source_path,
                    updated_at = now()
                """,
                (
                    _date_text(snapshot_date),
                    _as_int(user_id),
                    _as_int(target_role_id),
                    btlist.get("invisible") if isinstance(btlist.get("invisible"), bool) else None,
                    btlist.get("isGaming") if isinstance(btlist.get("isGaming"), bool) else None,
                    len(btlist.get("list") or []),
                    _jsonb(payload),
                    source_path,
                ),
            )
    return {"personal_snapshots": 1}


def read_personal_snapshot(snapshot_date, user_id):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT payload
                FROM hok.personal_snapshots
                WHERE snapshot_date = %s AND user_id = %s
                """,
                (_date_text(snapshot_date), _as_int(user_id)),
            )
            row = cursor.fetchone()
            return row["payload"] if row else None


def upsert_battle_power(game_seq, payload, source_path=None):
    if not isinstance(payload, dict):
        raise ValueError("battle power payload must be an object")
    game_seq = _as_int(game_seq or payload.get("GameSeq"))
    if game_seq is None:
        raise ValueError("battle power payload is missing GameSeq")
    my_side = payload.get("mySide") or {}
    opponent_side = payload.get("opSide") or {}
    players = payload.get("players") or []
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO hok.battle_power (
                    game_seq, role_id, map_name, game_result, game_time, evaluated_at,
                    my_side_level, opponent_side_level, my_side_tier, opponent_side_tier,
                    payload, source_path, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (game_seq) DO UPDATE SET
                    role_id = EXCLUDED.role_id,
                    map_name = EXCLUDED.map_name,
                    game_result = EXCLUDED.game_result,
                    game_time = EXCLUDED.game_time,
                    evaluated_at = EXCLUDED.evaluated_at,
                    my_side_level = EXCLUDED.my_side_level,
                    opponent_side_level = EXCLUDED.opponent_side_level,
                    my_side_tier = EXCLUDED.my_side_tier,
                    opponent_side_tier = EXCLUDED.opponent_side_tier,
                    payload = EXCLUDED.payload,
                    source_path = EXCLUDED.source_path,
                    updated_at = now()
                """,
                (
                    game_seq,
                    _as_int(payload.get("roleid")),
                    payload.get("mapName"),
                    str(payload.get("gameResult")) if payload.get("gameResult") is not None else None,
                    str(payload.get("gameTime")) if payload.get("gameTime") is not None else None,
                    payload.get("evaluatedAt"),
                    _as_float(my_side.get("level")),
                    _as_float(opponent_side.get("level")),
                    _as_float(my_side.get("tier")),
                    _as_float(opponent_side.get("tier")),
                    _jsonb(payload),
                    source_path,
                ),
            )
            cursor.execute("DELETE FROM hok.battle_power_players WHERE game_seq = %s", (game_seq,))
            for participant_index, player in enumerate(players):
                if not isinstance(player, dict):
                    continue
                cursor.execute(
                    """
                    INSERT INTO hok.battle_power_players (
                        game_seq, participant_index, role_id, user_id, nickname, side,
                        hero_name, hero_power, hero_win_rate, hero_average_score,
                        single_level, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        game_seq,
                        participant_index,
                        _as_int(player.get("roleId")),
                        _as_int(player.get("userId")),
                        player.get("nickname"),
                        player.get("side"),
                        player.get("heroName"),
                        _as_int(player.get("heroPower")),
                        _as_float(player.get("heroWinRate")),
                        _as_float(player.get("heroAvgScore")),
                        _as_float(player.get("singleLevel")),
                        _jsonb(player),
                    ),
                )
    return {"battle_power": 1, "battle_power_players": len(players)}


def read_battle_power(game_seq):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM hok.battle_power WHERE game_seq = %s",
                (_as_int(game_seq),),
            )
            row = cursor.fetchone()
            return row["payload"] if row else None


def battle_power_exists(game_seq):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM hok.battle_power WHERE game_seq = %s) AS found",
                (_as_int(game_seq),),
            )
            return bool(cursor.fetchone()["found"])


def replace_hero_tier_date(snapshot_date, payload, source_path=None):
    if not isinstance(payload, dict):
        raise ValueError("hero tier payload must be an object")
    snapshot_date = _date_text(snapshot_date)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM hok.hero_tier_scores WHERE snapshot_date = %s", (snapshot_date,))
            for hero_name, score in payload.items():
                numeric_score = _as_float(score)
                if numeric_score is None:
                    continue
                cursor.execute(
                    """
                    INSERT INTO hok.hero_tier_scores (
                        snapshot_date, hero_name, score, source_path, updated_at
                    ) VALUES (%s, %s, %s, %s, now())
                    """,
                    (snapshot_date, str(hero_name), numeric_score, source_path),
                )
    return {"hero_tier_scores": len(payload)}


def read_hero_tier_date(snapshot_date):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT hero_name, score
                FROM hok.hero_tier_scores
                WHERE snapshot_date = %s
                ORDER BY hero_name
                """,
                (_date_text(snapshot_date),),
            )
            return {row["hero_name"]: float(row["score"]) for row in cursor.fetchall()}


def replace_hero_rank_date(snapshot_date, payload, source_path=None):
    if not isinstance(payload, dict):
        raise ValueError("hero rank payload must be an object")
    snapshot_date = _date_text(snapshot_date)
    snapshot_count = 0
    entry_count = 0
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM hok.hero_rank_snapshots WHERE snapshot_date = %s", (snapshot_date,))
            for rank_id_raw, rank_payload in payload.items():
                rank_id = _as_int(rank_id_raw)
                if rank_id is None or not isinstance(rank_payload, dict):
                    continue
                cursor.execute(
                    """
                    INSERT INTO hok.hero_rank_snapshots (
                        snapshot_date, rank_id, title, update_time, sort_field,
                        sort_type, filter_data, payload, source_path, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        snapshot_date,
                        rank_id,
                        rank_payload.get("title"),
                        str(rank_payload.get("updateTime")) if rank_payload.get("updateTime") is not None else None,
                        str(rank_payload.get("sortField")) if rank_payload.get("sortField") is not None else None,
                        str(rank_payload.get("sortType")) if rank_payload.get("sortType") is not None else None,
                        _jsonb(rank_payload.get("filter") or {}),
                        _jsonb(rank_payload),
                        source_path,
                    ),
                )
                snapshot_count += 1
                entries = rank_payload.get("list") or []
                if not isinstance(entries, list):
                    continue
                for rank_index, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        continue
                    hero_info = entry.get("heroInfo") or {}
                    cursor.execute(
                        """
                        INSERT INTO hok.hero_rank_entries (
                            snapshot_date, rank_id, rank_index, hero_id, hero_name,
                            hero_career, tier_rank, ban_rate, show_rate, win_rate,
                            pick_count, ban_count, payload
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            snapshot_date,
                            rank_id,
                            rank_index,
                            _as_int(entry.get("heroId") or hero_info.get("heroId")),
                            hero_info.get("heroName"),
                            hero_info.get("heroCareer"),
                            entry.get("tRank"),
                            _as_float(entry.get("banRate")),
                            _as_float(entry.get("showRate")),
                            _as_float(entry.get("winRate")),
                            _as_int(entry.get("pick")),
                            _as_int(entry.get("ban")),
                            _jsonb(entry),
                        ),
                    )
                    entry_count += 1
    return {"hero_rank_snapshots": snapshot_count, "hero_rank_entries": entry_count}


def read_hero_rank_date(snapshot_date):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rank_id, payload
                FROM hok.hero_rank_snapshots
                WHERE snapshot_date = %s
                ORDER BY rank_id
                """,
                (_date_text(snapshot_date),),
            )
            return {str(row["rank_id"]): row["payload"] for row in cursor.fetchall()}


def manifest_matches(source_path, source_size, source_mtime_ns):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_size, source_mtime_ns
                FROM hok.json_import_manifest
                WHERE source_path = %s
                """,
                (source_path,),
            )
            row = cursor.fetchone()
            return bool(
                row
                and int(row["source_size"]) == int(source_size)
                and int(row["source_mtime_ns"]) == int(source_mtime_ns)
            )


def update_manifest(source_path, data_kind, source_size, source_mtime_ns, imported_rows):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO hok.json_import_manifest (
                    source_path, data_kind, source_size, source_mtime_ns,
                    imported_rows, imported_at
                ) VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (source_path) DO UPDATE SET
                    data_kind = EXCLUDED.data_kind,
                    source_size = EXCLUDED.source_size,
                    source_mtime_ns = EXCLUDED.source_mtime_ns,
                    imported_rows = EXCLUDED.imported_rows,
                    imported_at = now()
                """,
                (source_path, data_kind, int(source_size), int(source_mtime_ns), int(imported_rows)),
            )


def table_counts():
    table_names = (
        "history_players",
        "battle_records",
        "battle_details",
        "battle_participants",
        "personal_snapshots",
        "battle_power",
        "battle_power_players",
        "hero_tier_scores",
        "hero_rank_snapshots",
        "hero_rank_entries",
        "json_import_manifest",
    )
    counts = {}
    with _connect() as connection:
        with connection.cursor() as cursor:
            for table_name in table_names:
                cursor.execute(f"SELECT count(*) AS count FROM hok.{table_name}")
                counts[table_name] = int(cursor.fetchone()["count"])
    return counts


def _chat_sql_limits():
    """Read configurable chat bounds without changing ordinary database calls."""
    from .zstatic import chat_sql_config

    defaults = {
        "max_rows": 200,
        "max_columns": 40,
        "max_bytes": 60000,
        "max_sql_chars": 20000,
        "statement_timeout_ms": 5000,
        "connect_timeout_seconds": 5,
    }
    limits = {}
    for name, default in defaults.items():
        value = chat_sql_config.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"ChatSQL.{name} 必须为正整数")
        limits[name] = value
    return limits


def _chat_readonly_connect(limits):
    """Create the separate reader connection, never fall back to the writer."""
    from .zstatic import chat_readonly_dsn

    if not str(chat_readonly_dsn or "").strip():
        raise RuntimeError("ChatSQL只读数据库尚未配置")
    import psycopg
    from psycopg.rows import tuple_row

    return psycopg.connect(
        chat_readonly_dsn,
        row_factory=tuple_row,
        connect_timeout=limits["connect_timeout_seconds"],
        options="-c default_transaction_read_only=on -c search_path=pg_catalog,hok -c timezone=Asia/Shanghai",
    )


def _chat_json_value(value):
    """Preserve usable numbers, dates and nested JSON without invalid JSON."""
    from decimal import Decimal
    import math

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        # Game/role identifiers can exceed JavaScript's exact-integer range.
        return value if abs(value) <= 9007199254740991 else str(value)
    if isinstance(value, (float, Decimal)):
        number = float(value)
        return number if math.isfinite(number) else str(value)
    if isinstance(value, dict):
        return {str(key): _chat_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_chat_json_value(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def chat_schema_catalog():
    """Return the verified gameplay catalogue, rules and executable limits."""
    from .chat_sql_schema import schema_catalog
    from .zstatic import chat_readonly_dsn

    result = schema_catalog()
    result.update({"ok": True, "limits": _chat_sql_limits(), "configured": bool(chat_readonly_dsn)})
    return result


def chat_check_readonly(sql, params=None):
    """Validate one chat query against the same boundary used at execution."""
    from .tools.chat_sql import ChatSQLValidationError, validate_readonly_sql

    try:
        normalized = validate_readonly_sql(
            sql,
            params=params,
            max_sql_chars=_chat_sql_limits()["max_sql_chars"],
        )
        return {"ok": True, "normalized_sql": normalized}
    except (ChatSQLValidationError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def chat_query_readonly(sql, params=None, limit=None):
    """Run one model-generated analytical SELECT as a least-privileged reader.

    Always return a structured observation, including for rejected SQL, timeout,
    unavailable connection or partial results. Existing _connect() is never used.
    """
    from .chat_sql_schema import CHAT_SQL_ROLE
    from .tools.chat_sql import ChatSQLValidationError, validate_readonly_sql

    try:
        limits = _chat_sql_limits()
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ChatSQLValidationError("limit 必须为正整数")
        row_limit = min(limit or limits["max_rows"], limits["max_rows"])
        checked = chat_check_readonly(sql, params=params)
        if not checked["ok"]:
            raise ChatSQLValidationError(checked["error"])
        normalized = checked["normalized_sql"]
    except (ChatSQLValidationError, ValueError) as exc:
        return {"ok": False, "location": "chat_query_readonly.validate", "error": str(exc)}

    try:
        with _chat_readonly_connect(limits) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT set_config('statement_timeout', %s, true)", (str(limits["statement_timeout_ms"]),))
                cursor.execute("SELECT set_config('lock_timeout', %s, true)", (str(limits["statement_timeout_ms"]),))
                cursor.execute("SELECT set_config('idle_in_transaction_session_timeout', %s, true)", (str(limits["statement_timeout_ms"]),))
                cursor.execute("SELECT set_config('search_path', 'pg_catalog,hok', true)")
                cursor.execute("SELECT set_config('TimeZone', 'Asia/Shanghai', true)")
                # A misconfigured writer/superuser DSN must fail closed. The
                # deployment SQL creates this isolated role with no memberships.
                cursor.execute("""
                    SELECT r.rolname, r.rolsuper, r.rolcreaterole, r.rolcreatedb,
                           r.rolreplication, r.rolbypassrls,
                           EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member = r.oid)
                    FROM pg_catalog.pg_roles r WHERE r.rolname = CURRENT_USER
                """)
                identity = cursor.fetchone()
                if not identity or identity[0] != CHAT_SQL_ROLE or any(identity[1:]):
                    raise PermissionError("ChatSQL必须使用独立无特权的hok_chat_reader账号")

            # A server cursor avoids buffering every row. The outer LIMIT also
            # bounds result materialization even when the model omits LIMIT.
            with connection.cursor(name="hok_chat_observation") as cursor:
                cursor.execute(f"SELECT * FROM ({normalized}) AS chat_result LIMIT {row_limit + 1}")
                first_row = cursor.fetchone()
                columns = [column.name for column in cursor.description or ()]
                if len(columns) > limits["max_columns"]:
                    raise ChatSQLValidationError(f"结果超过 {limits['max_columns']} 列；请减少所选字段")
                if len(set(columns)) != len(columns):
                    raise ChatSQLValidationError("结果列名重复；请为连接表字段添加唯一别名")
                rows = []
                size = len(json.dumps(columns, ensure_ascii=False).encode("utf-8"))
                truncated = False
                reason = None
                row = first_row
                while row is not None:
                    if len(rows) >= row_limit:
                        truncated, reason = True, "row_limit"
                        break
                    item = {name: _chat_json_value(value) for name, value in zip(columns, row)}
                    encoded_size = len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                    if size + encoded_size > limits["max_bytes"]:
                        truncated, reason = True, "byte_limit"
                        break
                    rows.append(item)
                    size += encoded_size
                    row = cursor.fetchone()
                return {
                    "ok": True,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "truncated": truncated,
                    "truncation_reason": reason,
                    "row_limit": row_limit,
                    "notice": "结果已截断，请聚合或缩小日期/字段范围；不要据此推断完整总数。" if truncated else None,
                }
    except (ChatSQLValidationError, PermissionError) as exc:
        return {"ok": False, "location": "chat_query_readonly.execute", "error": str(exc)}
    except Exception as exc:
        # Libpq connection errors can expose connection details. Only SQL server
        # diagnostics (which describe the submitted query) are observations.
        sqlstate = getattr(exc, "sqlstate", None)
        diagnostic = getattr(getattr(exc, "diag", None), "message_primary", None)
        if sqlstate == "57014":
            message = "只读SQL执行超时，请缩小日期范围或简化连接/聚合"
        elif sqlstate and diagnostic:
            message = str(diagnostic)[:800]
        else:
            message = f"ChatSQL只读数据库连接或执行未就绪（{type(exc).__name__}）"
        return {"ok": False, "location": "chat_query_readonly.execute", "error": message, "sqlstate": sqlstate}

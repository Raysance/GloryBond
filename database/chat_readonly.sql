-- Run as the database owner / PostgreSQL administrator against the HOK database.
-- Passwords are deliberately absent. Provision the password separately and keep
-- the resulting DSN in private HOK_CHAT_READONLY_DSN, never in this repository.
-- Re-running this script is safe and does not alter gameplay tables or rows.
BEGIN;

DO $reader$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'hok_chat_reader') THEN
        CREATE ROLE hok_chat_reader LOGIN;
    END IF;
END
$reader$;

ALTER ROLE hok_chat_reader WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE hok_chat_reader SET default_transaction_read_only = on;
ALTER ROLE hok_chat_reader SET statement_timeout = '5s';
ALTER ROLE hok_chat_reader SET search_path = pg_catalog, hok;
ALTER ROLE hok_chat_reader SET timezone = 'Asia/Shanghai';

DO $reader$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members m
        JOIN pg_catalog.pg_roles r ON r.oid = m.member
        WHERE r.rolname = 'hok_chat_reader'
    ) THEN
        RAISE EXCEPTION 'hok_chat_reader must not be a member of another role';
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO hok_chat_reader', current_database());
END
$reader$;

REVOKE ALL ON SCHEMA hok FROM hok_chat_reader;
GRANT USAGE ON SCHEMA hok TO hok_chat_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA hok FROM hok_chat_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA hok FROM hok_chat_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA hok FROM hok_chat_reader;

-- Column grants deliberately exclude source_path. There are no grants on the
-- private group_chat_messages archive, import manifest, future tables, public
-- tables or database system tables.
GRANT SELECT (
    snapshot_date, player_key, player_index, user_id, role_id, nickname,
    rank_name, rank_star, star, star_up, today_num, total_num, visible,
    map_count, peak_up, gaming_info, payload, updated_at
) ON hok.history_players TO hok_chat_reader;

GRANT SELECT (
    snapshot_date, player_key, player_index, detail_index, user_id, role_id,
    game_seq, game_time_label, game_time_epoch, hero_name, map_name, map_type,
    star_after_game, peak_grade_after, peak_grade_before, kill_count, death_count,
    assist_count, result, game_grade, duration_seconds, params, others, payload
) ON hok.battle_records TO hok_chat_reader;

GRANT SELECT (
    game_seq, game_type, map_name, event_time_label, start_time_label,
    duration_seconds, payload, updated_at
) ON hok.battle_details TO hok_chat_reader;

GRANT SELECT (
    game_seq, participant_index, camp, role_id, user_id, role_name, hero_id,
    hero_name, kill_count, death_count, assist_count, game_grade, gold, payload
) ON hok.battle_participants TO hok_chat_reader;

GRANT SELECT (
    snapshot_date, user_id, target_role_id, invisible, is_gaming, battle_count,
    payload, updated_at
) ON hok.personal_snapshots TO hok_chat_reader;

GRANT SELECT (
    game_seq, role_id, map_name, game_result, game_time, evaluated_at,
    my_side_level, opponent_side_level, my_side_tier, opponent_side_tier,
    payload, updated_at
) ON hok.battle_power TO hok_chat_reader;

GRANT SELECT (
    game_seq, participant_index, role_id, user_id, nickname, side, hero_name,
    hero_power, hero_win_rate, hero_average_score, single_level, payload
) ON hok.battle_power_players TO hok_chat_reader;

GRANT SELECT (snapshot_date, hero_name, score, updated_at)
    ON hok.hero_tier_scores TO hok_chat_reader;

GRANT SELECT (
    snapshot_date, rank_id, title, update_time, sort_field, sort_type,
    filter_data, payload, updated_at
) ON hok.hero_rank_snapshots TO hok_chat_reader;

GRANT SELECT (
    snapshot_date, rank_id, rank_index, hero_id, hero_name, hero_career, tier_rank,
    ban_rate, show_rate, win_rate, pick_count, ban_count, payload
) ON hok.hero_rank_entries TO hok_chat_reader;

COMMIT;

CREATE SCHEMA IF NOT EXISTS hok;

CREATE TABLE IF NOT EXISTS hok.history_players (
    snapshot_date date NOT NULL,
    player_key text NOT NULL,
    player_index integer NOT NULL DEFAULT 0,
    user_id bigint,
    role_id bigint,
    nickname text,
    rank_name text,
    rank_star integer,
    star integer,
    star_up integer,
    today_num integer,
    total_num integer,
    visible boolean,
    map_count jsonb NOT NULL DEFAULT '{}'::jsonb,
    peak_up jsonb NOT NULL DEFAULT '[]'::jsonb,
    gaming_info jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload jsonb NOT NULL,
    source_path text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, player_index)
);

CREATE INDEX IF NOT EXISTS history_players_user_date_idx
    ON hok.history_players (user_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS history_players_role_date_idx
    ON hok.history_players (role_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS history_players_date_order_idx
    ON hok.history_players (snapshot_date, player_index);
CREATE INDEX IF NOT EXISTS history_players_key_date_idx
    ON hok.history_players (player_key, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS hok.battle_records (
    snapshot_date date NOT NULL,
    player_key text NOT NULL,
    player_index integer NOT NULL,
    detail_index integer NOT NULL,
    user_id bigint,
    role_id bigint,
    game_seq bigint,
    game_time_label text,
    game_time_epoch bigint,
    hero_name text,
    map_name text,
    map_type integer,
    star_after_game integer,
    peak_grade_after integer,
    peak_grade_before integer,
    kill_count integer,
    death_count integer,
    assist_count integer,
    result text,
    game_grade numeric(8,3),
    duration_seconds integer,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    others jsonb,
    payload jsonb NOT NULL,
    PRIMARY KEY (snapshot_date, player_index, detail_index),
    FOREIGN KEY (snapshot_date, player_index)
        REFERENCES hok.history_players (snapshot_date, player_index)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS battle_records_user_date_idx
    ON hok.battle_records (user_id, snapshot_date DESC, detail_index DESC);
CREATE INDEX IF NOT EXISTS battle_records_player_date_idx
    ON hok.battle_records (player_key, snapshot_date DESC, detail_index DESC);
CREATE INDEX IF NOT EXISTS battle_records_game_seq_idx
    ON hok.battle_records (game_seq);
CREATE INDEX IF NOT EXISTS battle_records_map_date_idx
    ON hok.battle_records (map_name, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS battle_records_event_epoch_idx
    ON hok.battle_records (game_time_epoch DESC);

CREATE TABLE IF NOT EXISTS hok.battle_details (
    game_seq bigint PRIMARY KEY,
    game_type integer,
    map_name text,
    event_time_label text,
    start_time_label text,
    duration_seconds integer,
    payload jsonb NOT NULL,
    source_path text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS battle_details_map_idx
    ON hok.battle_details (map_name);

CREATE TABLE IF NOT EXISTS hok.battle_participants (
    game_seq bigint NOT NULL REFERENCES hok.battle_details (game_seq) ON DELETE CASCADE,
    participant_index integer NOT NULL,
    camp text,
    role_id bigint,
    user_id bigint,
    role_name text,
    hero_id bigint,
    hero_name text,
    kill_count integer,
    death_count integer,
    assist_count integer,
    game_grade numeric(8,3),
    gold integer,
    payload jsonb NOT NULL,
    PRIMARY KEY (game_seq, participant_index)
);

CREATE INDEX IF NOT EXISTS battle_participants_role_idx
    ON hok.battle_participants (role_id, game_seq DESC);
CREATE INDEX IF NOT EXISTS battle_participants_user_idx
    ON hok.battle_participants (user_id, game_seq DESC);
CREATE INDEX IF NOT EXISTS battle_participants_hero_idx
    ON hok.battle_participants (hero_name, game_seq DESC);

CREATE TABLE IF NOT EXISTS hok.personal_snapshots (
    snapshot_date date NOT NULL,
    user_id bigint NOT NULL,
    target_role_id bigint,
    invisible boolean,
    is_gaming boolean,
    battle_count integer,
    payload jsonb NOT NULL,
    source_path text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, user_id)
);

CREATE INDEX IF NOT EXISTS personal_snapshots_user_date_idx
    ON hok.personal_snapshots (user_id, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS hok.battle_power (
    game_seq bigint PRIMARY KEY,
    role_id bigint,
    map_name text,
    game_result text,
    game_time text,
    evaluated_at text,
    my_side_level numeric(12,3),
    opponent_side_level numeric(12,3),
    my_side_tier numeric(12,3),
    opponent_side_tier numeric(12,3),
    payload jsonb NOT NULL,
    source_path text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS battle_power_role_idx
    ON hok.battle_power (role_id, game_seq DESC);
CREATE INDEX IF NOT EXISTS battle_power_map_idx
    ON hok.battle_power (map_name);

CREATE TABLE IF NOT EXISTS hok.battle_power_players (
    game_seq bigint NOT NULL REFERENCES hok.battle_power (game_seq) ON DELETE CASCADE,
    participant_index integer NOT NULL,
    role_id bigint,
    user_id bigint,
    nickname text,
    side text,
    hero_name text,
    hero_power integer,
    hero_win_rate numeric(10,6),
    hero_average_score numeric(10,3),
    single_level numeric(12,3),
    payload jsonb NOT NULL,
    PRIMARY KEY (game_seq, participant_index)
);

CREATE INDEX IF NOT EXISTS battle_power_players_role_idx
    ON hok.battle_power_players (role_id, game_seq DESC);
CREATE INDEX IF NOT EXISTS battle_power_players_hero_idx
    ON hok.battle_power_players (hero_name, game_seq DESC);

CREATE TABLE IF NOT EXISTS hok.hero_tier_scores (
    snapshot_date date NOT NULL,
    hero_name text NOT NULL,
    score numeric(12,4) NOT NULL,
    source_path text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, hero_name)
);

CREATE INDEX IF NOT EXISTS hero_tier_scores_hero_date_idx
    ON hok.hero_tier_scores (hero_name, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS hok.hero_rank_snapshots (
    snapshot_date date NOT NULL,
    rank_id integer NOT NULL,
    title text,
    update_time text,
    sort_field text,
    sort_type text,
    filter_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload jsonb NOT NULL,
    source_path text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, rank_id)
);

CREATE INDEX IF NOT EXISTS hero_rank_snapshots_rank_date_idx
    ON hok.hero_rank_snapshots (rank_id, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS hok.hero_rank_entries (
    snapshot_date date NOT NULL,
    rank_id integer NOT NULL,
    rank_index integer NOT NULL,
    hero_id bigint,
    hero_name text,
    hero_career text,
    tier_rank text,
    ban_rate numeric(10,6),
    show_rate numeric(10,6),
    win_rate numeric(10,6),
    pick_count bigint,
    ban_count bigint,
    payload jsonb NOT NULL,
    PRIMARY KEY (snapshot_date, rank_id, rank_index),
    FOREIGN KEY (snapshot_date, rank_id)
        REFERENCES hok.hero_rank_snapshots (snapshot_date, rank_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS hero_rank_entries_hero_date_idx
    ON hok.hero_rank_entries (hero_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS hero_rank_entries_name_date_idx
    ON hok.hero_rank_entries (hero_name, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS hero_rank_entries_rank_date_idx
    ON hok.hero_rank_entries (rank_id, snapshot_date DESC, rank_index);

-- Private group-chat archive. Model SQL never receives a direct grant on this
-- table; it can only read the transaction-scoped security-barrier view below.
CREATE TABLE IF NOT EXISTS hok.group_chat_messages (
    message_order bigserial PRIMARY KEY,
    group_id text NOT NULL,
    message_id text NOT NULL,
    user_id text,
    reply_to_message_id text,
    sent_at timestamptz NOT NULL,
    source_timestamp bigint NOT NULL,
    message_text text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (group_id, message_id),
    CHECK (group_id <> ''),
    CHECK (message_id <> ''),
    CHECK (message_text <> '')
);

CREATE INDEX IF NOT EXISTS group_chat_messages_group_time_idx
    ON hok.group_chat_messages (group_id, source_timestamp DESC, message_order DESC);
CREATE INDEX IF NOT EXISTS group_chat_messages_user_time_idx
    ON hok.group_chat_messages (group_id, user_id, source_timestamp DESC, message_order DESC);
CREATE INDEX IF NOT EXISTS group_chat_messages_reply_idx
    ON hok.group_chat_messages (group_id, reply_to_message_id)
    WHERE reply_to_message_id IS NOT NULL;

-- The application sets hok.chat_group_scope inside the read-only transaction
-- to one trusted event group or "*" for a verified super_qid private request.
-- Without that setting the view returns no rows. The model SQL validator only
-- exposes this view and never the private table or payload column.
CREATE OR REPLACE VIEW hok.chat_history_messages
WITH (security_barrier = true) AS
SELECT group_id, message_id, user_id, reply_to_message_id,
       sent_at, source_timestamp, message_text
FROM hok.group_chat_messages
WHERE current_setting('hok.chat_group_scope', true) = '*'
   OR group_id = ANY(string_to_array(
       current_setting('hok.chat_group_scope', true), ','
   ));

CREATE TABLE IF NOT EXISTS hok.json_import_manifest (
    source_path text PRIMARY KEY,
    data_kind text NOT NULL,
    source_size bigint NOT NULL,
    source_mtime_ns bigint NOT NULL,
    imported_rows integer NOT NULL DEFAULT 0,
    imported_at timestamptz NOT NULL DEFAULT now()
);

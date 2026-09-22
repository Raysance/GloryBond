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

CREATE TABLE IF NOT EXISTS hok.json_import_manifest (
    source_path text PRIMARY KEY,
    data_kind text NOT NULL,
    source_size bigint NOT NULL,
    source_mtime_ns bigint NOT NULL,
    imported_rows integer NOT NULL DEFAULT 0,
    imported_at timestamptz NOT NULL DEFAULT now()
);

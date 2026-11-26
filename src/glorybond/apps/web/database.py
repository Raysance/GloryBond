"""PostgreSQL reads used by the HOK web service."""


def _connect(dsn):
    if not dsn:
        raise ValueError("HOK_DATABASE_DSN is not configured")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise RuntimeError("PostgreSQL driver is unavailable; install psycopg[binary]") from exc
    return psycopg.connect(dsn, row_factory=dict_row)


def fetch_battle(dsn, game_seq):
    with _connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM hok.battle_details WHERE game_seq = %s",
                (int(game_seq),),
            )
            row = cursor.fetchone()
            return row["payload"] if row else None


def battle_exists(dsn, game_seq):
    with _connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM hok.battle_details WHERE game_seq = %s) AS found",
                (int(game_seq),),
            )
            return bool(cursor.fetchone()["found"])


def ping(dsn):
    with _connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            return cursor.fetchone()["ok"] == 1

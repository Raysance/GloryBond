# PostgreSQL history store

`schema.sql` defines the structured query store for the existing HOK JSON archives. The JSON files under `data/history/` and `data/herotier/` remain the original, read-only migration source and runtime fallback.

Run the idempotent importer from the NBot project root:

```bash
python -m local_debugger scripts/import_json_to_postgres.py
```

Use repeated `--kind` options to limit a run to `history`, `battle`, `personal`, `power`, or `hero_tier`. The importer records source size and nanosecond mtime in `hok.json_import_manifest`, so unchanged files are skipped unless `--force` is supplied. It only reads source JSON; it never rewrites, moves, or deletes an archive.

The connection string comes from `HOK_DATABASE_DSN`, then `PostgreSQL.dsn` in `config.yaml`. Runtime reads are PostgreSQL-first with JSON fallback.

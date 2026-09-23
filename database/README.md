# PostgreSQL history store

`schema.sql` defines the structured query store for the HOK history data. The original JSON archives were used as a read-only migration source and may be removed after a complete payload verification and database backup.

Run the idempotent importer from the NBot project root:

```bash
python -m local_debugger scripts/import_json_to_postgres.py
```

Use repeated `--kind` options to limit a run to `history`, `battle`, `personal`, `power`, or `hero_tier`. The importer records source size and nanosecond mtime in `hok.json_import_manifest`, so unchanged files are skipped unless `--force` is supplied. It only reads source JSON; it never rewrites, moves, or deletes an archive.

The connection string comes from `HOK_DATABASE_DSN`, then `PostgreSQL.dsn` in `config.yaml`. With `PostgreSQL.archive_json: false`, managed history writes go directly to PostgreSQL. A JSON file is created only as an emergency fallback when the database write fails; temporary Web artifacts and non-history configuration JSON are unaffected.

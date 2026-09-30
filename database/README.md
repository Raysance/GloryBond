# PostgreSQL history store

`schema.sql` defines the structured query store for HOK game history and the private `hok.group_chat_messages` archive. The original game JSON archives were used as a read-only migration source and may be removed after a complete payload verification and database backup. Group-chat rows are not granted to the model SQL reader; they remain accessible only through the bounded chat-history interfaces.

The chat agent uses a separate least-privileged reader created by `chat_readonly.sql`. See [chat tools and runtime setup](CHAT_AGENT.md) for model-generated SQL, plotting, memory and web search.

Run the idempotent importer from the NBot project root:

```bash
python -m local_debugger scripts/import_json_to_postgres.py
```

Use repeated `--kind` options to limit a run to `history`, `battle`, `personal`, `power`, `hero_tier`, or `hero_rank`. The importer records source size and nanosecond mtime in `hok.json_import_manifest`, so unchanged files are skipped unless `--force` is supplied. It only reads source JSON; it never rewrites, moves, or deletes an archive.

The connection string comes from `HOK_DATABASE_DSN`, then `PostgreSQL.dsn` in `config.yaml`. With `PostgreSQL.archive_json: false`, managed history writes go directly to PostgreSQL. A JSON file is created only as an emergency fallback when the database write fails; temporary Web artifacts and non-history configuration JSON are unaffected.

## Group-chat history migration

New inbound group messages are written idempotently to PostgreSQL. If that write fails, the message is appended to the legacy DB0 `hok:chat:group:<群号>` list so normal routing is not interrupted. Reads merge PostgreSQL with any Redis-only records by `(group_id, message_id)`, with PostgreSQL authoritative for duplicates.

Preview the existing DB0 migration, then apply it:

```bash
python -m local_debugger scripts/migrate_group_chat_history_to_postgres.py
python -m local_debugger scripts/migrate_group_chat_history_to_postgres.py --apply \
  --backup-dir /path/to/private/backups
```

Apply mode first writes a mode-0600 Redis DUMP backup, creates the idempotent schema, upserts every valid record and compares every unique source message with PostgreSQL. It deliberately retains the Redis lists as a recoverable migration source. Re-running it is safe and imports messages written by an older process during deployment.

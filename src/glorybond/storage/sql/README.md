# PostgreSQL history store

`schema.sql` defines the structured query store for HOK game history, the private `hok.group_chat_messages` archive, and the request-scoped `hok.chat_history_messages` security-barrier view. The original game JSON archives were used as a read-only migration source and may be removed after a complete payload verification and database backup. The model SQL reader never receives a direct grant on the private archive or its payload; it can query only the scoped view after the application binds the trusted current group, or all saved groups for verified administrator private chat.

The chat agent uses a separate least-privileged reader created by `chat_readonly.sql`. See [chat tools and runtime setup](CHAT_AGENT.md) for model-generated SQL, plotting, memory and web search.

Run the idempotent importer from the NBot project root:

```bash
python -m tools.debugger tools/maintenance/import_json_to_postgres.py
```

Use repeated `--kind` options to limit a run to `history`, `battle`, `personal`, `power`, `hero_tier`, or `hero_rank`. The importer records source size and nanosecond mtime in `hok.json_import_manifest`, so unchanged files are skipped unless `--force` is supplied. It only reads source JSON; it never rewrites, moves, or deletes an archive.

The connection string comes from `HOK_DATABASE_DSN`, then `PostgreSQL.dsn` in `config.yaml`. With `PostgreSQL.archive_json: false`, managed history writes go directly to PostgreSQL. A JSON file is created only as an emergency fallback when the database write fails; temporary Web artifacts and non-history configuration JSON are unaffected.

## Group-chat history migration

New inbound group messages are written idempotently to PostgreSQL. If that write fails, the message is appended to the legacy DB0 `hok:chat:group:<群号>` list so normal routing is not interrupted. Reads merge PostgreSQL with any Redis-only records by `(group_id, message_id)`, with PostgreSQL authoritative for duplicates.

Native mentions are captured from the current event's `original_message`, including adapter-stripped bot mentions and messages with no text body. `payload.mentions` contains one snapshot per target (`user_id`, `nickname`, `group_card`, `display_name`); `user_id="all"` denotes the whole group. Names come from fresh OneBot group-member reads, with at most four concurrent lookups and a two-second total budget per message. Missing names remain null, and completed snapshots survive partial failures/timeouts. These are names available at receipt, not proof of the exact label shown on the sender's client. Quoted messages are not inspected for mentions.

For mentioned messages, `payload.plain_text` retains the stripped text body and `message_text`/`payload.text` render text and mentions in segment order, using `@name(QQ:id)` or `@全体成员`. Existing scoped text-only SQL and history readers therefore retain mention targets without granting access to the private payload or requiring a schema migration. Snapshots survive Redis fallback and later nickname changes; old records are not backfilled from current profiles.

Preview the existing DB0 migration, then apply it:

```bash
python -m tools.debugger tools/maintenance/migrate_group_chat_history_to_postgres.py
python -m tools.debugger tools/maintenance/migrate_group_chat_history_to_postgres.py --apply \
  --backup-dir /path/to/private/backups
```

Apply mode first writes a mode-0600 Redis DUMP backup, creates the idempotent schema, upserts every valid record and compares every unique source message with PostgreSQL. It deliberately retains the Redis lists as a recoverable migration source. Re-running it is safe and imports messages written by an older process during deployment.

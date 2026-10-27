"""Import immutable JSON archives into the structured PostgreSQL store."""

from __future__ import annotations

import argparse

from local_debugger import bootstrap, import_hok_module, project_root


def build_parser():
    parser = argparse.ArgumentParser(
        description="Import HOK JSON archives into PostgreSQL without modifying the source files."
    )
    parser.add_argument(
        "--kind",
        action="append",
        choices=("history", "battle", "personal", "power", "hero_tier", "hero_rank"),
        help="Import only this archive kind; repeat for multiple kinds.",
    )
    parser.add_argument("--force", action="store_true", help="Reimport files even when size and mtime match.")
    parser.add_argument("--limit", type=int, help="Stop after this many candidate files.")
    parser.add_argument("--progress-every", type=int, default=100, help="Print progress every N imported files.")
    return parser


def main():
    args = build_parser().parse_args()
    bootstrap()
    zfile = import_hok_module("zfile")
    zdb = import_hok_module("zdb")

    schema_path = project_root() / "database" / "schema.sql"
    schema_sql = zfile.readera(str(schema_path))
    zdb.execute_schema(schema_sql)

    entries = zfile.list_postgres_archive_files(args.kind)
    if args.limit is not None:
        entries = entries[: max(args.limit, 0)]

    imported = 0
    skipped = 0
    failed = 0
    row_totals = {}
    for filepath, descriptor in entries:
        metadata = zfile.postgres_archive_metadata(filepath)
        source_path = descriptor["source_path"]
        try:
            if not args.force and zdb.manifest_matches(
                source_path, metadata["size"], metadata["mtime_ns"]
            ):
                skipped += 1
                continue
            payload = zfile.readerl(filepath)
            result = zdb.import_archive_payload(descriptor, payload)
            imported_rows = sum(int(value or 0) for value in result.values())
            zdb.update_manifest(
                source_path,
                descriptor["kind"],
                metadata["size"],
                metadata["mtime_ns"],
                imported_rows,
            )
            for key, value in result.items():
                row_totals[key] = row_totals.get(key, 0) + int(value or 0)
            imported += 1
            if args.progress_every > 0 and imported % args.progress_every == 0:
                print(f"progress imported={imported} skipped={skipped} failed={failed} source={source_path}")
        except Exception as exc:
            failed += 1
            print(
                f"import_error kind={descriptor['kind']} source={source_path} "
                f"error={repr(exc)}"
            )

    print(
        f"complete candidates={len(entries)} imported={imported} skipped={skipped} "
        f"failed={failed} rows={row_totals}"
    )
    print(f"database_counts={zdb.table_counts()}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Convert already-saved client matches to ordinary battle-detail storage; no game API calls."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_debugger import import_hok_module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--apply", action="store_true", help="Save converted details; otherwise only count saved matches")
    args = parser.parse_args()
    result = import_hok_module("zfunc").backfill_player_client_battle_details(
        start_date=args.start_date, end_date=args.end_date, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

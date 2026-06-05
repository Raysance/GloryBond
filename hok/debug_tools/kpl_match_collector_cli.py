"""CLI debug wrapper for qbot.tools.kpl_match_collector."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, List


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[3]
DEFAULT_NOW = datetime.datetime.now().replace(microsecond=0)
DEFAULT_DATE = DEFAULT_NOW.date().isoformat()
DEFAULT_TIME_MS = int(DEFAULT_NOW.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
DEFAULT_RUN_CONFIG = {
    "command": "",
    "mid": 214,
    "time_ms": DEFAULT_TIME_MS,
    "date": DEFAULT_DATE,
    "now": DEFAULT_NOW.isoformat(),
    "pn": 1,
    "ps": 50,
    "tz_name": "Asia/Shanghai",
    "cid": 34917,
    "format": "text",
    "include_raw": False,
}
INTERACTIVE_COMMANDS = [
    ("fetch-schedule", "获取指定日期赛程列表"),
    ("full-match-list", "获取完整赛程并按状态分组"),
    ("fetch-match-grade", "获取单场评分原始适配结果"),
    ("match-content", "获取单场内容"),
    ("series-summary", "获取系列赛摘要"),
    ("current-map-detail", "获取当前小局详情"),
]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def install_qbot_namespace():
    """Install qbot namespace packages without executing qbot plugin entry."""
    packages = {
        "src": REPO_ROOT / "src",
        "src.plugins": REPO_ROOT / "src" / "plugins",
        "src.plugins.qbot": REPO_ROOT / "src" / "plugins" / "qbot",
        "src.plugins.qbot.tools": REPO_ROOT / "src" / "plugins" / "qbot" / "tools",
    }
    for name, path in packages.items():
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            module.__package__ = name
            sys.modules[name] = module


def load_collector():
    """Load kpl_match_collector through the qbot namespace."""
    install_qbot_namespace()
    from src.plugins.qbot.tools import kpl_match_collector

    return kpl_match_collector


def parse_now(value: str) -> datetime.datetime:
    """Parse CLI datetime input."""
    if not value:
        return datetime.datetime.now()
    return datetime.datetime.fromisoformat(value)


def parse_time_ms(value: str, date_value: str) -> int:
    """Parse schedule time argument as epoch milliseconds."""
    if value:
        return int(value)
    if date_value:
        day = datetime.datetime.fromisoformat(date_value)
    else:
        day = datetime.datetime.now()
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def strip_raw(value: Any) -> Any:
    """Drop raw response branches for readable CLI output."""
    if isinstance(value, dict):
        return {k: strip_raw(v) for k, v in value.items() if k != "raw"}
    if isinstance(value, list):
        return [strip_raw(v) for v in value]
    return value


def team_name(value: Dict[str, Any], key: str) -> str:
    """Get a team display name from normalized schedule data."""
    team = value.get(key) or {}
    return str(team.get("name") or "-")


def score_text(value: Dict[str, Any]) -> str:
    """Format a score object."""
    score = value.get("score") or {}
    home = score.get("home")
    away = score.get("away")
    if home is None and away is None:
        return "-"
    return f"{home if home is not None else '-'}-{away if away is not None else '-'}"


def print_table(headers: List[str], rows: List[List[Any]]):
    """Print a width-aligned text table."""
    rendered = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rendered:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    header_line = "  ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers)))
    sep_line = "  ".join("-" * widths[idx] for idx in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rendered:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def print_json(value: Any, *, include_raw: bool):
    """Print JSON with Chinese text preserved."""
    out = value if include_raw else strip_raw(value)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


def print_schedule_text(result: Dict[str, Any]):
    """Print schedule items as a compact table."""
    rows = []
    for item in result.get("items") or []:
        rows.append(
            [
                item.get("contest_id") or "-",
                item.get("start_time_iso") or "-",
                item.get("game_stage") or item.get("title") or "-",
                team_name(item, "home_team"),
                score_text(item),
                team_name(item, "away_team"),
            ]
        )
    print_table(["cid", "start", "stage", "home", "score", "away"], rows)


def print_full_list_text(result: Dict[str, Any]):
    """Print grouped match list as readable tables."""
    counts = result.get("counts") or {}
    print(f"mid={result.get('mid')} time={result.get('time')} total={counts.get('total')} finished={counts.get('finished')} ongoing={counts.get('ongoing')} upcoming={counts.get('upcoming')}")
    for group in ["ongoing", "upcoming", "finished"]:
        items = (result.get("groups") or {}).get(group) or []
        print()
        print(f"[{group}] {len(items)}")
        rows = []
        for item in items:
            rows.append(
                [
                    item.get("cid") or "-",
                    datetime.datetime.fromtimestamp(item.get("stime")).strftime("%Y-%m-%d %H:%M:%S") if item.get("stime") else "-",
                    item.get("game_stage") or item.get("title") or "-",
                    team_name(item, "home"),
                    score_text(item),
                    team_name(item, "away"),
                ]
            )
        print_table(["cid", "start", "stage", "home", "score", "away"], rows)


def print_match_text(result: Dict[str, Any]):
    """Print match content as summary and player table."""
    print(f"cid={result.get('cid')} name={result.get('match_name') or '-'}")
    print(f"stage={result.get('game_stage') or '-'} current_bo={result.get('current_bo') or '-'} bo_status={result.get('bo_status') or '-'} score={score_text(result)}")
    print(f"start={result.get('start_time_iso') or '-'}")
    print(f"end={result.get('end_time_iso') or '-'}")
    rows = []
    for player in result.get("players") or []:
        kda = player.get("kda") or {}
        hero = player.get("hero") or {}
        rows.append(
            [
                player.get("team_name") or "-",
                player.get("position") or "-",
                player.get("player_name") or "-",
                player.get("avg_grade") or "-",
                f"{kda.get('kill', '-')}/{kda.get('death', '-')}/{kda.get('assist', '-')}",
                hero.get("hero_id") or "-",
                str(player.get("hot_comment") or "").replace("\n", " ")[:80],
            ]
        )
    if rows:
        print()
        print_table(["team", "pos", "player", "grade", "kda", "hero", "hot_comment"], rows)
    global_rows = []
    for player in result.get("global_players") or []:
        global_rows.append([player.get("side") or "-", player.get("position") or "-", player.get("player_name") or "-", player.get("avg_grade") or "-"])
    if global_rows:
        print()
        print_table(["side", "pos", "player", "grade"], global_rows)


def print_series_text(result: Dict[str, Any]):
    """Print series summary by team."""
    print(f"cid={result.get('cid')} name={result.get('match_name') or '-'} stage={result.get('game_stage') or '-'}")
    print(f"start={result.get('start_time_iso') or '-'}")
    print(f"end={result.get('end_time_iso') or '-'}")
    rows = []
    for team in result.get("teams") or []:
        players = []
        for player in team.get("players") or []:
            players.append(f"{player.get('pos') or '-'}:{player.get('name') or '-'}({player.get('score') or '-'})")
        rows.append([team.get("name") or "-", team.get("score") or "-", "  ".join(players)])
    if rows:
        print()
        print_table(["team", "score", "players"], rows)


def print_current_map_text(result: Dict[str, Any]):
    """Print current map detail."""
    print(f"cid={result.get('cid')} current_bo={result.get('current_bo') or '-'} bo_status={result.get('bo_status') or '-'} score={score_text(result)}")
    rows = []
    for player in result.get("players") or []:
        kda = player.get("kda") or {}
        hero = player.get("hero") or {}
        rows.append(
            [
                player.get("team_name") or "-",
                player.get("position") or "-",
                player.get("player_name") or "-",
                player.get("avg_grade") or "-",
                f"{kda.get('kill', '-')}/{kda.get('death', '-')}/{kda.get('assist', '-')}",
                hero.get("hero_id") or "-",
                str(player.get("hot_comment") or "").replace("\n", " ")[:80],
            ]
        )
    if rows:
        print()
        print_table(["team", "pos", "player", "grade", "kda", "hero", "hot_comment"], rows)


def output_result(command: str, result: Dict[str, Any], *, output_format: str, include_raw: bool):
    """Format and print command output."""
    if output_format == "json":
        print_json(result, include_raw=include_raw)
        return
    if command == "fetch-schedule":
        print_schedule_text(result)
    elif command == "full-match-list":
        print_full_list_text(result)
    elif command in {"fetch-match-grade", "match-content"}:
        print_match_text(result)
    elif command == "series-summary":
        print_series_text(result)
    elif command == "current-map-detail":
        print_current_map_text(result)
    else:
        print_json(result, include_raw=include_raw)


def add_common_args(parser: argparse.ArgumentParser):
    """Add output arguments shared by all subcommands."""
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--include-raw", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    """Build the kpl_match_collector debug CLI parser."""
    collector = load_collector()
    config = DEFAULT_RUN_CONFIG
    parser = argparse.ArgumentParser(description="Debug CLI for qbot.tools.kpl_match_collector")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_schedule = sub.add_parser("fetch-schedule", help="Call fetch_schedule")
    fetch_schedule.add_argument("--mid", type=int, default=config["mid"])
    fetch_schedule.add_argument("--time-ms", default=str(config["time_ms"]))
    fetch_schedule.add_argument("--date", default=str(config["date"]))
    fetch_schedule.add_argument("--pn", type=int, default=config["pn"])
    fetch_schedule.add_argument("--ps", type=int, default=config["ps"])
    add_common_args(fetch_schedule)

    fetch_grade = sub.add_parser("fetch-match-grade", help="Call fetch_match_grade")
    fetch_grade.add_argument("--cid", type=int, default=config["cid"])
    add_common_args(fetch_grade)

    full_list = sub.add_parser("full-match-list", help="Call get_full_match_list")
    full_list.add_argument("--mid", type=int, default=config["mid"])
    full_list.add_argument("--time-ms", default=str(config["time_ms"]))
    full_list.add_argument("--date", default=str(config["date"]))
    full_list.add_argument("--now", default=str(config["now"]))
    full_list.add_argument("--ps", type=int, default=config["ps"])
    full_list.add_argument("--tz-name", default=config["tz_name"])
    add_common_args(full_list)

    match_content = sub.add_parser("match-content", help="Call get_match_content")
    match_content.add_argument("--cid", type=int, default=config["cid"])
    add_common_args(match_content)

    series_summary = sub.add_parser("series-summary", help="Call get_series_summary")
    series_summary.add_argument("--cid", type=int, default=config["cid"])
    add_common_args(series_summary)

    current_map = sub.add_parser("current-map-detail", help="Call get_current_map_detail")
    current_map.add_argument("--cid", type=int, default=config["cid"])
    add_common_args(current_map)

    return parser


def build_internal_argv() -> List[str]:
    """Build CLI argv from script-level defaults."""
    config = DEFAULT_RUN_CONFIG
    command = str(config["command"] or "full-match-list")
    argv = [command]
    if command in {"fetch-schedule", "full-match-list"}:
        argv.extend(["--mid", str(config["mid"])])
        argv.extend(["--ps", str(config["ps"])])
        if config["time_ms"]:
            argv.extend(["--time-ms", str(config["time_ms"])])
        if config["date"]:
            argv.extend(["--date", str(config["date"])])
    if command == "fetch-schedule":
        argv.extend(["--pn", str(config["pn"])])
    if command == "full-match-list":
        if config["now"]:
            argv.extend(["--now", str(config["now"])])
        argv.extend(["--tz-name", str(config["tz_name"])])
    if command in {"fetch-match-grade", "match-content", "series-summary", "current-map-detail"}:
        argv.extend(["--cid", str(config["cid"])])
    argv.extend(["--format", str(config["format"])])
    if config["include_raw"]:
        argv.append("--include-raw")
    return argv


def read_value(prompt: str, default: Any) -> str:
    """Read an interactive value with a default."""
    value = input(f"{prompt} [{default}]: ").strip()
    return value if value else str(default)


def read_bool(prompt: str, default: bool) -> bool:
    """Read an interactive boolean value with a default."""
    label = "y" if default else "n"
    value = input(f"{prompt} [{label}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true", "t"}


def build_interactive_argv(command: str) -> List[str]:
    """Build argv for one interactive command invocation."""
    config = DEFAULT_RUN_CONFIG
    argv = [command]
    if command in {"fetch-schedule", "full-match-list"}:
        argv.extend(["--mid", read_value("mid", config["mid"])])
        argv.extend(["--ps", read_value("ps", config["ps"])])
        time_ms = read_value("time-ms", config["time_ms"])
        date = read_value("date", config["date"])
        if time_ms:
            argv.extend(["--time-ms", time_ms])
        elif date:
            argv.extend(["--date", date])
    if command == "fetch-schedule":
        argv.extend(["--pn", read_value("pn", config["pn"])])
    if command == "full-match-list":
        now = read_value("now", config["now"])
        if now:
            argv.extend(["--now", now])
        argv.extend(["--tz-name", read_value("tz-name", config["tz_name"])])
    if command in {"fetch-match-grade", "match-content", "series-summary", "current-map-detail"}:
        argv.extend(["--cid", read_value("cid", config["cid"])])
    argv.extend(["--format", read_value("format", config["format"])])
    if read_bool("include-raw", bool(config["include_raw"])):
        argv.append("--include-raw")
    return argv


def choose_interactive_command() -> str:
    """Choose one collector function from the interactive menu."""
    print()
    print("KPL match collector debug menu")
    for idx, item in enumerate(INTERACTIVE_COMMANDS, 1):
        print(f"{idx}. {item[0]} - {item[1]}")
    print("q. 退出")
    choice = input("请选择要调用的函数: ").strip().lower()
    if choice in {"q", "quit", "exit"}:
        return ""
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(INTERACTIVE_COMMANDS):
            return INTERACTIVE_COMMANDS[idx - 1][0]
    names = {item[0] for item in INTERACTIVE_COMMANDS}
    if choice in names:
        return choice
    print(f"kpl_debug_cli_error: unsupported selection {choice}")
    return "__invalid__"


def interactive_main(parser: argparse.ArgumentParser):
    """Run an interactive loop that repeatedly calls collector functions."""
    while True:
        command = choose_interactive_command()
        if not command:
            return
        if command == "__invalid__":
            continue
        args = parser.parse_args(build_interactive_argv(command))
        result = run(args)
        output_result(args.command, result, output_format=args.format, include_raw=args.include_raw)


def run(args: argparse.Namespace) -> Dict[str, Any]:
    """Call the selected kpl_match_collector function."""
    collector = load_collector()
    if args.command == "fetch-schedule":
        client = collector.BiliClient.create()
        time_ms = parse_time_ms(args.time_ms, args.date)
        return collector.fetch_schedule(client, mid=args.mid, time_ms=time_ms, pn=args.pn, ps=args.ps)
    if args.command == "fetch-match-grade":
        client = collector.BiliClient.create()
        return collector.fetch_match_grade(client, cid=args.cid)
    if args.command == "full-match-list":
        time_ms = parse_time_ms(args.time_ms, args.date)
        return collector.get_full_match_list(mid=args.mid, time_ms=time_ms, now=parse_now(args.now), ps=args.ps, tz_name=args.tz_name)
    if args.command == "match-content":
        return collector.get_match_content({"cid": args.cid})
    if args.command == "series-summary":
        return collector.get_series_summary({"cid": args.cid})
    if args.command == "current-map-detail":
        return collector.get_current_map_detail({"cid": args.cid})
    raise Exception(f"kpl_debug_cli_error: unsupported command {args.command}")


def main():
    """Parse CLI args, call collector, and print formatted output."""
    parser = build_parser()
    if len(sys.argv) == 1 and not DEFAULT_RUN_CONFIG["command"]:
        interactive_main(parser)
        return
    parse_args = sys.argv[1:] if len(sys.argv) > 1 else build_internal_argv()
    args = parser.parse_args(parse_args)
    result = run(args)
    output_result(args.command, result, output_format=args.format, include_raw=args.include_raw)


if __name__ == "__main__":
    main()

import json
import os
import hashlib
import importlib.util


def _load_gen_gametime_table():
    here = os.path.dirname(__file__)
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", "..", ".."))
    mod_path = os.path.join(repo_root, "src", "plugins", "qbot", "tools", "gen_gametime_table.py")
    spec = importlib.util.spec_from_file_location("gen_gametime_table", mod_path)
    if spec is None or spec.loader is None:
        raise Exception(f"load_tool_failed: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    here = os.path.dirname(__file__)
    data = json.load(open(os.path.join(here, "sample_gametime.json"), "r", encoding="utf-8"))
    gen_gametime_table = _load_gen_gametime_table()

    players = data.get("players") or []
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", "..", ".."))
    vs = json.load(open(os.path.join(repo_root, "variables_static.json"), "r", encoding="utf-8"))
    sameuser = vs.get("sameuser") or {}
    alias_to_main = {}
    main_to_aliases = {}
    for main, aliases in sameuser.items():
        if not isinstance(aliases, list):
            continue
        main_to_aliases[main] = list(aliases)
        for a in aliases:
            alias_to_main[a] = main

    merged = {}
    games = set()
    for p in players:
        name = p.get("player", "")
        gmap = p.get("games") or {}
        main = alias_to_main.get(name, name)
        if main not in merged:
            merged[main] = {"player": main, "subs": [], "total": 0.0, "games": {}}
        for g, v in gmap.items():
            merged[main]["games"][g] = merged[main]["games"].get(g, 0.0) + float(v or 0)
            games.add(g)
        merged[main]["total"] += sum(float(v or 0) for v in gmap.values())

    rows = []
    for main, item in merged.items():
        aliases = main_to_aliases.get(main, [])
        item["subs"] = [a for a in aliases if a != main]
        rows.append(item)

    rows = sorted(rows, key=lambda x: x.get("total", 0), reverse=True)
    sums = {}
    for r in rows:
        gmap = r.get("games") or {}
        for g, v in gmap.items():
            sums[g] = sums.get(g, 0) + float(v or 0)

    games_other = [g for g in games if g != "王者荣耀"]
    games_other.sort(key=lambda g: sums.get(g, 0), reverse=True)
    game_list = (["王者荣耀"] if "王者荣耀" in games else []) + games_other

    ts = str(round(os.times().elapsed * 1000000))
    filename_hashed = hashlib.sha256(ts.encode()).hexdigest()[:16]
    out_dir = os.path.join(here, "out")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"gametime_rank_demo_{filename_hashed}.png")

    title = f"最近{data.get('days', 14)}天游戏时长排行(离线示例)"
    gen_gametime_table.gen(rows, game_list, out_path, title=title)
    print(out_path)


if __name__ == "__main__":
    main()

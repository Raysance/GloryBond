"""Sync tracked source snapshots into the public showcase without runtime data."""
import argparse
import ast
import json
from pathlib import Path
import re
import subprocess

from dotenv import dotenv_values
import yaml


ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def files(root):
    return {value.decode() for value in git(root, "ls-files", "-z").split(b"\0") if value}


def redact_samples(value):
    if isinstance(value, dict):
        return {key: redact_samples(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_samples(item) for item in value]
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0
    return "" if isinstance(value, str) else None


def private_values(nbot):
    config = yaml.safe_load((nbot / "config.yaml").read_text())
    secrets = [str(v) for k, v in dotenv_values(nbot / ".env").items()
               if v and re.search(r"KEY|TOKEN|PASSWORD|SECRET|DSN", k) and len(str(v)) >= 8]
    identities = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                collect(key)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif str(value).isdigit() and len(str(value)) >= 8:
            identities.add(str(value))

    for name in ("qid", "userlist", "roleidlist", "extra_useridlist", "extra_roleidlist", "steam_userlist"):
        collect(config.get("StaticVariables", {}).get(name, {}))
    for name in ("bot_qid", "group_qid", "super_qid"):
        collect(config.get("QQBot", {}).get(name))
    collect(config.get("QQAgent", {}).get("admin_private_default_group_id"))
    return secrets, sorted(identities)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nbot", type=Path, required=True)
    parser.add_argument("--web", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sources = {"NBot": args.nbot.resolve(), "Web": args.web.resolve()}
    if git(ROOT, "status", "--porcelain", "--", "NBot", "Web").strip():
        raise ValueError("Mirror directories have local changes; commit or inspect before syncing")
    existing = files(ROOT)
    secrets, identities = private_values(sources["NBot"])
    replacements = {value: str(2000000000 + i) for i, value in enumerate(identities)}
    selected = {}
    for prefix, source in sources.items():
        for relative in sorted(files(source)):
            path = Path(relative)
            if prefix == "NBot":
                allowed = path.parts[0] in {"hok", "agent_console", "qq_agent", "shared", "resources", "tests", "database", "scripts", "local_debugger", "examples"}
                allowed |= relative in {"AGENTS.md", ".gitignore", "pyproject.toml", "agent_runtime", "data/honor/districts.json"}
            else:
                allowed = path.parts[0] in {"templates", "tools", "tests", "docs", "default_json_templates"} or path.suffix == ".py" or relative in {"AGENTS.md", ".gitignore", "requirements.txt"}
            if not allowed or ".DS_Store" in path.parts or any(part.startswith(".env") for part in path.parts):
                continue
            origin, target = source / path, f"{prefix}/{relative}"
            if origin.is_symlink():
                if relative != "agent_runtime" or origin.readlink() != Path("vendor/react-agent-runtime/src/agent_runtime"):
                    raise ValueError("Unexpected source symlink: " + target)
                selected[target] = ("symlink", str(origin.readlink()).encode())
                continue
            raw = origin.read_bytes()
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeError:
                if target in existing:
                    selected[target] = ("binary", raw)
                continue
            if relative.startswith(("resources/wzry_data_format/", "default_json_templates/")) and path.suffix == ".json" and content.strip():
                content = json.dumps(redact_samples(json.loads(content)), ensure_ascii=False, indent=2) + "\n"
            for value, substitute in replacements.items():
                content = re.sub(r"(?<!\d)" + re.escape(value) + r"(?!\d)",
                                 "[部署配置中的身份ID]" if path.suffix == ".md" else substitute, content)
            if path.suffix == ".py":
                for secret in secrets:
                    content = content.replace(json.dumps(secret), '""').replace(repr(secret), '""')
            if any(secret in content for secret in secrets):
                raise ValueError("Configured credential appears in source: " + target)
            if relative == "AGENTS.md" and prefix == "NBot":
                content = content.replace("本仓库为私有仓库，该文件允许提交 Git", "本目录为公开镜像，密钥文件禁止提交 Git")
                content = "<!-- Public mirror: root publication rules override private deployment notes. -->\n" + content
            if relative == "pyproject.toml":
                content = content.replace('readme = "deployment/README.md"', 'readme = "agent_console/README.md"')
            if path.suffix == ".py":
                normalized = "\n".join(line.rstrip() for line in content.splitlines()).rstrip() + "\n"
                if ast.dump(ast.parse(normalized)) == ast.dump(ast.parse(content)):
                    content = normalized
            selected[target] = ("text", content.encode())
    stale = sorted(path for path in existing if path.startswith(("NBot/", "Web/")) and path not in selected)
    revision = git(sources["NBot"], "rev-parse", "HEAD:vendor/react-agent-runtime").decode().strip()
    print(json.dumps({"selected_files": len(selected), "removed_stale_files": len(stale),
                      "identity_values_anonymized": len(identities), "private_core_included": False}))
    if not args.apply:
        return
    for relative in stale:
        path = ROOT / relative
        if path.is_file() or path.is_symlink():
            path.unlink()
    for relative, (kind, raw) in selected.items():
        target = ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        if kind == "symlink":
            target.symlink_to(raw.decode())
        else:
            target.write_bytes(raw)
    (ROOT / ".gitmodules").write_text('[submodule "NBot/vendor/react-agent-runtime"]\n\tpath = NBot/vendor/react-agent-runtime\n\turl = git@github.com:Raysance/react-agent-runtime.git\n')
    (ROOT / "NBot/vendor/react-agent-runtime").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(ROOT), "update-index", "--add", "--cacheinfo", "160000," + revision + ",NBot/vendor/react-agent-runtime"], check=True)
    release = "# Public source snapshot\n\n" + "\n".join(f"- {name}: `{git(source, 'rev-parse', 'HEAD').decode().strip()}`" for name, source in sources.items())
    release += f"\n- Agent runtime: `{revision}` (private dependency; source not exported).\n\n"
    release += "Configuration, credentials, runtime records, private deployments and new binary assets are excluded. Identity literals are anonymized; sample payloads preserve structure with empty/zero values. Public demonstration assets already in this repository are retained.\n"
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs/RELEASE.md").write_text(release)


if __name__ == "__main__":
    main()

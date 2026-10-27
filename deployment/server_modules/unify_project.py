#!/usr/bin/env python3
"""Migrate Aliyun's two HOK checkouts into one project, with private rollback files."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess


class Migration:
    def __init__(self, module, revision="origin/main"):
        self.module = Path(module).resolve()
        self.old = self.module / "apps/NBot"
        self.legacy_web = self.module / "apps/Web"
        self.project = self.module / "apps/HOK_QQBot"
        self.revision = revision
        self.saved = []
        self.directory = None
        self.original_revision = None

    def run(self, *args, cwd=None):
        environment = dict(os.environ)
        if cwd is not None and Path(cwd) in (self.old, self.project):
            environment.update(self.application_environment(Path(cwd)))
        result = subprocess.run(args, cwd=cwd, env=environment, capture_output=True)
        if self.directory:
            with (self.directory / "operations.log").open("ab") as output:
                output.write(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"Migration operation failed: {Path(args[0]).name}; see private operations.log")
        return result.stdout.decode().strip()

    def application_environment(self, root):
        return {"BOT_PATH": str(root), "WEB_PATH": str(root / "web"),
                "HOK_ENV_FILE": str(root / ".env"), "HOK_CONFIG_FILE": str(root / "config.yaml"),
                "HOK_DATA_DIR": str(root / "data"),
                "HOK_FILE_TRANSFER_DIR": str(self.module / "data/file_transfer"),
                "HOK_LOG_DIR": str(self.module / "logs/nbot"),
                "HOK_NAPCAT_ROOT": str(self.module / "apps/napcat")}

    def consolidate_credentials(self):
        from dotenv import dotenv_values, set_key

        destination = self.old / ".env"
        current = dotenv_values(destination, interpolate=False)
        legacy = dotenv_values(self.module / "config/nbot-host.env", interpolate=False)
        name = "HOK_CHAT_READONLY_DSN"
        if not current.get(name):
            if not legacy.get(name):
                raise ValueError("Independent read-only database credentials must be configured before cutover")
            set_key(destination, name, legacy[name], quote_mode="always")
            destination.chmod(0o600)

    def save(self, path):
        path = Path(path)
        entry = {"path": str(path), "exists": path.exists() or path.is_symlink()}
        if path.is_symlink():
            entry["link"] = str(path.readlink())
        elif path.exists():
            entry["backup"] = str(self.directory / f"saved-{len(self.saved)}")
            shutil.copy2(path, entry["backup"])
            entry["mode"] = path.stat().st_mode & 0o777
        self.saved.append(entry)
        (self.directory / "saved-files.json").write_text(json.dumps(self.saved, indent=2))

    def preflight(self):
        if self.project.exists():
            raise ValueError("Unified project already exists; use its normal deployment workflow")
        for repository in (self.old, self.legacy_web):
            if not (repository / ".git").is_dir():
                raise ValueError("Both original Git checkouts must exist before migration")
            changed = set(self.run("git", "diff", "--name-only", "HEAD", cwd=repository).splitlines())
            if changed - ({".env"} if repository == self.old else set()):
                raise ValueError("Tracked server source changes must be reconciled before migration")
        for path in (self.module / "data/nbot", self.module / "config/nbot.env", self.module / "config/config.yaml"):
            if path.exists() and not path.is_symlink():
                raise ValueError(f"Expected an index symlink: {path}")
        return {"project": str(self.project), "web": str(self.project / "web"),
                "services": ["hok-nbot.service", "hok-web.service"], "revision": self.revision}

    def unit(self, filename):
        source = self.project / "deployment/systemd" / (filename + ".in")
        values = {"NBOT_ROOT": self.project, "WEB_ROOT": self.project / "web",
                  "STATE_DIR": self.project, "FILE_TRANSFER_DIR": self.module / "data/file_transfer",
                  "LOG_DIR": self.module / "logs", "RUN_USER": "root", "RUN_GROUP": "root"}
        text = source.read_text()
        for name, value in values.items():
            text = text.replace("@" + name + "@", str(value))
        text = text.replace("[Unit]\n", "[Unit]\nPartOf=hok.target\n", 1)
        text = text.replace("[Service]\n", "[Service]\nEnvironment=HOK_NAPCAT_ROOT=" + str(self.module / "apps/napcat") + "\n", 1)
        if "@" in text:
            raise ValueError("Unresolved service template placeholder")
        return text

    def rebase_environment(self, before, after):
        root = after / ".venv"
        for path in (root / "bin").iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as stream:
                prefix = stream.read(512)
            if prefix.startswith(b"#!") and str(before).encode() in prefix:
                path.write_bytes(path.read_bytes().replace(str(before).encode(), str(after).encode()))
        config = root / "pyvenv.cfg"
        if config.exists():
            config.write_text(config.read_text().replace(str(before), str(after)))

    def apply(self):
        self.preflight()
        self.run("git", "fetch", "origin", "main", cwd=self.old)
        self.revision = self.run("git", "rev-parse", self.revision, cwd=self.old)
        self.run("git", "cat-file", "-e", self.revision + ":web/__main__.py", cwd=self.old)
        self.original_revision = self.run("git", "rev-parse", "HEAD", cwd=self.old)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.directory = self.module / "backups" / ("unified-project-" + stamp)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        shutil.copy2(self.old / ".env", self.directory / "credentials.env")
        (self.directory / "credentials.env").chmod(0o600)
        shutil.copy2(self.old / "deployment/scripts/restore_application.sh", self.directory / "restore.sh")
        for name, repository in (("bot", self.old), ("web", self.legacy_web)):
            self.run("git", "bundle", "create", str(self.directory / (name + ".bundle")), "--all", cwd=repository)
        print("Private Git and credential backups prepared", flush=True)
        (self.directory / "state.json").write_text(json.dumps({"original_revision": self.original_revision,
            "revision": self.revision, "project": str(self.project), "complete": False}, indent=2))
        self.run("systemctl", "stop", "hok-nbot.service", "hok-web.service")
        try:
            self.consolidate_credentials()
            self.old.rename(self.project)
            self.run("bash", str(self.directory / "restore.sh"), str(self.project), self.revision)
            self.legacy_web.rename(self.directory / "legacy-web")
            self.rebase_environment(self.old, self.project)
            print("Project moved; installing the shared Python environment", flush=True)
            self.run(str(self.project / ".venv/bin/python"), "-m", "pip", "install", "--no-build-isolation",
                     "--editable", str(self.project), cwd=self.project)
            self.run(str(self.project / ".venv/bin/python"), "-c", "import web.app; from qq_agent import QQAgentService", cwd=self.project)
            print("Shared Python imports verified; updating service paths", flush=True)
            (self.module / "config").rename(self.directory / "legacy-config")
            (self.module / "config").mkdir(mode=0o700)
            for name in (".env", "config.yaml"):
                (self.module / "config" / name).symlink_to(self.project / name)
            index = self.module / "data/nbot"
            self.save(index)
            index.unlink(missing_ok=True)
            index.symlink_to(self.project / "data")
            for name in ("hok-nbot.service", "hok-web.service"):
                path = self.module / "systemd" / name
                self.save(path)
                path.write_text(self.unit(name))
                self.run("systemd-analyze", "verify", str(path))
            manifest = self.module / "module.json"
            self.save(manifest)
            body = json.loads(manifest.read_text())
            body["project"] = {"directory": "apps/HOK_QQBot", "web_directory": "web",
                               "repository": "git@github.com:Raysance-Studio/HOK_QQBot.git"}
            manifest.write_text(json.dumps(body, indent=2) + "\n")
            source = self.project / "deployment/server_modules"
            for directory in (self.module.parent / "bin", self.module / "ops"):
                for filename in ("modulectl.py", "snapshot_hok.py", "verify_export.py"):
                    target = directory / filename
                    self.save(target)
                    shutil.copy2(source / filename, target)
            for directory in (self.module, self.module.parent / "bin"):
                for filename in ("README.md", "UNIFIED_PROJECT.md"):
                    target = directory / filename
                    self.save(target)
                    shutil.copy2(source / filename, target)
            self.run("systemctl", "daemon-reload")
            self.run("systemctl", "start", "hok-nbot.service", "hok-web.service")
            print("Bot and Web started; checking readiness", flush=True)
            self.run(str(self.project / ".venv/bin/python"), "deployment/scripts/verify_startup.py", cwd=self.project)
            (self.directory / "complete").touch()
            state_path = self.directory / "state.json"
            state = json.loads(state_path.read_text())
            state["complete"] = True
            state_path.write_text(json.dumps(state, indent=2))
            print("Unified project is ready; private rollback directory: " + str(self.directory))
        except BaseException:
            self.rollback()
            raise

    def rollback(self):
        self.run("systemctl", "stop", "hok-nbot.service", "hok-web.service")
        for entry in reversed(self.saved):
            path = Path(entry["path"])
            path.unlink(missing_ok=True)
            if "link" in entry:
                path.symlink_to(entry["link"])
            elif entry.get("backup"):
                shutil.copy2(entry["backup"], path)
        if (self.directory / "legacy-config").exists():
            shutil.rmtree(self.module / "config")
            (self.directory / "legacy-config").rename(self.module / "config")
        if (self.directory / "legacy-web").exists():
            (self.directory / "legacy-web").rename(self.legacy_web)
        if self.project.exists():
            self.project.rename(self.old)
            self.rebase_environment(self.project, self.old)
            self.run("bash", str(self.directory / "restore.sh"), str(self.old), self.original_revision)
            self.run(str(self.old / ".venv/bin/python"), "-m", "pip", "install", "--no-build-isolation", "--no-deps", "--editable", str(self.old), cwd=self.old)
        self.run("systemctl", "daemon-reload")
        self.run("systemctl", "start", "hok-nbot.service", "hok-web.service")
        print("Migration rolled back; original application services restarted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root", type=Path, default=Path("/srv/modules/hok"))
    parser.add_argument("--revision", default="origin/main")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    migration = Migration(args.module_root, args.revision)
    if args.apply:
        if os.geteuid() != 0:
            raise SystemExit("Run the cutover as root")
        migration.apply()
    else:
        print(json.dumps(migration.preflight(), indent=2))

#!/usr/bin/env python3
"""Control and privately export one manifest-defined server module."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone


MODULES = ("hok", "personal-site", "clash")
EXCLUDE_NAMES = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
# Only dependencies with a known source/lockfile rebuild path may be dropped.
# NapCat's bundled node_modules is part of the installed runtime and must travel.
EXCLUDE_RELATIVE_PATHS = {"personal-site": {"apps/site/node_modules"}}
EMPTY_DIRECTORIES = {"log", "logs", "backup", "backups", "snapshots"}
UNIT_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@:\\-]*\.(?:target|service|timer)\Z")


def load_module(root: Path, name: str) -> tuple[Path, dict]:
    directory = root.resolve() / name
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"Module must be a real directory: {directory}")
    manifest = json.loads((directory / "module.json").read_text(encoding="utf-8"))
    if manifest.get("name") != name or not str(manifest.get("target", "")).endswith(".target"):
        raise ValueError("Module manifest name or target is invalid")
    for field in ("members", "shared_dependencies"):
        if not isinstance(manifest.get(field), list):
            raise ValueError(f"Module manifest requires {field}: [unit, ...]")
    for unit in [manifest["target"], *manifest["members"], *manifest["shared_dependencies"]]:
        if not isinstance(unit, str) or not UNIT_PATTERN.fullmatch(unit):
            raise ValueError("Module manifest contains an invalid systemd unit")
    return directory, manifest


def unit_state(unit: str) -> str:
    result = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, check=False)
    return result.stdout.strip() or "unknown"


def wait_for_units(units: list[str], expected: str, timeout: float, context: str) -> dict[str, str]:
    """A target job can finish before its PartOf member jobs settle."""
    deadline = time.monotonic() + timeout
    while True:
        states = {unit: unit_state(unit) for unit in units}
        if set(states.values()) == {expected}:
            return states
        if any(state in {"failed", "unknown"} for state in states.values()):
            raise RuntimeError(f"{context}: terminal unit state: {states}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"{context}: timed out after {timeout:g}s: {states}")
        time.sleep(min(1.0, remaining))


def control(action: str, manifest: dict, wait_timeout: float = 120.0) -> int:
    units = list(dict.fromkeys([manifest["target"], *manifest["members"]]))
    if action != "status":
        subprocess.run(["systemctl", action, manifest["target"]], check=True)
        expected = "inactive" if action == "stop" else "active"
        states = wait_for_units(units, expected, wait_timeout, f"Module {action} did not reach {expected}")
    else:
        states = {unit: unit_state(unit) for unit in units}
    for unit, state in states.items():
        print(f"{unit}: {state}")
    shared_states = {unit: unit_state(unit) for unit in manifest["shared_dependencies"]}
    for unit, state in shared_states.items():
        print(f"{unit}: {state} (shared)")
    if action == "stop":
        return int(any(state != "inactive" for state in states.values()))
    return int(any(state != "active" for state in [*states.values(), *shared_states.values()]))


def private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("Export directory must not be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError(f"Export directory must be owned by the current user with mode 0700: {path}")
    return path.resolve()


def snapshot_python(directory: Path, override: str | None) -> str:
    candidates = [override] if override else [
        str(directory / "apps/NBot/.venv/bin/python"),
        "/root/miniconda3/bin/python",
        sys.executable,
    ]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        check = subprocess.run(
            [candidate, "-c", "import sys; assert sys.version_info >= (3, 10); import yaml, redis, psycopg"],
            capture_output=True, check=False,
        )
        if check.returncode == 0:
            return candidate
    raise RuntimeError("No Python 3.10+ runtime with PyYAML, redis and psycopg; use --snapshot-python")


def create_snapshot(directory: Path, destination: Path, args: argparse.Namespace) -> dict:
    command = [
        snapshot_python(directory, args.snapshot_python),
        str(Path(__file__).with_name("snapshot_hok.py")),
        "--module-dir", str(directory), "--output-dir", str(destination),
    ]
    if args.pg_dump:
        command.extend(["--pg-dump", args.pg_dump])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        # The helper deliberately emits stage/type only, never connection details.
        raise RuntimeError(f"HOK snapshot failed: {result.stderr.strip() or 'helper exited unsuccessfully'}")
    return json.loads(result.stdout)


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        block = self.stream.read(size)
        self.digest.update(block)
        return block


def add_entry(archive: tarfile.TarFile, path: Path, arcname: str, inventory: list) -> None:
    info = archive.gettarinfo(str(path), arcname=arcname)
    if info is None or not (info.isfile() or info.isdir() or info.issym() or info.islnk()):
        return
    entry = {"path": arcname, "mode": oct(info.mode), "type": "directory"}
    if info.isfile():
        with path.open("rb") as stream:
            reader = HashingReader(stream)
            archive.addfile(info, reader)
        entry.update(type="file", size=info.size, sha256=reader.digest.hexdigest())
    else:
        archive.addfile(info)
        if info.issym():
            entry.update(type="symlink", target=info.linkname)
        elif info.islnk():
            entry.update(type="hardlink", target=info.linkname)
    inventory.append(entry)


def add_tree(archive: tarfile.TarFile, directory: Path, name: str, inventory: list) -> None:
    def visit(path: Path, relative: Path, directories_only: bool = False, vendor: bool = False) -> None:
        if relative == Path("export-manifest.json"):
            return
        if relative.as_posix() in EXCLUDE_RELATIVE_PATHS.get(name, set()):
            return
        vendor = vendor or (path.name == "node_modules" and not directories_only)
        if not vendor and path.name in EXCLUDE_NAMES:
            return
        if directories_only and (path.is_symlink() or not path.is_dir()):
            return
        if not vendor and path.is_file() and path.suffix in {".pyc", ".pyo"}:
            return
        arcname = name if relative == Path(".") else f"{name}/{relative.as_posix()}"
        add_entry(archive, path, arcname, inventory)
        if path.is_symlink() or not path.is_dir():
            return
        directories_only = directories_only or (not vendor and path.name in EMPTY_DIRECTORIES)
        for child in sorted(path.iterdir()):
            visit(child, relative / child.name, directories_only, vendor)

    visit(directory, Path("."))


def export_module(directory: Path, manifest: dict, args: argparse.Namespace, capture: dict | None = None) -> int:
    output = private_directory(args.output_dir)
    if output == directory or directory in output.parents:
        raise ValueError("Export output must be outside the module directory")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    name = manifest["name"]
    destination = output / f"{name}-{stamp}.tar.gz"
    snapshot = None
    inventory = []
    with tempfile.TemporaryDirectory(prefix=f".{name}-export-", dir=output) as temporary:
        temporary_path = Path(temporary)
        if name == "hok":
            snapshot_dir = temporary_path / "snapshots"
            snapshot = create_snapshot(directory, snapshot_dir, args)
        partial = temporary_path / "bundle.tar.gz"
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            with tarfile.open(fileobj=stream, mode="w:gz", compresslevel=3, dereference=False) as archive:
                add_tree(archive, directory, name, inventory)
                if snapshot:
                    for path in sorted(snapshot_dir.iterdir()):
                        add_entry(archive, path, f"{name}/snapshots/{path.name}", inventory)
                metadata = {
                    "format_version": 1, "module": name, "created_at": stamp,
                    "contains_secrets": True, "source": str(directory),
                    "entry_count": len(inventory),
                    "file_count": sum(entry["type"] == "file" for entry in inventory),
                    "uncompressed_file_bytes": sum(entry.get("size", 0) for entry in inventory),
                    "excluded_names": sorted(EXCLUDE_NAMES),
                    "excluded_relative_paths": sorted(EXCLUDE_RELATIVE_PATHS.get(name, set())),
                    "empty_directory_contents": sorted(EMPTY_DIRECTORIES),
                    "runtime_dependencies": "Rebuild only the excluded environments on the target host; bundled application runtime dependencies are included.",
                    "capture_mode": "quiesced" if capture else "live",
                    "quiesce": capture,
                    "consistency": (
                        "Module target and members remain stopped during capture; shared databases remain running. PostgreSQL and Redis snapshots are not one cross-service transaction."
                        if capture else
                        "Live filesystem copy; PostgreSQL consistent dump and Redis per-key transactional snapshots are not one cross-service transaction."
                    ),
                    "snapshot": snapshot, "entries": inventory,
                }
                content = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
                info = tarfile.TarInfo(f"{name}/export-manifest.json")
                info.mode = 0o600
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        digest = hashlib.sha256()
        with partial.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        os.replace(partial, destination)
        checksum = destination.with_name(destination.name + ".sha256")
        descriptor = os.open(checksum, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{digest.hexdigest()}  {destination.name}\n")
    print(json.dumps({"archive": str(destination), "sha256": digest.hexdigest(), "file_count": metadata["file_count"], "entry_count": len(inventory)}, ensure_ascii=False))
    return 0


def quiesced_export(directory: Path, manifest: dict, args: argparse.Namespace) -> int:
    """Pause only this module and restore its original running state in all exits."""
    units = list(dict.fromkeys([manifest["target"], *manifest["members"]]))
    initial_states = {unit: unit_state(unit) for unit in units}
    state_values = set(initial_states.values())
    if state_values not in ({"active"}, {"inactive"}):
        raise RuntimeError(f"Quiesced export requires all target/member units active or all inactive: {initial_states}")
    restore_active = state_values == {"active"}
    wait_timeout = getattr(args, "wait_timeout", 120.0)
    capture = {"initial_states": initial_states, "restore_active": restore_active}
    try:
        if restore_active:
            print(f"Stopping module target {manifest['target']} for export", file=sys.stderr)
            subprocess.run(["systemctl", "stop", manifest["target"]], check=True)
        wait_for_units(units, "inactive", wait_timeout, "Module did not become fully inactive; export cancelled")
        return export_module(directory, manifest, args, capture=capture)
    finally:
        if restore_active:
            # This also runs when stop/export fails or the user interrupts with Ctrl-C.
            print(f"Restoring module target {manifest['target']} after export", file=sys.stderr)
            subprocess.run(["systemctl", "start", manifest["target"]], check=True)
            wait_for_units(units, "active", wait_timeout, "Module restart did not restore all active members")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "start", "stop", "restart", "export"))
    parser.add_argument("module", choices=MODULES)
    parser.add_argument("--root", type=Path, default=Path("/srv/modules"))
    parser.add_argument("--output-dir", type=Path, default=Path("/srv/module-exports"))
    parser.add_argument("--snapshot-python", help="Python 3.10+ with PyYAML, redis and psycopg")
    parser.add_argument("--pg-dump", help="pg_dump executable compatible with the database server")
    parser.add_argument("--quiesce", action="store_true", help="Export only: pause this module, then restore its previous running state")
    parser.add_argument("--wait-timeout", type=float, default=120.0, help="Seconds to wait for each start/stop/restart or --quiesce transition (default: 120)")
    args = parser.parse_args()
    if args.wait_timeout <= 0:
        parser.error("--wait-timeout must be positive")
    if args.quiesce and args.action != "export":
        parser.error("--quiesce is only valid with export")
    try:
        directory, manifest = load_module(args.root, args.module)
        if args.action == "export":
            if args.quiesce:
                return quiesced_export(directory, manifest, args)
            return export_module(directory, manifest, args)
        return control(args.action, manifest, args.wait_timeout)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"modulectl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Supplement an existing HOK export without recapturing state or touching services.

Only two management files and the missing NapCat vendor tree come from the live
filesystem. Every other original member, especially all snapshots, is copied
from the input archive and checked against its original manifest.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

import modulectl


VENDOR = "apps/napcat/opt/QQ/resources/app/app_launcher/napcat/node_modules"
REPLACEMENTS = {"ops/modulectl.py": "modulectl.py", "README.md": "README.md"}
MANIFEST = "hok/export-manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def member_entry(member: tarfile.TarInfo) -> dict:
    entry = {"path": member.name, "mode": oct(member.mode)}
    if member.isfile():
        entry.update(type="file", size=member.size)
    elif member.isdir():
        entry.update(type="directory")
    elif member.issym():
        entry.update(type="symlink", target=member.linkname)
    elif member.islnk():
        entry.update(type="hardlink", target=member.linkname)
    else:
        raise ValueError(f"Unsupported original archive member type: {member.name}")
    return entry


def add_vendor_tree(archive: tarfile.TarFile, directory: Path, inventory: list) -> None:
    """Include the full vendor subtree, without any rebuildable/cache exclusions."""
    def visit(path: Path, relative: Path) -> None:
        arcname = "hok/" + VENDOR
        if relative != Path("."):
            arcname += "/" + relative.as_posix()
        modulectl.add_entry(archive, path, arcname, inventory)
        if path.is_symlink() or not path.is_dir():
            return
        for child in sorted(path.iterdir()):
            visit(child, relative / child.name)

    visit(directory, Path("."))


def refresh(source_archive: Path, module_dir: Path, output: Path, source_dir: Path) -> dict:
    source_archive = source_archive.resolve(strict=True)
    module_dir = module_dir.resolve(strict=True)
    source_dir = source_dir.resolve(strict=True)
    output = Path(output)
    parent = modulectl.private_directory(output.parent)
    output = parent / output.name
    checksum = output.with_name(output.name + ".sha256")
    if output.exists() or output.is_symlink() or checksum.exists() or checksum.is_symlink():
        raise ValueError("Output archive/checksum already exists; input and existing exports are never overwritten")
    if output == source_archive or parent == module_dir or module_dir in parent.parents:
        raise ValueError("Output must be a new archive outside the live module")
    vendor = module_dir / VENDOR
    if vendor.is_symlink() or not vendor.is_dir():
        raise ValueError("The NapCat vendor root must be a real directory")
    for relative in REPLACEMENTS.values():
        path = source_dir / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Replacement source must be a regular file: {relative}")

    inventory, observed = [], {}
    metadata = None
    replaced = set()
    prefix = "hok/" + VENDOR
    original_archive_hash = sha256_file(source_archive)
    with tempfile.TemporaryDirectory(prefix=".hok-refresh-", dir=parent) as temporary:
        partial = Path(temporary) / "bundle.tar.gz"
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            with tarfile.open(source_archive, "r|gz") as original, tarfile.open(
                fileobj=stream, mode="w:gz", compresslevel=1, dereference=False,
            ) as archive:
                for member in original:
                    name = PurePosixPath(member.name)
                    if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != "hok":
                        raise ValueError("Original archive contains an unsafe or non-HOK path")
                    if member.name == MANIFEST:
                        if metadata is not None or not member.isfile():
                            raise ValueError("Duplicate or invalid original export manifest")
                        metadata = json.load(original.extractfile(member))
                        continue
                    if member.name in observed:
                        raise ValueError("Duplicate original archive member")
                    if member.name == prefix or member.name.startswith(prefix + "/"):
                        raise ValueError("Original export already contains the vendor tree; refusing ambiguous supplementation")
                    entry = member_entry(member)
                    relative = member.name.removeprefix("hok/")
                    replace = relative in REPLACEMENTS
                    if replace and not member.isfile():
                        raise ValueError("Original management file must be regular")
                    if member.isfile():
                        reader = modulectl.HashingReader(original.extractfile(member))
                        if replace:
                            for _ in iter(lambda: reader.read(1024 * 1024), b""):
                                pass
                        else:
                            archive.addfile(member, reader)
                        entry["sha256"] = reader.digest.hexdigest()
                    else:
                        archive.addfile(member)
                    observed[member.name] = entry
                    if replace:
                        replaced.add(relative)
                    else:
                        inventory.append(entry)

                if not metadata or metadata.get("module") != "hok":
                    raise ValueError("Missing HOK original export manifest")
                expected_entries = metadata.get("entries", [])
                expected = {item["path"]: item for item in expected_entries}
                if len(expected) != len(expected_entries) or set(expected) != set(observed):
                    raise ValueError("Original manifest member inventory mismatch")
                for name, entry in observed.items():
                    expected_entry = dict(expected[name])
                    # Python versions differ in whether gettarinfo().mode
                    # retains stat file-type bits before serializing a tar
                    # header. The header and decoded TarInfo retain permission
                    # bits only; validate type separately via the type field.
                    try:
                        expected_entry["mode"] = oct(int(expected_entry["mode"], 8) & 0o7777)
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError(f"Invalid original manifest mode: {name}") from exc
                    if any(expected_entry.get(key) != value for key, value in entry.items()):
                        raise ValueError(f"Original manifest hash/metadata mismatch: {name}")
                if replaced != set(REPLACEMENTS):
                    raise ValueError("Original export is missing an expected management file")
                snapshot = metadata.get("snapshot")
                if not isinstance(snapshot, dict) or not snapshot.get("created_at"):
                    raise ValueError("Original export has no snapshot capture timestamp")
                for filename, digest in snapshot.get("sha256", {}).items():
                    entry = observed.get("hok/snapshots/" + filename, {})
                    if entry.get("sha256") != digest:
                        raise ValueError("Original snapshot metadata hash mismatch")

                for relative, filename in REPLACEMENTS.items():
                    path = source_dir / filename
                    name = "hok/" + relative
                    info = archive.gettarinfo(str(path), arcname=name)
                    # Uploads commonly reset source mode to 0644; keep the
                    # installed management tool executable as in the old export.
                    info.mode = int(observed[name]["mode"], 8)
                    with path.open("rb") as replacement_stream:
                        reader = modulectl.HashingReader(replacement_stream)
                        archive.addfile(info, reader)
                    entry = member_entry(info)
                    entry["sha256"] = reader.digest.hexdigest()
                    inventory.append(entry)
                add_vendor_tree(archive, vendor, inventory)
                updated_at = datetime.now(timezone.utc).isoformat()
                metadata.setdefault("packaging_updates", []).append({
                    "type": "offline_vendor_supplement",
                    "updated_at": updated_at,
                    "original_archive": source_archive.name,
                    "original_archive_sha256": original_archive_hash,
                    "original_snapshot_captured_at": snapshot["created_at"],
                    "replaced_paths": ["hok/" + relative for relative in REPLACEMENTS],
                    "added_tree": prefix,
                    "snapshot_unchanged": True,
                    "original_other_members_unchanged": True,
                    "note": "Packaging-only update: original snapshot object and all original state/file bytes retained. Supplemented management files and NapCat vendor tree were read at packaging time; services were not queried or changed.",
                })
                metadata["excluded_names"] = [name for name in metadata.get("excluded_names", []) if name != "node_modules"]
                metadata["conditional_exclusions"] = {
                    **metadata.get("conditional_exclusions", {}),
                    "node_modules": {
                        "excluded_subtrees": ["personal-site/apps/site/node_modules"],
                        "included_complete_subtrees": ["hok/" + VENDOR],
                        "note": "No global node_modules exclusion applies to HOK; the website dependency exclusion is module-specific.",
                    },
                }
                metadata["entries"] = inventory
                metadata["entry_count"] = len(inventory)
                metadata["file_count"] = sum(entry["type"] == "file" for entry in inventory)
                metadata["uncompressed_file_bytes"] = sum(entry.get("size", 0) for entry in inventory)
                metadata["runtime_dependencies"] = "Rebuild Python virtualenvs and website node_modules; the NapCat vendor node_modules tree is included intact."
                content = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
                info = tarfile.TarInfo(MANIFEST)
                info.mode = 0o600
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))

        digest = sha256_file(partial)
        temporary_checksum = Path(temporary) / "bundle.sha256"
        descriptor = os.open(temporary_checksum, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{digest}  {output.name}\n")
        # Same-filesystem hard links publish complete artifacts without overwriting.
        os.link(partial, output)
        os.link(temporary_checksum, checksum)
    return {"archive": str(output), "sha256": digest, "file_count": metadata["file_count"],
            "original_snapshot_captured_at": snapshot["created_at"], "snapshot_unchanged": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--module-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(refresh(args.archive, args.module_dir, args.output, args.source_dir)))


if __name__ == "__main__":
    main()

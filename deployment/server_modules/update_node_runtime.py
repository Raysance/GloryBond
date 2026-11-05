#!/usr/bin/env python3
"""Update one standalone Node runtime within its existing major release line."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


BASE = "https://nodejs.org/dist/"
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)\Z")


def version_tuple(value):
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError("Invalid Node version")
    return tuple(int(part) for part in match.groups())


def latest_release(releases, major):
    candidates = [item["version"] for item in releases
                  if VERSION.fullmatch(item.get("version", ""))
                  and version_tuple(item["version"])[0] == major
                  and "linux-x64" in item.get("files", [])]
    return max(candidates, key=version_tuple)


def fetch(url, limit):
    with urllib.request.urlopen(url, timeout=60) as response:
        if not response.geturl().startswith(BASE):
            raise ValueError("Unexpected download origin")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Download exceeds size limit")
    return data


def expected_checksum(manifest, filename):
    matches = []
    for line in manifest.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == filename:
            if not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                raise ValueError("Invalid checksum")
            matches.append(parts[0])
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous checksum")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--major", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    binary = args.binary
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("Expected a regular standalone binary")
    current = subprocess.check_output([str(binary), "--version"], timeout=15).decode().strip()
    if version_tuple(current)[0] != args.major:
        raise ValueError("Current Node major differs from configured major")
    releases = json.loads(fetch(BASE + "index.json", 4 * 1024 * 1024))
    latest = latest_release(releases, args.major)
    changed = version_tuple(latest) > version_tuple(current)
    if args.apply and changed:
        filename = "node-{}-linux-x64.tar.xz".format(latest)
        manifest = fetch(BASE + latest + "/SHASUMS256.txt", 1024 * 1024).decode()
        expected = expected_checksum(manifest, filename)
        archive = fetch(BASE + latest + "/" + filename, 100 * 1024 * 1024)
        if hashlib.sha256(archive).hexdigest() != expected:
            raise ValueError("Node archive checksum mismatch")
        with tempfile.TemporaryDirectory(prefix="node-update-", dir=str(binary.parent)) as temp:
            archive_path = Path(temp) / filename
            archive_path.write_bytes(archive)
            candidate = Path(temp) / "node"
            with tarfile.open(str(archive_path), "r:xz") as bundle:
                member = bundle.getmember("node-{}-linux-x64/bin/node".format(latest))
                if not member.isfile() or member.size > 200 * 1024 * 1024:
                    raise ValueError("Unexpected Node archive member")
                with bundle.extractfile(member) as source, candidate.open("wb") as target:
                    shutil.copyfileobj(source, target)
            candidate.chmod(0o755)
            actual = subprocess.check_output([str(candidate), "--version"], timeout=15).decode().strip()
            if actual != latest:
                raise ValueError("Downloaded Node version mismatch")
            previous = binary.with_name(binary.name + ".previous")
            shutil.copy2(str(binary), str(Path(temp) / "previous"))
            os.replace(str(Path(temp) / "previous"), str(previous))
            os.replace(str(candidate), str(binary))
    print(json.dumps({"current": current, "available": latest,
                      "changed": changed, "applied": bool(args.apply and changed)}))


if __name__ == "__main__":
    main()

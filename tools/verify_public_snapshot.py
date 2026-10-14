"""Verify the staged public tree, not just working-directory ignore patterns."""
import argparse
import json
from pathlib import Path
import subprocess

from sync_public_snapshot import ROOT, private_values


def primitives(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from primitives(item)
    elif isinstance(value, list):
        for item in value:
            yield from primitives(item)
    else:
        yield value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nbot-private-source", type=Path, required=True)
    args = parser.parse_args()
    secrets, identities = private_values(args.nbot_private_source)
    entries = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "--stage", "-z"]).split(b"\0")
    count, samples, core = 0, 0, 0
    for entry in entries:
        if not entry:
            continue
        info, raw_path = entry.split(b"\t", 1)
        mode = info.decode().split()[0]
        relative = raw_path.decode()
        path = Path(relative)
        if mode == "160000":
            if relative != "NBot/vendor/react-agent-runtime":
                raise ValueError("Unexpected dependency: " + relative)
            core += 1
            continue
        if (any(part.startswith(".env") or part in {"config.yaml", "variables_static.json", "variables_dynamic.json", ".DS_Store"} for part in path.parts)
                or relative.startswith(("NBot/deployment/", "NBot/log/", "NBot/file_transfer/", "NBot/.github/", "Web/.github/"))
                or (relative.startswith("NBot/data/") and relative != "NBot/data/honor/districts.json")):
            raise ValueError("Private or runtime path staged: " + relative)
        raw = subprocess.check_output(["git", "-C", str(ROOT), "show", ":" + relative])
        if any(secret.encode() in raw for secret in secrets):
            raise ValueError("Configured credential remains in staged file: " + relative)
        try:
            content = raw.decode("utf-8")
        except UnicodeError:
            content = None
        if content is not None and any(identity in content for identity in identities):
            raise ValueError("Deployment identity remains in staged text: " + relative)
        if relative.startswith(("NBot/resources/wzry_data_format/", "Web/default_json_templates/")) and path.suffix == ".json" and raw.strip():
            if any(value not in ("", 0, False, None) for value in primitives(json.loads(raw))):
                raise ValueError("Sample payload contains populated values: " + relative)
            samples += 1
        count += 1
    if core != 1:
        raise ValueError("Pinned private dependency reference is missing")
    print(json.dumps({"staged_files_checked": count, "empty_sample_payloads": samples,
                      "private_dependency_references": core, "credential_or_identity_matches": 0}))


if __name__ == "__main__":
    main()

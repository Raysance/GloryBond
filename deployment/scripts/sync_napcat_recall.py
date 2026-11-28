"""Install the owned recall plugin through NapCat's existing plugin loader."""
import argparse
import hashlib
from pathlib import Path
import subprocess

import yaml


def sync(root, *, restart=False):
    config = yaml.safe_load((root / "config.yaml").read_text())
    configured = config.get("QQAgent", {}).get("napcat_plugin_directory")
    if not configured:
        return {"enabled": False, "changed": False}
    directory = Path(configured)
    if not directory.is_absolute() or not (directory.parent / "napcat.mjs").is_file():
        raise ValueError("napcat_plugin_directory must identify this host's NapCat plugins directory")
    source = root / "src/glorybond/integrations/napcat_recall.mjs"
    subprocess.run(["node", "--check", str(source)], check=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    directory.mkdir(exist_ok=True)
    target = directory / "glorybond_recall.mjs"
    if (target.exists() or target.is_symlink()) and (not target.is_symlink() or target.resolve() != source.resolve()):
        raise ValueError("Refusing to replace an unrelated NapCat plugin")
    state = root / "data/napcat_recall_bridge.sha256"
    changed = not target.exists() or not state.exists() or state.read_text().strip() != digest
    if not target.is_symlink():
        target.symlink_to(source.resolve())
    if changed and restart:
        subprocess.run(["systemctl", "restart", "hok-napcat.service"], check=True)
        state.parent.mkdir(exist_ok=True, mode=0o700)
        state.write_text(digest + "\n")
    return {"enabled": True, "changed": changed, "restarted": bool(changed and restart)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    print(sync(args.project_root.resolve(), restart=args.restart))


if __name__ == "__main__":
    main()

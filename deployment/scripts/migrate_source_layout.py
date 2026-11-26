"""Update the managed Web unit's source entry while preserving host settings."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def rewrite_unit(source: str, project_root: Path) -> str:
    source = re.sub(r"(?m)^(ExecStart=[^\n]* -m )web(?=\s|$)",
                    r"\1glorybond.apps.web", source)
    old = f"Environment=WEB_PATH={project_root}/web"
    new = f"Environment=WEB_PATH={project_root}/src/glorybond/apps/web"
    return "\n".join(new if line == old else line for line in source.split("\n"))


def migrate(project_root: Path):
    unit = subprocess.check_output(
        ["systemctl", "show", "hok-web.service", "-p", "FragmentPath", "--value"],
        text=True, timeout=10).strip()
    path = Path(unit)
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError("The managed Web unit could not be located")
    source = path.read_text()
    updated = rewrite_unit(source, project_root)
    if updated == source:
        return
    backup_root = project_root / "log" / "deployment-backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="source-layout-", dir=backup_root))
    shutil.copy2(path, backup / path.name)
    state = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=".glorybond-unit-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, state.st_mode & 0o7777)
        os.chown(temporary, state.st_uid, state.st_gid)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
    print("Updated the managed Web entry point; existing unit settings were retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    migrate(parser.parse_args().project_root.resolve())

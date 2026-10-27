"""Send the two ignored application configuration files over SSH, outside Git."""
import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess

from dotenv import dotenv_values
import yaml

# The remote program contains no credential values. Payload travels only on stdin.
REMOTE = r'''
import base64,fcntl,json,os,tempfile
from pathlib import Path
payload=json.load(__import__('sys').stdin)
root=Path(payload['project_root'])
if not root.is_absolute() or str(root)=='/':
    raise SystemExit('Invalid project root')
root.mkdir(parents=True,exist_ok=True)
lock_dir=root/'data/account_sessions';lock_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
with (lock_dir/'credentials.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    originals={name:(root/name).read_bytes() if (root/name).exists() else None for name in ('.env','config.yaml')}
    expected=payload.get('expected')
    import hashlib
    current={name:hashlib.sha256(raw).hexdigest() if raw is not None else None for name,raw in originals.items()}
    if expected is not None and current!=expected:
        raise SystemExit('Configuration changed during transfer; no files replaced')
    if payload['check']:
        print(json.dumps({'present':{name:raw is not None for name,raw in originals.items()},'versions':current}))
        raise SystemExit(0)
    backup=root/'log/config-backups';backup.mkdir(parents=True,exist_ok=True,mode=0o700)
    private_backup=Path(tempfile.mkdtemp(prefix='sync-',dir=backup));private_backup.chmod(0o700)
    for name,raw in originals.items():
        if raw is not None:
            target=private_backup/name;target.write_bytes(raw);target.chmod(0o600)
    def replace(name,raw):
        fd,path=tempfile.mkstemp(prefix='.config-transfer-',dir=root)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.chmod(path,0o600);os.replace(path,root/name)
        finally:
            if os.path.exists(path):os.unlink(path)
    completed=[]
    try:
        for name in ('config.yaml','.env'):
            replace(name,base64.b64decode(payload['files'][name],validate=True));completed.append(name)
    except BaseException:
        for name in completed:
            if originals[name] is None:(root/name).unlink(missing_ok=True)
            else:replace(name,originals[name])
        raise
    print(json.dumps({'updated':['.env','config.yaml'],'backup_created':True}))
'''


def send(host, payload):
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',host,'python3 -c '+shlex.quote(REMOTE)],
                          input=json.dumps(payload).encode(),capture_output=True)
    if result.returncode:
        raise RuntimeError('Private configuration transfer failed; inspect SSH/server access. Credential output suppressed.')
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True,help='SSH host alias')
    parser.add_argument('--project-root',required=True,help='Absolute server checkout directory')
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--check',action='store_true',help='Check presence without replacing files')
    args=parser.parse_args()
    if args.host.startswith('-'):
        parser.error('Invalid SSH host')
    payload={'project_root':args.project_root,'check':True}
    state=send(args.host,payload)
    if args.check:
        print(json.dumps({'present':state['present']}));return
    files={name:(args.source/name).read_bytes() for name in ('.env','config.yaml')}
    try:
        valid = bool(dotenv_values(args.source/'.env',interpolate=False)) and isinstance(yaml.safe_load(files['config.yaml']),dict)
    except (ValueError, yaml.YAMLError):
        raise ValueError('Invalid private configuration; values omitted') from None
    if not valid:
        raise ValueError('Both local configuration files must contain valid settings')
    payload.update(check=False,expected=state['versions'],files={name:base64.b64encode(raw).decode() for name,raw in files.items()})
    print(json.dumps(send(args.host,payload)))


if __name__=='__main__':
    main()

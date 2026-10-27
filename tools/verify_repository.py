"""Check the staged public tree and optionally all reachable source history."""
import argparse
from pathlib import Path
import subprocess
import json

from sanitize_repository_history import Inventory, TOKEN, DSN, git, objects, private_path, sample_path, empty_sample

ROOT=Path(__file__).resolve().parents[1]
SDK_PATHS={'vendor/hok-player-client','vendor/hok-camp-client','vendor/react-agent-runtime'}


def canonical(name):
    name=name.removeprefix('NBot/')
    return 'web/'+name[4:] if name.startswith('Web/') else name


def examples(name):
    name=canonical(name)
    return name.startswith('tests/') or '/tests/' in name or Path(name).name.startswith('test_')


def check_blob(name,raw,inventory=None):
    normalized=canonical(name)
    if private_path(normalized) or normalized.endswith('.pyc') or normalized.startswith('web/html/'):
        raise ValueError('Private/runtime path in publication: '+name)
    if any(normalized.startswith(path+'/') for path in SDK_PATHS):
        raise ValueError('Private SDK implementation in publication: '+name)
    if inventory and any(value.encode() in raw for value in inventory.secrets):
        raise ValueError('Configured credential in publication: '+name)
    try:
        content=raw.decode('utf-8')
    except UnicodeError:
        return
    if sample_path(name) and content.strip() and empty_sample(json.loads(content)) != json.loads(content):
        raise ValueError('Sample payload contains personal/runtime values: '+name)
    if inventory:
        inventory.check(content,name,examples=examples(name))
    elif not examples(name) and (TOKEN.search(content) or DSN.search(content)):
        raise ValueError('Credential-like literal in publication: '+name)


def verify(root=ROOT,inventory=None,history=False):
    checked=0;dependencies=set();paths=set()
    for row in git(root,'ls-files','--stage','-z').split(b'\0'):
        if not row:continue
        info,name=row.split(b'\t',1);mode,_,stage=info.split();name=name.decode()
        if stage!=b'0':raise ValueError('Unresolved index conflict')
        paths.add(name)
        if mode==b'160000':dependencies.add(name);continue
        if name.startswith(('NBot/','Web/')):raise ValueError('Obsolete split layout in staged tree')
        raw=git(root,'show',':'+name)
        check_blob(name,raw,inventory)
        if mode==b'120000' and (not raw.startswith(b'vendor/') or b'..' in raw.split(b'/')):
            raise ValueError('Unexpected source symlink: '+name)
        checked+=1
    if dependencies!=SDK_PATHS:raise ValueError('The three fixed private SDK gitlinks are required')
    for name in ['README.md','AGENTS.md','shared/agent/manual/catalog.json','shared/agent/manual/handbook.md','web/docs/accounts.md','deployment/scripts/deploy_project.sh','deployment/scripts/sync_private_config.py']:
        if name not in paths:raise ValueError('Required source/documentation missing: '+name)
    count=0
    if history:
        for _,name,raw in objects(root,('HEAD',)):
            check_blob(name,raw,inventory);count+=1
        if inventory:
            for message in git(root,'log','HEAD','--format=%B%x00').decode().split('\0'):
                inventory.check(message,'commit message',examples=True)
    return {'staged_files_checked':checked,'private_sdk_references':len(dependencies),'historical_blobs_checked':count,'sensitive_matches':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',action='store_true')
    parser.add_argument('--inventory-source',type=Path)
    args=parser.parse_args()
    inventory=Inventory(args.inventory_source) if args.inventory_source else None
    print(json.dumps(verify(inventory=inventory,history=args.history)))


if __name__=='__main__':main()

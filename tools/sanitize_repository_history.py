"""Import a private Git history without configuration, runtime state or private SDK code.

Run on an isolated clone. The original source is read only; the credential inventory
is held in memory. git-filter-repo must be installed in the invoking environment.
"""
import argparse
import ast
from collections import Counter
from io import StringIO
import json
from pathlib import Path
import re
import subprocess
import tokenize

from dotenv import dotenv_values
import yaml

PUBLIC_TERMS = {'自己', '本人', '群u', '玩家', '大家', 'None', '奶龙', 'touch'}
SECRET_KEY = re.compile(r'api.?key|token|secret|password|passwd|dsn|encoderes|encryptpara|openid|open_id|ticket|cookie|session|device.?id|guid|userkey', re.I)
LITERAL_KEY = re.compile(r'(?:api.?key|access.?token|refresh.?token|auth.?token|password|passwd|secret.?key|dsn|encoderes|encryptpara)', re.I)
TOKEN = re.compile(r'sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}')
DSN = re.compile(r'postgres(?:ql)?://[^\s\x22\x27]+')
SAMPLE_PARTS = ('wzry_data_format', 'default_json_templates/')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def objects(root, refs):
    rows = git(root, 'rev-list', '--objects', *refs).splitlines()
    request = b''.join(row.split(b' ', 1)[0] + b'\n' for row in rows)
    proc = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch'], input=request, capture_output=True, check=True)
    position = 0
    for row in rows:
        end = proc.stdout.index(b'\n', position)
        oid, kind, size = proc.stdout[position:end].split()
        position = end + 1
        raw = proc.stdout[position:position + int(size)]
        position += int(size) + 1
        if kind == b'blob':
            yield oid, row.split(b' ', 1)[1].decode('utf-8', 'replace') if b' ' in row else '', raw


def private_path(name):
    path = Path(name)
    parts = path.parts
    if not parts:
        return False
    if any(part in {'.git', '.venv', '__pycache__', 'file_transfer', 'log', 'logs', 'memory', 'chats', 'history', 'tmpfile', 'debug'} for part in parts):
        return True
    if any(part.startswith('.env') or part.startswith('variables_static') or part.startswith('variables_dynamic')
           or part in {'config.yaml', 'redis.json', 'emojiref.json', '.DS_Store'} for part in parts):
        return True
    if name.startswith(('agent_runtime/', 'hok_research/', 'hok_camp_client/')):
        return True
    if parts[0] == 'vendor' and len(parts) > 2:
        return True
    if parts[0] == 'data' and name != 'data/honor/districts.json':
        return True
    if name.endswith(('.rdb', '.db', '.sqlite', '.sqlite3', '.pem', '.key', '.p12', '.pfx', '.log')):
        return True
    return name in {'deepseek_output.txt', 'manual.png'} or '/generated/' in name or '/player_client/' in name and path.suffix.lower() in {'.jpg', '.png'}


def config_blob(name):
    return any(part.startswith('.env') or part.startswith('variables_static') or part in {'config.yaml', 'redis.json'} for part in Path(name).parts)


def sample_path(name):
    return name.endswith('.json') and (any(part in name for part in SAMPLE_PARTS)
        or Path(name).name == 'example.json' or Path(name).name.startswith('sample_'))


def empty_sample(value):
    if isinstance(value, dict):
        return {k: empty_sample(v) for k, v in value.items()}
    if isinstance(value, list):
        return [empty_sample(v) for v in value]
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0
    return '' if isinstance(value, str) else None


class Inventory:
    def __init__(self, source, refs=('main', 'web-history')):
        self.secrets, self.identities, self.names = set(), set(), set()
        self.blobs = list(objects(source, refs))
        configs = 0
        for _, name, raw in self.blobs:
            if not config_blob(name):
                continue
            configs += 1
            try:
                text = raw.decode('utf-8-sig')
                if Path(name).name.startswith('.env'):
                    value = dict(dotenv_values(stream=StringIO(text), interpolate=False))
                    for key, item in value.items():
                        if item and key not in {'ENVIRONMENT', 'DRIVER'}:
                            self.add_secret(item)
                            try:
                                self.collect(json.loads(item))
                            except (ValueError, TypeError):
                                pass
                else:
                    value = json.loads(text) if name.endswith('.json') else yaml.safe_load(text)
                self.collect(value)
                self.config_identities(value)
            except (ValueError, UnicodeError, yaml.YAMLError):
                raise ValueError('Unable to inspect historical configuration: ' + name) from None
        # Historic versions may have embedded credentials before configuration existed.
        for _, name, raw in self.blobs:
            if not name.endswith('.py') or private_path(name) or name.startswith('tests/') or '/tests/' in name:
                continue
            try:
                tree = ast.parse(raw.decode('utf-8-sig'))
            except (UnicodeError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    labels = [target.id for target in node.targets if isinstance(target, ast.Name)]
                    if any(LITERAL_KEY.search(label) for label in labels) and isinstance(node.value, ast.Constant):
                        self.add_secret(node.value.value)
                elif isinstance(node, ast.Dict):
                    for key, item in zip(node.keys, node.values):
                        if isinstance(key, ast.Constant) and LITERAL_KEY.search(str(key.value)) and isinstance(item, ast.Constant):
                            self.add_secret(item.value)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'getenv', 'get'}:
                    if len(node.args) >= 2 and isinstance(node.args[0], ast.Constant) and SECRET_KEY.search(str(node.args[0].value)) and isinstance(node.args[1], ast.Constant):
                        self.add_secret(node.args[1].value)
        # Common programming identifiers that happen to be nicknames are not identities.
        # Preserving these prevents rewriting CSS properties and Python method names.
        collisions = set()
        for _, name, raw in self.blobs:
            if name.endswith('.py') and not private_path(name):
                try:
                    for tok in tokenize.generate_tokens(StringIO(raw.decode('utf-8-sig')).readline):
                        if tok.type == tokenize.NAME and tok.string in self.names:
                            collisions.add(tok.string)
                except (UnicodeError, tokenize.TokenError, IndentationError, SyntaxError):
                    pass
        self.names.difference_update(collisions | PUBLIC_TERMS)
        self.secrets.difference_update(self.identities)
        self.ids = {v: str(2000000000 + i) for i, v in enumerate(sorted(self.identities))}
        self.labels = {v: 'example_user_' + str(i) if v.isascii() else '示例玩家' + str(i) for i, v in enumerate(sorted(self.names))}
        self.secret_pattern = re.compile('|'.join(re.escape(v) for v in sorted(self.secrets, key=len, reverse=True))) if self.secrets else None
        self.identity_pattern = re.compile(r'(?<!\d)(?:' + '|'.join(re.escape(v) for v in sorted(self.ids, key=len, reverse=True)) + r')(?!\d)') if self.ids else None
        self.name_patterns = [(re.compile(r'(?<!\w)' + re.escape(v) + r'(?!\w)' if v.isascii() else re.escape(v)), replacement) for v, replacement in sorted(self.labels.items(), key=lambda x: len(x[0]), reverse=True)]
        self.counts = {'historical_config_blobs': configs, 'credential_values': len(self.secrets), 'identity_values': len(self.ids), 'names': len(self.labels)}

    def add_secret(self, value):
        if isinstance(value, str) and len(value) >= 8 and not re.fullmatch(r'[A-Z][A-Z0-9_]+', value):
            self.secrets.add(value)

    def identity(self, value):
        if value is not None and str(value).isdigit() and len(str(value)) >= 6 and not re.fullmatch(r'10+', str(value)):
            self.identities.add(str(value))

    def collect(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if SECRET_KEY.search(str(key)) and not str(key).endswith('_env') and 'public' not in str(key).lower():
                    self.add_secret(item)
                if str(key).lower() in {'uid','uin','qq','user_id','userid','roleid','role_id','bot_qid','group_qid','super_qid'}:
                    self.identity(item)
                self.collect(item)
        elif isinstance(value, list):
            for item in value:
                self.collect(item)

    def config_identities(self, value):
        if not isinstance(value, dict):
            return
        static = value.get('StaticVariables', value)
        for mapping in ('qid','userlist','roleidlist','extra_useridlist','extra_roleidlist','steam_userlist'):
            for key, item in (static.get(mapping) or {}).items():
                self.identity(item)
                if len(str(key)) >= 3:
                    self.names.add(str(key))
        for mapping in ('namenick','extra_namenick','nameref'):
            for key, item in (static.get(mapping) or {}).items():
                for label in (item if isinstance(item, list) else [item]):
                    if label and len(str(label)) >= (3 if str(label).isascii() else 2):
                        self.names.add(str(label))

    def sanitize(self, text, examples=False):
        if self.secret_pattern:
            text = self.secret_pattern.sub('REDACTED_CREDENTIAL', text)
        if not examples:
            text = TOKEN.sub('REDACTED_CREDENTIAL', text)
            text = DSN.sub('REDACTED_DATABASE_DSN', text)
        if self.identity_pattern:
            text = self.identity_pattern.sub(lambda m: self.ids[m.group()], text)
        for pattern, replacement in self.name_patterns:
            text = pattern.sub(replacement, text)
        text = re.sub(r'/Users/[^/\s\"\']+', '/path/to/user', text)
        return text

    def check(self, text, name, examples=False):
        if (self.secret_pattern and self.secret_pattern.search(text)) or not examples and (TOKEN.search(text) or DSN.search(text)):
            raise ValueError('Credential match remains: ' + name)
        if self.identity_pattern and self.identity_pattern.search(text):
            raise ValueError('Configured identity remains: ' + name)


def rewrite(source, destination, inventory_source=None, public=False):
    import git_filter_repo as fr
    inv = Inventory(inventory_source or source)
    approved = set()
    for oid, name, raw in inv.blobs:
        if not private_path(name) and Path(name).suffix.lower() in {'.ttf','.woff','.woff2','.otf'}:
            approved.add(oid)
    subprocess.run(['git', 'clone', '--bare', '--no-hardlinks', '--no-tags', '--single-branch', '--branch', 'main', str(source), str(destination)], check=True, capture_output=True)
    if not public:
        subprocess.run(['git','-C',str(destination),'fetch',str(source),'web-history:refs/heads/web-history'],check=True,capture_output=True)
    cache, counts = {}, Counter()
    def callback(filename, mode, blob_id, value):
        name = filename.decode('utf-8')
        canonical = name.removeprefix('NBot/')
        if canonical.startswith('Web/'):
            canonical = 'web/' + canonical[4:]
        if private_path(canonical) or canonical.endswith('.pyc') or canonical.startswith('web/html/'):
            counts['private_changes_removed'] += 1
            return None, mode, blob_id
        if mode == b'160000':
            return filename, mode, blob_id
        key=(name,blob_id)
        if key in cache:
            return filename,mode,cache[key]
        raw=value.get_contents_by_identifier(blob_id)
        try:
            text=raw.decode('utf-8-sig')
            if '\0' in text:
                raise UnicodeError()
        except UnicodeError:
            # Opaque images/archives can contain users or sessions. Keep only fonts.
            if blob_id not in approved and not public:
                counts['opaque_changes_removed'] += 1
                return None,mode,blob_id
            return filename,mode,blob_id
        if sample_path(name) and text.strip():
            text=json.dumps(empty_sample(json.loads(text)),ensure_ascii=False,indent=2)+'\n'
        examples = canonical.startswith('tests/') or '/tests/' in canonical or Path(canonical).name.startswith('test_')
        clean=inv.sanitize(text, examples=examples)
        inv.check(clean,name, examples=examples)
        if clean != text:
            counts['redacted_blob_versions'] += 1
        result=value.insert_file_with_contents(clean.encode())
        cache[key]=result
        return filename,mode,result
    args=fr.FilteringOptions.parse_args(['--force','--preserve-commit-hashes','--prune-empty','never','--prune-degenerate','never'])
    import os
    previous=Path.cwd()
    try:
        os.chdir(destination)
        fr.RepoFilter(args,file_info_callback=callback,name_callback=lambda _: b'Raysance',email_callback=lambda _: b'Raysance@users.noreply.github.com').run()
    finally:
        os.chdir(previous)
    print(json.dumps(inv.counts | dict(counts)))
    return inv


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    rewrite(args.source.resolve(),args.destination.resolve())


if __name__=='__main__':
    main()

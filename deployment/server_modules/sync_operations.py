#!/usr/bin/env python3
"""Update module operations and Aliyun's explicit NBot host settings."""

import datetime
from pathlib import Path

from migrate_aliyun import ROOT, BACKUPS, UNIT_DIR, MEMBERS, Transaction, run


def main():
    source = Path(__file__).resolve().parent
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-ops')
    transaction = Transaction(BACKUPS / stamp)
    # The live CLI lives in Conda. Keep this host path in systemd instead of
    # creating a third application configuration file.
    unit = UNIT_DIR / 'hok-nbot.service'
    content = unit.read_text()
    setting = 'Environment=HOK_NB_BIN=/root/miniconda3/bin/nb\n'
    if setting not in content:
        content = content.replace('[Service]\n', '[Service]\n' + setting, 1)
    transaction.write(unit, content)
    transaction.write(ROOT / 'hok/systemd/hok-nbot.service', content)
    for filename in ['modulectl.py', 'snapshot_hok.py', 'verify_export.py', 'migrate_aliyun.py', 'README.md']:
        transaction.write(ROOT / 'bin' / filename, (source / filename).read_text(),
                          0o755 if filename.endswith('.py') else 0o644)
    for name in MEMBERS:
        for filename in ['modulectl.py', 'snapshot_hok.py', 'verify_export.py']:
            transaction.write(ROOT / name / 'ops' / filename, (source / filename).read_text(), 0o755)
        transaction.write(ROOT / name / 'README.md', (source / 'README.md').read_text())
    run('systemd-analyze', 'verify', str(unit))
    run('systemctl', 'daemon-reload')
    transaction.journal['complete'] = True
    transaction.flush()
    print(f'Operations synchronized; file backups: {transaction.directory}')


if __name__ == '__main__':
    main()

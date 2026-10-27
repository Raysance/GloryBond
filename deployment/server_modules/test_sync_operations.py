"""Maintenance synchronization preserves scope and recovers interrupted writes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment.server_modules import sync_operations as sync


class OperationsSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.module = self.base / 'hok'
        self.operations = self.module / 'ops'
        self.operations.mkdir(parents=True)
        (self.module / 'module.json').write_text(json.dumps({'name': 'hok'}))
        self.source = self.base / 'source'
        self.source.mkdir()
        for name in sync.CURRENT:
            (self.source / name).write_text('new ' + name)
            target = self.operations / name
            target.write_text('old ' + name)
            target.chmod(0o755 if name.endswith('.py') else 0o644)
        (self.operations / 'migrate_aliyun.py').write_text('retired')
        (self.module / '.env').write_text('PRIVATE=preserve')
        (self.module / 'service.conf').write_text('service unchanged')
        self.other = self.base / 'other/ops/modulectl.py'
        self.other.parent.mkdir(parents=True)
        self.other.write_text('other module unchanged')

    def test_preview_has_no_filesystem_side_effects(self):
        result = sync.synchronize(self.module, source=self.source)
        self.assertFalse(result['applied'])
        self.assertEqual((self.operations / 'modulectl.py').read_text(), 'old modulectl.py')
        self.assertTrue((self.operations / 'migrate_aliyun.py').exists())
        self.assertFalse((self.module / 'backups').exists())

    def test_apply_archives_retired_files_and_preserves_configuration_and_other_modules(self):
        result = sync.synchronize(self.module, source=self.source, apply=True)
        self.assertTrue(result['applied'])
        self.assertFalse((self.operations / 'migrate_aliyun.py').exists())
        self.assertEqual((Path(result['backup']) / 'migrate_aliyun.py').read_text(), 'retired')
        self.assertEqual((self.module / '.env').read_text(), 'PRIVATE=preserve')
        self.assertEqual((self.module / 'service.conf').read_text(), 'service unchanged')
        self.assertEqual(self.other.read_text(), 'other module unchanged')
        self.assertFalse(sync.synchronize(self.module, source=self.source, apply=True)['applied'])

    def test_failed_update_restores_previous_files_and_modes(self):
        writer = sync.atomic_write
        failed = False

        def fail_once(path, content, mode):
            nonlocal failed
            if path.name == 'snapshot_hok.py' and not failed:
                failed = True
                raise OSError('synthetic interrupted write')
            return writer(path, content, mode)

        with patch.object(sync, 'atomic_write', side_effect=fail_once), self.assertRaises(OSError):
            sync.synchronize(self.module, source=self.source, apply=True)
        for name in sync.CURRENT:
            self.assertEqual((self.operations / name).read_text(), 'old ' + name)
        self.assertTrue((self.operations / 'migrate_aliyun.py').exists())

    def test_replaces_an_operations_file_link_without_modifying_its_target(self):
        target = self.operations / 'modulectl.py'
        target.unlink()
        target.symlink_to(self.other)
        sync.synchronize(self.module, source=self.source, apply=True)
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), 'new modulectl.py')
        self.assertEqual(self.other.read_text(), 'other module unchanged')

    def test_rejects_other_modules_and_shared_operations_directories(self):
        (self.module / 'module.json').write_text(json.dumps({'name': 'other'}))
        with self.assertRaises(ValueError):
            sync.synchronize(self.module, source=self.source, apply=True)
        (self.module / 'module.json').write_text(json.dumps({'name': 'hok'}))
        import shutil
        shutil.rmtree(self.operations)
        self.operations.symlink_to(self.other.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            sync.synchronize(self.module, source=self.source, apply=True)
        self.assertEqual(self.other.read_text(), 'other module unchanged')

"""Publication permissions survive restrictive umasks without exposing private files."""

import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from deployment.scripts.public_artifact_permissions import nginx_group, prepare


class PublicArtifactPermissionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.public = self.root / 'file_transfer'
        self.public.mkdir(mode=0o700)
        self.file = self.public / 'battle.json'
        self.file.write_text('{"gameSeq":"123"}')
        self.file.chmod(0o600)
        self.private = self.root / '.env'
        self.private.write_text('TOKEN=private')
        self.private.chmod(0o600)

    def test_preview_changes_nothing_and_apply_keeps_private_files_and_links_untouched(self):
        (self.public / 'private-link').symlink_to(self.private)
        outside = self.root / 'private-directory'
        outside.mkdir(mode=0o700)
        (self.public / 'directory-link').symlink_to(outside, target_is_directory=True)
        before = stat.S_IMODE(self.public.stat().st_mode)
        self.assertFalse(prepare(self.public, os.getgid())['applied'])
        self.assertEqual(stat.S_IMODE(self.public.stat().st_mode), before)
        result = prepare(self.public, os.getgid(), apply=True)
        self.assertEqual(result['symlinks_skipped'], 2)
        self.assertTrue(self.public.stat().st_mode & stat.S_ISGID)
        self.assertEqual(stat.S_IMODE(self.private.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o700)
        self.assertEqual(self.file.read_text(), '{"gameSeq":"123"}')
        self.assertFalse(self.file.stat().st_mode & stat.S_IROTH)
        repeated = prepare(self.public, os.getgid(), apply=True)
        self.assertEqual((repeated['directories_changed'], repeated['files_changed']), (0, 0))

    def test_new_directories_and_files_inherit_the_read_group_under_service_umask(self):
        prepare(self.public, os.getgid(), apply=True)
        previous = os.umask(0o027)
        try:
            nested = self.public / 'new-results'
            nested.mkdir()
            artifact = nested / 'battle.json'
            artifact.write_text('{}')
        finally:
            os.umask(previous)
        self.assertEqual(artifact.stat().st_gid, self.public.stat().st_gid)
        self.assertTrue(artifact.stat().st_mode & stat.S_IRGRP)
        if sys.platform.startswith('linux'):
            self.assertTrue(nested.stat().st_mode & stat.S_ISGID)
        self.assertTrue(nested.stat().st_mode & stat.S_IXGRP)
        self.assertFalse(artifact.stat().st_mode & stat.S_IROTH)

    def test_application_root_is_rejected_before_permission_changes(self):
        with self.assertRaises(ValueError):
            prepare(self.root, os.getgid(), apply=True)
        self.assertEqual(stat.S_IMODE(self.private.stat().st_mode), 0o600)

    def test_worker_group_detection_preserves_an_accessible_installer_public_group(self):
        proc = self.root / 'proc'
        for pid, uid, gid, groups in (('10', 0, 0, '0'), ('11', 1001, 2001, '2001 '+str(os.getgid()))):
            process = proc / pid
            process.mkdir(parents=True)
            (process / 'comm').write_text('nginx\n')
            (process / 'status').write_text(f'Uid:\t{uid} {uid} {uid} {uid}\nGid:\t{gid} {gid} {gid} {gid}\nGroups:\t{groups}\n')
        self.assertEqual(nginx_group(self.public, proc), 2001)
        self.public.chmod(0o2750)
        self.assertEqual(nginx_group(self.public, proc), os.getgid())

    def test_missing_worker_does_not_guess_a_private_group(self):
        proc = self.root / 'proc'
        proc.mkdir()
        with self.assertRaises(RuntimeError):
            nginx_group(self.public, proc)

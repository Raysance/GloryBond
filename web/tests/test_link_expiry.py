"""File-backed links expire at the same boundary as Redis-backed links."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from web import app as web


class BenefitLinkExpiryTests(unittest.TestCase):
    def test_day_boundary_and_reads_do_not_renew_the_link(self):
        now = 1800000000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'temp_files' / 'saved.json'
            path.parent.mkdir()
            path.write_text('{}')
            created_at = now - 86399
            os.utime(path, (created_at, created_at))
            with patch.object(web, 'file_path_root', directory), \
                 patch.object(web, 'REDIS_TEXT_EXPIRE_SECONDS', 86400), \
                 patch.object(web, 'should_track_request', return_value=False), \
                 patch.object(web.time, 'time', return_value=now) as clock:
                client = TestClient(web.app)
                for key in ('saved', 'saved.json'):
                    self.assertEqual(client.get('/benefit', params={'key': key}).status_code, 200)
                self.assertEqual(path.stat().st_mtime, created_at)
                clock.return_value = now + 1
                expired = client.get('/benefit', params={'key': 'saved'})
                self.assertEqual(expired.status_code, 410)
                self.assertEqual(expired.headers['cache-control'], 'no-store')
                self.assertEqual(client.get('/benefit', params={'key': 'missing'}).status_code, 410)

    def test_invalid_path_is_rejected_before_file_access(self):
        with patch.object(web, 'should_track_request', return_value=False), patch.object(web.asyncio, 'to_thread') as stat:
            response = TestClient(web.app).get('/benefit', params={'key': '../private'})
            self.assertIn('key非法', response.text)
            stat.assert_not_called()


if __name__ == '__main__':
    unittest.main()

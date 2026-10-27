"""Readiness checks for the current Bot/Web deployment."""
from io import BytesIO
import unittest
from unittest.mock import Mock, patch

from deployment.scripts import verify_startup


class DeploymentReadinessTests(unittest.TestCase):
    def test_readiness_requires_both_services_and_web_health(self):
        opener = Mock()
        opener.open.return_value = BytesIO(b'{"status":"ok"}')
        with patch.object(verify_startup, "unit_property", side_effect=lambda unit, name:
                          "active" if name == "ActiveState" else "invocation"), \
             patch.object(verify_startup.subprocess, "check_output", return_value="Application startup complete."), \
             patch.object(verify_startup, "build_opener", return_value=opener):
            verify_startup.verify()
        opener.open.assert_called_once()

    def test_readiness_rejects_a_bot_restart(self):
        with patch.object(verify_startup, "unit_property", side_effect=["old", "new"]):
            with self.assertRaisesRegex(RuntimeError, "restarted"):
                verify_startup.verify()


if __name__ == "__main__":
    unittest.main()

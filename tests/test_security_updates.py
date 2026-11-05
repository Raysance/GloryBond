from pathlib import Path
import subprocess
import unittest


SCRIPT = (Path(__file__).parents[1] / "deployment/server_modules/security_updates.sh").read_text()


class MaintenanceGuardTests(unittest.TestCase):
    def test_health_propagates_failures_even_in_a_shell_conditional(self):
        # errexit is disabled inside functions called by `if`; each check must
        # explicitly return its failure, rather than accepting the final SQL ping.
        health = SCRIPT.split("health() {", 1)[1].split("\npreflight() {", 1)[0]
        for failing in ("nginx", "sshd", "systemctl", "curl", "redis-cli", "runuser"):
            with self.subTest(failing=failing):
                mocks = """
nginx() { return 0; }
sshd() { return 0; }
systemctl() { return 0; }
curl() { printf 200; }
redis-cli() { printf 'PONG\\n'; }
runuser() { printf '1\\n'; }
CRITICAL_UNITS=(example.service)
HEALTH_URLS=(https://example.invalid/health)
HEALTH_CODES=(200)
CURL_RESOLVE=()
"""
                code = "set -Eeuo pipefail\nhealth() {" + health + mocks
                code += "\n" + failing + "() { return 1; }\nif health; then exit 0; else exit 1; fi"
                result = subprocess.run(["bash", "-c", code], capture_output=True)
                self.assertEqual(result.returncode, 1, result.stderr.decode())

    def test_repository_error_is_not_treated_as_no_updates(self):
        function = SCRIPT.split("candidate_check() {", 1)[1].split("\nrollback_node() {", 1)[0]
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            code = "set -Eeuo pipefail\ncandidate_check() {" + function
            code += "\nSTATE_DIR=$1\ncommon=()\nchanges=0\ndnf() { return 1; }\n"
            code += "if candidate_check --security; then exit 0; else exit 1; fi"
            result = subprocess.run(["bash", "-c", code, "test", directory], capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()

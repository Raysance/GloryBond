import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "update_node_runtime",
    Path(__file__).parents[1] / "deployment/server_modules/update_node_runtime.py",
)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class NodeUpdateSelectionTests(unittest.TestCase):
    def test_only_same_major_and_matching_architecture(self):
        releases = [
            {"version": "v24.1.0", "files": ["linux-x64"]},
            {"version": "v22.9.0", "files": ["linux-x64"]},
            {"version": "v22.10.0", "files": ["linux-x64"]},
            {"version": "v22.99.0", "files": ["linux-arm64"]},
            {"version": "v22.100.0-rc.1", "files": ["linux-x64"]},
        ]
        self.assertEqual(updater.latest_release(releases, 22), "v22.10.0")

    def test_checksum_must_name_the_exact_archive_once(self):
        digest = "a" * 64
        filename = "node-v22.10.0-linux-x64.tar.xz"
        self.assertEqual(updater.expected_checksum(digest + "  " + filename, filename), digest)
        for manifest in (digest + "  other.tar.xz", "bad  " + filename,
                         (digest + "  " + filename + "\n") * 2):
            with self.assertRaises(ValueError):
                updater.expected_checksum(manifest, filename)

    def test_version_rejects_path_and_prerelease_input(self):
        for value in ("../v22.1.0", "v22.1.0-rc1", "22.1.0", "v22.1.0\n"):
            with self.assertRaises(ValueError):
                updater.version_tuple(value)


if __name__ == "__main__":
    unittest.main()

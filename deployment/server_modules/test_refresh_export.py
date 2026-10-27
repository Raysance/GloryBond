"""Offline fixtures for the packaging-only HOK vendor supplement."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import refresh_export
import verify_export


class RefreshExportTests(unittest.TestCase):
    def fixture(self, root, corrupt=False, legacy_modes=False):
        module = root / "hok"
        vendor = module / refresh_export.VENDOR
        vendor.mkdir(parents=True)
        for relative in ["package/index.js", "package/logs/code.js", "package/node_modules/transitive/index.js", ".git/vendor-metadata", "package/cache.pyc"]:
            path = vendor / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("vendor fixture " + relative)
        (vendor / "package/index.js").chmod(0o755)
        outside = root / "outside"
        outside.mkdir()
        (outside / "must-not-copy.txt").write_text("outside private contents")
        (vendor / "external-link").symlink_to(outside, target_is_directory=True)
        source = root / "sources"
        source.mkdir()
        (source / "modulectl.py").write_text("# updated management tool\n")
        (source / "README.md").write_text("Updated instructions\n")
        export = root / "exports"
        export.mkdir(mode=0o700)
        original = export / "original.tar.gz"
        files = {
            "hok/ops/modulectl.py": b"# previous tool\n",
            "hok/README.md": b"Previous instructions\n",
            "hok/data/runtime.json": b'{"unchanged": true}',
            "hok/apps/existing.txt": b"original application bytes",
            "hok/snapshots/postgresql.dump": b"PGDMP\x01old consistent database",
            "hok/snapshots/redis-db0-hok.jsonl": b'{"type":"metadata","db":0,"pattern":"hok:*"}\n{"type":"summary","key_count":0}\n',
        }
        snapshot = {"created_at": "2026-09-29T07:49:34+00:00", "sha256": {
            path.rsplit("/", 1)[1]: hashlib.sha256(data).hexdigest()
            for path, data in files.items() if "/snapshots/" in path
        }}
        metadata = {"module": "hok", "created_at": "original-export-created-at", "snapshot": snapshot,
                    "capture_mode": "quiesced", "quiesce": {"restore_active": True},
                    "excluded_names": ["node_modules", ".git", ".venv"], "entries": []}
        with tarfile.open(original, "w:gz") as archive:
            root_info = tarfile.TarInfo("hok")
            root_info.type = tarfile.DIRTYPE
            root_info.mode = 0o755
            archive.addfile(root_info)
            metadata["entries"].append({"path": "hok", "type": "directory", "mode": "0o40755" if legacy_modes else "0o755"})
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if name == "hok/ops/modulectl.py" else 0o640
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
                metadata["entries"].append({"path": name, "type": "file", "mode": oct(info.mode | (0o100000 if legacy_modes else 0)), "size": len(data),
                                            "sha256": "corrupt" if corrupt and name.endswith("runtime.json") else hashlib.sha256(data).hexdigest()})
            info = tarfile.TarInfo("hok/data/runtime-link")
            info.type = tarfile.SYMTYPE
            info.linkname = "runtime.json"
            info.mode = 0o777
            archive.addfile(info)
            metadata["entries"].append({"path": info.name, "type": "symlink", "target": "runtime.json", "mode": "0o120777" if legacy_modes else "0o777"})
            data = json.dumps(metadata).encode()
            info = tarfile.TarInfo("hok/export-manifest.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        return module, source, original, files, metadata

    def test_refresh_preserves_snapshots_and_state_adds_full_vendor_without_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, source, original, files, original_metadata = self.fixture(Path(temporary))
            input_digest = refresh_export.sha256_file(original)
            output = original.with_name("complete.tar.gz")
            with patch.object(refresh_export.modulectl.subprocess, "run", side_effect=AssertionError("No service/DB subprocess is allowed")):
                result = refresh_export.refresh(original, module, output, source)
            self.assertEqual(refresh_export.sha256_file(original), input_digest)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            checksum = output.with_name(output.name + ".sha256")
            self.assertEqual(checksum.stat().st_mode & 0o777, 0o600)
            self.assertEqual(checksum.read_text().split()[0], refresh_export.sha256_file(output))
            self.assertTrue(result["snapshot_unchanged"])
            verified = verify_export.verify(output)
            self.assertTrue(verified["postgres_custom_dump"])
            self.assertEqual(verified["capture_mode"], "quiesced")
            with tarfile.open(output) as archive:
                names = archive.getnames()
                self.assertEqual(len(names), len(set(names)))
                for name, data in files.items():
                    if name not in {"hok/README.md", "hok/ops/modulectl.py"}:
                        self.assertEqual(archive.extractfile(name).read(), data)
                self.assertEqual(archive.extractfile("hok/README.md").read(), (source / "README.md").read_bytes())
                self.assertEqual(archive.extractfile("hok/ops/modulectl.py").read(), (source / "modulectl.py").read_bytes())
                self.assertEqual(archive.getmember("hok/ops/modulectl.py").mode, 0o755)
                vendor_prefix = "hok/" + refresh_export.VENDOR
                for relative in ["package/logs/code.js", "package/node_modules/transitive/index.js", ".git/vendor-metadata", "package/cache.pyc"]:
                    self.assertIn(vendor_prefix + "/" + relative, names)
                self.assertTrue(archive.getmember(vendor_prefix + "/external-link").issym())
                self.assertFalse(any("must-not-copy.txt" in name for name in names))
                self.assertEqual(archive.getmember(vendor_prefix + "/package/index.js").mode, 0o755)
                metadata = json.load(archive.extractfile("hok/export-manifest.json"))
                self.assertEqual(metadata["snapshot"], original_metadata["snapshot"])
                self.assertEqual(metadata["created_at"], original_metadata["created_at"])
                self.assertEqual(metadata["quiesce"], original_metadata["quiesce"])
                self.assertEqual(metadata["entry_count"], len(names) - 1)
                self.assertNotIn("node_modules", metadata["excluded_names"])
                self.assertEqual(metadata["conditional_exclusions"]["node_modules"]["included_complete_subtrees"], ["hok/" + refresh_export.VENDOR])
                self.assertEqual(metadata["conditional_exclusions"]["node_modules"]["excluded_subtrees"], ["personal-site/apps/site/node_modules"])
                self.assertEqual(metadata["packaging_updates"][0]["original_archive_sha256"], input_digest)
                self.assertEqual(metadata["packaging_updates"][0]["original_snapshot_captured_at"], original_metadata["snapshot"]["created_at"])

    def test_corrupt_original_manifest_aborts_without_publishing(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, source, original, _, _ = self.fixture(Path(temporary), corrupt=True)
            output = original.with_name("complete.tar.gz")
            with self.assertRaisesRegex(ValueError, "manifest hash/metadata mismatch"):
                refresh_export.refresh(original, module, output, source)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_name(output.name + ".sha256").exists())

    def test_legacy_stat_modes_include_file_type_bits_but_hashes_remain_strict(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, source, original, _, _ = self.fixture(Path(temporary), legacy_modes=True)
            output = original.with_name("complete.tar.gz")
            refresh_export.refresh(original, module, output, source)
            self.assertTrue(verify_export.verify(output)["postgres_custom_dump"])
            with tarfile.open(output) as archive:
                self.assertEqual(archive.getmember("hok").mode, 0o755)
                self.assertEqual(archive.getmember("hok/ops/modulectl.py").mode, 0o755)
                self.assertEqual(archive.getmember("hok/data/runtime-link").mode, 0o777)
        with tempfile.TemporaryDirectory() as temporary:
            module, source, original, _, _ = self.fixture(Path(temporary), corrupt=True, legacy_modes=True)
            with self.assertRaisesRegex(ValueError, "manifest hash/metadata mismatch"):
                refresh_export.refresh(original, module, original.with_name("complete.tar.gz"), source)

    def test_never_overwrites_original_or_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, source, original, _, _ = self.fixture(Path(temporary))
            before = original.read_bytes()
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                refresh_export.refresh(original, module, original, source)
            self.assertEqual(original.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

"""Checks for the read-only performance artifact inventory."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "p7a_artifacts", Path(__file__).parent / "scripts/notrios_p7a_artifacts.py")
artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifacts)


class ArtifactInventoryTests(unittest.TestCase):
    def test_recursive_sizes_ignore_external_symlinks_and_own_manifest(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            root = base / "run"
            (root / "stage" / "nested").mkdir(parents=True)
            (root / "summary.json").write_bytes(b"123")
            (root / "stage" / "nested" / "data").write_bytes(b"45678")
            (base / "external").write_bytes(b"do not inspect me")
            (root / "link").symlink_to(base / "external")
            (root / "cycle").symlink_to(root, target_is_directory=True)
            (root / "ARTIFACT_MANIFEST.json").write_bytes(b"old report")
            report = artifacts.inventory(root)
            self.assertEqual(report["total_files"], 2)
            self.assertEqual(report["total_logical_bytes"], 8)
            self.assertEqual(report["directories"][0]["ignored_symlinks"], 2)
            self.assertFalse(report["deletion_authorized"])
            self.assertEqual((base / "external").read_bytes(), b"do not inspect me")

    def test_terminal_status_is_not_deletion_authorization(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "notification.json").write_text('{"status":"complete"}')
            report = artifacts.inventory(root)
            self.assertEqual(report["run_status"], "complete")
            self.assertFalse(report["deletion_authorized"])
            self.assertGreater(len(report["cleanup_conditions"]), 0)


if __name__ == "__main__":
    unittest.main()

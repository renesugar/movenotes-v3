"""Focused checks for the P7c disposable variant and benchmark harnesses."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_script("notrios_p7c_prepare.py")
benchmark = load_script("notrios_p7c_benchmark.py")
subset = load_script("notrios_p7c_recipe_subset.py")
merge_fixture = load_script("notrios_p7c_merge_fixture.py")
long_batch = load_script("notrios_p7c_long_batch.py")


class P7cPrepareTests(unittest.TestCase):
    def test_variant_transforms_are_isolated(self) -> None:
        f02 = "        notesdb.ensure_joplin_id_index(sqlconn)\n"
        candidate = (
            "prefix\n"
            + f02
            + "def _native_rows(\n"
            + "    values: list[tuple[Path, str]]\n"
            + "    return values\n"
            + "def main(argv: list[str]) -> int:\n"
            + "    return 0\n"
        )
        reference = (
            "prefix\n"
            + f02
            + "def _native_rows(\n"
            + "    values: list[Path]\n"
            + "    return values\n"
            + "def main(argv: list[str]) -> int:\n"
            + "    return 0\n"
        )
        no_f02 = prepare._without_f02(candidate)
        self.assertNotIn(f02, no_f02)
        no_f04 = prepare._without_f04(candidate, reference)
        self.assertIn("list[Path]", no_f04)
        self.assertNotIn("list[tuple[Path, str]]", no_f04)
        with self.assertRaises(ValueError):
            prepare._without_f02(no_f02)

    def test_recipe_subset_is_deterministic_and_preserves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            first = source / "z" / "first.md"
            second = source / "a" / "second.md"
            config = source / "config.json"
            ignored = source / "asset.bin"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("first\n", encoding="utf-8")
            second.write_text("second\n", encoding="utf-8")
            config.write_text("{}\n", encoding="utf-8")
            ignored.write_bytes(b"ignored")
            os.utime(first, ns=(1_000_000_001, 1_000_000_002))
            result = subset.build_subset(source, root / "subset", 1)
            self.assertEqual(result["full_markdown_count"], 2)
            self.assertEqual(result["selected_markdown_count"], 1)
            self.assertEqual(result["metadata_config_count"], 1)
            selected_entry = next(item for item in result["source_files"] if item["kind"] == "markdown")
            selected = root / "subset" / "vault" / selected_entry["path"]
            selected_source = source / selected_entry["path"]
            self.assertTrue(selected.is_file())
            self.assertEqual((root / "subset" / "vault" / "config.json").read_text(), "{}\n")
            self.assertFalse((root / "subset" / "vault" / "asset.bin").exists())
            self.assertTrue((root / "subset" / "SUBSET_MANIFEST.json").is_file())
            self.assertFalse((root / "subset" / "vault" / "SUBSET_MANIFEST.json").exists())
            self.assertEqual(selected.stat().st_mtime_ns, selected_source.stat().st_mtime_ns)


class P7cBenchmarkTests(unittest.TestCase):
    def test_time_record_and_comparison_capture_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics"
            path.write_text("P7C_TIME 1.25 0.75 0.20 4096 7\n", encoding="utf-8")
            parsed = benchmark._parse_time(path)
        self.assertEqual(parsed["max_rss_kib"], 4096)
        self.assertEqual(parsed["filesystem_input_operations"], 7)
        records = [
            {
                "case": "native",
                "pair": 1,
                "side": "left",
                "status": "complete",
                "wall_seconds": 10.0,
                "max_rss_kib": 100,
                "fingerprint": {"notes_sha256": "same"},
            },
            {
                "case": "native",
                "pair": 1,
                "side": "right",
                "status": "complete",
                "wall_seconds": 8.0,
                "max_rss_kib": 90,
                "fingerprint": {"notes_sha256": "same"},
            },
        ]
        comparison = benchmark._comparison(records, ["native"], 1)["native"]
        self.assertTrue(comparison["all_fingerprints_equal"])
        self.assertEqual(comparison["pairs"][0]["right_minus_left_seconds"], -2.0)
        self.assertEqual(comparison["pairs"][0]["right_max_rss_kib"], 90)

    def test_matrix_requires_both_sides_and_resume_uses_new_attempt_path(self) -> None:
        record = {
            "case": "native",
            "pair": 1,
            "side": "left",
            "status": "complete",
            "attempt": 1,
        }
        self.assertFalse(benchmark._matrix_complete([record], ["native"], 1))
        complete = [
            {**record, "side": "left", "fingerprint": {"notes_sha256": "x"}},
            {**record, "side": "right", "fingerprint": {"notes_sha256": "x"}},
        ]
        self.assertTrue(benchmark._matrix_complete(complete, ["native"], 1))
        self.assertFalse(benchmark._matrix_complete(complete + [{**record, "case": "extra", "side": "left", "fingerprint": {"notes_sha256": "x"}}], ["native"], 1))
        self.assertFalse(benchmark._matrix_complete([], [], 1))
        self.assertEqual(
            benchmark._attempt_destination(Path("/tmp/out"), "native", 1, "left", 2),
            Path("/tmp/out/native/pair-01/left-attempt-02"),
        )

    def test_persist_is_atomic_and_records_notification_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            metadata = {"cases": ["native"], "pairs": 1}
            records = []
            benchmark._persist(output, "running", records, metadata)
            results = json.loads((output / "results.json").read_text(encoding="utf-8"))
            notification = json.loads((output / "notification.json").read_text(encoding="utf-8"))
        self.assertEqual(results["status"], "running")
        self.assertIn("harness_sha256", results)
        self.assertEqual(notification["total_records"], 2)
        self.assertFalse((output / "results.json.tmp").exists())

    def test_resume_drops_inherited_runtime_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            metadata = {"cases": ["native"], "pairs": 1}
            benchmark._persist(output, "complete", [], metadata)
            payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
            loaded, records = benchmark._load_resume(output)
        self.assertNotIn("status", loaded)
        self.assertNotIn("records", loaded)
        self.assertEqual(records, [])
        self.assertEqual(payload["status"], "complete")

    def test_changed_completed_output_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            destination = output / "native" / "pair-01" / "left"
            destination.mkdir(parents=True)
            database = destination / "notesdb.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE notes (note_id INTEGER, joplin_id TEXT, joplin_type_ INTEGER, note_uuid TEXT, note_obsidian_path TEXT)"
                )
                connection.execute("INSERT INTO notes VALUES (1, 'id', 1, 'uuid', 'note.md')")
                connection.commit()
            fingerprint = benchmark._fingerprint(database, destination / "resources")
            record = {
                "status": "complete",
                "destination": "native/pair-01/left",
                "fingerprint": fingerprint,
            }
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO notes VALUES (2, 'id2', 1, 'uuid2', 'two.md')")
                connection.commit()
            with self.assertRaises(SystemExit):
                benchmark._verify_completed_outputs(output, [record])

    def test_prepared_seed_clone_is_hash_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = root / "seed"
            destination = root / "destination"
            seed.mkdir()
            (seed / "notesdb.sqlite").write_bytes(b"seed")
            (seed / "resources").mkdir()
            phase = benchmark._clone_seed(seed, destination)
            self.assertEqual(phase["seed_source_sha256"], phase["seed_clone_sha256"])
            self.assertEqual((destination / "notesdb.sqlite").read_bytes(), b"seed")

    def test_replay_logs_refuse_clobber_and_use_attempt_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / "left-fresh.log").write_text("old\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                benchmark._phase_paths(stage, "left", "fresh", 1)
            log, metrics = benchmark._phase_paths(stage, "left", "fresh", 2)
            self.assertEqual(log.name, "left-fresh-attempt-02.log")
            self.assertEqual(metrics.name, "left-fresh-attempt-02.time")
            batch_log = long_batch.next_batch_log(stage, "matrix")
            batch_log.write_text("old batch\n", encoding="utf-8")
            self.assertEqual(long_batch.next_batch_log(stage, "matrix").name, "matrix-attempt-02.log")

    def test_disjoint_merge_fixture_has_no_import_identity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = merge_fixture.build_fixture(Path(directory) / "fixture", 3)
            vault = Path(directory) / "fixture" / "vault"
            files = sorted(vault.rglob("*.md"))
            self.assertEqual(result["count"], 3)
            self.assertEqual(len(files), 3)
            self.assertTrue(all(".movenotes" not in path.parts for path in files))
            self.assertTrue(all("tags:" not in path.read_text(encoding="utf-8") for path in files))
            self.assertTrue(all(not path.read_text(encoding="utf-8").startswith("---") for path in files))
            self.assertTrue((Path(directory) / "fixture" / "MERGE_FIXTURE_MANIFEST.json").is_file())


if __name__ == "__main__":
    unittest.main()

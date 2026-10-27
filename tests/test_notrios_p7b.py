"""Focused checks for the P7b comparison harness itself."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import notesdb


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "notrios_p7b_benchmark.py"
SPEC = importlib.util.spec_from_file_location("notrios_p7b_benchmark", SCRIPT)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class P7bFingerprintTest(unittest.TestCase):
    def _database(self, root: Path) -> Path:
        database = root / "notesdb.sqlite"
        conn = notesdb.connect(database)
        notesdb.create_database(conn)
        notesdb.add_joplin_note(conn, {
            "note_uuid": "a" * 32, "joplin_id": "a" * 32,
            "note_title": "title", "note_data": "body", "note_source_raw": b"raw",
            "note_source_sha256": b"x" * 32, "joplin_type_": 1,
            "joplin_created_time": "2020-01-01T00:00:00.000Z",
        })
        conn.execute("CREATE TABLE aux (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO aux VALUES ('key', 'value')")
        conn.commit()
        conn.close()
        return database

    def test_fingerprint_detects_content_timestamp_auxiliary_and_resource_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"; second = root / "second"
            first.mkdir(); second.mkdir()
            db1 = self._database(first); db2 = self._database(second)
            for directory in (first / "resources", second / "resources"):
                directory.mkdir(); (directory / "resource.bin").write_bytes(b"same")
            self.assertEqual(benchmark._fingerprint(db1, first / "resources"), benchmark._fingerprint(db2, second / "resources"))
            mutations = [
                ("UPDATE notes SET note_data='changed'", first / "resources"),
                ("UPDATE notes SET note_source_raw=X'6368616e676564'", first / "resources"),
                ("UPDATE notes SET joplin_created_time='2021-01-01T00:00:00.000Z'", first / "resources"),
                ("UPDATE aux SET value='changed'", first / "resources"),
            ]
            for statement, resources in mutations:
                before = benchmark._fingerprint(db1, resources)
                conn = sqlite3.connect(db1); conn.execute(statement); conn.commit(); conn.close()
                self.assertNotEqual(before, benchmark._fingerprint(db1, resources))
            before = benchmark._fingerprint(db1, first / "resources")
            (first / "resources" / "resource.bin").write_bytes(b"changed")
            self.assertNotEqual(before, benchmark._fingerprint(db1, first / "resources"))

    def test_persist_keeps_metadata_on_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            benchmark._persist(root, [], "failed", input_sha256={"raw": "x"}, source_sha256={"candidate": "y"}, reason="exception")
            import json
            result = json.loads((root / "results.json").read_text())
            notification = json.loads((root / "notification.json").read_text())
            self.assertEqual(result["input_sha256"]["raw"], "x")
            self.assertEqual(notification["source_sha256"]["candidate"], "y")

    def test_recompare_rejects_empty_partial_duplicate_and_failed_record_sets(self) -> None:
        variants = [
            {"cases": [], "pairs": 0, "records": []},
            {"cases": ["native"], "pairs": 1, "records": [{"case": "native", "pair": 1, "side": "baseline", "returncode": 0}]},
            {"cases": ["native"], "pairs": 1, "records": [{"case": "native", "pair": 1, "side": "baseline", "returncode": 0}, {"case": "native", "pair": 1, "side": "baseline", "returncode": 0}]},
            {"cases": ["native"], "pairs": 1, "records": [{"case": "native", "pair": 1, "side": "baseline", "returncode": 1}, {"case": "native", "pair": 1, "side": "candidate", "returncode": 0}]},
        ]
        import json
        for result in variants:
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                result.update({"source_sha256": {"baseline": "x", "candidate": "x"}, "input_sha256": {"vault": "x", "raw": "x", "preserved": "x"}})
                (root / "results.json").write_text(json.dumps(result))
                with mock.patch.object(benchmark, "_tree_sha256", return_value="x"):
                    self.assertEqual(benchmark._recompare(root, {"baseline": root, "candidate": root}, {"vault": root, "raw": root, "preserved": root}), 3)

    def test_generated_tag_envelope_normalizes_only_its_four_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"; second = root / "second"
            first.mkdir(); second.mkdir()
            db1 = self._database(first); db2 = self._database(second)
            properties = [["id", "tag"], ["created_time", "first"], ["unknown", "kept"], ["updated_time", "first"], ["user_created_time", "first"], ["user_updated_time", "first"]]
            for database, stamp in ((db1, "first"), (db2, "second")):
                conn = sqlite3.connect(database)
                value = [[key, stamp if key.endswith("time") else item] for key, item in properties]
                conn.execute("UPDATE notes SET joplin_type_=5, note_obsidian_path='.movenotes/tags/tag', note_source_properties=?, note_data='body', joplin_created_time=?", (json.dumps(value), stamp))
                conn.commit(); conn.close()
            (first / "resources").mkdir(); (second / "resources").mkdir()
            self.assertEqual(benchmark._fingerprint(db1, first / "resources"), benchmark._fingerprint(db2, second / "resources"))
            conn = sqlite3.connect(db2); conn.execute("UPDATE notes SET note_source_properties=?", (json.dumps([["unknown", "changed"]] + properties[1:]),)); conn.commit(); conn.close()
            self.assertNotEqual(benchmark._fingerprint(db1, first / "resources"), benchmark._fingerprint(db2, second / "resources"))
            conn = sqlite3.connect(db2); conn.execute("UPDATE notes SET joplin_type_=1, note_obsidian_path='note.md', joplin_created_time='third'"); conn.commit(); conn.close()
            self.assertNotEqual(benchmark._fingerprint(db1, first / "resources"), benchmark._fingerprint(db2, second / "resources"))

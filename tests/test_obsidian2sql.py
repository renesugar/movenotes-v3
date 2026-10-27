#!/usr/bin/env python3
"""Round-trip and regression tests for Obsidian import support."""

from __future__ import annotations

import configparser
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import constants
import common
import notesdb
import obsidian2sql
import sql2obsidian

PROJECT_DIR = Path(__file__).resolve().parent.parent


def run(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROJECT_DIR / script), *args],
        capture_output=True,
        text=True,
        check=check,
    )


class ObsidianRoundTripTest(unittest.TestCase):
    def test_same_batch_item_id_collision_is_rejected_before_insert(self) -> None:
        """A batch must not bypass the exact-source identity collision rule."""
        with tempfile.TemporaryDirectory(prefix="obsidian-batch-collision-") as temporary:
            database = Path(temporary) / notesdb.DATABASE_FILENAME
            conn = notesdb.connect(database)
            self.addCleanup(conn.close)
            notesdb.create_database(conn)
            item_id = "a" * 32
            first = {
                "joplin_id": item_id,
                "note_uuid": item_id,
                "note_obsidian_sha256": b"a" * 32,
            }
            second = {**first, "note_obsidian_sha256": b"b" * 32}
            with self.assertRaisesRegex(SystemExit, "item id collision"):
                obsidian2sql._insert_rows(conn, [first, second], 500)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0
            )
            inserted, skipped = obsidian2sql._insert_rows(conn, [first, first], 500)
            self.assertEqual((inserted, skipped), (1, 1))

    def test_cross_batch_collision_can_rollback_the_import_transaction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-cross-batch-collision-") as temporary:
            conn = notesdb.connect(Path(temporary) / notesdb.DATABASE_FILENAME)
            self.addCleanup(conn.close)
            notesdb.create_database(conn)
            item_id = "c" * 32
            first = {"joplin_id": item_id, "note_uuid": item_id, "note_obsidian_sha256": b"a" * 32}
            second = {**first, "note_obsidian_sha256": b"b" * 32}
            conn.execute("BEGIN")
            obsidian2sql._insert_rows(conn, [first], 1)
            with self.assertRaisesRegex(SystemExit, "item id collision"):
                obsidian2sql._insert_rows(conn, [second], 1)
            conn.rollback()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)

    def test_preservation_resource_collision_keeps_existing_bytes(self) -> None:
        """Preservation must never replace a resource with the same name."""
        with tempfile.TemporaryDirectory(prefix="obsidian-resource-collision-") as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            name = "a" * 32 + ".bin"
            (source / name).write_bytes(b"preserved source")
            existing = destination / name
            existing.write_bytes(b"existing destination")
            with self.assertRaisesRegex(SystemExit, "resource collision"):
                common.copy_resources(source, destination, reject_collisions=True)
            self.assertEqual(existing.read_bytes(), b"existing destination")

    def test_preservation_resource_prevalidation_avoids_partial_copy_and_rows(self) -> None:
        """A later resource collision leaves no earlier resource or row behind."""
        with tempfile.TemporaryDirectory(prefix="obsidian-resource-barrier-") as temporary:
            root = Path(temporary)
            raw = root / "raw"
            sqlite1 = root / "sqlite1"
            vault = root / "vault"
            sqlite2 = root / "sqlite2"
            for path in (raw / "resources", sqlite1, vault, sqlite2 / "resources"):
                path.mkdir(parents=True, exist_ok=True)
            first_id = "a" * 32
            colliding_id = "b" * 32
            for resource_id, payload in ((first_id, b"first"), (colliding_id, b"source")):
                (raw / f"{resource_id}.md").write_text(
                    f"{resource_id}.bin\n\nid: {resource_id}\nfilename: {resource_id}.bin\n"
                    "file_extension: bin\nmime: application/octet-stream\n"
                    f"size: {len(payload)}\ntype_: 4\n",
                    encoding="utf-8",
                )
                (raw / "resources" / f"{resource_id}.bin").write_bytes(payload)
            run("joplin2sql.py", "--input", str(raw), "--output", str(sqlite1), "--progress-every", "0")
            run("sql2obsidian.py", "--input", str(sqlite1), "--output", str(vault), "--progress-every", "0")
            existing = sqlite2 / "resources" / f"{colliding_id}.bin"
            existing.write_bytes(b"destination")
            result = run(
                "obsidian2sql.py", "--input", str(vault), "--output", str(sqlite2),
                "--progress-every", "0", check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("resource collision", result.stderr)
            self.assertFalse((sqlite2 / "resources" / f"{first_id}.bin").exists())
            self.assertEqual(existing.read_bytes(), b"destination")
            conn = sqlite3.connect(sqlite2 / notesdb.DATABASE_FILENAME)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)
            finally:
                conn.close()

    def test_folder_parent_lookup_uses_existing_import_time_index(self) -> None:
        """The fresh-import folder repair does not make a parent table scan."""
        with tempfile.TemporaryDirectory(prefix="obsidian-folder-index-") as temporary:
            conn = notesdb.connect(Path(temporary) / notesdb.DATABASE_FILENAME)
            self.addCleanup(conn.close)
            notesdb.create_database(conn, create_indexes=False)
            notesdb.ensure_joplin_id_index(conn)
            plan = conn.execute(
                "EXPLAIN QUERY PLAN SELECT parent.note_title FROM notes AS parent "
                "WHERE parent.joplin_id = ? AND parent.joplin_type_ = ? "
                "ORDER BY parent.note_id LIMIT 1",
                ("f" * 32, int(constants.JoplinType.FOLDER)),
            ).fetchall()
            self.assertTrue(
                any("joplinididx" in str(row[-1]) for row in plan), plan
            )

    def test_fresh_import_batch_id_lookups_use_the_index(self) -> None:
        """No batch of a fresh import scans the rows imported before it."""
        with tempfile.TemporaryDirectory(prefix="obsidian-batch-index-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            output = root / "sqlite"
            (vault / "folder").mkdir(parents=True)
            output.mkdir()
            for index in range(4):
                (vault / "folder" / f"note {index}.md").write_text(
                    f"# Note {index}\n\nbody {index}\n", encoding="utf-8"
                )
            plans: list[str] = []
            original = obsidian2sql._existing_import_hashes

            def recording(sqlconn: sqlite3.Connection, item_ids: list[str]):
                plans.append(" ".join(
                    str(row[-1]) for row in sqlconn.execute(
                        "EXPLAIN QUERY PLAN SELECT joplin_id, note_obsidian_sha256, "
                        "note_source_sha256 FROM notes WHERE joplin_id IN (?)",
                        item_ids[:1],
                    )
                ))
                return original(sqlconn, item_ids)

            with mock.patch.object(obsidian2sql, "_existing_import_hashes", recording), \
                    contextlib.redirect_stdout(io.StringIO()):
                obsidian2sql.main([
                    "--input", str(vault), "--output", str(output),
                    "--progress-every", "0", "--batch-size", "1",
                ])
            self.assertGreater(len(plans), 4)
            for plan in plans:
                self.assertIn("joplinididx", plan)
                self.assertNotIn("SCAN", plan)

    def test_manifest_reader_matches_json_loads(self) -> None:
        """M1, V1: the incremental reader keeps exactly what json.loads would give.

        Tiny reads split every key, string and number across buffers; "1.5"
        cut after "1." is the case a naive reader decodes as 1.  Every document
        json.loads rejects is refused as malformed, and every well-formed one
        that is not an importable version-1 manifest for the reason V1 gives.
        """
        note, resource = int(constants.JoplinType.NOTE), int(constants.JoplinType.RESOURCE)
        fmt = '"format": "movenotes-lossless-joplin-preservation", "version": 1'
        items = (
            f'[{{"id": "n1", "type": {note}, "raw_path": "joplin-raw/é 1.md", '
            f'"obsidian_path": "A/😀.md", "obsidian_sha256": "{"ab" * 32}"}}, 7, '
            f'{{"id": "r1", "type": {resource}, "raw_path": "joplin-raw/r.md"}}, '
            f'{{"id": 5, "type": {note}, "raw_path": 3}}, '
            f'{{"id": "n2", "type": true, "obsidian_path": ["x"], "raw_path": "joplin-raw/n2.md"}}]'
        )
        documents = [
            f'{{{fmt}, "raw_directory": "joplin-raw", "items": {items}, '
            '"resource_files": 1.5e+10, "attachments": {"r1": "a/r.png"}}\n',
            f'{{"items": [], "version": 12345678901234567890, {fmt}, "items": {items}}}',
            f'{{{fmt}, "items": {{}}}}',
            f'{{{fmt}}}',
            '{"format": "other", "version": 1, "items": []}',
            '{"version": 1, "items": []}',
            '{"format": "movenotes-lossless-joplin-preservation", "items": []}',
            '{"format": "movenotes-lossless-joplin-preservation", "version": 2}',
            '{"format": "movenotes-lossless-joplin-preservation", "version": true}',
            '{"format": "movenotes-lossless-joplin-preservation", "version": 1.0}',
            f'{{{fmt}, "items": [1,]}}',
            f'{{{fmt}, "items":[ {{"id": "r2", "type": {resource}}} \n,\t7\r\n ,{{}}]}}',
            f'{{{fmt}, "items": [{{}} {{}}]}}',
            f'{{{fmt}, "items": []}} extra',
            f'\ufeff{{{fmt}}}',
            f'{{{fmt}, "items": [{{"id": "n1"',
            '[]',
            '[] x',
            '',
        ]

        def reference(text: str) -> object:
            try:
                manifest = json.loads(text)
            except ValueError:
                return "syntax"
            if not isinstance(manifest, dict) or manifest.get("format") != (
                "movenotes-lossless-joplin-preservation"
            ):
                return "format"
            if type(manifest.get("version")) is not int:
                return "format"
            if manifest["version"] != 1:
                return "version"
            values = manifest.get("items", [])
            if not isinstance(values, list):
                return "items"
            objects = [value for value in values if isinstance(value, dict)]

            def text_or_none(value: object) -> str | None:
                return value if isinstance(value, str) else None

            return obsidian2sql._Manifest(
                len(objects),
                [value["raw_path"] for value in objects if isinstance(value.get("raw_path"), str)],
                [value["id"] for value in objects
                 if value.get("type") == resource and isinstance(value.get("id"), str)],
                [obsidian2sql._ManifestNote(
                    value["id"], text_or_none(value.get("obsidian_path")),
                    text_or_none(value.get("obsidian_sha256")),
                ) for value in objects
                    if value.get("type") == note and isinstance(value.get("id"), str)],
                manifest.get("raw_directory", "joplin-raw"),
                manifest.get("attachments", {}),
            )

        def observed(path: Path) -> object:
            try:
                return obsidian2sql._load_manifest(path)
            except obsidian2sql._BundleProblem as problem:
                return problem.kind

        with tempfile.TemporaryDirectory(prefix="obsidian-manifest-reader-") as temporary:
            path = Path(temporary) / "manifest.json"
            for text in documents:
                path.write_text(text, encoding="utf-8")
                expected = reference(text)
                for chunk in (1, 2, 3, 7, 1 << 20):
                    with self.subTest(text=text[:40], chunk=chunk), \
                            mock.patch.object(obsidian2sql._JsonReader, "_CHUNK", chunk):
                        self.assertEqual(observed(path), expected)
            self.assertIsInstance(reference(documents[0]), obsidian2sql._Manifest)
            self.assertEqual(reference(documents[1]).item_count, 4)
            self.assertEqual(
                [reference(text) for text in documents[2:10]],
                ["items", obsidian2sql._Manifest(0, [], [], [], "joplin-raw", {}),
                 "format", "format", "format", "version", "format", "format"],
            )

    @staticmethod
    def _library_state(output: Path) -> tuple[list, list]:
        with contextlib.closing(sqlite3.connect(output / notesdb.DATABASE_FILENAME)) as conn:
            rows = conn.execute("SELECT * FROM notes ORDER BY note_id").fetchall()
            indexes = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' ORDER BY name"
            ).fetchall()
        return rows, indexes

    @staticmethod
    def _fixed_clock():  # noqa: ANN205
        """Give tag rows, which are stamped with the import time, a fixed one."""
        class FixedDatetime(obsidian2sql.datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: ANN001, ANN206
                return obsidian2sql.datetime(2026, 1, 1, tzinfo=tz)

        return mock.patch.object(obsidian2sql, "datetime", FixedDatetime)

    def _write_index_vault(self, vault: Path) -> None:
        (vault / "folder").mkdir(parents=True)
        for index in range(4):
            (vault / "folder" / f"note {index}.md").write_text(
                f"---\ntags:\n  - tag{index}\n---\n# Note {index}\n\nbody {index}\n",
                encoding="utf-8",
            )

    def _indexes_seen_by_batches(self, vault: Path, output: Path) -> list[set[str]]:
        seen: list[set[str]] = []
        original = obsidian2sql._existing_import_hashes

        def recording(sqlconn: sqlite3.Connection, item_ids: list[str]):
            seen.append({
                row[0] for row in sqlconn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' "
                    "AND name NOT LIKE 'sqlite_autoindex_%'"
                )
            })
            return original(sqlconn, item_ids)

        with mock.patch.object(obsidian2sql, "_existing_import_hashes", recording):
            self._import_quietly(vault, output, "--batch-size", "1")
        return seen

    def test_import_into_empty_library_defers_indexes(self) -> None:
        """A library with no rows inserts with only joplinididx, like a new one."""
        with tempfile.TemporaryDirectory(prefix="obsidian-empty-library-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            new = root / "new"
            empty = root / "empty"
            self._write_index_vault(vault)
            new.mkdir()
            empty.mkdir()
            with self._fixed_clock():
                self._import_quietly(vault, new)
            with contextlib.closing(notesdb.connect(empty / notesdb.DATABASE_FILENAME)) as conn, \
                    contextlib.redirect_stdout(io.StringIO()):
                notesdb.create_database(conn)
            with self._fixed_clock():
                seen = self._indexes_seen_by_batches(vault, empty)
            self.assertGreater(len(seen), 4)
            for names in seen:
                self.assertEqual(names, {"joplinididx"})
            self.assertEqual(self._library_state(empty), self._library_state(new))

    def test_import_into_non_empty_library_keeps_its_indexes(self) -> None:
        """A library that already holds rows keeps every index while merging."""
        with tempfile.TemporaryDirectory(prefix="obsidian-non-empty-library-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            output = root / "sqlite"
            self._write_index_vault(vault)
            output.mkdir()
            self._import_quietly(vault, output)
            (vault / "folder" / "added.md").write_text("# Added\n\nnew\n", encoding="utf-8")
            seen = self._indexes_seen_by_batches(vault, output)
            self.assertTrue(seen)
            for names in seen:
                self.assertEqual(names, set(notesdb._INDEX_NAMES))

    def test_interrupted_imports_recover_with_the_same_indexes(self) -> None:
        """Interrupted fresh and empty-library imports leave no rows, and recover."""
        with tempfile.TemporaryDirectory(prefix="obsidian-interrupted-index-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            new = root / "new"
            output = root / "sqlite"
            self._write_index_vault(vault)
            new.mkdir()
            output.mkdir()
            with self._fixed_clock():
                self._import_quietly(vault, new)
            expected = self._library_state(new)
            original = obsidian2sql._insert_rows
            for attempt in ("fresh", "empty library"):
                calls = 0

                def interrupting(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                    nonlocal calls
                    calls += 1
                    if calls == 3:
                        raise KeyboardInterrupt
                    return original(*args, **kwargs)

                with self.subTest(attempt=attempt), \
                        mock.patch.object(obsidian2sql, "_insert_rows", interrupting), \
                        self.assertRaises(KeyboardInterrupt):
                    self._import_quietly(vault, output, "--batch-size", "1")
                rows, indexes = self._library_state(output)
                self.assertEqual(rows, [])
                self.assertNotIn("hashidx", {name for name, _ in indexes})
            with self._fixed_clock():
                self._import_quietly(vault, output, "--batch-size", "1")
            self.assertEqual(self._library_state(output), expected)

    def _import_quietly(self, vault: Path, output: Path, *extra: str) -> str:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            obsidian2sql.main([
                "--input", str(vault), "--output", str(output),
                "--progress-every", "0", *extra,
            ])
        return stdout.getvalue()

    def test_unchanged_rerun_converts_no_note(self) -> None:
        """A note stored with the same ID and bytes is skipped before conversion."""
        with tempfile.TemporaryDirectory(prefix="obsidian-unchanged-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            output = root / "sqlite"
            (vault / "folder").mkdir(parents=True)
            output.mkdir()
            for index in range(3):
                (vault / "folder" / f"note {index}.md").write_text(
                    f"---\ntags:\n  - shared\n  - tag{index}\n---\n# Note {index}\n\n"
                    f"[[note {(index + 1) % 3}]] body {index}\n",
                    encoding="utf-8",
                )
            first = self._import_quietly(vault, output, "--batch-size", "2")
            self.assertIn("0 unchanged item(s) skipped", first)
            database = output / notesdb.DATABASE_FILENAME
            with contextlib.closing(sqlite3.connect(database)) as conn:
                before = conn.execute(
                    "SELECT * FROM notes ORDER BY note_id"
                ).fetchall()
            converted: list[str] = []
            original = obsidian2sql.rewrite_obsidian_links

            def counting(body, relative, *args):  # noqa: ANN001, ANN202
                converted.append(str(relative))
                return original(body, relative, *args)

            with mock.patch.object(obsidian2sql, "rewrite_obsidian_links", counting):
                second = self._import_quietly(vault, output, "--batch-size", "2")
            self.assertEqual(converted, [])
            self.assertIn("imported 0 item(s)", second)
            self.assertIn(f"; {len(before):,} unchanged item(s) skipped", second)
            with contextlib.closing(sqlite3.connect(database)) as conn:
                self.assertEqual(
                    conn.execute("SELECT * FROM notes ORDER BY note_id").fetchall(),
                    before,
                )

            # Changed bytes under a stored ID still refuse, and are converted.
            (vault / "folder" / "note 1.md").write_text("# Note 1\n\nedited\n", encoding="utf-8")
            with mock.patch.object(obsidian2sql, "rewrite_obsidian_links", counting), \
                    self.assertRaisesRegex(SystemExit, "item id collision"):
                self._import_quietly(vault, output, "--batch-size", "2")
            self.assertEqual(converted, ["folder/note 1.md"])

    def test_skipped_notes_still_restore_missing_tags(self) -> None:
        """Tags of an unchanged note are still collected, so missing rows return."""
        with tempfile.TemporaryDirectory(prefix="obsidian-unchanged-tags-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            output = root / "sqlite"
            vault.mkdir()
            output.mkdir()
            (vault / "tagged.md").write_text(
                "---\ntags:\n  - alpha\n  - beta\n---\nbody\n", encoding="utf-8"
            )
            self._import_quietly(vault, output)
            database = output / notesdb.DATABASE_FILENAME
            tag_types = (int(constants.JoplinType.TAG), int(constants.JoplinType.NOTE_TAG))
            query = (
                "SELECT joplin_id, joplin_type_, note_title FROM notes "
                "WHERE joplin_type_ IN (?, ?) ORDER BY joplin_id"
            )
            with contextlib.closing(sqlite3.connect(database)) as conn:
                tags = conn.execute(query, tag_types).fetchall()
                self.assertEqual(len(tags), 4)
                conn.execute("DELETE FROM notes WHERE joplin_type_ IN (?, ?)", tag_types)
                conn.commit()
            output_text = self._import_quietly(vault, output)
            self.assertIn("imported 4 item(s)", output_text)
            with contextlib.closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute(query, tag_types).fetchall(), tags)

    def test_unreadable_note_after_unchanged_notes_reports_utf8_error(self) -> None:
        """A read-ahead decoding failure is still reported as before."""
        with tempfile.TemporaryDirectory(prefix="obsidian-unchanged-utf8-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            output = root / "sqlite"
            vault.mkdir()
            output.mkdir()
            (vault / "a.md").write_text("first\n", encoding="utf-8")
            self._import_quietly(vault, output)
            (vault / "b.md").write_bytes(b"\xff\xfe broken\n")
            with self.assertRaisesRegex(SystemExit, r"b\.md' is not valid UTF-8"):
                self._import_quietly(vault, output)

    def test_native_obsidian_survives_joplin_round_trip_exactly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-native-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            sqlite1 = root / "sqlite1"
            joplin = root / "joplin"
            sqlite2 = root / "sqlite2"
            restored = root / "restored"
            for path in (
                vault / "Folder", vault / "assets", vault / ".obsidian",
                vault / "Empty", sqlite1, joplin, sqlite2, restored,
            ):
                path.mkdir(parents=True, exist_ok=True)
            (vault / "assets" / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\nexample")
            (vault / ".obsidian" / "app.json").write_text('{"theme":"moon"}\n', encoding="utf-8")
            note = (
                "---\n"
                'title: "Exact note"\n'
                "tags:\n  - alpha\n"
                "custom:\n  nested: true\n"
                "---\n"
                "Body with ![[../assets/picture.png]] and arbitrary YAML.\n"
            )
            (vault / "Folder" / "Note.md").write_text(note, encoding="utf-8")
            (vault / "Other.md").write_text("# Other\n\nSecond note.\n", encoding="utf-8")

            run("obsidian2sql.py", "--input", str(vault), "--output", str(sqlite1), "--progress-every", "0")
            run("sql2joplin.py", "--input", str(sqlite1), "--output", str(joplin), "--progress-every", "0")
            run("joplin2sql.py", "--input", str(joplin), "--output", str(sqlite2), "--progress-every", "0")
            run("sql2obsidian.py", "--input", str(sqlite2), "--output", str(restored), "--progress-every", "0")

            for relative in ("Folder/Note.md", "Other.md", "assets/picture.png", ".obsidian/app.json"):
                self.assertEqual(
                    (vault / relative).read_bytes(),
                    (restored / relative).read_bytes(),
                    relative,
                )
            self.assertTrue((restored / "Empty").is_dir())

    def test_edited_joplin_vault_note_survives_joplin_transit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-edited-joplin-") as temporary:
            root = Path(temporary)
            raw = root / "raw"
            sqlite1 = root / "sqlite1"
            vault = root / "vault"
            sqlite2 = root / "sqlite2"
            joplin = root / "joplin"
            sqlite3_dir = root / "sqlite3"
            restored = root / "restored"
            for path in (raw, sqlite1, vault, sqlite2, joplin, sqlite3_dir, restored):
                path.mkdir(parents=True, exist_ok=True)
            item_id = "e" * 32
            (raw / f"{item_id}.md").write_text(
                f"Title\n\nBody\n\nid: {item_id}\nparent_id: \n"
                "created_time: 2026-01-01T00:00:00.000Z\n"
                "updated_time: 2026-01-01T00:00:00.000Z\ntype_: 1",
                encoding="utf-8",
            )
            run("joplin2sql.py", "--input", str(raw), "--output", str(sqlite1), "--progress-every", "0")
            run("sql2obsidian.py", "--input", str(sqlite1), "--output", str(vault), "--progress-every", "0")
            visible = vault / "Title.md"
            visible.write_text(visible.read_text(encoding="utf-8") + "\nEdited in Obsidian.\n", encoding="utf-8")
            expected = visible.read_bytes()
            run("obsidian2sql.py", "--input", str(vault), "--output", str(sqlite2), "--progress-every", "0")
            run("sql2joplin.py", "--input", str(sqlite2), "--output", str(joplin), "--progress-every", "0")
            run("joplin2sql.py", "--input", str(joplin), "--output", str(sqlite3_dir), "--progress-every", "0")
            run("sql2obsidian.py", "--input", str(sqlite3_dir), "--output", str(restored), "--progress-every", "0")
            self.assertEqual(expected, (restored / "Title.md").read_bytes())

    def test_joplin_frontmatter_ids_are_used_without_preservation_bundle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-frontmatter-joplin-") as temporary:
            root = Path(temporary)
            raw = root / "raw"
            sqlite1 = root / "sqlite1"
            vault = root / "vault"
            sqlite2 = root / "sqlite2"
            restored = root / "restored"
            for path in (raw, sqlite1, vault, sqlite2, restored):
                path.mkdir(parents=True, exist_ok=True)
            folder_id = "b" * 32
            note_id = "c" * 32
            (raw / f"{folder_id}.md").write_text(
                f"Folder\n\nid: {folder_id}\nparent_id: \ntype_: 2",
                encoding="utf-8",
            )
            (raw / f"{note_id}.md").write_text(
                f"Title\n\nBody\n\nid: {note_id}\nparent_id: {folder_id}\n"
                "created_time: 2026-01-01T00:00:00.000Z\n"
                "updated_time: 2026-01-01T00:00:00.000Z\ntype_: 1",
                encoding="utf-8",
            )
            run("joplin2sql.py", "--input", str(raw), "--output", str(sqlite1), "--progress-every", "0")
            run(
                "sql2obsidian.py", "--input", str(sqlite1), "--output", str(vault),
                "--no-preserve-joplin", "--progress-every", "0",
            )
            run("obsidian2sql.py", "--input", str(vault), "--output", str(sqlite2), "--progress-every", "0")
            conn = sqlite3.connect(sqlite2 / notesdb.DATABASE_FILENAME)
            ids = {row[0] for row in conn.execute("SELECT joplin_id FROM notes")}
            conn.close()
            self.assertIn(folder_id, ids)
            self.assertIn(note_id, ids)
            run("sql2joplin.py", "--input", str(sqlite2), "--output", str(restored), "--progress-every", "0")
            self.assertTrue((restored / f"{folder_id}.md").is_file())
            self.assertTrue((restored / f"{note_id}.md").is_file())

    def test_joplin_preservation_bundle_returns_exact_raw(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-joplin-") as temporary:
            root = Path(temporary)
            raw = root / "raw"
            sqlite1 = root / "sqlite1"
            vault = root / "vault"
            sqlite2 = root / "sqlite2"
            restored = root / "restored"
            for path in (raw / "resources", sqlite1, vault, sqlite2, restored):
                path.mkdir(parents=True, exist_ok=True)
            folder_id = "1" * 32
            note_id = "2" * 32
            resource_id = "3" * 32
            (raw / f"{folder_id}.md").write_bytes(
                f"Folder\r\n\r\nid: {folder_id}\r\nparent_id: \r\ntype_: 2".encode()
            )
            (raw / f"{resource_id}.md").write_text(
                f"file.pdf\n\nid: {resource_id}\nmime: application/pdf\nfilename: file.pdf\nfile_extension: pdf\nsize: 4\ntype_: 4",
                encoding="utf-8",
            )
            (raw / "resources" / f"{resource_id}.pdf").write_bytes(b"%PDF")
            (raw / f"{note_id}.md").write_text(
                f"Title\n\n[PDF](:/{resource_id})\n\nid: {note_id}\nparent_id: {folder_id}\ncreated_time: 2026-01-01T00:00:00.000Z\nupdated_time: 2026-01-01T00:00:00.000Z\ntype_: 1",
                encoding="utf-8",
            )

            run("joplin2sql.py", "--input", str(raw), "--output", str(sqlite1), "--progress-every", "0")
            run("sql2obsidian.py", "--input", str(sqlite1), "--output", str(vault), "--progress-every", "0")
            run("obsidian2sql.py", "--input", str(vault), "--output", str(sqlite2), "--progress-every", "0")
            run("sql2joplin.py", "--input", str(sqlite2), "--output", str(restored), "--progress-every", "0")

            for source in raw.glob("*.md"):
                self.assertEqual(source.read_bytes(), (restored / source.name).read_bytes())
            self.assertEqual(
                (raw / "resources" / f"{resource_id}.pdf").read_bytes(),
                (restored / "resources" / f"{resource_id}.pdf").read_bytes(),
            )

    def test_new_obsidian_files_are_merged_with_preservation_bundle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-joplin-additions-") as temporary:
            root = Path(temporary)
            raw = root / "raw"
            sqlite1 = root / "sqlite1"
            vault = root / "vault"
            sqlite2 = root / "sqlite2"
            joplin = root / "joplin"
            sqlite3_dir = root / "sqlite3"
            restored = root / "restored"
            for path in (raw, sqlite1, vault, sqlite2, joplin, sqlite3_dir, restored):
                path.mkdir(parents=True, exist_ok=True)
            note_id = "4" * 32
            original_raw = (
                f"Original\n\nBody\n\nid: {note_id}\nparent_id: \n"
                "created_time: 2026-01-01T00:00:00.000Z\n"
                "updated_time: 2026-01-01T00:00:00.000Z\ntype_: 1"
            ).encode()
            (raw / f"{note_id}.md").write_bytes(original_raw)
            run("joplin2sql.py", "--input", str(raw), "--output", str(sqlite1), "--progress-every", "0")
            run("sql2obsidian.py", "--input", str(sqlite1), "--output", str(vault), "--progress-every", "0")

            added_note = b"---\ncustom: retained\n---\n# Added\n\n![[assets/extra.bin]]\n"
            (vault / "Added.md").write_bytes(added_note)
            (vault / "assets").mkdir(exist_ok=True)
            added_resource = b"\x00\x01native-attachment\xff"
            (vault / "assets" / "extra.bin").write_bytes(added_resource)
            (vault / "New Empty Folder").mkdir()

            run("obsidian2sql.py", "--input", str(vault), "--output", str(sqlite2), "--progress-every", "0")
            run("sql2joplin.py", "--input", str(sqlite2), "--output", str(joplin), "--progress-every", "0")
            self.assertEqual(original_raw, (joplin / f"{note_id}.md").read_bytes())
            run("joplin2sql.py", "--input", str(joplin), "--output", str(sqlite3_dir), "--progress-every", "0")
            run("sql2obsidian.py", "--input", str(sqlite3_dir), "--output", str(restored), "--progress-every", "0")

            self.assertEqual(added_note, (restored / "Added.md").read_bytes())
            self.assertEqual(added_resource, (restored / "assets" / "extra.bin").read_bytes())
            self.assertTrue((restored / "New Empty Folder").is_dir())


class DamagedBundleTest(unittest.TestCase):
    """V1: a damaged preservation bundle is refused, with next steps that work as printed.

    The fixture's paths contain spaces, the import runs from the vault's
    parent with relative paths, and the export used options a re-export must
    repeat, so each printed command is checked as a user would run it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="obsidian v1 bundle ")
        cls.root = Path(cls._temporary.name).resolve()
        raw = cls.root / "joplin raw"
        (raw / "resources").mkdir(parents=True)
        public, private, note, secret, resource = ("1" * 32, "4" * 32, "2" * 32, "5" * 32, "3" * 32)
        stamp = "created_time: 2026-01-01T00:00:00.000Z\nupdated_time: 2026-01-01T00:00:00.000Z\n"
        (raw / f"{public}.md").write_text(f"Public\n\nid: {public}\nparent_id: \ntype_: 2", encoding="utf-8")
        (raw / f"{private}.md").write_text(f"Private\n\nid: {private}\nparent_id: \ntype_: 2", encoding="utf-8")
        (raw / f"{resource}.md").write_text(
            f"file.pdf\n\nid: {resource}\nmime: application/pdf\nfilename: file.pdf\n"
            "file_extension: pdf\nsize: 4\ntype_: 4",
            encoding="utf-8",
        )
        (raw / "resources" / f"{resource}.pdf").write_bytes(b"%PDF")
        (raw / f"{note}.md").write_text(
            f"Open note\n\nSee [the PDF](:/{resource}) and https://example.com/x\n\n"
            f"id: {note}\nparent_id: {public}\n{stamp}type_: 1",
            encoding="utf-8",
        )
        (raw / f"{secret}.md").write_text(
            f"Secret note\n\nPrivate body\n\nid: {secret}\nparent_id: {private}\n{stamp}type_: 1",
            encoding="utf-8",
        )
        cls.library = cls.root / "source library"
        cls.pristine = cls.root / "pristine vault"
        cls.reference = cls.root / "reference library"
        for path in (cls.library, cls.pristine, cls.reference):
            path.mkdir()
        run("joplin2sql.py", "--input", str(raw), "--output", str(cls.library), "--progress-every", "0")
        cls.export_options = ["--notebooks", "Public", "--no-frontmatter"]
        run(
            "sql2obsidian.py", "--input", str(cls.library), "--output", str(cls.pristine),
            *cls.export_options, "--progress-every", "0",
        )
        run("obsidian2sql.py", "--input", str(cls.pristine), "--output", str(cls.reference),
            "--progress-every", "0")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    @staticmethod
    def _items(output: Path) -> list[tuple]:
        with contextlib.closing(sqlite3.connect(output / notesdb.DATABASE_FILENAME)) as conn:
            return conn.execute(
                "SELECT joplin_id, joplin_type_, note_title, note_data, note_obsidian_path "
                "FROM notes ORDER BY joplin_id, note_obsidian_path"
            ).fetchall()

    @staticmethod
    def _tree(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()
        }

    def _case(self, damage: Callable[[Path], None] | None = None) -> Path:
        """A copy of the exported vault, damaged, beside an empty library directory."""
        case = Path(tempfile.mkdtemp(prefix="case ", dir=self.root))
        shutil.copytree(self.pristine, case / "my vault")
        (case / "new library").mkdir()
        if damage is not None:
            damage(case / "my vault" / ".movenotes")
        return case

    def _import(self, case: Path, *extra: str, output: str = "new library",
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(PROJECT_DIR / "obsidian2sql.py"), "--input", "my vault",
             "--output", output, "--progress-every", "0", *extra],
            cwd=case, capture_output=True, text=True, env=env,
        )

    @staticmethod
    def _steps(stderr: str) -> list[tuple[str, list[str]]]:
        """Each numbered next step's title and its command lines, as printed."""
        steps: list[tuple[str, list[str]]] = []
        for line in stderr.splitlines():
            match = re.match(r"\d+\. (.*)", line)
            if match:
                steps.append((match.group(1), []))
            elif steps and line.startswith("     "):
                steps[-1][1].append(line[5:])
        return steps

    def _step(self, stderr: str, opening: str) -> list[str]:
        found = [commands for title, commands in self._steps(stderr) if title.startswith(opening)]
        self.assertEqual(len(found), 1, stderr)
        return found[0]

    def _shell(self, case: Path, commands: list[str]) -> None:
        for command in commands:
            result = subprocess.run(command, shell=True, cwd=case, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{command}\n{result.stdout}{result.stderr}")

    @staticmethod
    def _cut(bundle: Path) -> None:
        """Cut the manifest inside its first RAW path, as an interrupted write would."""
        manifest = bundle / "manifest.json"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(text[: text.index('"joplin-raw/') + 8], encoding="utf-8")

    @staticmethod
    def _rewrite(change: Callable[[dict], object]) -> Callable[[Path], None]:
        def damage(bundle: Path) -> None:
            manifest = bundle / "manifest.json"
            value = json.loads(manifest.read_text(encoding="utf-8"))
            manifest.write_text(json.dumps(change(value) or value), encoding="utf-8")
        return damage

    def _refusal_cases(self) -> dict[str, tuple[Callable[[Path], None], str]]:
        manifest = ".movenotes/manifest.json"

        def replace(old: bytes, new: bytes) -> Callable[[Path], None]:
            def damage(bundle: Path) -> None:
                path = bundle / "manifest.json"
                data = path.read_bytes()
                self.assertIn(old, data)
                path.write_bytes(data.replace(old, new, 1))
            return damage

        def remove(*names: str) -> Callable[[Path], None]:
            def damage(bundle: Path) -> None:
                for name in names:
                    path = bundle / name
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
            return damage

        def directory(bundle: Path) -> None:
            (bundle / "manifest.json").unlink()
            (bundle / "manifest.json").mkdir()

        return {
            "cut": (self._cut, "ends in the middle of the document"),
            "syntax": (replace(b'"items": [', b'"items": [}'), f"{manifest} is not valid JSON: "),
            "utf8": (replace(b'"scope"', b'"sc\xffope"'), f"{manifest} is not valid UTF-8 at byte "),
            "empty": (lambda bundle: (bundle / "manifest.json").write_bytes(b""),
                      f"{manifest} is empty, which is what an interrupted export leaves."),
            "array": (lambda bundle: (bundle / "manifest.json").write_text("[]"),
                      f"{manifest} is not a movenotes preservation manifest: it is not a JSON object."),
            "format": (self._rewrite(lambda value: value.update(format="other")),
                       f'{manifest} is not a movenotes preservation manifest: its format is "other".'),
            "version": (self._rewrite(lambda value: value.update(version=2)),
                        f"{manifest} is version 2, and this release of obsidian2sql.py reads version 1 only."),
            "items": (self._rewrite(lambda value: value.update(items={})),
                      f"{manifest} is damaged: its items field is not a list."),
            "directory": (directory, f"{manifest} cannot be read: "),
            "no-manifest": (remove("manifest.json"),
                            ".movenotes/joplin-raw/ is present but .movenotes/manifest.json is not"),
            "unfinished": (remove("manifest.json", "joplin-raw", "README.md"),
                           ".movenotes/export.json is present but there is no manifest and no Joplin RAW copy"),
        }

    def test_every_damaged_bundle_is_refused_and_writes_nothing(self) -> None:
        other = self.root / "existing library"
        if not other.exists():
            shutil.copytree(self.reference, other)
        before = self._tree(other)
        for name, (damage, reason) in self._refusal_cases().items():
            with self.subTest(name):
                case = self._case(damage)
                for output in ("new library", str(other)):
                    result = self._import(case, output=output)
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertEqual(result.stdout, "")
                    lines = result.stderr.splitlines()
                    self.assertEqual(
                        lines[0],
                        f"ERROR: cannot import '{case / 'my vault'}': "
                        "its movenotes preservation bundle is damaged.",
                    )
                    self.assertIn(reason, lines[1])
                    self.assertEqual(lines[2:5], ["Nothing was imported.", "", "Next steps, any one of:"])
                self.assertEqual(list((case / "new library").iterdir()), [])
                self.assertEqual(self._tree(other), before)
                titles = [title.split(" ")[0] for title, _ in self._steps(result.stderr)]
                expected = ["Import", "Import", "Export"]
                if name == "version":
                    expected = ["Update"] + expected
                elif name == "unfinished":
                    expected = ["Import", "Export"]
                else:
                    expected = ["Restore"] + expected
                self.assertEqual(titles, expected)

    def test_refusal_message_is_exact(self) -> None:
        case = self._case(self._cut)
        vault = case / "my vault"
        text = (vault / ".movenotes" / "manifest.json").read_text(encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError) as caught:
            json.loads(text)
        error = caught.exception
        result = self._import(case)
        python, script = sys.executable, str(PROJECT_DIR / "obsidian2sql.py")
        original = [python, script, "--input", "my vault", "--output", "new library", "--progress-every", "0"]
        target = case / "my vault-reexport"
        expected = "\n".join([
            f"ERROR: cannot import '{vault}': its movenotes preservation bundle is damaged.",
            f".movenotes/manifest.json is not valid JSON: Unterminated string starting at line "
            f"{error.lineno:,}, column {error.colno:,} (byte {len(text[:error.pos].encode()):,} of "
            f"{len(text.encode()):,}). The file ends in the middle of the document, which is what "
            "an interrupted export leaves.",
            "Nothing was imported.",
            "",
            "Next steps, any one of:",
            "",
            "1. Restore .movenotes/manifest.json from a backup, then rerun this command:",
            "     " + shlex.join(original),
            "",
            "2. Import the Joplin RAW copy instead. It is lossless for the export, but leaves out "
            "any Obsidian edits made since:",
            "     " + shlex.join([python, str(PROJECT_DIR / "joplin2sql.py"), "--input",
                                  str(vault / ".movenotes" / "joplin-raw"), "--output",
                                  str(case / "new library")]),
            "",
            "3. Import the vault as plain Obsidian notes. This keeps edits made since the export, "
            "but drops the Joplin-only items and properties the bundle holds:",
            "     " + shlex.join(original + ["--ignore-preservation"]),
            "",
            "4. Export the source library again into a new directory and import that. This leaves "
            "out any edits made since the export:",
            f"     mkdir {shlex.quote(str(target))}  # suggested; any new empty directory works",
            "     " + shlex.join([python, str(PROJECT_DIR / "sql2obsidian.py"), "--input",
                                  str(self.library), "--output", str(target), *self.export_options]),
            "     " + shlex.join([python, script, "--input", str(target), "--output",
                                  str(case / "new library"), "--progress-every", "0"]),
        ]) + "\n"
        self.assertEqual(result.stderr, expected)

    def test_printed_commands_succeed_as_printed(self) -> None:
        reference = self._items(self.reference)
        # Restoring the manifest makes the original command succeed.
        case = self._case(self._cut)
        commands = self._step(self._import(case).stderr, "Restore")
        shutil.copy2(self.pristine / ".movenotes" / "manifest.json", case / "my vault" / ".movenotes")
        self._shell(case, commands)
        self.assertEqual(self._items(case / "new library"), reference)
        # The RAW copy imports exactly the items the export preserved.
        manifest = json.loads((self.pristine / ".movenotes" / "manifest.json").read_text(encoding="utf-8"))
        case = self._case(self._cut)
        self._shell(case, self._step(self._import(case).stderr, "Import the Joplin RAW copy"))
        self.assertEqual(
            {row[0] for row in self._items(case / "new library")},
            {item["id"] for item in manifest["items"]},
        )
        # The plain import takes the vault's own files and none of the bundle.
        case = self._case(self._cut)
        self._shell(case, self._step(self._import(case).stderr, "Import the vault as plain"))
        paths = {row[4] for row in self._items(case / "new library") if row[4]}
        self.assertIn("Public/Open note.md", paths)
        self.assertFalse(any(path.startswith(".movenotes/") for path in paths))
        # The re-export repeats the recorded source and options, so its vault is
        # the original export, and importing it gives the reference library.
        case = self._case(self._cut)
        self._shell(case, self._step(self._import(case).stderr, "Export the source library"))
        self.assertEqual(self._tree(case / "my vault-reexport"), self._tree(self.pristine))
        self.assertEqual(self._items(case / "new library"), reference)

    def test_ignore_preservation_imports_the_vault_as_native(self) -> None:
        for damage in (None, self._cut):
            with self.subTest(damaged=damage is not None):
                case = self._case(damage)
                result = self._import(case, "--ignore-preservation")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("from native Obsidian vault (", result.stdout)
                paths = {row[4] for row in self._items(case / "new library")}
                self.assertFalse(any(str(path).startswith(".movenotes") for path in paths if path))
                self.assertIn("Public/Open note.md", paths)

    def test_valid_bundle_still_imports(self) -> None:
        case = self._case()
        result = self._import(case)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("from Joplin preservation bundle", result.stdout)
        self.assertEqual(self._items(case / "new library"), self._items(self.reference))

    def _export(self, library: Path, vault: Path, env: dict[str, str]) -> dict:
        vault.mkdir(parents=True)
        result = subprocess.run(
            [sys.executable, str(PROJECT_DIR / "sql2obsidian.py"), "--input", str(library),
             "--output", str(vault), "--progress-every", "0"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((vault / ".movenotes" / "export.json").read_text(encoding="utf-8"))

    def _reexport_source(self, vault: Path, env: dict[str, str]) -> str:
        """The --input of the printed re-export, marked if it is labelled as not found."""
        (vault / ".movenotes" / "manifest.json").write_text("{", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(PROJECT_DIR / "obsidian2sql.py"), "--input", str(vault),
             "--output", str(vault.parent)],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        command = self._step(result.stderr, "Export the source library")[1]
        words = shlex.split(command, comments=True)
        source = words[words.index("--input") + 1]
        return source + ("  [not found]" if "not found here" in command else "")

    def test_export_record_keeps_the_user_name_out(self) -> None:
        user, other_user = "v1user", "v1other"
        base = Path(tempfile.mkdtemp(prefix="record ", dir=self.root))
        home, other_home = base / "home" / user, base / "home" / other_user
        environment = {**os.environ, "HOME": str(home), "USER": user}
        moved = {**os.environ, "HOME": str(other_home), "USER": other_user}

        # Under the home directory: "~/...", with neither the home nor the name.
        under_home = home / "notes lib"
        shutil.copytree(self.library, under_home)
        record = self._export(under_home, base / "vault a", environment)
        self.assertEqual(record["source_database"], {"path": "~/notes lib", "home": True, "user_segments": []})
        text = json.dumps(record)
        self.assertNotIn(user, text)
        self.assertNotIn(str(home), text)
        self.assertEqual(self._reexport_source(base / "vault a", environment), str(under_home))
        # Read by another user, it names their home; found there or labelled.
        self.assertEqual(self._reexport_source(base / "vault a", moved),
                         str(other_home / "notes lib") + "  [not found]")
        shutil.copytree(self.library, other_home / "notes lib")
        self.assertEqual(self._reexport_source(base / "vault a", moved), str(other_home / "notes lib"))

        # Elsewhere: each segment equal to the name becomes $USER, and only those.
        outside = base / "media" / user / f"{user}-backup" / user / "lib"
        shutil.copytree(self.library, outside)
        record = self._export(outside, base / "vault b", environment)
        parts = list(outside.parts)
        recorded = [("$USER" if part == user else part) for part in parts]
        self.assertEqual(record["source_database"], {
            "path": str(Path(*recorded)), "home": False,
            "user_segments": [index for index, part in enumerate(parts) if part == user],
        })
        self.assertNotIn(user, Path(record["source_database"]["path"]).parts)
        self.assertIn(f"{user}-backup", record["source_database"]["path"])
        self.assertEqual(self._reexport_source(base / "vault b", environment), str(outside))
        self.assertEqual(
            self._reexport_source(base / "vault b", moved),
            str(Path(*[(other_user if part == user else part) for part in parts])) + "  [not found]",
        )

        # A literal "~" or "$USER" directory is not a substitution and round-trips.
        literal = base / "~" / "$USER" / "lib"
        shutil.copytree(self.library, literal)
        record = self._export(literal, base / "vault c", environment)
        self.assertEqual(record["source_database"], {"path": str(literal), "home": False, "user_segments": []})
        self.assertEqual(self._reexport_source(base / "vault c", moved), str(literal))

    def test_missing_or_unreadable_record_gets_a_labelled_placeholder(self) -> None:
        note = ("SOURCE_LIBRARY is the directory that was given to sql2obsidian.py --input when this "
                "vault was exported; it holds notesdb.sqlite.")
        cases = {
            "missing": (lambda bundle: (bundle / "export.json").unlink(),
                        " This vault has no export record, so it is not known here."),
            "unreadable": (lambda bundle: (bundle / "export.json").write_text("{"),
                           " The export record, .movenotes/export.json, cannot be read ("),
            "other format": (lambda bundle: (bundle / "export.json").write_text('{"format": "x"}'),
                             " The export record, .movenotes/export.json, cannot be read (it is not a "
                             "version-1 movenotes export record)"),
            # A vault can come from someone else: an escape sequence in its
            # record must not reach the terminal.
            "control characters": (self._record(notebooks=["Public\x1b[2J"]),
                                   " The export record, .movenotes/export.json, cannot be read (its "
                                   "source library or options are malformed)"),
        }
        for name, (damage, reason) in cases.items():
            with self.subTest(name):
                def both(bundle: Path) -> None:
                    damage(bundle)
                    self._cut(bundle)
                result = self._import(self._case(both))
                commands = self._step(result.stderr, "Export the source library")
                self.assertIn(" --input SOURCE_LIBRARY --output ", commands[1])
                self.assertNotIn("--notebooks", commands[1])
                self.assertIn("   " + note + reason, result.stderr)
                self.assertIn("Add the options that export used, if any: --notebooks, "
                              "--no-frontmatter, --no-simplify-urls, --include-notrios-receipt.",
                              result.stderr)
                self.assertNotIn("\x1b", result.stderr)

    @staticmethod
    def _record(**options: object) -> Callable[[Path], None]:
        def damage(bundle: Path) -> None:
            path = bundle / "export.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["options"].update(options)
            path.write_text(json.dumps(record), encoding="utf-8")
        return damage

    def test_recorded_notebook_names_are_passed_as_values(self) -> None:
        """A name starting with "-" must not be read by argparse as an option."""
        def damage(bundle: Path) -> None:
            self._record(notebooks=["-dash", "Public"])(bundle)
            self._cut(bundle)
        command = self._step(self._import(self._case(damage)).stderr, "Export the source library")[1]
        words = shlex.split(command)
        self.assertEqual(words[words.index("--output") + 2:],
                         ["--notebooks=-dash", "--notebooks", "Public", "--no-frontmatter"])


    def _export_in_process(self, vault: Path, *extra: str) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            sql2obsidian.main(["--input", str(self.library), "--output", str(vault),
                               "--progress-every", "0", *extra])

    def test_interrupted_export_leaves_no_manifest(self) -> None:
        """The manifest appears only by rename, so a stopped export has none."""
        case = Path(tempfile.mkdtemp(prefix="interrupted ", dir=self.root))
        (case / "my vault").mkdir()
        (case / "new library").mkdir()
        with mock.patch.object(sql2obsidian.os, "replace", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            self._export_in_process(case / "my vault", *self.export_options)
        bundle = case / "my vault" / ".movenotes"
        self.assertFalse((bundle / "manifest.json").exists())
        self.assertFalse((bundle / "manifest.json.partial").exists())
        result = self._import(case)
        self.assertEqual(result.returncode, 1)
        self.assertIn(".movenotes/joplin-raw/ is present but .movenotes/manifest.json is not",
                      result.stderr)
        # A killed export leaves the partial file; it is not taken for a manifest.
        (bundle / "manifest.json.partial").write_bytes(
            (self.pristine / ".movenotes" / "manifest.json").read_bytes()
        )
        self.assertIn(".movenotes/joplin-raw/ is present", self._import(case).stderr)
        self.assertEqual(list((case / "new library").iterdir()), [])

    def test_reexport_removes_the_previous_bundle_first(self) -> None:
        """A re-export stopped among the notes must not leave the old bundle beside them."""
        case = self._case()
        vault = case / "my vault"
        written = Path.write_bytes

        def fail_on_notes(path: Path, data: bytes) -> int:
            if path.suffix == ".md" and ".movenotes" not in path.parts:
                raise KeyboardInterrupt
            return written(path, data)

        with mock.patch.object(Path, "write_bytes", fail_on_notes), \
                self.assertRaises(KeyboardInterrupt):
            self._export_in_process(vault, *self.export_options)
        self.assertEqual(sorted(path.name for path in (vault / ".movenotes").iterdir()), ["export.json"])
        result = self._import(case)
        self.assertEqual(result.returncode, 1)
        self.assertIn("the export that wrote this vault did not finish", result.stderr)
        # Without preservation the old bundle goes too, instead of describing
        # notes it no longer matches.
        self._export_in_process(vault, *self.export_options, "--no-preserve-joplin")
        self.assertFalse((vault / ".movenotes").exists())
        result = self._import(case)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("from native Obsidian vault (", result.stdout)

class ExportAndImageRegressionTest(unittest.TestCase):
    def test_multibyte_long_title_is_shortened_without_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="long-name-") as temporary:
            root = Path(temporary)
            sqlite_dir = root / "sqlite"
            vault = root / "vault"
            sqlite_dir.mkdir()
            vault.mkdir()
            conn = notesdb.connect(sqlite_dir / notesdb.DATABASE_FILENAME)
            notesdb.create_database(conn)
            title = "🕊" * 100
            notesdb.add_joplin_note(
                conn,
                {
                    "note_type": "note", "note_uuid": "a" * 32,
                    "note_original_format": "test", "note_title": title,
                    "note_data": title + "\n\nBody", "note_data_format": "text/markdown",
                    "joplin_id": "a" * 32, "joplin_type_": int(constants.JoplinType.NOTE),
                    "joplin_parent_id": "", "joplin_created_time": "2026-01-01T00:00:00.000Z",
                    "joplin_updated_time": "2026-01-01T00:00:00.000Z",
                },
            )
            conn.commit()
            conn.close()
            run("sql2obsidian.py", "--input", str(sqlite_dir), "--output", str(vault), "--progress-every", "0")
            notes = [path for path in vault.glob("*.md") if path.name != "README.md"]
            self.assertEqual(len(notes), 1)
            self.assertLessEqual(len(notes[0].name.encode("utf-8")), 240)

    def test_domain_quarantine_and_managed_config_repair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quarantine-domain-") as temporary:
            root = Path(temporary)
            sqlite_dir = root / "sqlite"
            sqlite_dir.mkdir()
            conn = notesdb.connect(sqlite_dir / notesdb.DATABASE_FILENAME)
            notesdb.create_database(conn)
            for index in range(2):
                item_id = f"{index + 1:032x}"
                notesdb.add_joplin_note(
                    conn,
                    {
                        "note_type": "note", "note_uuid": item_id,
                        "note_original_format": "test", "note_title": f"Note {index}",
                        "note_data": f"![bad](https://img.bad.example/{index}.png)",
                        "note_data_format": "text/markdown", "joplin_id": item_id,
                        "joplin_type_": int(constants.JoplinType.NOTE),
                    },
                )
            conn.commit()
            conn.close()
            config = root / "images.ini"
            config.write_text(
                "[images2resources]\n\n[quarantine]\n"
                "replacement_title = Image removed\n"
                "quarantine_domains = bad.example\n"
                "replacement_resource_id =\n"
                "replacement_resource_file =\n"
                "replacement_mime =\n",
                encoding="utf-8",
            )
            result = run(
                "quarantinelinks.py", "--input", str(sqlite_dir), "--config", str(config)
            )
            self.assertIn("quarantine_domains matched 2 image link(s)", result.stdout)
            conn = sqlite3.connect(sqlite_dir / notesdb.DATABASE_FILENAME)
            bodies = [row[0] for row in conn.execute("SELECT note_data FROM notes WHERE joplin_type_ = 1")]
            conn.close()
            self.assertTrue(all("https://img.bad.example" not in body for body in bodies))
            parser = configparser.ConfigParser()
            parser.read(config, encoding="utf-8")
            quarantine = parser["quarantine"]
            self.assertTrue(quarantine["replacement_resource_id"])
            self.assertTrue(quarantine["replacement_resource_file"])
            self.assertTrue(quarantine["replacement_mime"])
            text = config.read_text(encoding="utf-8")
            self.assertIn("# Managed by quarantinelinks.py", text)

            # A partially blank managed block is repaired while reusing the
            # existing replacement resource rather than creating another one.
            parser["quarantine"]["replacement_mime"] = ""
            with config.open("w", encoding="utf-8") as handle:
                parser.write(handle)
            conn = sqlite3.connect(sqlite_dir / notesdb.DATABASE_FILENAME)
            before_resources = conn.execute(
                "SELECT COUNT(*) FROM notes WHERE joplin_type_ = 4"
            ).fetchone()[0]
            item_id = "f" * 32
            columns = {name: None for name in notesdb.NOTE_COLUMNS | notesdb.JOPLIN_COLUMNS}
            columns.update(
                {
                    "note_type": "note", "note_uuid": item_id,
                    "note_original_format": "test", "note_title": "Third",
                    "note_data": "![bad](https://bad.example/third.png)",
                    "note_data_format": "text/markdown", "joplin_id": item_id,
                    "joplin_type_": int(constants.JoplinType.NOTE),
                }
            )
            conn.close()
            conn = notesdb.open_database(sqlite_dir / notesdb.DATABASE_FILENAME, "test")
            notesdb.add_joplin_note(conn, columns)
            conn.commit()
            conn.close()
            run("quarantinelinks.py", "--input", str(sqlite_dir), "--config", str(config))
            parser = configparser.ConfigParser()
            parser.read(config, encoding="utf-8")
            self.assertTrue(parser["quarantine"]["replacement_mime"])
            conn = sqlite3.connect(sqlite_dir / notesdb.DATABASE_FILENAME)
            after_resources = conn.execute(
                "SELECT COUNT(*) FROM notes WHERE joplin_type_ = 4"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(before_resources, after_resources)

    def test_images_progress_reports_processed_out_of_total(self) -> None:
        with tempfile.TemporaryDirectory(prefix="images-progress-") as temporary:
            root = Path(temporary)
            sqlite_dir = root / "sqlite"
            sqlite_dir.mkdir()
            conn = notesdb.connect(sqlite_dir / notesdb.DATABASE_FILENAME)
            notesdb.create_database(conn)
            for index in range(2):
                item_id = f"{index + 10:032x}"
                notesdb.add_joplin_note(
                    conn,
                    {
                        "note_type": "note", "note_uuid": item_id,
                        "note_original_format": "test", "note_title": str(index),
                        "note_data": "No images", "note_data_format": "text/markdown",
                        "joplin_id": item_id, "joplin_type_": int(constants.JoplinType.NOTE),
                    },
                )
            conn.commit()
            conn.close()
            result = run(
                "images2resources.py", "--input", str(sqlite_dir),
                "--progress-every", "1",
            )
            self.assertIn("processed 1 of 2 note(s)", result.stdout)
            self.assertIn("processed 2 of 2 note(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""End-to-end verification of the movenotes scripts.

Runs the command-line scripts against the Joplin RAW dataset in sample/ and
verifies that:

* Joplin RAW -> SQLite -> Joplin RAW preserves every item and resource
  byte-for-byte by default, including unknown properties and line endings;
* merging two sources, removedups.py, and cleanres.py behave as expected;
* URL-only links are preserved by default and simplified only with the
  explicit --simplify-urls option;
* the Obsidian vault export produces the expected structure, mapped and
  namespaced front matter, attachments, and a lossless Joplin RAW bundle;
* schema v1 databases are rejected.

Usage: python3 test_movenotes.py
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta, timezone

import joplin2sql
import constants
import notesdb
import sql2obsidian
import twitterx2sql

PROJECT_DIR = Path(__file__).resolve().parent
SAMPLE_SOURCE1 = PROJECT_DIR / "sample" / "source1"
SAMPLE_SOURCE2 = PROJECT_DIR / "sample" / "source2"
PRESERVATION_DIR_NAME = ".movenotes"

# Item ids in the sample dataset.
DUPLICATE_NOTE_ID = "55555555555555555555555555555555"  # same body as 2222...
LINKS_NOTE_ID = "66666666666666666666666666666666"
ORPHAN_RESOURCE = "ffffffffffffffffffffffffffffffff.bin"
PDF_RESOURCE = "aaaabbbbccccddddeeeeffff00001111.pdf"
PNG_RESOURCE = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    """Run a project script, failing the test run on a non-zero exit."""
    return subprocess.run(
        [sys.executable, str(PROJECT_DIR / script), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def property_set(path: Path) -> list[str]:
    """A file's non-blank lines, sorted.

    Joplin parses the properties block by key, so property line order does
    not matter; comparing sorted lines checks content without depending on
    column order.
    """
    return sorted(line for line in path.read_text().strip().split("\n"))


class MovenotesEndToEnd(unittest.TestCase):
    """Import the sample, exercise every script, and check the results."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="movenotes-test-")
        tmp = Path(cls._tmp.name)
        cls.sqlite_dir = tmp / "sqlite"
        cls.joplin_out = tmp / "joplin_out"
        cls.joplin_out_simplified = tmp / "joplin_out_simplified"
        cls.vault = tmp / "vault"
        for d in (cls.sqlite_dir, cls.joplin_out, cls.joplin_out_simplified, cls.vault):
            d.mkdir()

        # Merge both sample sources into one database.
        run("joplin2sql.py", "--input", str(SAMPLE_SOURCE1), "--output", str(cls.sqlite_dir))
        run("joplin2sql.py", "--input", str(SAMPLE_SOURCE2), "--output", str(cls.sqlite_dir))
        cls.removedups = run("removedups.py", "--input", str(cls.sqlite_dir))
        cls.cleanres = run("cleanres.py", "--input", str(cls.sqlite_dir))
        run(
            "sql2joplin.py",
            "--input", str(cls.sqlite_dir),
            "--output", str(cls.joplin_out),
        )
        run(
            "sql2joplin.py",
            "--simplify-urls",
            "--input", str(cls.sqlite_dir),
            "--output", str(cls.joplin_out_simplified),
        )
        run("sql2obsidian.py", "--input", str(cls.sqlite_dir), "--output", str(cls.vault))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # -- import / merge -----------------------------------------------------

    def test_merge_imports_all_items(self) -> None:
        conn = sqlite3.connect(self.sqlite_dir / "notesdb.sqlite")
        counts = dict(
            conn.execute("SELECT joplin_type_, COUNT(*) FROM notes GROUP BY 1")
        )
        conn.close()
        # After removedups: 6 notes (7 imported, 1 duplicate removed),
        # 3 folders, 2 resources, 1 tag, 1 note_tag.
        self.assertEqual(counts, {1: 6, 2: 3, 4: 2, 5: 1, 6: 1})

    def test_note_folder_titles(self) -> None:
        conn = sqlite3.connect(self.sqlite_dir / "notesdb.sqlite")
        folders = dict(
            conn.execute(
                "SELECT joplin_id, note_folder FROM notes WHERE joplin_type_ = 1"
            )
        )
        conn.close()
        self.assertEqual(folders["22222222222222222222222222222222"], "Work")
        self.assertEqual(folders[LINKS_NOTE_ID], "Personal")
        self.assertEqual(folders["88888888888888888888888888888888"], "Projects")

    def test_removedups_removed_one(self) -> None:
        self.assertIn("removed 1 duplicate note(s)", self.removedups.stdout)

    def test_cleanres_deleted_only_orphan(self) -> None:
        self.assertIn("deleted 1 unused resource file(s)", self.cleanres.stdout)
        resources = self.sqlite_dir / "resources"
        self.assertFalse((resources / ORPHAN_RESOURCE).exists())
        self.assertTrue((resources / PDF_RESOURCE).exists())
        self.assertTrue((resources / PNG_RESOURCE).exists())

    # -- Joplin round trip ---------------------------------------------------

    def test_joplin_round_trip_is_lossless(self) -> None:
        sample_files = sorted(SAMPLE_SOURCE1.glob("*.md")) + sorted(
            SAMPLE_SOURCE2.glob("*.md")
        )
        checked = 0
        for source_file in sample_files:
            if source_file.stem == DUPLICATE_NOTE_ID:
                continue  # removed by removedups.py
            exported = self.joplin_out / source_file.name
            self.assertTrue(exported.is_file(), f"missing {source_file.name}")
            self.assertEqual(
                source_file.read_bytes(),
                exported.read_bytes(),
                f"content differs for {source_file.name}",
            )
            checked += 1
        self.assertEqual(checked, len(sample_files) - 1)

    def test_joplin_round_trip_resources_identical(self) -> None:
        for name, source_dir in (
            (PDF_RESOURCE, SAMPLE_SOURCE1),
            (PNG_RESOURCE, SAMPLE_SOURCE2),
        ):
            self.assertEqual(
                (source_dir / "resources" / name).read_bytes(),
                (self.joplin_out / "resources" / name).read_bytes(),
                f"resource bytes differ for {name}",
            )

    def test_duplicate_note_not_exported(self) -> None:
        self.assertFalse((self.joplin_out / f"{DUPLICATE_NOTE_ID}.md").exists())

    # -- URL simplification ---------------------------------------------------

    def test_urls_simplified_with_flag(self) -> None:
        body = (self.joplin_out_simplified / f"{LINKS_NOTE_ID}.md").read_text()
        self.assertIn("Plain: https://example.com\n", body)
        self.assertIn("Auto: https://example.org/page?x=1\n", body)
        # Titled/image/resource links and code are untouched.
        self.assertIn("[Docs](https://docs.example.com)", body)
        self.assertIn("![https://x.io/i.png](https://x.io/i.png)", body)
        self.assertIn("[report.pdf](:/aaaabbbbccccddddeeeeffff00001111)", body)
        self.assertIn("`[https://a.io](https://a.io)` stays", body)
        self.assertIn("<https://in-code.example> stays", body)

    def test_urls_preserved_by_default(self) -> None:
        body = (self.joplin_out / f"{LINKS_NOTE_ID}.md").read_text()
        self.assertIn("[https://example.com](https://example.com)", body)
        self.assertIn("<https://example.org/page?x=1>", body)

    # -- Obsidian vault --------------------------------------------------------

    def test_vault_structure(self) -> None:
        expected = {
            "Work/Note With Attachment.md",
            # The duplicate 'Note With Attachment' under Personal was
            # removed by removedups.py before the export.
            "Personal/Unique Note.md",
            "Personal/Links Note.md",
            "Personal/Projects/Meeting Notes.md",
            "Personal/Projects/Meeting Notes 2.md",  # duplicate title deduplicated
            "Personal/Projects/Q1 Q2 Plan.md",  # 'Q1/Q2: Plan?*' sanitized
            "attachments/report.pdf",
            "attachments/photo.png",
        }
        actual = {
            str(p.relative_to(self.vault))
            for p in self.vault.rglob("*")
            if p.is_file() and PRESERVATION_DIR_NAME not in p.parts
        }
        self.assertEqual(actual, expected)

    def test_vault_resource_links_rewritten(self) -> None:
        body = (self.vault / "Personal" / "Projects" / "Q1 Q2 Plan.md").read_text()
        self.assertIn("![[photo.png]]", body)
        self.assertIn("[report.pdf](../../attachments/report.pdf)", body)
        self.assertIn("url https://a.io", body)  # simplified
        body = (self.vault / "Work" / "Note With Attachment.md").read_text()
        self.assertIn("[report.pdf](../attachments/report.pdf)", body)

    def test_vault_attachments_identical(self) -> None:
        self.assertEqual(
            (SAMPLE_SOURCE2 / "resources" / PNG_RESOURCE).read_bytes(),
            (self.vault / "attachments" / "photo.png").read_bytes(),
        )
        self.assertEqual(
            (SAMPLE_SOURCE1 / "resources" / PDF_RESOURCE).read_bytes(),
            (self.vault / "attachments" / "report.pdf").read_bytes(),
        )

    def test_vault_frontmatter(self) -> None:
        body = (self.vault / "Personal" / "Unique Note.md").read_text()
        self.assertTrue(body.startswith("---\n"))
        self.assertIn('title: "Unique Note"', body)
        self.assertIn('joplin-id: "44444444444444444444444444444444"', body)
        self.assertIn('created: "2020-04-04T00:00:00.000Z"', body)
        self.assertIn('joplin-parent-id: "33333333333333333333333333333333"', body)
        self.assertIn("joplin-properties-json:", body)
        self.assertIn('  - "work"', body)  # tag resolved via tag/note_tag items
        # The title field carries the original title even when the file
        # name had to be sanitized (useful for Quartz publishing).
        sanitized = (self.vault / "Personal" / "Projects" / "Q1 Q2 Plan.md").read_text()
        self.assertIn('title: "Q1/Q2: Plan?*"', sanitized)

    def test_vault_strips_leading_title_line(self) -> None:
        body = (self.vault / "Personal" / "Projects" / "Meeting Notes.md").read_text()
        self.assertNotIn("Meeting Notes\n", body)
        self.assertIn("First meeting.", body)

    # -- schema versioning ------------------------------------------------------

    def test_v1_database_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "notesdb.sqlite")
            conn.execute("CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO settings VALUES ('db_version', '1')")
            conn.commit()
            conn.close()
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_DIR / "sql2joplin.py"),
                    "--input", tmp,
                    "--output", tmp,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 4)
            self.assertIn("version 1", result.stdout)


    def test_v2_database_is_migrated_to_v4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            output = tmp / "output"
            output.mkdir()
            conn = sqlite3.connect(tmp / "notesdb.sqlite")
            conn.execute("CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO settings VALUES ('db_version', '2')")
            conn.execute(
                "CREATE TABLE notes (note_id INTEGER PRIMARY KEY, "
                "note_internal_date DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.commit()
            conn.close()
            run("sql2joplin.py", "--input", str(tmp), "--output", str(output))
            conn = sqlite3.connect(tmp / "notesdb.sqlite")
            version = conn.execute(
                "SELECT value FROM settings WHERE name = 'db_version'"
            ).fetchone()[0]
            columns = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(notes)")}
            conn.close()
            self.assertEqual(version, "5")
            self.assertIn("note_source_raw", columns)
            self.assertIn("note_source_sha256", columns)
            self.assertIn("joplin_share_id", columns)
            self.assertIn("joplinididx", indexes)
            self.assertIn("joplintypeidx", indexes)

    def test_v3_source_bytes_are_fingerprinted_during_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            database_path = Path(tmp_name) / "notesdb.sqlite"
            raw = b"Title\n\nid: abcdefabcdefabcdefabcdefabcdefab\ntype_: 1"
            conn = sqlite3.connect(database_path)
            conn.execute("CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO settings VALUES ('db_version', '3')")
            conn.execute(
                "CREATE TABLE notes (note_id INTEGER PRIMARY KEY, "
                "joplin_id TEXT, note_source_raw BLOB)"
            )
            conn.execute(
                "INSERT INTO notes (joplin_id, note_source_raw) VALUES (?, ?)",
                ("abcdefabcdefabcdefabcdefabcdefab", raw),
            )
            conn.commit()
            conn.close()

            migrated = notesdb.open_database(database_path, "test")
            value = migrated.execute(
                "SELECT note_source_sha256 FROM notes"
            ).fetchone()[0]
            version = migrated.execute(
                "SELECT value FROM settings WHERE name = 'db_version'"
            ).fetchone()[0]
            migrated.close()
            self.assertEqual(value, hashlib.sha256(raw).digest())
            self.assertEqual(version, "5")


class NumericOrderPropertyTest(unittest.TestCase):
    """Joplin's numeric order property accepts scientific notation."""

    def test_subnormal_scientific_order_imports_and_round_trips(self) -> None:
        self.assertEqual(notesdb.JOPLIN_COLUMNS["joplin_order"], "REAL")
        self.assertEqual(
            joplin2sql._convert_known_value("6e-323", "REAL"),
            float("6e-323"),
        )
        self.assertIsNone(joplin2sql._convert_known_value("", "REAL"))
        note_id = "000132e29b64495c85903ff1b0f5f208"
        raw = (
            "Kate Garraway’s husband Derek Draper became \n\n"
            f"id: {note_id}\n"
            "parent_id: e772bcd6354341d8ae41575daa1572da\n"
            "created_time: 2022-05-17T21:42:57.051Z\n"
            "updated_time: 2023-08-26T00:51:05.626Z\n"
            "is_conflict: 0\n"
            "latitude: 49.29270935\n"
            "longitude: -123.04773712\n"
            "altitude: 0.0000\n"
            "author: \n"
            "source_url: \n"
            "is_todo: 0\n"
            "todo_due: 0\n"
            "todo_completed: 0\n"
            "source: joplin-desktop\n"
            "source_application: net.cozic.joplin-desktop\n"
            "application_data: \n"
            "order: 6e-323\n"
            "user_created_time: 2022-05-17T21:42:57.051Z\n"
            "user_updated_time: 2022-05-17T21:53:33.597Z\n"
            "encryption_cipher_text: \n"
            "encryption_applied: 0\n"
            "markup_language: 1\n"
            "is_shared: 0\n"
            "share_id: \n"
            "conflict_original_id: \n"
            "master_key_id: \n"
            "user_data: \n"
            "deleted_time: 0\n"
            "type_: 1"
        ).encode("utf-8")

        with tempfile.TemporaryDirectory(prefix="movenotes-order-") as tmp_name:
            tmp = Path(tmp_name)
            source = tmp / "source"
            sqlite_dir = tmp / "sqlite"
            joplin_out = tmp / "joplin"
            vault = tmp / "vault"
            for directory in (source, sqlite_dir, joplin_out, vault):
                directory.mkdir()
            (source / f"{note_id}.md").write_bytes(raw)

            run("joplin2sql.py", "--input", str(source), "--output", str(sqlite_dir))

            conn = sqlite3.connect(sqlite_dir / "notesdb.sqlite")
            declared_type = next(
                row[2]
                for row in conn.execute("PRAGMA table_info(notes)")
                if row[1] == "joplin_order"
            )
            value, storage_type = conn.execute(
                "SELECT joplin_order, typeof(joplin_order) FROM notes WHERE joplin_id = ?",
                (note_id,),
            ).fetchone()
            conn.close()
            self.assertEqual(declared_type, "REAL")
            self.assertEqual(storage_type, "real")
            self.assertEqual(value, float("6e-323"))

            run("sql2joplin.py", "--input", str(sqlite_dir), "--output", str(joplin_out))
            self.assertEqual((joplin_out / f"{note_id}.md").read_bytes(), raw)

            run("sql2obsidian.py", "--input", str(sqlite_dir), "--output", str(vault))
            exported_notes = list(vault.rglob("*.md"))
            visible_notes = [
                path
                for path in exported_notes
                if PRESERVATION_DIR_NAME not in path.parts
            ]
            self.assertEqual(len(visible_notes), 1)
            obsidian = visible_notes[0].read_text(encoding="utf-8")
            self.assertIn('joplin-order: "6e-323"', obsidian)
            self.assertIn('"order":"6e-323"', obsidian)


class PerformanceRegressionTest(unittest.TestCase):
    """Guard the linear-time data structures used by large conversions."""

    @staticmethod
    def _make_source(directory: Path, count: int) -> str:
        directory.mkdir(parents=True, exist_ok=True)
        folder_id = "f" * 32
        (directory / f"{folder_id}.md").write_text(
            "Perf Folder\n\n"
            f"id: {folder_id}\nparent_id: \n"
            "created_time: 2020-01-01T00:00:00.000Z\n"
            "updated_time: 2020-01-01T00:00:00.000Z\n"
            "is_shared: 0\ntype_: 2\n",
            encoding="utf-8",
        )
        for index in range(count):
            item_id = f"{index:032x}"
            (directory / f"{item_id}.md").write_text(
                f"Note {index}\n\nBody {index}.\n\n"
                f"id: {item_id}\nparent_id: {folder_id}\n"
                "created_time: 2020-02-02T00:00:00.000Z\n"
                "updated_time: 2020-02-02T00:00:00.000Z\n"
                "markup_language: 1\nis_shared: 0\ntype_: 1\n",
                encoding="utf-8",
            )
        return folder_id

    def test_joplin_id_lookup_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="movenotes-index-") as tmp_name:
            root = Path(tmp_name)
            source = root / "source"
            output = root / "output"
            output.mkdir()
            self._make_source(source, 3)
            run("joplin2sql.py", "--input", str(source), "--output", str(output))

            conn = sqlite3.connect(output / notesdb.DATABASE_FILENAME)
            plan = conn.execute(
                "EXPLAIN QUERY PLAN SELECT note_source_sha256 FROM notes "
                "WHERE joplin_id = ?",
                ("x",),
            ).fetchall()
            conn.close()
            detail = " ".join(str(row[-1]) for row in plan)
            self.assertIn("USING INDEX", detail)
            self.assertNotIn("SCAN notes", detail)

    def test_existing_database_repairs_missing_joplin_id_index(self) -> None:
        with tempfile.TemporaryDirectory(prefix="movenotes-index-repair-") as tmp_name:
            root = Path(tmp_name)
            source = root / "source"
            output = root / "output"
            output.mkdir()
            self._make_source(source, 2)
            run("joplin2sql.py", "--input", str(source), "--output", str(output))

            database = output / notesdb.DATABASE_FILENAME
            conn = sqlite3.connect(database)
            conn.execute('DROP INDEX IF EXISTS "joplinididx"')
            conn.commit()
            conn.close()

            conn = notesdb.open_database(database, "test")
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = 'notes'"
                )
            }
            conn.close()
            self.assertIn("joplinididx", names)

    def test_import_uses_batched_input_scoped_fingerprint_queries(self) -> None:
        from unittest import mock

        counts: dict[int, int] = {}
        for size in (5, 40):
            with tempfile.TemporaryDirectory(
                prefix=f"movenotes-query-count-{size}-"
            ) as tmp_name:
                root = Path(tmp_name)
                source = root / "source"
                output = root / "output"
                output.mkdir()
                self._make_source(source, size)
                run("joplin2sql.py", "--input", str(source), "--output", str(output))

                statements: list[str] = []
                original_connect = notesdb.connect

                def counting_connect(path):  # noqa: ANN001
                    conn = original_connect(path)
                    conn.set_trace_callback(statements.append)
                    return conn

                with mock.patch.object(notesdb, "connect", side_effect=counting_connect):
                    with mock.patch("sys.stdout", new=io.StringIO()):
                        joplin2sql.main(
                            [
                                "--input",
                                str(source),
                                "--output",
                                str(output),
                                "--progress-every",
                                "0",
                            ]
                        )

                selects = [
                    statement
                    for statement in statements
                    if statement.lstrip().upper().startswith("SELECT")
                ]
                fingerprint_selects = [
                    statement
                    for statement in selects
                    if "note_source_sha256" in statement
                ]
                self.assertTrue(fingerprint_selects)
                self.assertTrue(all(" IN (" in statement for statement in fingerprint_selects))
                counts[size] = len(selects)

        self.assertLessEqual(counts[40], counts[5] + 1, counts)

    def test_folder_source_is_parsed_once_and_database_update_is_avoided(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory(prefix="movenotes-folder-cache-") as tmp_name:
            root = Path(tmp_name)
            source = root / "source"
            output = root / "output"
            output.mkdir()
            folder_id = self._make_source(source, 100)
            folder_path = source / f"{folder_id}.md"
            original = joplin2sql.parse_joplin_note

            with mock.patch.object(
                joplin2sql, "parse_joplin_note", wraps=original
            ) as parser, mock.patch.object(
                notesdb, "populate_missing_note_folders", wraps=notesdb.populate_missing_note_folders
            ) as fallback, mock.patch("sys.stdout", new=io.StringIO()):
                joplin2sql.main(
                    [
                        "--input",
                        str(source),
                        "--output",
                        str(output),
                        "--progress-every",
                        "0",
                    ]
                )

            folder_calls = [
                call for call in parser.call_args_list if call.args[0] == folder_path
            ]
            self.assertEqual(len(folder_calls), 1)
            fallback.assert_not_called()

    def test_noncanonical_folder_filename_uses_targeted_fallback(self) -> None:
        folder_id = "f" * 32
        note_id = "0" * 32
        with tempfile.TemporaryDirectory(prefix="movenotes-folder-fallback-") as tmp_name:
            root = Path(tmp_name)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            (source / "z-renamed-folder.md").write_text(
                f"Renamed Folder\n\nid: {folder_id}\ntype_: 2\n",
                encoding="utf-8",
            )
            (source / f"{note_id}.md").write_text(
                f"Child\n\nid: {note_id}\nparent_id: {folder_id}\ntype_: 1\n",
                encoding="utf-8",
            )
            run(
                "joplin2sql.py",
                "--input",
                str(source),
                "--output",
                str(output),
                "--batch-size",
                "1",
            )
            conn = sqlite3.connect(output / notesdb.DATABASE_FILENAME)
            folder = conn.execute(
                "SELECT note_folder FROM notes WHERE joplin_id = ?", (note_id,)
            ).fetchone()[0]
            conn.close()
            self.assertEqual(folder, "Renamed Folder")

    def test_uppercase_markdown_extension_is_imported(self) -> None:
        item_id = "abcdefabcdefabcdefabcdefabcdefab"
        with tempfile.TemporaryDirectory(prefix="movenotes-uppercase-") as tmp_name:
            root = Path(tmp_name)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            (source / f"{item_id}.MD").write_text(
                f"Uppercase\n\nid: {item_id}\ntype_: 1\n", encoding="utf-8"
            )
            run("joplin2sql.py", "--input", str(source), "--output", str(output))
            conn = sqlite3.connect(output / notesdb.DATABASE_FILENAME)
            count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)

    def test_twitter_media_fallback_uses_one_directory_index(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory(prefix="movenotes-twitter-media-index-") as tmp_name:
            root = Path(tmp_name)
            media = root / "media"
            resources = root / "resources"
            media.mkdir()
            resources.mkdir()
            tweet_ids = [str(10_000_000_000 + index) for index in range(200)]
            for tweet_id in tweet_ids:
                (media / f"{tweet_id}-video.mp4").write_bytes(tweet_id.encode())

            importer = twitterx2sql.ResourceImporter(media, resources, set())
            with mock.patch.object(
                Path, "glob", side_effect=AssertionError("repeated directory scan")
            ):
                for tweet_id in tweet_ids:
                    source = importer._archive_file(
                        tweet_id, f"https://example.invalid/{tweet_id}-thumb.jpg"
                    )
                    self.assertIsNotNone(source)
                    self.assertEqual(source.name, f"{tweet_id}-video.mp4")

    def test_name_deduplication_keeps_a_forward_counter(self) -> None:
        dedup = sql2obsidian.NameDeduplicator()
        names = [dedup.reserve("folder", "Repeated", ".md") for _ in range(5000)]
        self.assertEqual(names[0], "Repeated.md")
        self.assertEqual(names[-1], "Repeated 5000.md")
        self.assertEqual(len(set(names)), len(names))

    def test_filtered_preservation_parses_each_row_once(self) -> None:
        from unittest import mock

        count = 1000
        rows = []
        for index in range(count):
            item_id = f"{index:032x}"
            properties = [["id", item_id], ["type_", "1"]]
            if index + 1 < count:
                properties.append(["master_key_id", f"{index + 1:032x}"])
            rows.append(
                {
                    "note_id": index + 1,
                    "joplin_id": item_id,
                    "joplin_type_": int(constants.JoplinType.NOTE),
                    "note_source_properties": json.dumps(properties),
                }
            )

        original = sql2obsidian._property_id_map
        with mock.patch.object(
            sql2obsidian, "_property_id_map", wraps=original
        ) as property_map:
            selected = sql2obsidian._select_preserved_rows(
                rows, set(), {f'{0:032x}'}, set()
            )
        self.assertEqual(len(selected), count)
        self.assertEqual(property_map.call_count, count)

    def test_source_fingerprint_skips_exact_reimport_and_rejects_collision(self) -> None:
        item_id = "abcdefabcdefabcdefabcdefabcdefab"
        with tempfile.TemporaryDirectory(prefix="movenotes-fingerprint-") as tmp_name:
            tmp = Path(tmp_name)
            source1 = tmp / "source1"
            source2 = tmp / "source2"
            output = tmp / "sqlite"
            for directory in (source1, source2, output):
                directory.mkdir()
            raw1 = f"One\n\nid: {item_id}\ntype_: 1".encode()
            raw2 = f"Two\n\nid: {item_id}\ntype_: 1".encode()
            (source1 / f"{item_id}.md").write_bytes(raw1)
            (source2 / f"{item_id}.md").write_bytes(raw2)

            run("joplin2sql.py", "--input", str(source1), "--output", str(output))
            repeated = run(
                "joplin2sql.py", "--input", str(source1), "--output", str(output)
            )
            self.assertIn("1 already present", repeated.stdout)
            conn = sqlite3.connect(output / notesdb.DATABASE_FILENAME)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 1)
            digest = conn.execute(
                "SELECT note_source_sha256 FROM notes"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(digest, hashlib.sha256(raw1).digest())

            collision = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_DIR / "joplin2sql.py"),
                    "--input",
                    str(source2),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(collision.returncode, 0)
            self.assertIn("item id collision", collision.stderr)




class PdfResourceOcrControlCharactersTest(unittest.TestCase):
    """Resource OCR text may contain controls that are not physical newlines."""

    def test_pdf_resource_ocr_controls_import_and_round_trip(self) -> None:
        resource_id = "1a60ac9eba4e4d03988f7ce662f7cb2b"
        # These controls are among the characters str.splitlines() treats as
        # line boundaries. They must remain inside one ocr_text property.
        ocr_text = "SIP\\npage\x0bform\x0cfile\x1crecord\x1enext\x85end"
        raw = (
            "an-overview-of-coding-tools-in-av1.pdf\n\n"
            f"id: {resource_id}\n"
            "mime: application/pdf\n"
            "filename: \n"
            "file_extension: pdf\n"
            "size: 740260\n"
            f"ocr_text: {ocr_text}\n"
            "ocr_details: \n"
            "ocr_status: 2\n"
            "ocr_error: \n"
            "ocr_driver_id: 1\n"
            "type_: 4"
        ).encode("utf-8")

        with tempfile.TemporaryDirectory(prefix="movenotes-pdf-ocr-") as tmp_name:
            tmp = Path(tmp_name)
            source = tmp / "source"
            sqlite_dir = tmp / "sqlite"
            joplin_out = tmp / "joplin"
            for directory in (source, sqlite_dir, joplin_out):
                directory.mkdir()
            (source / f"{resource_id}.md").write_bytes(raw)

            run("joplin2sql.py", "--input", str(source), "--output", str(sqlite_dir))

            conn = sqlite3.connect(sqlite_dir / "notesdb.sqlite")
            row = conn.execute(
                "SELECT joplin_ocr_text, note_source_raw, note_source_properties "
                "FROM notes WHERE joplin_id = ?",
                (resource_id,),
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], ocr_text)
            self.assertEqual(row[1], raw)
            self.assertIn(["ocr_text", ocr_text], json.loads(row[2]))

            run("sql2joplin.py", "--input", str(sqlite_dir), "--output", str(joplin_out))
            self.assertEqual((joplin_out / f"{resource_id}.md").read_bytes(), raw)

class LosslessPreservationTest(unittest.TestCase):
    """Exercise future fields, CRLF input, non-note items and raw resources."""

    def test_unknown_properties_and_all_items_survive_both_exports(self) -> None:
        folder_id = "10000000000000000000000000000000"
        note_id = "20000000000000000000000000000000"
        resource_id = "30000000000000000000000000000000"
        aux_id = "40000000000000000000000000000000"

        with tempfile.TemporaryDirectory(prefix="movenotes-lossless-") as tmp_name:
            tmp = Path(tmp_name)
            source = tmp / "source"
            sqlite_dir = tmp / "sqlite"
            joplin_out = tmp / "joplin"
            vault = tmp / "vault"
            for directory in (source, sqlite_dir, joplin_out, vault):
                directory.mkdir()
            (source / "resources").mkdir()

            raw_items = {
                f"{folder_id}.md": (
                    "Future Notebook\r\n\r\n"
                    f"id: {folder_id}\r\n"
                    "created_time: 2026-07-01T01:02:03.004Z\r\n"
                    "updated_time: 2026-07-02T01:02:03.004Z\r\n"
                    "icon: fas fa-archive\r\n"
                    "future_folder_field: alpha:beta\r\n"
                    "parent_id: \r\n"
                    "type_: 2"
                ).encode(),
                f"{note_id}.md": (
                    "Future Note\r\n\r\n"
                    f"Attachment: [payload.bin](:/{resource_id})\r\n"
                    "URL: [https://example.com](https://example.com)\r\n\r\n"
                    f"id: {note_id}\r\n"
                    f"parent_id: {folder_id}\r\n"
                    "created_time: 2026-07-03T01:02:03.004Z\r\n"
                    "updated_time: 2026-07-04T01:02:03.004Z\r\n"
                    "share_id: share-123\r\n"
                    "source_url:  https://example.org/source  \r\n"
                    "master_key_id: key-456\r\n"
                    "user_data: {\"nested\":\"a:b\"}\r\n"
                    "deleted_time: 123456789\r\n"
                    "is_locked: 1\r\n"
                    "future_property:  value:with:colons  \r\n"
                    "duplicate_future: first\r\n"
                    "duplicate_future: second\r\n"
                    "foo_bar: underscore\r\n"
                    "foo-bar: hyphen\r\n"
                    "type_: 1"
                ).encode(),
                f"{resource_id}.md": (
                    "payload.bin\r\n\r\n"
                    f"id: {resource_id}\r\n"
                    "mime: application/octet-stream\r\n"
                    "file_extension: bin\r\n"
                    "ocr_text: line one\\nline two\r\n"
                    "ocr_status: 2\r\n"
                    "future_resource_field: retained\r\n"
                    "type_: 4"
                ).encode(),
                f"{aux_id}.md": (
                    f"id: {aux_id}\r\n"
                    f"note_id: {note_id}\r\n"
                    "state: custom\r\n"
                    "type_: 18"
                ).encode(),
            }
            for name, data in raw_items.items():
                (source / name).write_bytes(data)
            resource_bytes = b"\x00\x01lossless-resource\xff"
            (source / "resources" / f"{resource_id}.bin").write_bytes(resource_bytes)

            run("joplin2sql.py", "--input", str(source), "--output", str(sqlite_dir))

            conn = sqlite3.connect(sqlite_dir / "notesdb.sqlite")
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM notes WHERE joplin_id = ?", (note_id,)
            ).fetchone()
            self.assertEqual(row["note_source_raw"], raw_items[f"{note_id}.md"])
            self.assertEqual(row["joplin_share_id"], "share-123")
            self.assertEqual(row["joplin_master_key_id"], "key-456")
            self.assertEqual(row["joplin_source_url"], "https://example.org/source")
            self.assertEqual(row["joplin_deleted_time"], 123456789)
            properties = json.loads(row["note_source_properties"])
            self.assertIn(["future_property", " value:with:colons  "], properties)
            self.assertEqual(
                [pair for pair in properties if pair[0] == "duplicate_future"],
                [["duplicate_future", "first"], ["duplicate_future", "second"]],
            )
            conn.close()

            run("sql2joplin.py", "--input", str(sqlite_dir), "--output", str(joplin_out))
            for name, data in raw_items.items():
                self.assertEqual((joplin_out / name).read_bytes(), data)
            self.assertEqual(
                (joplin_out / "resources" / f"{resource_id}.bin").read_bytes(),
                resource_bytes,
            )

            run("sql2obsidian.py", "--input", str(sqlite_dir), "--output", str(vault))
            note = (vault / "Future Notebook" / "Future Note.md").read_text()
            self.assertIn('joplin-share-id: "share-123"', note)
            self.assertIn('joplin-future-property: " value:with:colons  "', note)
            self.assertIn('joplin-foo-bar: "underscore"', note)
            self.assertIn('joplin-foo-bar-2: "hyphen"', note)
            frontmatter_lines = dict(
                line.split(": ", 1)
                for line in note.splitlines()
                if line.startswith(("joplin: ", "joplin-properties: "))
            )
            structured = json.loads(frontmatter_lines["joplin"])
            ordered = json.loads(frontmatter_lines["joplin-properties"])
            self.assertEqual(structured["future_property"], " value:with:colons  ")
            self.assertEqual(structured["source_url"], " https://example.org/source  ")
            self.assertEqual(structured["duplicate_future"], "second")
            self.assertEqual(
                [pair for pair in ordered if pair[0] == "duplicate_future"],
                [["duplicate_future", "first"], ["duplicate_future", "second"]],
            )
            self.assertIn("joplin-properties-json:", note)
            self.assertIn("URL: https://example.com", note)

            preserved = vault / PRESERVATION_DIR_NAME / "joplin-raw"
            for name, data in raw_items.items():
                self.assertEqual((preserved / name).read_bytes(), data)
            self.assertEqual(
                (preserved / "resources" / f"{resource_id}.bin").read_bytes(),
                resource_bytes,
            )
            manifest = json.loads(
                (vault / PRESERVATION_DIR_NAME / "manifest.json").read_text()
            )
            self.assertEqual(manifest["scope"], "full")
            self.assertEqual(len(manifest["items"]), len(raw_items))
            self.assertTrue(all(item["sha256"] for item in manifest["items"]))

    def test_preservation_bundle_reports_its_phases(self) -> None:
        """Step 44: the bundle runs after the last `exported N` line.

        On a full Joplin library it writes 173,290 files and an 83 MB manifest,
        long enough that silence there reads as a hang. Each phase says what it
        is, the item loop counts like the export loop, and `--progress-every 0`
        turns all of it off.
        """
        with tempfile.TemporaryDirectory(prefix="movenotes-phases-") as tmp_name:
            tmp = Path(tmp_name)
            source, sqlite_dir, vault = tmp / "raw", tmp / "db", tmp / "vault"
            for path in (source, sqlite_dir, vault):
                path.mkdir(parents=True)
            (source / "resources").mkdir()
            note_id = "b" * 32
            (source / f"{note_id}.md").write_bytes(
                f"Phase Note\n\nBody\n\nid: {note_id}\ntype_: 1".encode()
            )
            run("joplin2sql.py", "--input", str(source), "--output", str(sqlite_dir))

            first = run(
                "sql2obsidian.py", "--input", str(sqlite_dir), "--output", str(vault),
                "--progress-every", "1",
            )
            self.assertIn("writing preserved Joplin item(s)...", first.stdout)
            # An exact line: the summary also contains "preserved 1 Joplin
            # item(s) and ...", so a substring test would pass without the
            # counter existing at all.
            self.assertIn("preserved 1 Joplin item(s)", first.stdout.splitlines())
            self.assertIn("writing the preservation manifest for", first.stdout)
            # Nothing to remove on a first export.
            self.assertNotIn("removing the previous preservation bundle", first.stdout)

            # A re-export deletes the old bundle first, which on a real library
            # is thousands of files and the slowest phase of the four.
            second = run(
                "sql2obsidian.py", "--input", str(sqlite_dir), "--output", str(vault),
                "--progress-every", "1",
            )
            self.assertIn("removing the previous preservation bundle...", second.stdout)

            quiet = run(
                "sql2obsidian.py", "--input", str(sqlite_dir), "--output", str(vault),
                "--progress-every", "0",
            )
            for phase in (
                "removing the previous preservation bundle",
                "writing preserved Joplin item(s)",
                "copying raw resource file(s)",
                "writing the preservation manifest",
            ):
                self.assertNotIn(phase, quiet.stdout)
            self.assertNotIn("preserved 1 Joplin item(s)", quiet.stdout.splitlines())
            # The summary is not progress and must survive.
            self.assertIn("preserved 1 Joplin item(s) and", quiet.stdout)

    def test_conflicting_resource_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="movenotes-collision-") as tmp_name:
            tmp = Path(tmp_name)
            sqlite_dir = tmp / "sqlite"
            sqlite_dir.mkdir()
            resource_name = "abcdefabcdefabcdefabcdefabcdefab.bin"
            sources = []
            for index, payload in enumerate((b"first", b"second"), start=1):
                source = tmp / f"source{index}"
                (source / "resources").mkdir(parents=True)
                (source / "resources" / resource_name).write_bytes(payload)
                sources.append(source)
            run("joplin2sql.py", "--input", str(sources[0]), "--output", str(sqlite_dir))
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_DIR / "joplin2sql.py"),
                    "--input", str(sources[1]),
                    "--output", str(sqlite_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("resource collision", result.stderr)



SAMPLE_TWITTER = PROJECT_DIR / "sample" / "twitter-archive"


class TwitterImportEndToEnd(unittest.TestCase):
    """Import the sample Twitter/X archive and export it both ways."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="movenotes-twitter-")
        tmp = Path(cls._tmp.name)
        cls.sqlite_dir = tmp / "sqlite"
        cls.joplin_out = tmp / "joplin_out"
        cls.vault = tmp / "vault"
        for d in (cls.sqlite_dir, cls.joplin_out, cls.vault):
            d.mkdir()
        run(
            "twitterx2sql.py",
            "--input", str(SAMPLE_TWITTER),
            "--output", str(cls.sqlite_dir),
            "--notebook", "Tweets",
            "--no-expand-tco",
        )
        run("sql2joplin.py", "--input", str(cls.sqlite_dir), "--output", str(cls.joplin_out))
        run("sql2obsidian.py", "--input", str(cls.sqlite_dir), "--output", str(cls.vault))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _note_bodies(self) -> list[str]:
        conn = sqlite3.connect(self.sqlite_dir / "notesdb.sqlite")
        bodies = [
            row[0]
            for row in conn.execute(
                "SELECT note_data FROM notes WHERE joplin_type_ = 1 "
                "ORDER BY note_internal_date"
            )
        ]
        conn.close()
        return bodies

    def test_import_counts_and_notebook(self) -> None:
        conn = sqlite3.connect(self.sqlite_dir / "notesdb.sqlite")
        counts = dict(
            conn.execute("SELECT joplin_type_, COUNT(*) FROM notes GROUP BY 1")
        )
        folders = [
            r[0] for r in conn.execute("SELECT note_folder FROM notes WHERE joplin_type_=1")
        ]
        conn.close()
        self.assertEqual(counts, {1: 3, 2: 1, 4: 1})  # 3 tweets, notebook, photo
        self.assertEqual(folders, ["Tweets"] * 3)

    def test_tco_expanded_from_entities(self) -> None:
        bodies = "\n".join(self._note_bodies())
        self.assertIn("https://example.com/notes-article", bodies)
        self.assertNotIn("https://t.co/abc123", bodies)

    def test_html_entities_unescaped(self) -> None:
        self.assertIn("notes & tools", "\n".join(self._note_bodies()))

    def test_uncovered_tco_kept_without_network(self) -> None:
        # Not in URL entities and --no-expand-tco: left in place.
        self.assertIn("https://t.co/leftover1", "\n".join(self._note_bodies()))

    def test_media_becomes_embedded_resource(self) -> None:
        bodies = "\n".join(self._note_bodies())
        self.assertNotIn("https://t.co/med456", bodies)
        match = re.search(r"!\[sunset\.jpg\]\(:/([a-f0-9]{32})\)", bodies)
        self.assertIsNotNone(match)
        resource_file = self.sqlite_dir / "resources" / f"{match.group(1)}.jpg"
        self.assertEqual(
            resource_file.read_bytes(),
            (SAMPLE_TWITTER / "data" / "tweets_media"
             / "1000000000000000002-sunset.jpg").read_bytes(),
        )

    def test_notebook_reused_on_second_import(self) -> None:
        run(
            "twitterx2sql.py",
            "--input", str(SAMPLE_TWITTER),
            "--output", str(self.sqlite_dir),
            "--notebook", "Tweets",
            "--no-expand-tco",
        )
        conn = sqlite3.connect(self.sqlite_dir / "notesdb.sqlite")
        (folder_count,) = conn.execute(
            "SELECT COUNT(*) FROM notes WHERE joplin_type_ = 2"
        ).fetchone()
        conn.close()
        self.assertEqual(folder_count, 1)
        # The duplicated tweets are removable.
        result = run("removedups.py", "--input", str(self.sqlite_dir))
        self.assertIn("removed 3 duplicate note(s)", result.stdout)

    def test_joplin_export_items_reparse(self) -> None:
        sys.path.insert(0, str(PROJECT_DIR))
        try:
            from joplin2sql import parse_joplin_note
        finally:
            sys.path.pop(0)
        md_files = sorted(self.joplin_out.glob("*.md"))
        self.assertEqual(len(md_files), 5)
        for md_file in md_files:
            columns = parse_joplin_note(md_file)
            self.assertTrue(columns["joplin_id"], md_file.name)
            self.assertEqual(columns["joplin_id"], md_file.stem)

    def test_source_url_in_vault_frontmatter(self) -> None:
        body = (self.vault / "Tweets" / "Sunset from the office.md").read_text()
        self.assertIn(
            'source-url: "https://x.com/example_user/status/1000000000000000002"',
            body,
        )
        self.assertIn("![[sunset.jpg]]", body)


class TwitterMetadataFormattingTest(unittest.TestCase):
    def test_reply_timestamp_and_engagement_are_rendered(self) -> None:
        with tempfile.TemporaryDirectory(prefix="movenotes-twitter-metadata-") as temporary:
            root = Path(temporary)
            resources = twitterx2sql.ResourceImporter(None, root / "resources", set())
            expander = twitterx2sql.TcoExpander(root / "cache.json", enabled=False)
            row = twitterx2sql.convert_tweet(
                {
                    "id_str": "1287363990922891265",
                    "created_at": "Tue Jul 21 18:08:00 +0000 2026",
                    "full_text": "tweet/post text",
                    "in_reply_to_status_id_str": "1928909355815952492",
                    "in_reply_to_screen_name": "renesugar",
                    "retweet_count": 10,
                    "favorite_count": 5,
                },
                "folder-id",
                "Twitter",
                "example_user",
                resources,
                expander,
                timezone(timedelta(hours=-7)),
            )
            body = row["note_data"]
            self.assertIn(
                "In reply to: [@renesugar](https://x.com/i/web/status/1928909355815952492)",
                body,
            )
            self.assertIn("tweet/post text", body)
            self.assertIn(
                "[11:08 AM · Jul 21, 2026](https://x.com/i/web/status/1287363990922891265) 🔁 10 💙 5",
                body,
            )
            metadata = json.loads(row["joplin_application_data"])["movenotes"]["twitter"]
            self.assertEqual(metadata["status_id"], "1287363990922891265")
            self.assertEqual(metadata["in_reply_to_screen_name"], "renesugar")
            self.assertEqual(metadata["retweet_count"], 10)
            self.assertEqual(metadata["favorite_count"], 5)


class TcoExpanderTest(unittest.TestCase):
    """Test redirect following against a local HTTP server."""

    def test_expand_follows_redirect_chain_and_caches(self) -> None:
        import http.server
        import threading

        from twitterx2sql import TcoExpander

        class Redirector(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                if self.path == "/hop1":
                    self.send_response(301)
                    self.send_header(
                        "Location",
                        f"http://127.0.0.1:{self.server.server_port}/hop2",
                    )
                elif self.path == "/hop2":
                    self.send_response(301)
                    self.send_header("Location", "https://example.com/final")
                else:
                    self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        url = f"http://127.0.0.1:{server.server_port}/hop1"

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "tco_cache.json"
            expander = TcoExpander(cache_path, enabled=True)
            self.assertEqual(expander.expand(url), "https://example.com/final")
            expander.save_cache()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

            # Second instance answers from the cache with the server gone.
            cached = TcoExpander(cache_path, enabled=True)
            self.assertEqual(cached.expand(url), "https://example.com/final")

            # Unreachable links fall back to the original URL.
            uncached = TcoExpander(Path(tmp) / "x.json", enabled=True, timeout=2)
            self.assertEqual(uncached.expand(url), url)

            # A disabled expander is a no-op.
            disabled = TcoExpander(Path(tmp) / "y.json", enabled=False)
            self.assertEqual(disabled.expand(url), url)

    def test_expand_resolves_relative_and_network_path_locations(self) -> None:
        import http.server
        import threading

        from twitterx2sql import TcoExpander

        class RelativeRedirector(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                if self.path == "/short":
                    self.send_response(302)
                    self.send_header("Location", "/x/nowthisnews/status/1148324122746851330")
                elif self.path == "/x/nowthisnews/status/1148324122746851330":
                    self.send_response(301)
                    self.send_header(
                        "Location",
                        f"//127.0.0.1:{self.server.server_port}/nowthisimpact/status/1148324122746851330",
                    )
                else:
                    self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), RelativeRedirector)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"

        try:
            with tempfile.TemporaryDirectory() as tmp:
                expander = TcoExpander(Path(tmp) / "cache.json", enabled=True)
                self.assertEqual(
                    expander.expand(f"{origin}/short"),
                    f"{origin}/nowthisimpact/status/1148324122746851330",
                )
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_relative_cache_entry_is_ignored(self) -> None:
        from twitterx2sql import TcoExpander

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            cache_path.write_text(
                json.dumps({"https://t.co/example": "/missing-domain/status/1"}),
                encoding="utf-8",
            )
            expander = TcoExpander(cache_path, enabled=True, timeout=0.01)
            self.assertEqual(expander.expand("https://t.co/example"), "https://t.co/example")

    def test_invalid_redirect_schemes_and_malformed_urls_are_rejected(self) -> None:
        from twitterx2sql import TcoExpander

        base = "https://x.com/nowthisnews/status/1148324122746851330"
        self.assertEqual(
            TcoExpander._resolve_location(
                base, "/nowthisimpact/status/1148324122746851330"
            ),
            "https://x.com/nowthisimpact/status/1148324122746851330",
        )
        self.assertIsNone(TcoExpander._resolve_location(base, "javascript:alert(1)"))
        self.assertIsNone(TcoExpander._resolve_location(base, "http://[invalid"))


class NotebookFilteringTest(unittest.TestCase):
    """Test sql2obsidian.py --notebooks selection for publishing subsets."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="movenotes-filter-")
        tmp = Path(cls._tmp.name)
        cls.sqlite_dir = tmp / "sqlite"
        cls.sqlite_dir.mkdir()
        run("joplin2sql.py", "--input", str(SAMPLE_SOURCE1), "--output", str(cls.sqlite_dir))
        run("joplin2sql.py", "--input", str(SAMPLE_SOURCE2), "--output", str(cls.sqlite_dir))

        # Add two NOTE_RESOURCE relationship items for the same resource.  The
        # selected Projects note's relation belongs in a filtered preservation
        # bundle; the private Personal note's backlink must not be pulled in
        # merely because the resource itself is selected.
        relation_source = tmp / "relations"
        relation_source.mkdir()
        (relation_source / "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee.md").write_text(
            "id: eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee\n"
            "note_id: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "resource_id: aaaabbbbccccddddeeeeffff00001111\n"
            "type_: 11",
            encoding="utf-8",
        )
        (relation_source / "ffffffffffffffffffffffffffffffff.md").write_text(
            "id: ffffffffffffffffffffffffffffffff\n"
            "note_id: 44444444444444444444444444444444\n"
            "resource_id: aaaabbbbccccddddeeeeffff00001111\n"
            "type_: 11",
            encoding="utf-8",
        )
        run("joplin2sql.py", "--input", str(relation_source), "--output", str(cls.sqlite_dir))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _export(self, *notebook_args: str) -> Path:
        vault = Path(tempfile.mkdtemp(dir=self._tmp.name))
        run(
            "sql2obsidian.py",
            *notebook_args,
            "--input", str(self.sqlite_dir),
            "--output", str(vault),
        )
        return vault

    def _files(self, vault: Path) -> set[str]:
        return {
            str(p.relative_to(vault))
            for p in vault.rglob("*")
            if p.is_file() and PRESERVATION_DIR_NAME not in p.parts
        }

    def test_nested_notebook_is_rerooted(self) -> None:
        vault = self._export("--notebooks", "Projects")
        self.assertEqual(
            self._files(vault),
            {
                # 'Projects' is nested under 'Personal' in the source, but
                # the published vault must not expose the parent's name.
                "Projects/Meeting Notes.md",
                "Projects/Meeting Notes 2.md",
                "Projects/Q1 Q2 Plan.md",
                "attachments/photo.png",
                "attachments/report.pdf",
            },
        )
        # Relative links adapt to the re-rooted depth.
        body = (vault / "Projects" / "Q1 Q2 Plan.md").read_text()
        self.assertIn("[report.pdf](../attachments/report.pdf)", body)

    def test_selection_includes_subnotebooks(self) -> None:
        vault = self._export("--notebooks", "Personal")
        files = self._files(vault)
        self.assertIn("Personal/Projects/Meeting Notes.md", files)
        self.assertNotIn("Work/Note With Attachment.md", files)

    def test_only_referenced_attachments_copied(self) -> None:
        vault = self._export("--notebooks", "Work")
        self.assertEqual(
            self._files(vault),
            {"Work/Note With Attachment.md", "attachments/report.pdf"},
        )

    def test_preservation_bundle_matches_filtered_scope(self) -> None:
        vault = self._export("--notebooks", "Projects")
        raw = vault / PRESERVATION_DIR_NAME / "joplin-raw"
        raw_names = {path.name for path in raw.glob("*.md")}
        self.assertIn("77777777777777777777777777777777.md", raw_names)
        self.assertIn("88888888888888888888888888888888.md", raw_names)
        self.assertIn("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee.md", raw_names)
        self.assertNotIn("33333333333333333333333333333333.md", raw_names)
        self.assertNotIn("44444444444444444444444444444444.md", raw_names)
        self.assertNotIn("ffffffffffffffffffffffffffffffff.md", raw_names)
        manifest = json.loads(
            (vault / PRESERVATION_DIR_NAME / "manifest.json").read_text()
        )
        self.assertEqual(manifest["scope"], "selected-notebooks")

    def test_comma_separated_and_repeated_flags(self) -> None:
        for args in (
            ("--notebooks", "Work,Projects"),
            ("--notebooks", "Work", "--notebooks", "Projects"),
        ):
            files = self._files(self._export(*args))
            self.assertIn("Work/Note With Attachment.md", files)
            self.assertIn("Projects/Q1 Q2 Plan.md", files)
            self.assertNotIn("Personal/Unique Note.md", files)

    def test_unknown_notebook_is_an_error(self) -> None:
        vault = Path(tempfile.mkdtemp(dir=self._tmp.name))
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_DIR / "sql2obsidian.py"),
                "--notebooks", "Nope",
                "--input", str(self.sqlite_dir),
                "--output", str(vault),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("notebook 'Nope' not found", result.stderr)
        self.assertEqual(self._files(vault), set())  # nothing published


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Round-trip and regression tests for Obsidian import support."""

from __future__ import annotations

import configparser
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import constants
import notesdb

PROJECT_DIR = Path(__file__).resolve().parent


def run(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROJECT_DIR / script), *args],
        capture_output=True,
        text=True,
        check=check,
    )


class ObsidianRoundTripTest(unittest.TestCase):
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

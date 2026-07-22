#!/usr/bin/env python3
"""Integration tests for images2resources.py and quarantinelinks.py."""

from __future__ import annotations

import base64
import configparser
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import constants
import image_resources
import notesdb
import sql2obsidian

PROJECT_DIR = Path(__file__).resolve().parent
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
)
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")


def run(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROJECT_DIR / script), *args],
        capture_output=True,
        text=True,
        check=check,
    )


class ImageHandler(BaseHTTPRequestHandler):
    get_counts: dict[str, int] = {}

    def log_message(self, format, *args):  # noqa: A003, ANN001
        return

    def _send(self, body: bytes, content_type: str, *, head: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path == "/image.png":
            self._send(PNG, "image/png", head=True)
        elif self.path == "/head405.png":
            self.send_response(405)
            self.end_headers()
        elif self.path == "/redirect.png":
            self.send_response(302)
            self.send_header("Content-Type", "image/png")
            self.send_header("Location", "/final.jpg")
            self.end_headers()
        elif self.path == "/final.jpg":
            self._send(GIF, "image/jpeg", head=True)
        elif self.path == "/wrong.png":
            self._send(GIF, "image/png", head=True)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self.get_counts[self.path] = self.get_counts.get(self.path, 0) + 1
        if self.path in {"/image.png", "/head405.png"}:
            self._send(PNG, "image/png")
        elif self.path == "/redirect.png":
            self.send_response(302)
            self.send_header("Content-Type", "image/png")
            self.send_header("Location", "/final.jpg")
            self.end_headers()
        elif self.path == "/final.jpg":
            self._send(GIF, "image/jpeg")
        elif self.path == "/wrong.png":
            self._send(GIF, "image/png")
        else:
            self.send_response(404)
            self.end_headers()


class ImageResourceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), ImageHandler)
        cls.port = cls._server.server_address[1]
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

        cls._tmp = tempfile.TemporaryDirectory(prefix="movenotes-images-test-")
        cls.root = Path(cls._tmp.name)
        cls.sqlite_dir = cls.root / "sqlite"
        cls.sqlite_dir.mkdir()
        cls.resources = cls.sqlite_dir / "resources"
        cls.resources.mkdir()
        cls.report = cls.root / "report.md"
        cls.config = cls.root / "images.ini"

        gif_data = base64.b64encode(GIF).decode("ascii")
        body = "\n".join(
            [
                "# Image test",
                f"![Embedded](data:image/gif;base64,{gif_data})",
                f"![Remote](http://127.0.0.1:{cls.port}/image.png)",
                f"![HEAD fallback](http://127.0.0.1:{cls.port}/head405.png)",
                f"![Redirect mismatch](http://127.0.0.1:{cls.port}/redirect.png)",
                f"![Wrong bytes](http://127.0.0.1:{cls.port}/wrong.png)",
                "![Blocked](https://blocked.example/image.png)",
                "![Invalid](data:image/png;base64,%%%%)",
                "![Malformed](data:image/png;base64,AAAA",
                "`![Code](https://blocked.example/code.png)`",
                "",
            ]
        )
        conn = notesdb.connect(cls.sqlite_dir / notesdb.DATABASE_FILENAME)
        notesdb.create_database(conn)
        notesdb.add_joplin_note(
            conn,
            {
                "note_type": "note",
                "note_uuid": "11111111111111111111111111111111",
                "note_original_format": "test",
                "note_title": "Image test",
                "note_data": body,
                "note_data_format": "text/markdown",
                "joplin_id": "11111111111111111111111111111111",
                "joplin_type_": int(constants.JoplinType.NOTE),
                "joplin_parent_id": "",
                "joplin_created_time": "2026-01-01T00:00:00.000000Z",
                "joplin_updated_time": "2026-01-01T00:00:00.000000Z",
                "joplin_user_created_time": "2026-01-01T00:00:00.000000Z",
                "joplin_user_updated_time": "2026-01-01T00:00:00.000000Z",
                "joplin_encryption_applied": 0,
                "joplin_is_shared": 0,
            },
        )
        conn.commit()
        conn.close()

        cls.config.write_text(
            "[images2resources]\n"
            "allow_private_networks = true\n"
            "stop_domains = blocked.example\n"
            "workers = 4\n"
            "allow_svg = false\n",
            encoding="utf-8",
        )
        cls.convert = run(
            "images2resources.py",
            "--input",
            str(cls.sqlite_dir),
            "--config",
            str(cls.config),
            "--report",
            str(cls.report),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)
        cls._tmp.cleanup()

    def _body(self) -> str:
        conn = sqlite3.connect(self.sqlite_dir / notesdb.DATABASE_FILENAME)
        body = conn.execute(
            "SELECT note_data FROM notes WHERE joplin_type_ = 1"
        ).fetchone()[0]
        conn.close()
        return body

    def test_converts_data_and_remote_images(self) -> None:
        body = self._body()
        self.assertEqual(len(re.findall(r"\(:/[0-9a-f]{32}\)", body)), 3)
        self.assertNotIn("data:image/gif;base64", body)
        self.assertNotIn(f"http://127.0.0.1:{self.port}/image.png", body)
        self.assertNotIn(f"http://127.0.0.1:{self.port}/head405.png", body)
        self.assertIn("https://blocked.example/image.png", body)
        self.assertIn("data:image/png;base64,%%%%", body)
        self.assertIn("![Malformed](data:image/png;base64,AAAA", body)
        self.assertIn("`![Code](https://blocked.example/code.png)`", body)

    def test_content_deduplicated_into_two_resources(self) -> None:
        conn = sqlite3.connect(self.sqlite_dir / notesdb.DATABASE_FILENAME)
        count = conn.execute("SELECT COUNT(*) FROM notes WHERE joplin_type_ = 4").fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)
        self.assertEqual(len(list(self.resources.iterdir())), 2)
        self.assertIn("converted 3 image link(s)", self.convert.stdout)


    def test_redirect_mime_mismatch_is_not_downloaded(self) -> None:
        self.assertEqual(ImageHandler.get_counts.get("/redirect.png", 0), 0)
        self.assertEqual(ImageHandler.get_counts.get("/final.jpg", 0), 0)

    def test_remote_source_urls_are_retained_on_deduplicated_resource(self) -> None:
        conn = sqlite3.connect(self.sqlite_dir / notesdb.DATABASE_FILENAME)
        rows = conn.execute(
            "SELECT joplin_user_data FROM notes WHERE joplin_type_ = 4 AND joplin_mime = 'image/png'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        value = rows[0][0]
        self.assertIn(f"http://127.0.0.1:{self.port}/image.png", value)
        self.assertIn(f"http://127.0.0.1:{self.port}/head405.png", value)

    def test_conversion_rerun_is_idempotent(self) -> None:
        conn = sqlite3.connect(self.sqlite_dir / notesdb.DATABASE_FILENAME)
        before_count = conn.execute("SELECT COUNT(*) FROM notes WHERE joplin_type_ = 4").fetchone()[0]
        before_body = conn.execute("SELECT note_data FROM notes WHERE joplin_type_ = 1").fetchone()[0]
        conn.close()
        result = run(
            "images2resources.py",
            "--input",
            str(self.sqlite_dir),
            "--config",
            str(self.config),
            "--report",
            str(self.report),
        )
        conn = sqlite3.connect(self.sqlite_dir / notesdb.DATABASE_FILENAME)
        after_count = conn.execute("SELECT COUNT(*) FROM notes WHERE joplin_type_ = 4").fetchone()[0]
        after_body = conn.execute("SELECT note_data FROM notes WHERE joplin_type_ = 1").fetchone()[0]
        conn.close()
        self.assertEqual(before_count, after_count)
        self.assertEqual(before_body, after_body)
        self.assertIn("updated 0", result.stdout)

    def test_report_has_required_problem_classes(self) -> None:
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("## Could not be converted", report)
        self.assertIn("## Should not be converted", report)
        self.assertIn("## Badly formatted embedded images", report)
        self.assertIn("**redirect-content-type-change**", report)
        self.assertIn("image/png", report)
        self.assertIn("image/jpeg", report)
        self.assertIn("**content-type-mismatch**", report)
        self.assertIn("**stop-listed-domain**", report)
        self.assertIn("**invalid-base64**", report)
        self.assertIn("**malformed-markdown-data-image**", report)
        self.assertIn("11111111111111111111111111111111.md", report)
        self.assertNotIn("code.png", report)

    def _ensure_quarantined(self) -> None:
        if "https://blocked.example/image.png" not in self._body():
            return
        report = self.report.read_text(encoding="utf-8")
        lines = report.splitlines()
        for index, line in enumerate(lines):
            if "**stop-listed-domain**" in line:
                lines[index] = line.replace("- [ ]", "- [x]", 1)
                break
        else:
            self.fail("stop-listed-domain report item not found")
        self.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        first = run(
            "quarantinelinks.py",
            "--input",
            str(self.sqlite_dir),
            "--config",
            str(self.config),
            "--report",
            str(self.report),
        )
        self.assertIn("quarantined 1 image link", first.stdout)

    def test_quarantine_checked_problem_and_reuse_resource(self) -> None:
        self._ensure_quarantined()
        body = self._body()
        self.assertNotIn("https://blocked.example/image.png", body)
        self.assertIn("![Image removed](:/", body)

        parser = configparser.ConfigParser()
        parser.read(self.config, encoding="utf-8")
        resource_id = parser["quarantine"]["replacement_resource_id"]
        resource_file = parser["quarantine"]["replacement_resource_file"]
        self.assertEqual(len(resource_id), 32)
        self.assertTrue((self.sqlite_dir / resource_file).is_file())

        conn = sqlite3.connect(self.sqlite_dir / notesdb.DATABASE_FILENAME)
        before = conn.execute("SELECT COUNT(*) FROM notes WHERE joplin_type_ = 4").fetchone()[0]
        conn.close()
        second = run(
            "quarantinelinks.py",
            "--input",
            str(self.sqlite_dir),
            "--config",
            str(self.config),
            "--report",
            str(self.report),
            check=False,
        )
        conn = sqlite3.connect(self.sqlite_dir / notesdb.DATABASE_FILENAME)
        after = conn.execute("SELECT COUNT(*) FROM notes WHERE joplin_type_ = 4").fetchone()[0]
        conn.close()
        self.assertEqual(before, after)
        self.assertEqual(second.returncode, 1)

    def test_exports_use_local_attachments(self) -> None:
        # Ensure quarantine ran even when this test is selected independently.
        self._ensure_quarantined()
        joplin_out = self.root / "joplin-out"
        vault = self.root / "vault"
        joplin_out.mkdir(exist_ok=True)
        vault.mkdir(exist_ok=True)
        run("sql2joplin.py", "--input", str(self.sqlite_dir), "--output", str(joplin_out))
        run("sql2obsidian.py", "--input", str(self.sqlite_dir), "--output", str(vault))

        raw = (joplin_out / "11111111111111111111111111111111.md").read_text()
        self.assertGreaterEqual(raw.count(":/"), 4)
        self.assertTrue((joplin_out / "resources").is_dir())
        note = (vault / "Image test.md").read_text()
        self.assertGreaterEqual(note.count("![["), 4)
        self.assertIn(f"http://127.0.0.1:{self.port}/redirect.png", note)
        self.assertIn(f"http://127.0.0.1:{self.port}/wrong.png", note)


class ImageReplacementPerformanceTest(unittest.TestCase):
    def test_many_replacements_are_applied_in_one_forward_pass(self) -> None:
        parts = []
        replacements = []
        cursor = 0
        for index in range(2000):
            token = f"old-{index}"
            parts.append(token)
            start = cursor
            end = start + len(token)
            replacements.append((start, end, f"new-{index}"))
            parts.append("|")
            cursor = end + 1
        original = "".join(parts)
        updated = image_resources.apply_replacements(original, replacements)
        self.assertTrue(updated.startswith("new-0|new-1|"))
        self.assertTrue(updated.endswith("new-1999|"))
        self.assertNotIn("old-", updated)

    def test_resource_file_lookups_use_one_directory_index(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory(prefix="movenotes-resource-index-") as tmp_name:
            root = Path(tmp_name)
            resources = root / "resources"
            vault = root / "vault"
            resources.mkdir()
            vault.mkdir()
            database = root / notesdb.DATABASE_FILENAME
            conn = notesdb.connect(database)
            notesdb.create_database(conn)

            resource_ids = [f"{index:032x}" for index in range(200)]
            rows = []
            for resource_id in resource_ids:
                (resources / f"{resource_id}.bin").write_bytes(resource_id.encode())
                rows.append(
                    {
                        "note_type": "resource",
                        "note_uuid": resource_id,
                        "note_original_format": "test",
                        "note_title": resource_id,
                        "note_data": "",
                        "note_data_format": "text/markdown",
                        "joplin_id": resource_id,
                        "joplin_type_": int(constants.JoplinType.RESOURCE),
                        "joplin_file_extension": "",
                        "joplin_mime": "application/octet-stream",
                    }
                )
            notesdb.add_joplin_notes(conn, rows)

            store = image_resources.ResourceStore(conn, resources)
            attachments = sql2obsidian.AttachmentTable(
                conn.cursor(), resources, vault, sql2obsidian.NameDeduplicator()
            )
            with mock.patch.object(
                Path, "glob", side_effect=AssertionError("repeated directory scan")
            ):
                for resource_id in resource_ids:
                    self.assertEqual(
                        store._resource_file_candidates(resource_id)[0].name,
                        f"{resource_id}.bin",
                    )
                    self.assertEqual(
                        attachments._source_file(resource_id, "").name,
                        f"{resource_id}.bin",
                    )
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

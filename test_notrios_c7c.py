#!/usr/bin/env python3
"""Focused tests for the C7c comparison and long-wait monitor helpers."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest import mock

import obsidianmeta
from notrios_c7c import (
    C7CError,
    C7CQueryTimeout,
    CheckpointMismatch,
    Limits,
    QueryRunner,
    _decode_snapshot,
    _deterministic_note_id,
    _create_spool,
    _dependency_code_inventory,
    _index_spool,
    _materialize_route_identity_map,
    _compare,
    _distinct_missing_extra,
    _privacy_plain_text_projection,
    _publication_comparison,
    _verified_publication_summary,
    _frontmatter_tags,
    _parser,
    _strict_object,
    _pinned_frontmatter_scalar,
    _value_scalar,
    _SkipSourceSnapshot,
    parse_frontmatter,
    _route_body,
    run_comparison,
)


REPO = Path(__file__).resolve().parent


def _make_producer_db(path: Path, route: str, rows: list[dict[str, object]]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE documents(
            id TEXT PRIMARY KEY, title TEXT, current_revision_id TEXT,
            deleted_at TEXT
        );
        CREATE TABLE document_revisions(
            id TEXT PRIMARY KEY, document_id TEXT, title TEXT, body TEXT
        );
        CREATE TABLE document_sources(
            document_id TEXT PRIMARY KEY, source_system TEXT, external_id TEXT,
            metadata_json TEXT
        );
        CREATE TABLE tags(id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE note_tags(document_id TEXT, tag_id TEXT);
        """
    )
    for number, row in enumerate(rows):
        document_id = str(row.get("document_id", f"doc-{number}"))
        revision_id = f"revision-{number}"
        external_id = str(row["external_id"])
        metadata = row.get("source_metadata", {})
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, NULL)",
            (document_id, str(row.get("title", "")), revision_id),
        )
        connection.execute(
            "INSERT INTO document_revisions VALUES (?, ?, ?, ?)",
            (revision_id, document_id, str(row.get("title", "")), str(row["body"])),
        )
        connection.execute(
            "INSERT INTO document_sources VALUES (?, ?, ?, ?)",
            (document_id, "joplin" if route == "raw" else "obsidian", external_id, json.dumps(metadata)),
        )
        for tag_number, tag in enumerate(row.get("tags", [])):
            tag_id = f"tag-{route}-{tag_number}-{document_id}"
            connection.execute("INSERT INTO tags VALUES (?, ?)", (tag_id, str(tag)))
            connection.execute("INSERT INTO note_tags VALUES (?, ?)", (document_id, tag_id))
    connection.commit()
    connection.close()


def _raw_route_body(title: str, recipe_body: str, tags: list[str]) -> str:
    lines = ["---", "source_system: joplin_raw", "joplin_id: ignored"]
    if tags:
        lines.append("joplin_tags:")
        lines.extend(f"  - {tag}" for tag in tags)
    lines.extend(["---", recipe_body])
    return "\n".join(lines)


def _vault_route_body(path: str, title: str, recipe_frontmatter: str, recipe_body: str) -> str:
    parts = ["---", "source_system: obsidian", f"obsidian_path: {path}"]
    if recipe_frontmatter:
        parts.append(recipe_frontmatter)
    parts.extend(["---", recipe_body])
    return "\n".join(parts)


class C7cFixture:
    def __init__(
        self,
        root: Path,
        *,
        changed_body: bool = False,
        duplicate_raw: bool = False,
        metadata_value: str = "3",
    ):
        self.root = root
        self.raw_source = root / "raw-source"
        self.vault_source = root / "vault-source"
        self.raw_source.mkdir(parents=True)
        (self.vault_source / "nested").mkdir(parents=True)
        self.raw_db = root / "raw.sqlite"
        self.vault_db = root / "vault.sqlite"
        self.output = root / "comparison"
        self.raw_rows: list[dict[str, object]] = []
        self.vault_rows: list[dict[str, object]] = []
        for name, title, tag in (("note.md", "Same title", "one"), ("other.md", "Same title", "two")):
            relative = f"Recipes/{name}"
            raw_vault = (
                "---\n"
                f"title: {title}\n"
                f"tags:\n  - {tag}\n"
                f"difficulty: {metadata_value}\n"
                "---\n"
                f"Body for {name}\n"
            ).encode()
            if changed_body and name == "other.md":
                raw_vault = raw_vault.replace(b"Body for other.md", b"Changed other.md")
            (self.vault_source / name).write_bytes(raw_vault)
            note_id = _deterministic_note_id(relative)
            raw_body = f"{title}\n\nBody for {name}\n"
            appdata = obsidianmeta.encode_note_application_data(
                relative_path=relative,
                raw=raw_vault,
                generated_joplin_body=raw_body,
            )
            raw_file = (
                raw_body
                + "\n"
                + f"id: {note_id}\n"
                + f"application_data: {appdata}\n"
            ).encode()
            (self.raw_source / f"{note_id}.md").write_bytes(raw_file)
            raw_route_body = _raw_route_body(title, f"Body for {name}\n", [tag])
            if changed_body and name == "other.md":
                raw_route_body = raw_route_body.replace("Body for other.md", "Changed other.md")
            self.raw_rows.append({"external_id": note_id, "title": title, "body": raw_route_body, "tags": [tag]})
            self.vault_rows.append({
                "external_id": name,
                "title": title,
                "body": _vault_route_body(
                    name,
                    title,
                    f"title: {title}\ntags:\n  - {tag}\ndifficulty: {metadata_value}\n",
                    ("Changed " if changed_body and name == "other.md" else "") + f"Body for {name}\n",
                ),
                "source_metadata": {"relative_path": name},
            })
        if duplicate_raw:
            duplicate = dict(self.raw_rows[0], document_id="duplicate")
            self.raw_rows.append(duplicate)
        _make_producer_db(self.raw_db, "raw", self.raw_rows)
        _make_producer_db(self.vault_db, "vault", self.vault_rows)


def _args(fixture: C7cFixture):
    return _parser().parse_args([
        "--raw-db", str(fixture.raw_db),
        "--vault-db", str(fixture.vault_db),
        "--raw-source-root", str(fixture.raw_source),
        "--vault-root", str(fixture.vault_source),
        "--output", str(fixture.output),
    ])


class C7cComparisonTest(unittest.TestCase):
    def test_privacy_plain_text_projection_validates_spans_and_targets(self):
        source = b"before [private](document://default/documents/withheld) after"
        start = source.index(b"[private]")
        end = source.index(b" after")
        row = (
            "source", "withheld", "", "document://default/documents/withheld",
            "resolved", "link", "document://default/documents/withheld", "private",
            start, end,
        )
        projected, counts = _privacy_plain_text_projection(
            source, [row], lambda kind, record_id: False,
        )
        self.assertEqual(projected, b"before private after")
        self.assertEqual(counts["candidates"], 1)
        self.assertEqual(counts["rewrites"], 1)

        retained, retained_counts = _privacy_plain_text_projection(
            source, [row], lambda kind, record_id: True,
        )
        self.assertEqual(retained, source)
        self.assertEqual(retained_counts, {})

        stale = (*row[:8], start, start + 4)
        unchanged, stale_counts = _privacy_plain_text_projection(
            source, [stale], lambda kind, record_id: False,
        )
        self.assertEqual(unchanged, source)
        self.assertEqual(stale_counts["stale_span"], 1)

    def test_null_identity_rows_remain_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            connection = _create_spool(Path(temporary) / "nulls.sqlite")
            try:
                connection.execute(
                    "INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("source", "key", None, "path", "title", "title", "title", "body", "body", "tags", "meta", "snap", "vault", "ok", "ok"),
                )
                connection.execute(
                    "INSERT INTO route_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("raw", "raw", "doc", None, "ok", "title", "body", "exact", "tags", 0, "meta", "ok", "ok;ok"),
                )
                value = _distinct_missing_extra(connection, "source", "raw", "raw", "raw_external_id")
            finally:
                connection.close()
            self.assertEqual(value["source_rows"], 1)
            self.assertEqual(value["route_rows"], 1)
            self.assertEqual(value["missing_identities"], 1)
            self.assertEqual(value["extra_identities"], 1)

    def test_scaled_end_to_end_comparison_uses_bounded_indexed_queries(self):
        """All comparison query labels finish on a 20k-row synthetic spool."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = _create_spool(root / "scaled.sqlite")
            rows = 20_000
            source_rows = []
            route_rows = []
            publication_rows = []
            for number in range(rows):
                source_key = f"source-{number}"
                raw_identity = f"raw-{number}"
                vault_identity = f"Recipes/note-{number}.md"
                source_rows.append((
                    "source", source_key, raw_identity, vault_identity,
                    "title", "title", "title", "body", "body",
                    "tags", "metadata", "snapshot", "vault", "ok", "ok",
                ))
                route_rows.extend((
                    (
                        "raw", "raw", f"raw-doc-{number}", raw_identity, "ok",
                        "title", "body", "exact", "tags", 1, "metadata", "ok", "ok;ok",
                    ),
                    (
                        "vault", "vault", f"vault-doc-{number}", vault_identity, "ok",
                        "title", "body", "exact", "tags", 0, "metadata", "ok", "ok;ok",
                    ),
                ))
                publication_rows.extend((
                    ("publication", "raw", f"raw-doc-{number}", "title", "body", 1),
                    ("publication", "vault", f"vault-doc-{number}", "title", "body", 1),
                ))
            try:
                connection.executemany(
                    "INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    source_rows,
                )
                connection.executemany(
                    "INSERT INTO route_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    route_rows,
                )
                connection.executemany(
                    "INSERT INTO publication_records VALUES (?,?,?,?,?,?)",
                    publication_rows,
                )
                _index_spool(connection)
                _materialize_route_identity_map(connection, "source", "raw", "vault")
                archives = {
                    label: {
                        "status": "complete",
                        "document_rows": rows,
                        "body_rows_verified": rows,
                        "counts": {"documents": rows},
                        "producer_content_ready": True,
                        "producer_equivalence_ready": True,
                        "manifest": {"selection_manifest_sha256": label},
                    }
                    for label in ("joplin", "raw", "vault")
                }
                archives["joplin"]["producer_content_ready"] = False
                archives["joplin"]["producer_equivalence_ready"] = True
                archives["joplin"]["privacy_plain_text"] = {
                    "status": "verified",
                    "classification_counts": {
                        "exact": rows - 1,
                        "privacy_plain_text_exact": 1,
                        "unexplained": 0,
                    },
                }
                progress = root / "progress.json"
                runner = QueryRunner(connection, 30.0, progress)
                publication = _publication_comparison(
                    connection, "publication", "source", "raw", "vault", archives,
                    query_runner=runner,
                )
                result = _compare(
                    connection, "source", "raw", "vault",
                    {"source_parse_failures": 0, "source_record_failures": 0},
                    {"comparison": publication},
                    query_runner=runner,
                )
            finally:
                connection.close()
            self.assertEqual(publication["status"], "complete")
            self.assertEqual(
                publication["source_cohort"]["joplin"]["body_equivalence"]["classification_counts"][
                    "privacy_plain_text_exact"
                ],
                1,
            )
            self.assertEqual(result["source_rows"], rows)
            # The synthetic rows intentionally carry a source tag hash and a
            # RAW producer association.  They exercise the separate-channel
            # contract; query completion must not turn that into equivalence.
            self.assertFalse(result["semantic_equal"])
            self.assertFalse(result["tag_channel_comparison"]["equivalence_established"])
            trace = json.loads(progress.read_text())
            self.assertTrue(trace["completed_queries"])
            self.assertTrue(all(item["status"] == "complete" for item in trace["completed_queries"]))
            labels = {item["label"] for item in trace["completed_queries"]}
            self.assertIn("compare.raw.identity_join", labels)
            self.assertIn("compare.route_pair.row_multiset", labels)
            self.assertIn("publication.raw_vault.body_matches", labels)

    def test_publication_joins_use_bounded_composite_indexes(self):
        """A scaled route map must resolve publication identities by both keys."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = _create_spool(root / "scaled.sqlite")
            try:
                rows = 4096
                source_rows = []
                route_rows = []
                publication_rows = []
                for number in range(rows):
                    source_key = f"source-{number}"
                    raw_identity = f"raw-{number}"
                    vault_identity = f"Recipes/note-{number}.md"
                    source_rows.append((
                        "source", source_key, raw_identity, vault_identity,
                        "title", "pinned", "raw-title", "body", "raw-body",
                        "tags", "metadata", "snapshot", "vault", "ok", "ok",
                    ))
                    route_rows.extend((
                        (
                            "raw", "raw", f"raw-doc-{number}", raw_identity, "ok",
                            "title", "body", "exact", "tags", 0, "metadata", "ok", "ok",
                        ),
                        (
                            "vault", "vault", f"vault-doc-{number}", vault_identity, "ok",
                            "title", "body", "exact", "tags", 0, "metadata", "ok", "ok",
                        ),
                    ))
                    if number < 512:
                        publication_rows.extend((
                            ("publication", "raw", f"raw-doc-{number}", "title", "body", 1),
                            ("publication", "vault", f"vault-doc-{number}", "title", "body", 1),
                        ))
                connection.executemany("INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", source_rows)
                connection.executemany("INSERT INTO route_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", route_rows)
                connection.executemany("INSERT INTO publication_records VALUES (?,?,?,?,?,?)", publication_rows)
                _index_spool(connection)
                _materialize_route_identity_map(connection, "source", "raw", "vault")
                query = """SELECT COUNT(DISTINCT m.source_key) FROM publication_records p
                    JOIN route_records r ON r.run_id = ? AND r.route = ? AND r.document_id = p.document_id
                    JOIN route_identity_map m ON m.route = ? AND m.route_identity = r.identity
                    WHERE p.run_id = ? AND p.label = ?"""
                plan = "\n".join(
                    row[3] for row in connection.execute(
                        "EXPLAIN QUERY PLAN " + query,
                        ("raw", "raw", "raw", "publication", "raw"),
                    )
                )
            finally:
                connection.close()
            self.assertIn("route_publication_doc_idx", plan)
            self.assertIn("route_identity_map_route_identity", plan)
            self.assertNotIn("route_identity_map_route (route=?)", plan)

    def test_query_timeout_writes_durable_labelled_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = sqlite3.connect(":memory:")
            progress = root / "comparison-progress.json"
            runner = QueryRunner(connection, 0.01, progress)
            try:
                with self.assertRaises(C7CQueryTimeout) as raised:
                    runner.call(
                        "test.scaled_cross_join",
                        lambda: connection.execute(
                            """WITH RECURSIVE numbers(n) AS (
                                   SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 100000000
                               ) SELECT sum(a.n * b.n) FROM numbers a CROSS JOIN numbers b"""
                        ).fetchone(),
                    )
            finally:
                connection.close()
            self.assertEqual(raised.exception.label, "test.scaled_cross_join")
            value = json.loads(progress.read_text())
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["error"]["label"], "test.scaled_cross_join")
            self.assertEqual(value["completed_queries"][-1]["status"], "timed_out")

    def test_source_recipe_equality_uses_nested_publication_readiness(self):
        """A valid source recipe comparison must read publication.comparison.ready."""
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary), metadata_value="medium")
            args = _args(fixture)
            with mock.patch(
                "notrios_c7c._publication_comparison",
                return_value={"status": "complete", "ready": True},
            ):
                result, _status = run_comparison(args)
            self.assertTrue(result["source_recipe_semantic_equal"])
            self.assertFalse(result["route_output_semantic_equal"])

    def test_publication_summary_uses_verified_archive_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = _create_spool(root / "comparison.sqlite")
            try:
                summary = _verified_publication_summary(
                    connection,
                    "run",
                    "raw",
                    REPO / "testdata" / "notrios" / "publication-loose" / "archive",
                    None,
                    root / "verify",
                )
            finally:
                connection.close()
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["document_rows"], summary["counts"]["documents"])
            self.assertEqual(summary["body_rows_verified"], summary["document_rows"])
            self.assertNotIn("path", summary)

    def test_duplicate_titles_use_source_identity_and_report_body_difference(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary))
            connection = sqlite3.connect(fixture.raw_db)
            connection.execute(
                "UPDATE document_revisions SET body = replace(body, 'Body for other.md', 'Changed other.md') "
                "WHERE document_id = ?",
                ("doc-1",),
            )
            connection.commit()
            connection.close()
            result, status = run_comparison(_args(fixture))
            self.assertEqual(status, 0)
            self.assertEqual(result["source_rows"], 2)
            self.assertEqual(result["joins"]["raw"]["missing_identities"], 0)
            self.assertEqual(result["joins"]["vault"]["missing_identities"], 0)
            self.assertEqual(result["fields"]["raw"]["title_matches"], 2)
            self.assertEqual(result["fields"]["raw"]["body_matches"], 1)
            self.assertEqual(result["unexplained_differences"]["source_route_body"]["raw"], 1)
            self.assertFalse(result["semantic_equal"])
            self.assertFalse(any("Same title" in path.read_text(errors="ignore") for path in fixture.output.rglob("*.json")))

    def test_checkpoint_rejects_changed_source_and_preserves_old_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary))
            first, _status = run_comparison(_args(fixture))
            result_path = fixture.output / "result.json"
            before = result_path.read_bytes()
            source_path = next(fixture.vault_source.glob("*.md"))
            source_path.write_bytes(source_path.read_bytes() + b" ")
            with self.assertRaises(CheckpointMismatch):
                run_comparison(_args(fixture))
            self.assertEqual(result_path.read_bytes(), before)
            self.assertEqual(json.loads(before), first)
            self.assertFalse((fixture.output / "notification.json.tmp").exists())

    def test_checkpoint_rejects_changed_dependency_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary))
            args = _args(fixture)
            first, _status = run_comparison(args)
            result_path = fixture.output / "result.json"
            before = result_path.read_bytes()
            checkpoint = json.loads((fixture.output / "checkpoint.json").read_text())
            inventory = _dependency_code_inventory()
            self.assertEqual(
                inventory,
                checkpoint["fingerprint"]["profile"]["dependency_code_inventory"],
            )
            changed = [dict(entry) for entry in inventory]
            changed[0]["sha256"] = "0" * 64
            with mock.patch(
                "notrios_c7c._dependency_code_inventory", return_value=changed
            ):
                with self.assertRaises(CheckpointMismatch):
                    run_comparison(args)
            self.assertEqual(result_path.read_bytes(), before)
            self.assertEqual(json.loads(before), first)

    def test_checkpoint_rejects_changed_publication_blob_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = C7cFixture(root)
            publication = root / "publication"
            publication.mkdir()
            (publication / "manifest.json").write_bytes(b"manifest")
            blob = publication / "blob.bin"
            blob.write_bytes(b"first publication bytes")
            args = _args(fixture)
            args.publication = [f"raw={publication}"]
            with mock.patch(
                "notrios_c7c._verified_publication_summary",
                return_value={"status": "complete"},
            ), mock.patch(
                "notrios_c7c._publication_comparison",
                return_value={"status": "complete", "ready": True},
            ):
                first, _status = run_comparison(args)
            result_path = fixture.output / "result.json"
            before = result_path.read_bytes()
            blob.write_bytes(b"changed publication bytes")
            with self.assertRaises(CheckpointMismatch):
                run_comparison(args)
            self.assertEqual(result_path.read_bytes(), before)
            self.assertEqual(json.loads(before), first)

    def test_stage_disk_preflight_is_recorded_and_configurable(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary))
            args = _args(fixture)
            args.min_free_bytes = 1
            run_comparison(args)
            checkpoint = json.loads((fixture.output / "checkpoint.json").read_text())
            self.assertEqual(
                set(checkpoint["disk_preflight"]),
                {"source", "raw", "vault", "comparison"},
            )
            for value in checkpoint["disk_preflight"].values():
                self.assertGreaterEqual(value["free_bytes"], 1)

            blocked = C7cFixture(Path(temporary) / "blocked")
            blocked_args = _args(blocked)
            blocked_args.min_free_bytes = 1 << 62
            with self.assertRaises(C7CError):
                run_comparison(blocked_args)

    def test_checkpoint_resume_reuses_completed_stages(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary))
            args = _args(fixture)
            first, _status = run_comparison(args)
            checkpoint_path = fixture.output / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text())
            checkpoint["status"] = "failed"
            checkpoint["failed_stage"] = "comparison"
            checkpoint_path.write_text(json.dumps(checkpoint))
            second, _status = run_comparison(args)
            self.assertEqual(first, second)
            attempts = list((fixture.output / "attempts").glob("*.json"))
            self.assertEqual(len(attempts), 1)

    def test_snapshot_decoder_rejects_unsafe_path_and_decompression_limit(self):
        raw = b"safe bytes"
        def payload(path: str, compressed: bytes = zlib.compress(raw)):
            return json.dumps({"movenotes_obsidian_v1": {
                "kind": "note", "path": path,
                "raw_zlib_base64": base64.urlsafe_b64encode(compressed).decode(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "joplin_body_sha256": hashlib.sha256(b"body").hexdigest(),
            }})
        with self.assertRaises(C7CError):
            _decode_snapshot(payload("../escape"), Limits())
        with self.assertRaises(C7CError):
            _decode_snapshot(payload("safe.md"), Limits(max_decompressed_bytes=2))

    def test_strict_json_scopes_duplicate_names_and_flow_scalars(self):
        self.assertEqual(_strict_object('{"a":{"x":1},"b":{"x":2}}'), {"a": {"x": 1}, "b": {"x": 2}})
        with self.assertRaises(C7CError):
            _strict_object('{"a":1,"a":2}')
        self.assertEqual(_value_scalar('["true", "3"]'), ["true", "3"])
        self.assertEqual(_value_scalar("on"), "on")
        self.assertEqual(_value_scalar("yes"), "yes")
        self.assertEqual(_value_scalar("4"), 4)
        self.assertIs(_value_scalar("true"), True)
        self.assertIs(_value_scalar("false"), False)
        self.assertIsNone(_value_scalar("null"))
        self.assertIsNone(_value_scalar("~"))
        tags, _tags_digest = _frontmatter_tags(
            {"tags": [1, True, None, "family"]}, Limits()
        )
        self.assertEqual(tags, ["1", "True", "family"])
        with self.assertRaises(C7CError):
            _frontmatter_tags({"tags": [{"nested": "value"}]}, Limits())
        with self.assertRaises(C7CError):
            _value_scalar("'unterminated")

    def test_pinned_frontmatter_scalar_matches_producer_quote_trim(self):
        self.assertEqual(
            _pinned_frontmatter_scalar('title: "Example Recipe \'"\n', "title"),
            "Example Recipe",
        )
        self.assertEqual(
            _pinned_frontmatter_scalar("title: \"ordinary title\"\n", "title"),
            "ordinary title",
        )

    def test_folder_snapshot_is_skipped_as_a_non_note(self):
        payload = json.dumps({
            "movenotes_obsidian_v1": {"kind": "folder", "path": "Recipes/folder"},
        })
        with self.assertRaises(_SkipSourceSnapshot):
            _decode_snapshot(payload, Limits())

    def test_vault_metadata_parser_does_not_turn_proven_wrapper_into_body_failure(self):
        body = (
            '---\nsource_system: obsidian\nobsidian_path: "note.md"\n'
            'servings: 4\n---\n\nrecipe\n'
        )
        semantics = _route_body("vault", body, Limits(), expected_path="note.md")
        self.assertEqual(semantics["body_status"], "ok")
        self.assertEqual(semantics["metadata_status"], "ok")

    def test_tag_channels_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary), metadata_value="medium")
            args = _args(fixture)
            with mock.patch(
                "notrios_c7c._publication_comparison",
                return_value={"status": "complete", "ready": True},
            ):
                result, _status = run_comparison(args)
            self.assertIsNone(result["fields"]["raw"]["tags_matches"])
            self.assertEqual(
                result["tag_channel_comparison"]["status"], "separate_channels"
            )
            self.assertFalse(result["tag_channel_comparison"]["equivalence_established"])

    def test_snapshot_body_digest_and_outer_wrapper_are_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary))
            source = next(fixture.raw_source.glob("*.md"))
            text = source.read_text()
            source.write_text(text.replace("application_data: ", "application_data: ", 1))
            # Changing the stored generated-body digest while keeping the
            # compressed snapshot valid must become a source status, not pass.
            raw = json.loads(text.split("application_data: ", 1)[1])
            raw["movenotes_obsidian_v1"]["joplin_body_sha256"] = "0" * 64
            source.write_text(text.split("application_data: ", 1)[0] + "application_data: " + json.dumps(raw) + "\n")
            result, _status = run_comparison(_args(fixture))
            self.assertGreater(result["source_scan_failures"], 0)
            self.assertFalse(result["source_recipe_semantic_equal"])

            # A forged producer path must not be stripped as if it were the
            # validated wrapper field.
            connection = sqlite3.connect(fixture.vault_db)
            connection.execute("UPDATE document_revisions SET body = replace(body, 'obsidian_path: note.md', 'obsidian_path: forged.md')")
            connection.commit()
            connection.close()
            fixture.output = Path(temporary) / "comparison-forged"
            forged, _status = run_comparison(_args(fixture))
            self.assertFalse(forged["source_recipe_semantic_equal"])
            self.assertGreater(forged["fields"]["vault"]["metadata_unavailable_rows"], 0)

    def test_duplicate_identity_rows_require_complete_row_multiset(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = C7cFixture(Path(temporary), duplicate_raw=True)
            connection = sqlite3.connect(fixture.raw_db)
            rows = connection.execute("SELECT document_id, body FROM document_revisions ORDER BY document_id").fetchall()
            first, second = rows[0], rows[1]
            connection.execute("UPDATE document_revisions SET body = ? WHERE document_id = ?", (second[1], first[0]))
            connection.execute("UPDATE document_revisions SET body = ? WHERE document_id = ?", (first[1], second[0]))
            connection.commit()
            connection.close()
            result, _status = run_comparison(_args(fixture))
            self.assertLess(result["fields"]["raw"]["row_multiset_matches"], result["joins"]["raw"]["source_rows"])
            self.assertFalse(result["semantic_equal"])


class C7cMonitorTest(unittest.TestCase):
    def test_monitor_waits_for_child_once_and_writes_terminal_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            result = root / "result.json"
            notification = root / "notification.json"
            child_code = (
                "import json,sys; cp,res=sys.argv[1:]; "
                "fp={'code_sha256':'c','profile_sha256':'p'}; "
                "json.dump({'status':'complete','run_id':'new','fingerprint':fp},open(cp,'w')); "
                "json.dump({'status':'complete','run_id':'new','semantic_equal':False,'fingerprint':fp},open(res,'w'))"
            )
            command = [
                sys.executable, "-B", str(REPO / "scripts" / "notrios_c7c_monitor.py"),
                "--checkpoint", str(checkpoint), "--result", str(result),
                "--notification", str(notification), "--",
                sys.executable, "-c", child_code, str(checkpoint), str(result),
            ]
            completed = subprocess.run(command, cwd=REPO, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0)
            value = json.loads(notification.read_text())
            self.assertEqual(value["status"], "complete")
            self.assertFalse(value["source_content_included"])
            self.assertGreater(value["child_rusage"]["max_rss_kib"], 0)

    def test_monitor_rejects_old_result_when_new_command_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            result = root / "result.json"
            notification = root / "notification.json"
            fp = {"code_sha256": "old", "profile_sha256": "old"}
            checkpoint.write_text(json.dumps({"status": "complete", "run_id": "old", "fingerprint": fp}))
            result.write_text(json.dumps({"status": "complete", "run_id": "old", "semantic_equal": True, "fingerprint": fp}))
            command = [
                sys.executable, "-B", str(REPO / "scripts" / "notrios_c7c_monitor.py"),
                "--checkpoint", str(checkpoint), "--result", str(result),
                "--notification", str(notification), "--",
                sys.executable, "-c", "raise SystemExit(7)",
            ]
            completed = subprocess.run(command, cwd=REPO, check=False, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            value = json.loads(notification.read_text())
            self.assertEqual(value["status"], "blocked")
            self.assertEqual(value["reason"], "child_failed")

    def test_monitor_rejects_old_result_when_new_command_succeeds_without_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            result = root / "result.json"
            notification = root / "notification.json"
            fp = {"code_sha256": "old", "profile_sha256": "old"}
            checkpoint.write_text(json.dumps({"status": "complete", "run_id": "old", "fingerprint": fp}))
            result.write_text(json.dumps({"status": "complete", "run_id": "old", "semantic_equal": True, "fingerprint": fp}))
            command = [
                sys.executable, "-B", str(REPO / "scripts" / "notrios_c7c_monitor.py"),
                "--checkpoint", str(checkpoint), "--result", str(result),
                "--notification", str(notification), "--",
                sys.executable, "-c", "pass",
            ]
            completed = subprocess.run(command, cwd=REPO, check=False, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            value = json.loads(notification.read_text())
            self.assertEqual(value["status"], "blocked")
            self.assertEqual(value["reason"], "stale_result")

    def test_monitor_fails_closed_when_successful_child_has_no_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            result = root / "result.json"
            notification = root / "notification.json"
            command = [
                sys.executable, "-B", str(REPO / "scripts" / "notrios_c7c_monitor.py"),
                "--checkpoint", str(checkpoint), "--result", str(result),
                "--notification", str(notification), "--",
                sys.executable, "-c", "pass",
            ]
            completed = subprocess.run(command, cwd=REPO, check=False, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            value = json.loads(notification.read_text())
            self.assertEqual(value["status"], "blocked")
            self.assertEqual(value["reason"], "missing_or_invalid_result")

    def test_monitor_reconnect_recovers_helper_exit_receipt_and_resume_run_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            result = root / "result.json"
            notification = root / "notification.json"
            child_code = (
                "import json,sys,time; cp,res=sys.argv[1:]; time.sleep(1); "
                "fp={'code_sha256':'same','profile_sha256':'same'}; "
                "json.dump({'status':'complete','run_id':'resume','fingerprint':fp},open(cp,'w')); "
                "json.dump({'status':'complete','run_id':'resume','semantic_equal':True,'fingerprint':fp},open(res,'w'))"
            )
            command = [
                sys.executable, "-B", str(REPO / "scripts" / "notrios_c7c_monitor.py"),
                "--checkpoint", str(checkpoint), "--result", str(result),
                "--notification", str(notification), "--",
                sys.executable, "-c", child_code, str(checkpoint), str(result),
            ]
            monitor = subprocess.Popen(command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            state_path = checkpoint.with_name(checkpoint.name + ".monitor.json")
            deadline = time.monotonic() + 5
            while not state_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(state_path.exists())
            state = json.loads(state_path.read_text())
            monitor.terminate()
            monitor.wait(timeout=5)
            if monitor.stdout is not None:
                monitor.stdout.close()
            if monitor.stderr is not None:
                monitor.stderr.close()
            reconnect = [
                sys.executable, "-B", str(REPO / "scripts" / "notrios_c7c_monitor.py"),
                "--pid", str(state["pid"]), "--checkpoint", str(checkpoint),
                "--result", str(result), "--notification", str(notification),
            ]
            completed = subprocess.run(reconnect, cwd=REPO, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            value = json.loads(notification.read_text())
            self.assertEqual(value["status"], "complete")
            self.assertEqual(value["returncode"], 0)
            self.assertEqual(value["monitor_run_id"], state["monitor_run_id"])


if __name__ == "__main__":
    unittest.main()

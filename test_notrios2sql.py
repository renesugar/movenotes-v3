#!/usr/bin/env python3
"""Offline Notrios fixture baselines and manifest-admission tests.

The helpers read only the small, trusted synthetic fixture. They are not the
strict archive verifier and must not be used to admit untrusted publications.
Future mutation tests should copy the archive before changing any bytes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import copy
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote
from unittest import mock

import notrios_archive as archive_v2
import notrios_receipt
import notrios_mapping as mapping
import notrios2sql as importer
import notrios_links as links
from notrios_links import ConversionLimits
import notesdb


FIXTURE_ROOT = Path(__file__).resolve().parent / "testdata" / "notrios"
PUBLICATION_ROOT = FIXTURE_ROOT / "publication-loose"
PUBLICATION_ARCHIVE = PUBLICATION_ROOT / "archive"
EXPECTED_COUNTS = {
    "collections": 1, "notebooks": 2, "search_notebooks": 0, "tags": 4,
    "documents": 3, "revisions": 3, "document_tags": 6, "resources": 3,
    "document_resources": 4, "links": 8, "provenance": 0, "source_bundles": 0,
}
RECORD_COUNTS = {
    "collection": "collections", "notebook": "notebooks",
    "search_notebook": "search_notebooks", "tag": "tags",
    "document": "documents", "revision": "revisions",
    "document_tag": "document_tags", "resource": "resources",
    "document_resource": "document_resources", "link": "links",
    "provenance": "provenance", "source_bundle": "source_bundles",
}


def load_json(path: Path):
    return json.loads(path.read_bytes())


def fixture_inventory(root: Path) -> dict[str, dict]:
    """Hash the tiny fixture files; refuse links/special files, not follow them."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError(f"fixture contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise AssertionError(f"fixture contains a special file: {path}")
        raw = path.read_bytes()
        result[path.relative_to(root).as_posix()] = {
            "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
        }
    return result


def copy_publication(destination: Path) -> Path:
    """Copy archive bytes only, to a new destination owned by the caller."""
    return Path(shutil.copytree(PUBLICATION_ARCHIVE, destination, symlinks=True))


def read_fixture_jsonl(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise AssertionError(f"fixture JSONL lacks final LF: {path}")
    return [json.loads(line) for line in raw[:-1].split(b"\n")]


def read_fixture_records(archive: Path) -> tuple[dict, list[dict], dict[str, list[dict]]]:
    """Decode known fixture objects without invoking the future verifier."""
    manifest = load_json(archive / "manifest.json")
    entries = []
    records = defaultdict(list)
    for descriptor in manifest["index"]:
        entries.extend(read_fixture_jsonl(archive / descriptor["location"]["path"]))
    for entry in entries:
        if entry["kind"] == "records":
            for envelope in read_fixture_jsonl(archive / entry["location"]["path"]):
                records[envelope["type"]].append(envelope["payload"])
    return manifest, entries, dict(records)


class NotriosPublicationFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="movenotes-notrios-test-")
        self.addCleanup(temporary.cleanup)
        self.archive = copy_publication(Path(temporary.name) / "archive")
        self.expected = load_json(PUBLICATION_ROOT / "expected.json")
        self.manifest, self.entries, self.records = read_fixture_records(self.archive)

    def blob_bytes(self, reference: dict) -> bytes:
        digest = reference["sha256"]
        return (self.archive / "objects" / "sha256" / digest[:2] / digest[2:4] / digest).read_bytes()

    def test_archive_inventory_and_copy_isolation(self) -> None:
        expected = self.expected["archive_files"]
        self.assertEqual(len(expected), 9)
        self.assertEqual(fixture_inventory(self.archive), expected)
        self.assertEqual(fixture_inventory(PUBLICATION_ARCHIVE), expected)
        # Mutations must not reach the checked-in fixture or another test.
        (self.archive / "manifest.json").write_bytes(b"changed\n")
        self.assertEqual(fixture_inventory(PUBLICATION_ARCHIVE), expected)
        with self.assertRaises(FileExistsError):
            copy_publication(self.archive)

    def test_manifest_and_saved_review_agree(self) -> None:
        manifest = self.manifest
        snapshot = manifest["snapshot"]
        report = load_json(PUBLICATION_ROOT / "reports" / "publish-run.json")["report"]
        plan = load_json(PUBLICATION_ROOT / "reports" / "plan.json")["plan"]
        self.assertEqual((manifest["format"], manifest["version"]), ("notrios-archive", 2))
        self.assertEqual(snapshot["target"], "publication_handoff")
        for name in ("database_id", "snapshot_id"):
            self.assertEqual(report[name], self.expected[name])
        self.assertEqual(snapshot["id"], self.expected["snapshot_id"])
        self.assertEqual(snapshot["database_id"], self.expected["database_id"])
        self.assertEqual(manifest["commit_sha256"], self.expected["commit_sha256"])
        self.assertEqual(report["commit_sha256"], manifest["commit_sha256"])
        selection = self.expected["selection_manifest_sha256"]
        self.assertEqual(snapshot["selection_manifest_sha256"], selection)
        self.assertEqual(report["selection_manifest_sha256"], selection)
        self.assertEqual(plan["manifest_sha256"], selection)
        self.assertIs(report["verified"], True)
        self.assertIs(report["full_backup"], False)
        self.assertEqual(report["skipped_rewrites"], 0)
        self.assertEqual(report["cleared_link_targets"], 0)
        self.assertEqual(report["rewritten_links"], 3)
        self.assertEqual(report["rewritten_documents"], 1)
        self.assertEqual(report["selected_documents"], 3)
        self.assertEqual(report["counts"], EXPECTED_COUNTS)

    def test_index_hashes_counts_and_totals(self) -> None:
        self.assertEqual(self.manifest["counts"], EXPECTED_COUNTS)
        self.assertEqual(self.expected["counts"], EXPECTED_COUNTS)
        self.assertEqual(self.manifest["totals"], self.expected["totals"])
        actual = {name: len(self.records.get(kind, [])) for kind, name in RECORD_COUNTS.items()}
        self.assertEqual(actual, EXPECTED_COUNTS)
        self.assertFalse(set(self.records) - RECORD_COUNTS.keys())
        hashes = [entry["sha256"] for entry in self.entries]
        self.assertEqual(hashes, sorted(set(hashes)))
        self.assertEqual(Counter(entry["kind"] for entry in self.entries), {"records": 1, "blob": 6})
        self.assertEqual(len(self.entries), self.manifest["totals"]["objects"])
        self.assertEqual(sum(e["size_bytes"] for e in self.entries), self.manifest["totals"]["bytes"])
        for entry in [*self.manifest["index"], *self.entries]:
            with self.subTest(sha256=entry["sha256"]):
                digest = entry["sha256"]
                self.assertEqual(entry["location"], {
                    "layout": "fanout", "path": f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}",
                })
                raw = self.blob_bytes(entry)
                self.assertEqual(len(raw), entry["size_bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                if "entries" in entry:
                    self.assertEqual(len(read_fixture_jsonl(self.archive / entry["location"]["path"])), entry["entries"])
                if entry.get("kind") == "records":
                    self.assertEqual(entry["records"], sum(EXPECTED_COUNTS.values()))
                    self.assertEqual(entry["record_counts"], EXPECTED_COUNTS)

    def test_current_notes_bodies_hierarchy_and_tags(self) -> None:
        docs = {r["id"]: r for r in self.records["document"]}
        revisions = {r["document_id"]: r for r in self.records["revision"]}
        notebooks = {r["id"]: r for r in self.records["notebook"]}
        self.assertEqual(set(docs), {"doc_public", "doc_child", "doc_duplicate"})
        self.assertEqual(set(revisions), set(docs))
        self.assertEqual(sorted(notebooks.values(), key=lambda r: r["id"]),
                         sorted(self.expected["notebooks"], key=lambda r: r["id"]))
        tags = {r["id"]: r["name"] for r in self.records["tag"]}
        self.assertEqual(set(tags.values()), {"café", "published", "research notes", "東京"})
        for ident, expected in self.expected["notes"].items():
            with self.subTest(document=ident):
                doc, revision = docs[ident], revisions[ident]
                self.assertEqual(doc["current_revision_id"], revision["id"])
                self.assertEqual(revision["id"], expected["current_revision_id"])
                self.assertEqual(revision["title"], expected["title"])
                self.assertEqual(revision["metadata_json"], {})
                self.assertEqual(doc.get("deleted_at", ""), "")
                for field in ("created_at", "updated_at"):
                    self.assertEqual(doc[field], expected[field])
                raw = self.blob_bytes(revision["body"])
                self.assertEqual(len(raw), revision["body"]["size_bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected["body_sha256"])
                self.assertEqual(raw, expected["body"].encode("utf-8"))
                self.assertEqual(revision["body_mime_type"], "text/markdown")
                self.assertEqual(revision["body"]["media_type"], "text/markdown")
                folder = notebooks[doc["notebook_id"]]
                path = folder["name"]
                if folder.get("parent_id"):
                    path = notebooks[folder["parent_id"]]["name"] + "/" + path
                self.assertEqual(path, expected["notebook_path"])
                self.assertEqual(sorted(tags[r["tag_id"]] for r in self.records["document_tag"]
                                        if r["document_id"] == ident), expected["tags"])

    def test_publication_body_matches_synthetic_seed_rewrites(self) -> None:
        for ident, expected in self.expected["notes"].items():
            source = "update-v1" if ident == "doc_public" else "seed-v1"
            body = (FIXTURE_ROOT / source / "notes" / f"{ident}.md").read_bytes().split(b"\n---\n\n", 1)[1]
            if ident == "doc_public":
                for link, plain in (
                    (b"[withheld note](document://default/documents/doc_private)", b"withheld note"),
                    (b"[unpublished](document://default/documents/doc_draft)", b"unpublished"),
                    (b"[missing label](No Such Fixture Note)", b"missing label"),
                ):
                    self.assertEqual(body.count(link), 1)
                    body = body.replace(link, plain)
            self.assertEqual(body, expected["body"].encode("utf-8"), ident)
        self.assertIn("```note-query\nquery: tag:private\nfields: title, snippet\nlimit: 5\n```",
                      self.expected["notes"]["doc_public"]["body"])

    def test_resource_bytes_and_relation_only_attachment(self) -> None:
        resources = {r["id"]: r for r in self.records["resource"]}
        self.assertEqual(set(resources), {"res_image", "res_text", "res_sidecar"})
        for ident, expected in self.expected["resources"].items():
            with self.subTest(resource=ident):
                resource = resources[ident]
                for field in ("filename", "mime_type"):
                    self.assertEqual(resource[field], expected[field])
                raw = self.blob_bytes(resource["blob"])
                self.assertEqual(len(raw), expected["size_bytes"])
                self.assertEqual(len(raw), resource["blob"]["size_bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected["sha256"])
                self.assertEqual(resource["blob"]["media_type"], resource["mime_type"])
                seed_files = list((FIXTURE_ROOT / "seed-v1" / "resources").glob(ident + "__*"))
                self.assertEqual(len(seed_files), 1)
                self.assertEqual(raw, seed_files[0].read_bytes())
        relations = self.records["document_resource"]
        self.assertCountEqual(relations, self.expected["document_resources"])
        self.assertEqual({r["document_id"] for r in relations if r["resource_id"] == "res_image"},
                         {"doc_public", "doc_child"})
        self.assertEqual({r["document_id"] for r in relations if r["resource_id"] == "res_sidecar"}, {"doc_public"})
        self.assertFalse(any(r.get("target_resource_id") == "res_sidecar" for r in self.records["link"]))

    def test_retained_links_have_exact_utf8_spans(self) -> None:
        self.assertCountEqual(self.records["link"], self.expected["retained_links"])
        for link in self.records["link"]:
            with self.subTest(link=link["id"]):
                body = self.expected["notes"][link["source_document_id"]]["body"].encode("utf-8")
                start, end = link["source_start_byte"], link["source_end_byte"]
                self.assertLess(start, end)
                self.assertLessEqual(end, len(body))
                bang = "!" if link["relation_type"] == "embed" else ""
                target = link["raw_target"]
                if link.get("anchor_value"):
                    self.assertEqual(link["anchor_type"], "heading")
                    target += "#" + link["anchor_value"]
                token = f"{bang}[{link['display_text']}]({target})"
                self.assertEqual(body[start:end], token.encode("utf-8"))
                self.assertEqual(link["source_format"], "markdown")
                self.assertEqual(link.get("context", ""), "")
        statuses = Counter(r["resolution_status"] for r in self.records["link"])
        self.assertEqual(statuses, {"resolved": 7, "external": 1})
        anchor = next(r for r in self.records["link"] if r["display_text"] == "this section")
        self.assertEqual(anchor["raw_target"], "")
        self.assertEqual(anchor["target_document_id"], anchor["source_document_id"])

    def test_excluded_sentinels_and_history_are_absent(self) -> None:
        self.assertGreater(len(self.expected["forbidden_in_archive"]), 0)
        for relative in self.expected["archive_files"]:
            raw = (self.archive / relative).read_bytes()
            for sentinel in self.expected["forbidden_in_archive"]:
                self.assertNotIn(sentinel.encode("utf-8"), raw, (relative, sentinel))
        audit = load_json(PUBLICATION_ROOT / "source-audit.json")
        self.assertEqual(audit["historical_sentinel_revisions"], 1)
        self.assertEqual(audit["revision_counts"]["doc_public"], 2)
        self.assertEqual({r["id"] for r in audit["documents"]},
                         {"doc_public", "doc_duplicate", "doc_child", "doc_private", "doc_draft"})
        self.assertIn("res_hidden", audit["resource_ids"])
        for collection in self.records["collection"]:
            self.assertEqual(collection["settings_json"], {})
        for kind in ("search_notebook", "provenance", "source_bundle"):
            self.assertEqual(self.records.get(kind, []), [])

    def test_design_vectors_shape_and_fixture_linkage(self) -> None:
        design = load_json(FIXTURE_ROOT / "design-v1.json")
        self.assertEqual(design["design_version"], 1)
        self.assertEqual(design["mapper"], "movenotes-notrios-v1")
        self.assertEqual(design["fixture_database_id"], self.expected["database_id"])
        for field in ("commit_sha256", "selection_manifest_sha256"):
            self.assertEqual(design["fixture_" + field], self.expected[field])
        self.assertEqual(len(design["id_vectors"]), 13)
        for vector in design["id_vectors"]:
            self.assertEqual(set(vector), {"database_id", "kind", "parts", "source_key_hex", "sha256", "mapped_id"})
            self.assertIsInstance(vector["database_id"], str)
            self.assertIsInstance(vector["kind"], str)
            self.assertIsInstance(vector["parts"], list)
            self.assertTrue(all(isinstance(part, str) for part in vector["parts"]))
            self.assertRegex(vector["source_key_hex"], r"^(?:[0-9a-f]{2})+$")
            self.assertRegex(vector["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(vector["mapped_id"], r"^[0-9a-f]{32}$")
        # Only check the frozen data here; exercise the mapper algorithm in 3a.
        self.assertEqual(set(design["fixture_projected_notes"]), set(self.expected["notes"]))
        for ident, note in design["fixture_projected_notes"].items():
            self.assertEqual(set(note), {"mapped_id", "body", "body_sha256"})
            self.assertEqual(note["mapped_id"], design["fixture_ids"]["document"][ident])
            self.assertEqual(hashlib.sha256(note["body"].encode("utf-8")).hexdigest(), note["body_sha256"])
        self.assertEqual(design["resource_extensions"], {"res_image": "png", "res_text": "txt", "res_sidecar": "bin"})
        self.assertEqual(len(design["relative_path_examples"]), 3)
        for example in design["relative_path_examples"]:
            self.assertEqual(set(example), {"source_path", "target_path", "fragment", "href"})
            self.assertTrue(all(isinstance(value, str) for value in example.values()))
        self.assertEqual(len(design["timestamp_vectors"]), 2)
        for vector in design["timestamp_vectors"]:
            self.assertEqual(set(vector), {"source", "joplin", "internal"})
            self.assertTrue(all(isinstance(value, str) for value in vector.values()))


class NotriosStrictJSONTest(unittest.TestCase):
    def decode(self, raw, **overrides):
        return archive_v2.strict_json_loads(raw, **({"max_bytes": 4096, "max_depth": 32} | overrides))

    def assert_code(self, code, call):
        with self.assertRaises(archive_v2.NotriosError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_strict_json_rejects_invalid_encoding_and_ambiguous_values(self):
        cases = [b'{"a":1,"a":2}', b'{"a":{"b":1,"\\u0062":2}}',
                 b'{"a":NaN}', b'Infinity', b'-Infinity', b'1e9999',
                 b'{"a":"\xff"}', b'"\\ud800"', b'"\\udfff"', b'{"\\ud800":1}',
                 b'{} {}', b'{} trailing', b'\xef\xbb\xbf{}', b'"raw\x01control"',
                 b'9223372036854775808', b'-9223372036854775809', b'9' * 100,
                 b'', b'{', b'{"a":01}', b'{"a":true,}']
        for raw in cases:
            with self.subTest(raw=raw):
                self.assert_code("json", lambda: self.decode(raw))
        self.assertEqual(self.decode(b'[-9223372036854775808,9223372036854775807]'),
                         [-(1 << 63), (1 << 63) - 1])
        self.assertEqual(self.decode(b'"\\ud83d\\ude00"'), "😀")
        self.assertEqual(self.decode(b'{"value":1.5}'), {"value": 1.5})

    def test_depth_and_byte_bounds_are_checked_before_json_materialization(self):
        at_limit = b'[' * 32 + b'0' + b']' * 32
        self.decode(at_limit)
        with mock.patch.object(archive_v2.json, "loads", side_effect=AssertionError("decoder reached")):
            self.assert_code("limit", lambda: self.decode(b'[' + at_limit + b']'))
            self.assert_code("limit", lambda: self.decode(b'{} ', max_bytes=2))
        self.assertEqual(self.decode(b'{}', max_bytes=2), {})
        self.assertEqual(self.decode(b'{"text":"[ { \\" ["}', max_depth=1), {"text": '[ { " ['})
        self.assert_code("limit", lambda: self.decode(b'{"child":{}}', max_depth=1))

    def test_bounded_stream_and_final_lf(self):
        stream = io.BytesIO(b'{}' + b' ' * 100)
        self.assert_code("limit", lambda: archive_v2.read_bounded_json(stream, max_bytes=8, max_depth=32))
        self.assertEqual(stream.tell(), 9)
        class ShortReads(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 1))
        self.assertEqual(archive_v2.read_bounded_json(ShortReads(b'{}\r\n'), max_bytes=4,
                                                    max_depth=32, require_final_lf=True), {})
        self.assert_code("json", lambda: archive_v2.read_bounded_json(io.BytesIO(b'{}'), max_bytes=2,
                                                                      max_depth=32, require_final_lf=True))
        self.assert_code("limit", lambda: archive_v2.read_bounded_json(io.BytesIO(b'{}\n'), max_bytes=2,
                                                                       max_depth=32, require_final_lf=True))
        broken = mock.Mock()
        broken.read.side_effect = OSError("sensitive local input detail")
        error = self.assert_code("io", lambda: archive_v2.read_bounded_json(broken, max_bytes=8, max_depth=32))
        self.assertNotIn("sensitive", str(error))

    def test_limits_only_allow_positive_integer_reductions(self):
        defaults = archive_v2.DEFAULT_LIMITS
        self.assertEqual(len(fields(defaults)), 20)
        for field in fields(defaults):
            with self.subTest(field=field.name):
                self.assertEqual(getattr(archive_v2.ArchiveLimits(**{field.name: 1}), field.name), 1)
                for value in (0, -1, True, 1.0, getattr(defaults, field.name) + 1):
                    self.assert_code("limit", lambda: archive_v2.ArchiveLimits(**{field.name: value}))
        with self.assertRaises(FrozenInstanceError):
            defaults.max_records = 1


class NotriosManifestTest(unittest.TestCase):
    def setUp(self):
        self.base = load_json(PUBLICATION_ARCHIVE / "manifest.json")
        temporary = tempfile.TemporaryDirectory(prefix="movenotes-manifest-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def parse(self, value, *, rehash=True, limits=archive_v2.DEFAULT_LIMITS):
        value = copy.deepcopy(value)
        if rehash:
            value["commit_sha256"] = archive_v2.compute_commit_sha256(archive_v2.Manifest.from_dict(value))
        (self.root / "manifest.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        # No objects directory exists. Both positive admission and specific
        # refusal codes must be obtainable from the manifest alone.
        return archive_v2.read_manifest(self.root, limits=limits)

    def assert_refused(self, value, code, *, rehash=True, limits=archive_v2.DEFAULT_LIMITS):
        with self.assertRaises(archive_v2.NotriosError) as caught:
            self.parse(value, rehash=rehash, limits=limits)
        self.assertEqual(caught.exception.code, code)

    def test_publication_admission_without_objects_and_immutable_model(self):
        manifest = self.parse(self.base, rehash=False)
        self.assertEqual(manifest.commit_sha256, self.base["commit_sha256"])
        self.assertEqual(manifest.snapshot["database_id"], self.base["snapshot"]["database_id"])
        self.assertFalse((self.root / "objects").exists())
        with self.assertRaises(TypeError):
            manifest.snapshot["id"] = "changed"
        with self.assertRaises(TypeError):
            manifest.index[0]["location"]["path"] = "changed"
        with self.assertRaises(FrozenInstanceError):
            manifest.version = 1

    def test_go_digest_vectors_and_alternate_input_serialization(self):
        vectors = load_json(FIXTURE_ROOT / "manifest-vectors.json")
        self.assertEqual(len(vectors), 6)
        for vector in vectors:
            with self.subTest(vector=vector["name"]):
                original = copy.deepcopy(vector["manifest"])
                model = archive_v2.Manifest.from_dict(original)
                self.assertEqual(archive_v2.canonical_manifest_bytes(model), vector["canonical_utf8"].encode())
                self.assertEqual(archive_v2.compute_commit_sha256(model), vector["sha256"])
                self.assertEqual(original, vector["manifest"])
                # Object order and whitespace are not part of semantic hashing.
                reordered = json.loads(json.dumps(original, sort_keys=True, indent=4, ensure_ascii=True))
                self.assertEqual(archive_v2.compute_commit_sha256(archive_v2.Manifest.from_dict(reordered)), vector["sha256"])
        self.assertEqual(vectors[0]["sha256"], self.base["commit_sha256"])
        self.assertEqual(vectors[0]["sha256"], vectors[1]["sha256"])
        self.assertEqual(vectors[0]["sha256"], vectors[5]["sha256"])
        altered = json.dumps(self.base, sort_keys=True, indent=3).encode() + b'\r\n'
        self.assertEqual(archive_v2.parse_manifest(altered).commit_sha256, self.base["commit_sha256"])

    def test_unknown_missing_null_and_wrong_types_at_each_structure(self):
        paths = [(), ("snapshot",), ("compatibility",), ("index", 0),
                 ("index", 0, "location"), ("totals",), ("counts",)]
        for path in paths:
            for mutation in ("unknown", "missing", "null"):
                value = copy.deepcopy(self.base)
                target = value
                for part in path:
                    target = target[part]
                with self.subTest(path=path, mutation=mutation):
                    if mutation == "unknown":
                        target["sensitive_unknown_field"] = "DO_NOT_ECHO"
                    elif mutation == "missing":
                        target.pop(next(iter(target)))
                    else:
                        target[next(iter(target))] = None
                    self.assert_refused(value, "json", rehash=False)
        for key in ("required_capabilities", "optional_capabilities"):
            for invalid in (None, {}, "objects.index.v1", [True]):
                value = copy.deepcopy(self.base)
                value["compatibility"][key] = invalid
                self.assert_refused(value, "json", rehash=False)
        for invalid in (True, 2.0, "2", None):
            value = copy.deepcopy(self.base)
            value["version"] = invalid
            self.assert_refused(value, "json", rehash=False)
        raw = json.dumps(self.base).encode().replace(b'"version": 2', b'"version": 2e0')
        with self.assertRaises(archive_v2.NotriosError) as caught:
            archive_v2.parse_manifest(raw)
        self.assertEqual(caught.exception.code, "json")

    def test_other_formats_targets_and_schema_bounds_refuse(self):
        for target in ("full_archive", "subset_transfer", "unknown"):
            value = copy.deepcopy(self.base)
            value["snapshot"]["target"] = target
            self.assert_refused(value, "publication")
        for value in ({"format": "notrios-sqlite-image"}, {"format": "notrios-archive", "version": 1},
                      {"format": "NCB1"}):
            self.assert_refused(value, "format", rehash=False)
        for fields_to_change in ({"minimum_reader_version": 1}, {"minimum_reader_version": 3},
                                 {"minimum_schema_version": 11}, {"minimum_schema_version": 28},
                                 {"source_schema_version": 11}, {"source_schema_version": 28},
                                 {"maximum_schema_version": 26}):
            value = copy.deepcopy(self.base)
            value["compatibility"].update(fields_to_change)
            self.assert_refused(value, "format")

    def test_schema_28_and_future_source_bounds(self):
        # Minimum is the reader requirement; source/maximum are not ceilings.
        for minimum, source, maximum in ((12, 27, 27), (12, 28, 28),
                                          (28, 28, 28), (28, 29, 99)):
            with self.subTest(minimum=minimum, source=source, maximum=maximum):
                value = copy.deepcopy(self.base)
                value["compatibility"].update(minimum_schema_version=minimum,
                                              source_schema_version=source,
                                              maximum_schema_version=maximum)
                self.parse(value)
        for minimum, source, maximum in ((29, 29, 29), (11, 28, 28),
                                          (28, 27, 28), (28, 28, 27)):
            with self.subTest(minimum=minimum, source=source, maximum=maximum):
                value = copy.deepcopy(self.base)
                value["compatibility"].update(minimum_schema_version=minimum,
                                              source_schema_version=source,
                                              maximum_schema_version=maximum)
                self.assert_refused(value, "format")

    def test_capability_and_pack_refusals(self):
        for names in ([], list(reversed(archive_v2.REQUIRED_CAPABILITIES)),
                      sorted([*archive_v2.REQUIRED_CAPABILITIES, "unknown.required.v1"]),
                      sorted([*archive_v2.REQUIRED_CAPABILITIES, "objects.pack.v1"]),
                      sorted([*archive_v2.REQUIRED_CAPABILITIES, archive_v2.REQUIRED_CAPABILITIES[0]])):
            value = copy.deepcopy(self.base)
            value["compatibility"]["required_capabilities"] = names
            self.assert_refused(value, "capability")
        for names in (["future.z", "future.a"], ["future.a", "future.a"], ["bad name"],
                      ["x"], ["東京"], ["x" * 129], [archive_v2.REQUIRED_CAPABILITIES[0]]):
            value = copy.deepcopy(self.base)
            value["compatibility"]["optional_capabilities"] = names
            self.assert_refused(value, "capability")
        value = copy.deepcopy(self.base)
        value["compatibility"]["optional_capabilities"] = ["future.preview.v1", "objects.pack.v1"]
        self.parse(value)  # Optional names do not activate packed-object support.
        for field, data in (("offset", 0), ("length", 0), ("pack_sha256", ""), ("layout", "pack")):
            value = copy.deepcopy(self.base)
            value["index"][0]["location"][field] = data
            self.assert_refused(value, "capability")
        value = copy.deepcopy(self.base)
        value["totals"]["packs"] = 1
        self.assert_refused(value, "capability")
        value["totals"]["packs"] = 0
        self.parse(value)

    def test_identity_time_and_declaration_consistency(self):
        cases = [(("snapshot", "id"), "Bad-ID", "format"),
                 (("snapshot", "database_id"), "x" * 129, "format"),
                 (("snapshot", "consistency"), "unknown", "format"),
                 (("snapshot", "collection_ids"), ["default", "default"], "format"),
                 (("snapshot", "collection_ids"), ["zz", "aa"], "format"),
                 (("snapshot", "collection_ids"), [], "limit"),
                 (("snapshot", "selection_manifest_sha256"), "G" * 64, "format"),
                 (("counts", "collections"), 2, "integrity"),
                 (("counts", "provenance"), 1, "publication"),
                 (("counts", "source_bundles"), 1, "publication"),
                 (("counts", "search_notebooks"), 1, "publication"),
                 (("totals", "objects"), 8, "integrity"),
                 (("totals", "blobs"), 7, "integrity"),
                 (("totals", "record_chunks"), 0, "limit"),
                 (("counts", "tags"), -1, "limit")]
        for path, replacement, code in cases:
            with self.subTest(path=path, replacement=replacement):
                value = copy.deepcopy(self.base)
                value[path[0]][path[1]] = replacement
                self.assert_refused(value, code)
        for timestamp in ("2026-02-30T00:00:00Z", "2026-09-05T21:17:09+01:00", "2026-09-05",
                          "2026-09-05t21:17:09z", "2026-09-05T21:17:60Z", "2026-09-05T21:17:09.1234567890Z"):
            value = copy.deepcopy(self.base)
            value["snapshot"]["created_at"] = timestamp
            self.assert_refused(value, "format")
        for timestamp in ("2026-09-05T21:17:09.123456789Z", "2026-09-05T21:17:09+00:00",
                          "2026-09-05T21:17:09-00:00", "0000-02-29T00:00:00Z"):
            value = copy.deepcopy(self.base)
            value["snapshot"]["created_at"] = timestamp
            self.parse(value)

    def test_index_descriptor_paths_shapes_and_limits(self):
        for key, invalid, code in (("sha256", "A" * 64, "format"),
                                   ("entries", 0, "limit"), ("entries", 10001, "limit"),
                                   ("size_bytes", 0, "limit"), ("media_type", "text/plain", "format")):
            value = copy.deepcopy(self.base)
            value["index"][0][key] = invalid
            self.assert_refused(value, code)
        for path in ("../outside", "objects\\sha256\\file", "/absolute", "objects/sha256/aa/bb/wrong"):
            value = copy.deepcopy(self.base)
            value["index"][0]["location"]["path"] = path
            self.assert_refused(value, "path")
        value = copy.deepcopy(self.base)
        value["index"] *= 2
        self.assert_refused(value, "integrity")
        value["index"] = []
        self.assert_refused(value, "limit")
        for name, lower in (("max_objects", 6), ("max_records", 33), ("max_notebooks", 1),
                            ("max_total_bytes", 9505), ("max_index_entries_per_object", 6),
                            ("max_index_object_bytes", 2119), ("max_path_bytes", 84),
                            ("max_path_depth", 4), ("max_capabilities", 4), ("max_capability_name_bytes", 5)):
            with self.subTest(limit=name):
                self.assert_refused(self.base, "limit", limits=archive_v2.ArchiveLimits(**{name: lower}))

    def test_checksum_mismatch_is_not_admitted(self):
        value = copy.deepcopy(self.base)
        value["snapshot"]["id"] = "snap_changed"
        self.assert_refused(value, "integrity", rehash=False)
        value["commit_sha256"] = "A" * 64
        self.assert_refused(value, "format", rehash=False)

    def test_manifest_filesystem_and_read_size_bounds(self):
        raw = (PUBLICATION_ARCHIVE / "manifest.json").read_bytes()
        path = self.root / "manifest.json"
        path.write_bytes(raw)
        exact = archive_v2.ArchiveLimits(max_manifest_bytes=len(raw))
        archive_v2.read_manifest(self.root, limits=exact)
        with mock.patch.object(archive_v2, "_read_bounded_bytes", side_effect=AssertionError("oversized file read")):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                archive_v2.read_manifest(self.root, limits=archive_v2.ArchiveLimits(max_manifest_bytes=len(raw)-1))
            self.assertEqual(caught.exception.code, "limit")
        path.unlink()
        for make, code in ((lambda: path.symlink_to(PUBLICATION_ARCHIVE / "manifest.json"), "io"),
                           (lambda: path.mkdir(), "path"), (lambda: os.mkfifo(path), "path")):
            make()
            with self.assertRaises(archive_v2.NotriosError) as caught:
                archive_v2.read_manifest(self.root)
            self.assertEqual(caught.exception.code, code)
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        linked = self.root / "linked-root"
        linked.symlink_to(PUBLICATION_ARCHIVE, target_is_directory=True)
        with self.assertRaises(archive_v2.NotriosError) as caught:
            archive_v2.read_manifest(linked)
        self.assertEqual(caught.exception.code, "io")
        with self.assertRaises(archive_v2.NotriosError) as caught:
            archive_v2.read_manifest(linked / "..")
        self.assertEqual(caught.exception.code, "io")


class NotriosObjectSpoolTest(unittest.TestCase):
    """Rehashed object, typed-record and graph mutations on owned fixture copies."""

    fixture_source = PUBLICATION_ARCHIVE

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="movenotes-objects-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.case = 0
        self.fresh_archive()

    def fresh_archive(self):
        self.case += 1
        self.archive = Path(shutil.copytree(self.fixture_source, self.root / f"archive-{self.case}", symlinks=True))
        self.manifest, self.entries, _records = read_fixture_records(self.archive)

    def write_manifest(self):
        self.manifest["commit_sha256"] = archive_v2.compute_commit_sha256(
            archive_v2.Manifest.from_dict(self.manifest))
        (self.archive / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def put_object(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        relative = f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}"
        target = self.archive / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return digest, relative

    def write_index(self, groups=None, *, raw=None):
        # Rehash only caller-owned synthetic copies. Independent 2a Go vectors
        # remain the oracle for the semantic digest helper used here.
        for descriptor in self.manifest["index"]:
            (self.archive / descriptor["location"]["path"]).unlink()
        self.manifest["index"] = []
        for group in groups if groups is not None else [self.entries]:
            data = raw if raw is not None else b"".join(
                json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode() + b"\n" for entry in group)
            digest, relative = self.put_object(data)
            self.manifest["index"].append({
                "sha256": digest, "size_bytes": len(data), "entries": len(group),
                "media_type": archive_v2.INDEX_MEDIA_TYPE, "location": {"layout": "fanout", "path": relative},
            })
        self.write_manifest()

    def replace_record_bytes(self, raw):
        entry = next(entry for entry in self.entries if entry["kind"] == "records")
        old_size = entry["size_bytes"]
        (self.archive / entry["location"]["path"]).unlink()
        digest, relative = self.put_object(raw)
        entry.update(sha256=digest, size_bytes=len(raw), location={"layout": "fanout", "path": relative})
        self.manifest["totals"]["bytes"] += len(raw) - old_size
        self.entries.sort(key=lambda entry: entry["sha256"])
        self.write_index()

    def stage(self, **kwargs):
        return archive_v2._stage_archive_objects(self.archive, work_dir=self.work, **kwargs)

    def assert_refused(self, code, message=None, **kwargs):
        unusual = any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in self.archive.rglob("*"))
        before = None if unusual else fixture_inventory(self.archive)
        with self.assertRaises(archive_v2.NotriosError) as caught:
            with self.stage(**kwargs):
                self.fail("invalid object inventory yielded a checkpoint")
        self.assertEqual(caught.exception.code, code)
        if message:
            self.assertIn(message, str(caught.exception))
        self.assertNotIn("PRIVATE-SENTINEL", str(caught.exception))
        self.assertEqual(list(self.work.iterdir()), [])
        if before is not None:
            self.assertEqual(fixture_inventory(self.archive), before)

    def test_fixture_copies_spools_and_context_lifetime(self):
        expected = load_json(PUBLICATION_ROOT / "expected.json")
        with self.stage() as spool:
            saved = spool.directory
            self.assertEqual(spool.manifest.commit_sha256, expected["commit_sha256"])
            self.assertEqual(spool.connection.execute("SELECT count(*) FROM objects").fetchone(), (8,))
            self.assertEqual(spool.connection.execute("SELECT count(*) FROM records").fetchone(), (34,))
            self.assertEqual(spool.connection.execute("SELECT count(*) FROM source_files").fetchone(), (9,))
            self.assertEqual(spool.connection.execute("PRAGMA cache_size").fetchone(), (-8192,))
            self.assertEqual(spool.connection.execute("PRAGMA temp_store").fetchone(), (1,))
            for relative, data in expected["archive_files"].items():
                copied = saved / relative
                self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), data["sha256"])
                self.assertEqual(copied.stat().st_mode & 0o222, 0)
            for digest, number, raw in spool.connection.execute(
                "SELECT object_sha256,line_number,raw FROM records ORDER BY seq"
            ):
                object_path = saved / f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}"
                self.assertEqual(raw, object_path.read_bytes().split(b"\n")[number - 1] + b"\n")
            # Retained copies have no dependency on subsequent source writes.
            (self.archive / "manifest.json").write_bytes(b"changed")
            self.assertEqual(hashlib.sha256((saved / "manifest.json").read_bytes()).hexdigest(),
                             expected["archive_files"]["manifest.json"]["sha256"])
        self.assertFalse(saved.exists())
        self.assertEqual(list(self.work.iterdir()), [])
        with self.assertRaises(sqlite3.ProgrammingError):
            spool.connection.execute("SELECT 1")

    def test_empty_fanout_directories_and_legacy_zero_blob_counts(self):
        (self.archive / "objects" / "sha256" / "ff" / "ee").mkdir(parents=True, exist_ok=True)
        for entry in self.entries:
            if entry["kind"] == "blob":
                entry["records"] = 0
                entry["record_counts"] = dict.fromkeys(EXPECTED_COUNTS, 0)
        self.write_index()
        with self.stage() as spool:
            self.assertEqual(spool.connection.execute("SELECT count(*) FROM objects WHERE kind='blob'").fetchone(), (6,))
        self.assertEqual(list(self.work.iterdir()), [])

    def test_multiple_index_chunks_use_entry_order(self):
        groups = [self.entries[:3], self.entries[3:]]
        self.write_index(groups)
        # Deliberately put descriptor hashes out of lexical order while leaving
        # their contained entry hashes globally sorted.
        first, second = self.manifest["index"]
        raw = (self.archive / first["location"]["path"]).read_bytes()
        for padding in range(1000):
            candidate = b" " * padding + raw
            if hashlib.sha256(candidate).hexdigest() > second["sha256"]:
                break
        else:
            self.fail("could not construct descending index descriptor hashes")
        (self.archive / first["location"]["path"]).unlink()
        digest, relative = self.put_object(candidate)
        first.update(sha256=digest, size_bytes=len(candidate), location={"layout": "fanout", "path": relative})
        self.write_manifest()
        self.assertGreater(first["sha256"], second["sha256"])
        with self.stage() as spool:
            self.assertEqual(spool.connection.execute("SELECT count(*) FROM objects WHERE kind='index'").fetchone(), (2,))
        # Same totals and entries, but a reversed cross-chunk boundary.
        self.write_index([self.entries[:2] + [self.entries[3]], [self.entries[2]] + self.entries[4:]])
        self.assert_refused("integrity", "globally ordered")

    def test_missing_corrupt_and_truncated_objects_refuse(self):
        for kind in ("index", "records", "blob"):
            for damage in ("missing", "corrupt", "truncated"):
                with self.subTest(kind=kind, damage=damage):
                    self.fresh_archive()
                    entry = self.manifest["index"][0] if kind == "index" else next(e for e in self.entries if e["kind"] == kind)
                    path = self.archive / entry["location"]["path"]
                    raw = path.read_bytes()
                    if damage == "missing":
                        path.unlink()
                    elif damage == "corrupt":
                        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                    else:
                        path.write_bytes(raw[:-1])
                    self.assert_refused("io" if damage == "missing" else "integrity")

    def test_duplicate_order_counts_and_totals_refuse(self):
        self.entries[1] = copy.deepcopy(self.entries[0])
        self.write_index()
        self.assert_refused("integrity", "globally ordered")
        self.fresh_archive()
        entry = next(e for e in self.entries if e["kind"] == "records")
        entry["records"] += 1
        self.write_index()
        self.assert_refused("integrity", "record counts do not agree")
        self.fresh_archive()
        self.manifest["totals"]["bytes"] += 1
        self.write_manifest()
        self.assert_refused("integrity", "totals/counts differ")
        self.fresh_archive()
        self.manifest["counts"]["tags"] += 1
        self.write_manifest()
        self.assert_refused("integrity", "totals/counts differ")

    def test_entry_unknown_fields_types_paths_and_pack_refuse(self):
        cases = [("unknown", 1, "json"), ("size_bytes", True, "json"),
                 ("records", None, "json"), ("record_counts", None, "json"),
                 ("kind", "pack", "capability"), ("kind", "other", "format"),
                 ("media_type", "text/plain; invalid", "format")]
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                self.fresh_archive()
                entry = next(e for e in self.entries if e["kind"] == "blob")
                entry[field] = value
                self.write_index()
                self.assert_refused(code)
        for location, code in (({"layout": "fanout", "path": "../outside"}, "path"),
                               ({"layout": "fanout", "path": "objects\\sha256\\bad"}, "path"),
                               ({"layout": "pack", "offset": 0, "length": 0}, "capability")):
            self.fresh_archive()
            self.entries[0]["location"] = location
            self.write_index()
            self.assert_refused(code)

    def test_jsonl_line_termination_and_counts(self):
        for damage, code in (("no_lf", "json"), ("blank", "json"), ("fewer", "integrity"),
                             ("duplicate_key", "json")):
            with self.subTest(damage=damage):
                self.fresh_archive()
                raw = (self.archive / self.manifest["index"][0]["location"]["path"]).read_bytes()
                if damage == "no_lf":
                    raw = raw[:-1]
                elif damage == "blank":
                    raw = b"\n" + raw
                elif damage == "fewer":
                    raw = raw.split(b"\n", 1)[1]
                else:
                    raw = raw.replace(b'{"sha256":', b'{"kind":"blob","sha256":', 1)
                self.write_index(raw=raw)
                self.assert_refused(code)
        for damage, code in (("no_lf", "json"), ("blank", "json"), ("type", "format"),
                             ("counts", "integrity"), ("field", "json")):
            with self.subTest(records=damage):
                self.fresh_archive()
                entry = next(e for e in self.entries if e["kind"] == "records")
                raw = (self.archive / entry["location"]["path"]).read_bytes()
                if damage == "no_lf":
                    raw = raw[:-1]
                elif damage == "blank":
                    raw = b"\n" + raw
                else:
                    lines = raw[:-1].split(b"\n")
                    record = json.loads(lines[0])
                    if damage == "type":
                        record["type"] = "unknown"
                    elif damage == "counts":
                        record["type"] = "tag"
                    else:
                        record["extra"] = "not allowed"
                    lines[0] = json.dumps(record).encode()
                    raw = b"\n".join(lines) + b"\n"
                self.replace_record_bytes(raw)
                self.assert_refused(code)

    def test_symlink_parent_and_unexpected_tree_entries_refuse(self):
        target = self.archive / self.entries[0]["location"]["path"]
        external = self.root / "external-object"
        external.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(external)
        self.assert_refused("io")
        self.fresh_archive()
        (self.archive / "objects").rename(self.root / "moved-objects")
        (self.archive / "objects").symlink_to(self.root / "moved-objects", target_is_directory=True)
        self.assert_refused("io")
        for name, directory in (("extra.txt", False), ("other", True), ("objects/sha256/zz", True),
                                ("objects/sha256/aa/bb/cc", True)):
            self.fresh_archive()
            target = self.archive / name
            if directory:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.write_text("extra", encoding="utf-8")
            self.assert_refused("path")
        self.fresh_archive()
        self.put_object(b"an unlisted but correctly named object")
        self.assert_refused("integrity")
        self.fresh_archive()
        target = self.archive / self.entries[0]["location"]["path"]
        target.unlink()
        os.mkfifo(target)
        self.assert_refused("path")

    def test_line_bounds_and_copy_chunk_size(self):
        self.assert_refused("limit", "JSONL line bytes", limits=archive_v2.ArchiveLimits(max_index_entry_bytes=16))
        self.assert_refused("limit", "JSONL line bytes", limits=archive_v2.ArchiveLimits(max_record_bytes=16))
        original_open = archive_v2._open_regular_file
        requests = []
        @contextmanager
        def tracked(root_fd, relative):
            with original_open(root_fd, relative) as stream:
                if relative == "manifest.json":
                    yield stream
                else:
                    class Reader:
                        def fileno(self):
                            return stream.fileno()
                        def read(self, size):
                            requests.append(size)
                            self_test.assertLessEqual(size, 7)
                            return stream.read(size)
                    yield Reader()
        self_test = self
        with mock.patch.object(archive_v2, "_COPY_BYTES", 7), mock.patch.object(archive_v2, "_open_regular_file", tracked):
            with self.stage() as spool:
                self.assertEqual(spool.connection.execute("SELECT count(*) FROM records").fetchone(), (34,))
        self.assertGreater(len(requests), 100)

    def test_failure_cleanup_and_archive_work_overlap(self):
        original = fixture_inventory(self.archive)
        with mock.patch.object(archive_v2, "_stage_data_objects", side_effect=OSError("injected disk failure")):
            self.assert_refused("io")
        self.assertEqual(fixture_inventory(self.archive), original)
        with self.assertRaises(archive_v2.NotriosError) as caught:
            with archive_v2._stage_archive_objects(self.archive, work_dir=self.archive):
                self.fail("archive used as work directory")
        self.assertEqual(caught.exception.code, "path")
        self.assertEqual(fixture_inventory(self.archive), original)

    def test_sqlite_insert_batches_remain_bounded(self):
        observed = []
        class TracedConnection(sqlite3.Connection):
            def executemany(self, sql, rows):
                rows = list(rows)
                size = sum(len(value.encode()) if isinstance(value, str) else
                           len(value) if isinstance(value, bytes) else 8 for row in rows for value in row)
                observed.append((len(rows), size))
                return super().executemany(sql, rows)
        connect = sqlite3.connect
        def traced_connect(*args, **kwargs):
            return connect(*args, **kwargs, factory=TracedConnection)
        with mock.patch.object(archive_v2, "_BATCH_ROWS", 2), mock.patch.object(archive_v2, "_BATCH_BYTES", 300), \
                mock.patch.object(archive_v2.sqlite3, "connect", traced_connect):
            with self.stage() as spool:
                self.assertEqual(spool.connection.execute("SELECT count(*) FROM records").fetchone(), (34,))
        self.assertGreater(len(observed), 10)
        for count, size in observed:
            self.assertLessEqual(count, 2)
            self.assertTrue(size <= 300 or count == 1)
        self.assertTrue(any(size > 300 and count == 1 for count, size in observed))

    def test_exact_jsonl_byte_limits_include_lf_and_crlf(self):
        for kind, limit in (("index", 4096), ("records", 1048576)):
            for ending in (b"\n", b"\r\n"):
                for excess in (0, 1):
                    with self.subTest(kind=kind, ending=ending, excess=excess):
                        self.fresh_archive()
                        entry = (self.manifest["index"][0] if kind == "index" else
                                 next(e for e in self.entries if e["kind"] == "records"))
                        raw = (self.archive / entry["location"]["path"]).read_bytes()
                        first, rest = raw.split(b"\n", 1)
                        first = first.rstrip(b"\r")
                        raw = first + b" " * (limit + excess - len(first) - len(ending)) + ending + rest
                        self.assertEqual(len(raw.split(b"\n", 1)[0]) + 1, limit + excess)
                        if kind == "index":
                            self.write_index(raw=raw)
                        else:
                            self.replace_record_bytes(raw)
                        if excess:
                            self.assert_refused("limit", "JSONL line bytes")
                        else:
                            with self.stage():
                                pass
                            self.assertEqual(list(self.work.iterdir()), [])

    def test_index_integer_tokens_and_nested_count_shapes(self):
        for value in (True, 1.0, 1e20, 2 ** 63, -(2 ** 63) - 1):
            with self.subTest(integer=value):
                self.fresh_archive()
                self.entries[0]["size_bytes"] = value
                self.write_index()
                self.assert_refused("json", "integer")
        for damage in ("missing", "unknown", "null", "boolean", "nonzero"):
            with self.subTest(counts=damage):
                self.fresh_archive()
                entry = next(e for e in self.entries if e["kind"] == "blob")
                counts = dict.fromkeys(self.manifest["counts"], 0)
                if damage == "missing":
                    del counts["tags"]
                elif damage == "unknown":
                    counts["future"] = 0
                elif damage == "null":
                    counts["tags"] = None
                elif damage == "boolean":
                    counts["tags"] = False
                else:
                    counts["tags"] = 1
                entry["record_counts"] = counts
                self.write_index()
                code, message = (("integrity", "blob entry declares records") if damage == "nonzero" else
                                 ("json", "missing or unknown fields") if damage in ("missing", "unknown") else
                                 ("json", "integer"))
                self.assert_refused(code, message)

    def test_storage_mime_utf8_byte_boundary(self):
        # A quoted parameter accepts Unicode; the storage bound counts UTF-8 bytes.
        for size in (255, 256):
            with self.subTest(size=size):
                self.fresh_archive()
                entry = next(e for e in self.entries if e["kind"] == "blob")
                prefix = 'text/plain; note="é'
                entry["media_type"] = prefix + "a" * (size - len(prefix.encode()) - 1) + '"'
                self.assertEqual(len(entry["media_type"].encode()), size)
                self.assertLess(len(entry["media_type"]), size)
                self.write_index()
                if size == 255:
                    with self.stage():
                        pass
                else:
                    self.assert_refused("format", "storage MIME length")

    def test_optional_capability_count_and_name_boundaries(self):
        for total in (64, 65):
            with self.subTest(total=total):
                self.fresh_archive()
                compat = self.manifest["compatibility"]
                compat["optional_capabilities"] = [f"future-{i:03}" for i in
                                                   range(total - len(compat["required_capabilities"]))]
                self.write_manifest()
                if total == 64:
                    with self.stage():
                        pass
                else:
                    self.assert_refused("limit", "capability count")
        for size in (128, 129):
            with self.subTest(name_bytes=size):
                self.fresh_archive()
                self.manifest["compatibility"]["optional_capabilities"] = ["x" * size]
                self.write_manifest()
                if size == 128:
                    with self.stage():
                        pass
                else:
                    self.assert_refused("capability", "invalid capability name")

    def test_rehashed_hostile_record_json(self):
        cases = ((b'{"type":"tag","payload":{},"type":"tag"}\n', "duplicate"),
                 (b'{"type":"tag","payload":{"x":NaN}}\n', "nonfinite"),
                 (b'{"type":"tag","payload":{"x":"\xff"}}\n', "UTF-8"),
                 (b'{"type":"tag","payload":{"x":' + b'[' * 32 + b'0' + b']' * 32 + b'}}\n', "depth"))
        for first, message in cases:
            with self.subTest(message=message):
                self.fresh_archive()
                entry = next(e for e in self.entries if e["kind"] == "records")
                raw = (self.archive / entry["location"]["path"]).read_bytes()
                self.replace_record_bytes(first + raw.split(b"\n", 1)[1])
                self.assert_refused("limit" if message == "depth" else "json", "nesting limit" if message == "depth" else message)

    def test_index_chunk_cannot_be_indexed_as_a_blob(self):
        # The referenced chunk is a different chunk, avoiding impossible self-hashing.
        second = b"".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode() + b"\n" for e in self.entries)
        digest = hashlib.sha256(second).hexdigest()
        shadow = {"sha256": digest, "size_bytes": len(second), "kind": "blob",
                  "media_type": "application/octet-stream",
                  "location": {"layout": "fanout", "path": f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}"}}
        self.manifest["totals"]["objects"] += 1
        self.manifest["totals"]["blobs"] += 1
        self.manifest["totals"]["bytes"] += len(second)
        self.write_index([[shadow], self.entries])
        self.assert_refused("integrity", "distinct from index chunks")

    def envelopes(self):
        entry = next(e for e in self.entries if e["kind"] == "records")
        return [json.loads(line) for line in (self.archive / entry["location"]["path"]).read_bytes().split(b"\n") if line]

    def write_records(self, records):
        counts = dict.fromkeys(RECORD_COUNTS.values(), 0)
        for record in records:
            counts[RECORD_COUNTS[record["type"]]] += 1
        entry = next(e for e in self.entries if e["kind"] == "records")
        entry["records"], entry["record_counts"] = len(records), counts
        self.manifest["counts"] = counts.copy()
        self.replace_record_bytes(b"".join(json.dumps(r, ensure_ascii=False).encode() + b"\n" for r in records))

    def verify(self, **kwargs):
        return archive_v2.verify_archive(self.archive, work_dir=self.work, **kwargs)

    def assert_verification_refused(self, code, message, **kwargs):
        with mock.patch.object(self, "stage", self.verify):
            self.assert_refused(code, message, **kwargs)

    def test_verified_fixture_api_and_immutable_payloads(self):
        before = fixture_inventory(self.archive)
        with self.verify() as verified:
            self.assertEqual(dict(verified.counts), EXPECTED_COUNTS)
            for kind, count_name in RECORD_COUNTS.items():
                if not EXPECTED_COUNTS[count_name]:
                    continue
                records = list(verified.iter_records(kind))
                self.assertEqual(len(records), EXPECTED_COUNTS[count_name])
                # Independently frame the variable part of the frozen source key.
                order = lambda r: b"".join(len(p.encode()).to_bytes(4, "big") + p.encode() for p in r.key)
                self.assertEqual(records, sorted(records, key=order))
                for record in records:
                    self.assertEqual(verified.get_record(kind, record.key), record)
            for doc in verified.iter_records("document"):
                for kind in ("document_tag", "document_resource", "link"):
                    field = "source_document_id" if kind == "link" else "document_id"
                    expected = [r for r in verified.iter_records(kind) if r.payload[field] == doc.key[0]]
                    self.assertEqual(list(verified.iter_relations(kind, doc.key[0])), expected)
            revision = next(verified.iter_records("revision"))
            with self.assertRaises(TypeError):
                revision.payload["title"] = "changed"
            with self.assertRaises(TypeError):
                revision.payload["body"]["size_bytes"] = 0
            with verified.open_blob(archive_v2.BlobRef(**revision.payload["body"])) as stream:
                raw = stream.read()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), revision.payload["body"]["sha256"])
            iterator = verified.iter_records("tag")
            next(iterator)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(fixture_inventory(self.archive), before)
        for action in (lambda: next(iterator), lambda: verified.get_record("tag", ("tag_missing",))):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                action()
            self.assertEqual(caught.exception.code, "io")

    def test_payload_structured_shapes(self):
        # Every admitted kind: missing required field, unknown field, null and
        # wrong type. These records are rehashed through both index and manifest.
        for kind in ("collection", "notebook", "tag", "document", "revision", "document_tag", "resource", "document_resource", "link"):
            for damage in ("missing", "unknown", "null", "type"):
                with self.subTest(kind=kind, damage=damage):
                    self.fresh_archive()
                    records = self.envelopes()
                    p = next(r["payload"] for r in records if r["type"] == kind)
                    required = "document_id" if kind in ("document_tag", "document_resource") else "id"
                    if damage == "missing":
                        del p[required]
                    elif damage == "unknown":
                        p["unknown"] = "PRIVATE-SENTINEL"
                    else:
                        p[required] = None if damage == "null" else 123
                    self.write_records(records)
                    self.assert_verification_refused("json", "missing or unknown" if damage in ("missing", "unknown") else "string field")
        for kind, field, value, message in (
            ("notebook", "builtin", 0, "boolean"), ("notebook", "position", True, "integer"),
            ("notebook", "position", 1.0, "integer"), ("collection", "capabilities", {}, "array"),
            ("collection", "settings_json", "{}", "requires an object"),
            ("revision", "metadata_json", [], "requires an object"),
            ("resource", "metadata_json", None, "requires an object"),
            ("document_resource", "anchor_json", "{}", "requires an object"),
            ("document_resource", "ordinal", 1.0, "integer"),
            ("link", "source_start_byte", False, "integer")):
            with self.subTest(kind=kind, field=field):
                self.fresh_archive()
                records = self.envelopes()
                next(r["payload"] for r in records if r["type"] == kind)[field] = value
                self.write_records(records)
                self.assert_verification_refused("json", message)

    def test_record_semantic_scalar_refusals(self):
        cases = (("notebook", "parent_id", "", "format", "identity"),
                 ("link", "target_document_id", "", "format", "identity"),
                 ("tag", "name", " \t", "format", "nonblank"),
                 ("tag", "name", "é" * 2049, "limit", "name bytes"),
                 ("resource", "filename", "é" * 2049, "limit", "filename bytes"),
                 ("document", "created_at", "2026-02-30T00:00:00Z", "format", "calendar"),
                 ("resource", "unreferenced_at", "2026-01-01T00:00:00+01:00", "format", "RFC3339 UTC"),
                 ("collection", "capabilities", ["b", "a"], "format", "sorted and unique"),
                 ("collection", "capabilities", ["a", "a"], "format", "sorted and unique"),
                 ("document_resource", "relation_type", " ", "format", "nonblank"),
                 ("document_resource", "ordinal", -1, "format", "nonnegative"),
                 ("link", "source_end_byte", 0, "format", "span is reversed"),
                 ("link", "source_line", -1, "format", "nonnegative"))
        for kind, field, value, code, message in cases:
            with self.subTest(kind=kind, field=field, message=message):
                self.fresh_archive()
                records = self.envelopes()
                next(r["payload"] for r in records if r["type"] == kind)[field] = value
                self.write_records(records)
                self.assert_verification_refused(code, message)

    def test_duplicate_record_identities_refuse(self):
        for kind in ("notebook", "tag", "document", "revision", "resource", "document_tag", "document_resource", "link"):
            with self.subTest(kind=kind):
                self.fresh_archive()
                records = self.envelopes()
                records.append(copy.deepcopy(next(r for r in records if r["type"] == kind)))
                self.write_records(records)
                self.assert_verification_refused("integrity", "duplicate record identity")
        self.fresh_archive()
        records = self.envelopes()
        records.append(copy.deepcopy(next(r for r in records if r["type"] == "collection")))
        self.manifest["snapshot"]["collection_ids"].append("other_collection")
        self.manifest["snapshot"]["collection_ids"].sort()
        self.write_records(records)
        self.assert_verification_refused("integrity", "duplicate record identity")

    def test_missing_record_references_refuse(self):
        for kind, field in (("notebook", "parent_id"), ("document", "collection_id"),
                            ("document", "notebook_id"), ("document", "current_revision_id"),
                            ("revision", "document_id"), ("resource", "collection_id"),
                            ("document_tag", "document_id"), ("document_tag", "tag_id"),
                            ("document_resource", "document_id"), ("document_resource", "resource_id"),
                            ("link", "source_document_id"), ("link", "target_document_id")):
            with self.subTest(kind=kind, field=field):
                self.fresh_archive()
                records = self.envelopes()
                p = next(r["payload"] for r in records if r["type"] == kind)
                if kind == "link":
                    p.pop("target_resource_id", None)
                    p["resolution_status"] = "resolved"
                p[field] = "missing_target"
                self.write_records(records)
                self.assert_verification_refused("graph", "reference has no target")

    def test_notebook_cycles_depth_and_collection_scope(self):
        records = self.envelopes()
        notebooks = [r["payload"] for r in records if r["type"] == "notebook"]
        notebooks[0]["parent_id"] = notebooks[1]["id"]
        notebooks[1]["parent_id"] = notebooks[0]["id"]
        self.write_records(records)
        self.assert_verification_refused("graph", "parent cycle")
        self.fresh_archive()
        records = self.envelopes()
        template = copy.deepcopy(next(r for r in records if r["type"] == "notebook"))
        records = [r for r in records if r["type"] != "notebook"]
        for depth in range(1, 34):
            node = copy.deepcopy(template)
            node["payload"].update(id=f"tree_{depth:02}")
            node["payload"].pop("parent_id", None)
            if depth > 1:
                node["payload"]["parent_id"] = f"tree_{depth-1:02}"
            records.append(node)
        for r in records:
            if r["type"] == "document":
                r["payload"]["notebook_id"] = "tree_01"
        self.write_records(records[:-1])
        with self.verify():
            pass
        self.write_records(records)
        self.assert_verification_refused("limit", "notebook depth")
        self.fresh_archive()
        self.manifest["snapshot"]["collection_ids"] = ["other_collection"]
        self.write_manifest()
        self.assert_verification_refused("graph", "snapshot scope")

    def test_publication_metadata_history_and_reachability(self):
        for kind, field, value, message in (
            ("collection", "settings_json", {"private": "PRIVATE-SENTINEL"}, "settings must be empty"),
            ("revision", "metadata_json", {"private": "PRIVATE-SENTINEL"}, "metadata must be empty"),
            ("document", "deleted_at", "2026-01-01T00:00:00Z", "deleted documents"),
            ("link", "context", "PRIVATE-SENTINEL", "context must be empty"),
            ("link", "resolution_status", "withheld", "status is not publishable")):
            with self.subTest(kind=kind, field=field):
                self.fresh_archive()
                records = self.envelopes()
                next(r["payload"] for r in records if r["type"] == kind)[field] = value
                self.write_records(records)
                self.assert_verification_refused("publication", message)
        self.fresh_archive()
        records = self.envelopes()
        revision = copy.deepcopy(next(r for r in records if r["type"] == "revision"))
        revision["payload"]["id"] = "old_revision"
        records.append(revision)
        self.write_records(records)
        self.assert_verification_refused("publication", "noncurrent revision history")
        self.fresh_archive()
        records = self.envelopes()
        docs = [r["payload"] for r in records if r["type"] == "document"]
        docs[0]["current_revision_id"] = docs[1]["current_revision_id"]
        self.write_records(records)
        self.assert_verification_refused("graph", "belongs to another document")
        self.fresh_archive()
        records = [r for r in self.envelopes() if r["type"] != "document_resource"]
        self.write_records(records)
        self.assert_verification_refused("publication", "not reachable")

    def test_blob_reference_shape_mime_and_matching_bytes(self):
        for field, value, code, message in (
            ("sha256", "0" * 64, "integrity", "matching hash and size"),
            ("size_bytes", 0, "integrity", "matching hash and size"),
            ("size_bytes", True, "json", "integer"),
            ("sha256", "A" * 64, "format", "reference hash"),
            ("media_type", "Text/Markdown", "format", "must be canonical"),
            ("media_type", "text/plain", "integrity", "MIME differs"),
            ("extra", 1, "json", "missing or unknown")):
            with self.subTest(field=field, value=value):
                self.fresh_archive()
                records = self.envelopes()
                next(r["payload"] for r in records if r["type"] == "revision")["body"][field] = value
                self.write_records(records)
                self.assert_verification_refused(code, message)
        self.fresh_archive()
        records = self.envelopes()
        revisions = [r["payload"] for r in records if r["type"] == "revision"]
        revisions[0]["body"] = copy.deepcopy(revisions[1]["body"])
        self.write_records(records)
        self.assert_verification_refused("integrity", "unreferenced blob")

    def test_valid_metadata_optional_fields_and_opaque_body_mime(self):
        records = self.envelopes()
        for r in records:
            p = r["payload"]
            if r["type"] == "resource":
                p.update(metadata_json={"nested": [{"public": 1.5}]}, unreferenced_at="", unreferenced_reason="unused state")
            elif r["type"] == "document":
                p["deleted_at"] = ""
            elif r["type"] == "revision":
                p.update(message="retained but not projected", body_mime_type='TEXT/PLAIN; Charset="utf-8"')
                p["body"]["media_type"] = "text/plain; charset=utf-8"
            elif r["type"] == "notebook":
                p["position"] = -1  # Signed positions have no nonnegative restriction.
            if "created_at" in p:
                p["created_at"] = "0000-02-29T23:59:59.123456789+00:00"
        # Descriptor media types remain hints and may differ from semantic MIME.
        for entry in self.entries:
            if entry["kind"] == "blob":
                entry["media_type"] = "application/octet-stream"
        self.write_records(records)
        with self.verify() as verified:
            resource = next(verified.iter_records("resource"))
            with self.assertRaises(TypeError):
                resource.payload["metadata_json"]["nested"][0]["public"] = 0
            self.assertEqual(next(verified.iter_records("revision")).payload["body"]["media_type"], "text/plain; charset=utf-8")

    def test_link_publication_target_rules(self):
        for damage, message in (("two_targets", "multiple internal targets"),
                                ("external_internal", "HTTP(S)"), ("external_scheme", "HTTP(S)"),
                                ("external_host", "HTTP(S)"), ("idless", "self-anchor")):
            with self.subTest(damage=damage):
                self.fresh_archive()
                records = self.envelopes()
                p = next(r["payload"] for r in records if r["type"] == "link")
                p.pop("target_document_id", None)
                p.pop("target_resource_id", None)
                p.pop("target_uri", None)
                p["resolution_status"] = "resolved"
                if damage == "two_targets":
                    p.update(target_document_id="doc_public", target_resource_id="res_image")
                elif damage.startswith("external"):
                    p["resolution_status"] = "external"
                    p["raw_target"] = "https://example.com/"
                    if damage == "external_internal":
                        p["target_document_id"] = "doc_public"
                    else:
                        p["raw_target"] = "file:///private" if damage == "external_scheme" else "https:///missing"
                else:
                    p.update(raw_target="", anchor_type="", anchor_value="")
                self.write_records(records)
                self.assert_verification_refused("publication", message)
        self.fresh_archive()
        records = self.envelopes()
        p = next(r["payload"] for r in records if r["type"] == "link")
        for field in ("target_document_id", "target_resource_id"):
            p.pop(field, None)
        p.update(resolution_status="resolved", raw_target="", anchor_type="heading", anchor_value="details",
                 target_uri=f"document://default/documents/{p['source_document_id']}")
        self.write_records(records)
        with self.verify():
            pass

    def test_blob_context_requires_authenticated_eof(self):
        with self.verify() as verified:
            ref = archive_v2.BlobRef(**next(verified.iter_records("revision")).payload["body"])
            with self.assertRaises(archive_v2.NotriosError) as caught:
                with verified.open_blob(ref) as stream:
                    stream.read(1)
            self.assertEqual(caught.exception.code, "integrity")
            self.assertIn("verified EOF", str(caught.exception))
            with verified.open_blob(ref) as stream:
                output = bytearray()
                buffer = bytearray(7)
                while n := stream.readinto(buffer):
                    output.extend(buffer[:n])
            self.assertEqual(hashlib.sha256(output).hexdigest(), ref.sha256)
            self.assertTrue(stream.closed)
            path = verified._spool.directory / f"objects/sha256/{ref.sha256[:2]}/{ref.sha256[2:4]}/{ref.sha256}"
            path.chmod(0o600)
            path.write_bytes(b"x" * ref.size_bytes)
            with self.assertRaises(archive_v2.NotriosError) as caught:
                with verified.open_blob(ref) as stream:
                    stream.read()
            self.assertEqual(caught.exception.code, "integrity")
            self.assertIn("bytes changed", str(caught.exception))

    def test_revision_ids_are_unique_across_owners(self):
        records = self.envelopes()
        revisions = [r["payload"] for r in records if r["type"] == "revision"]
        revisions[1]["id"] = revisions[0]["id"]
        self.write_records(records)
        self.assert_verification_refused("integrity", "duplicate record identity")

    def test_relation_keys_preserve_unrestricted_strings_and_ordinals(self):
        records = self.envelopes()
        relation = next(r for r in records if r["type"] == "document_resource")
        expected = []
        for text, ordinal in (("a", 0), ("a\x1f0", 0), ("a\x00b", 0), ("a", 10), ("a", 2)):
            item = copy.deepcopy(relation)
            item["payload"].update(relation_type=text, ordinal=ordinal)
            records.append(item)
            expected.append((relation["payload"]["document_id"], relation["payload"]["resource_id"], text, str(ordinal)))
        self.write_records(records)
        with self.verify() as verified:
            for key in expected:
                self.assertEqual(verified.get_record("document_resource", key).key, key)
            keys = [r.key for r in verified.iter_records("document_resource")]
            encode = lambda key: b"".join(len(p.encode()).to_bytes(4, "big") + p.encode() for p in key)
            self.assertEqual(keys, sorted(keys, key=encode))

    def test_empty_referenced_blob_and_exact_name_filename_limits(self):
        records = self.envelopes()
        resource = next(r["payload"] for r in records if r["type"] == "resource")
        old_hash = resource["blob"]["sha256"]
        entry = next(e for e in self.entries if e["sha256"] == old_hash)
        self.manifest["totals"]["bytes"] -= entry["size_bytes"]
        (self.archive / entry["location"]["path"]).unlink()
        digest, path = self.put_object(b"")
        entry.update(sha256=digest, size_bytes=0, location={"layout": "fanout", "path": path})
        resource["blob"].update(sha256=digest, size_bytes=0)
        resource["filename"] = "é" * 2048
        next(r["payload"] for r in records if r["type"] == "tag")["name"] = "é" * 2048
        self.write_records(records)
        with self.verify() as verified:
            with verified.open_blob(archive_v2.BlobRef(**resource["blob"])) as stream:
                self.assertEqual(stream.read(), b"")

    def test_forbidden_payload_schemas_are_recognized_but_never_admitted(self):
        # Nonzero counts refuse at manifest admission. Direct schema probes prove
        # these envelope types cannot accidentally become silent no-op records.
        timestamp = "2026-01-01T00:00:00Z"
        payloads = {
            "search_notebook": {"id": "search_test", "name": "Search", "query": "all", "builtin": False,
                                "sort_anchor": "normal", "created_at": timestamp},
            "provenance": {"document_id": "doc_public", "source_system": "test", "metadata_json": {},
                           "created_at": timestamp, "updated_at": timestamp},
            "source_bundle": {"source_system": "test", "source_key_sha256": "a" * 64, "collection_id": "default",
                              "item_key_sha256": "b" * 64, "item_type": "note", "relative_path": "note.md",
                              "content": {"sha256": "c" * 64, "size_bytes": 0, "media_type": "text/plain"},
                              "property_order_json": [], "updated_at": timestamp},
        }
        for kind, payload in payloads.items():
            with self.subTest(kind=kind):
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    archive_v2._typed_record(kind, payload, archive_v2.DEFAULT_LIMITS)
                self.assertEqual(caught.exception.code, "publication")
                self.assertIn("forbidden", str(caught.exception))
                malformed = dict(payload, unknown=True)
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    archive_v2._typed_record(kind, malformed, archive_v2.DEFAULT_LIMITS)
                self.assertEqual(caught.exception.code, "json")
                self.fresh_archive()
                records = self.envelopes() + [{"type": kind, "payload": payload}]
                self.write_records(records)
                self.assert_verification_refused("publication", "declares forbidden record types")

    def apply_audit_case(self, case):
        """Bounded synthetic fixtures shared with the development-only Go audit."""
        action = case["action"]
        if action == "none":
            return
        if action == "schema_bounds":
            self.manifest["compatibility"].update(case["value"])
            self.write_manifest()
            return
        if action == "blob_entry":
            next(e for e in self.entries if e["kind"] == "blob")[case["field"]] = copy.deepcopy(case["value"])
            self.write_index()
            return
        if action == "capability":
            self.manifest["compatibility"]["optional_capabilities"] = ["future.optional.v1"]
            self.write_manifest()
            return
        records = self.envelopes()
        def first(kind):
            return next(r["payload"] for r in records if r["type"] == kind)
        if action in ("set", "delete"):
            p = first(case["kind"])
            if case["kind"] == "link" and case["field"] == "target_resource_id":
                p.pop("target_document_id", None)
                p["resolution_status"] = "resolved"
            names = case["field"].split(".")
            for field in names[:-1]:
                p = p[field]
            if action == "delete":
                del p[names[-1]]
            else:
                p[names[-1]] = copy.deepcopy(case["value"])
        elif action == "reverse":
            records.reverse()
        elif action == "duplicate":
            records.append({"type": case["kind"], "payload": copy.deepcopy(first(case["kind"]))})
        elif action == "wrong_owner":
            docs = [r["payload"] for r in records if r["type"] == "document"]
            docs[0]["current_revision_id"] = docs[1]["current_revision_id"]
        elif action == "revision_collision":
            revisions = [r["payload"] for r in records if r["type"] == "revision"]
            revisions[1]["id"] = revisions[0]["id"]
            next(r["payload"] for r in records if r["type"] == "document" and
                 r["payload"]["id"] == revisions[1]["document_id"])["current_revision_id"] = revisions[0]["id"]
        elif action == "history":
            revision = copy.deepcopy(first("revision"))
            revision["id"] = "old_revision"
            records.append({"type": "revision", "payload": revision})
        elif action == "drop_relations":
            records = [r for r in records if r["type"] != "document_resource"]
        elif action == "unused_blob":
            revisions = [r["payload"] for r in records if r["type"] == "revision"]
            revisions[0]["body"] = copy.deepcopy(revisions[1]["body"])
        elif action == "cycle":
            nodes = [r["payload"] for r in records if r["type"] == "notebook"]
            nodes[0]["parent_id"], nodes[1]["parent_id"] = nodes[1]["id"], nodes[0]["id"]
        elif action in ("external_file", "two_targets"):
            p = first("link")
            p.pop("target_document_id", None)
            p.pop("target_resource_id", None)
            p.pop("target_uri", None)
            if action == "external_file":
                p.update(resolution_status="external", raw_target="file:///withheld")
            else:
                p.update(resolution_status="resolved", target_document_id="doc_public", target_resource_id="res_image")
        elif action == "forbidden":
            timestamp = "2026-01-01T00:00:00Z"
            payload = {
                "search_notebook": {"id": "search_test", "name": "Search", "query": "all", "builtin": False,
                                    "sort_anchor": "normal", "created_at": timestamp},
                "provenance": {"document_id": "doc_public", "source_system": "test", "metadata_json": {},
                               "created_at": timestamp, "updated_at": timestamp},
                "source_bundle": {"source_system": "test", "source_key_sha256": "a" * 64,
                                  "collection_id": first("collection")["id"], "item_key_sha256": "b" * 64,
                                  "item_type": "note", "relative_path": "note.md", "content": dict(first("revision")["body"]),
                                  "property_order_json": [], "updated_at": timestamp},
            }[case["kind"]]
            records.append({"type": case["kind"], "payload": payload})
        else:
            self.fail(f"unknown synthetic audit action: {action}")
        self.write_records(records)

    def test_frozen_differential_cases_without_go_dependency(self):
        cases = load_json(FIXTURE_ROOT / "verifier-audit-cases.json")
        report = load_json(FIXTURE_ROOT / "verifier-audit.json")
        generation = load_json(PUBLICATION_ROOT / "generation.json")
        for field in ("producer_commit", "cli_sha256"):
            self.assertEqual(report[field], generation[field])
        self.assertEqual(report["case_spec_sha256"], hashlib.sha256((FIXTURE_ROOT / "verifier-audit-cases.json").read_bytes()).hexdigest())
        self.assertEqual([r["name"] for r in report["results"]], [c["name"] for c in cases])
        for case, result in zip(cases, report["results"]):
            self.assertTrue(result["matched"])
            self.assertEqual(result["go_accepted"], case["expect_go"])
            self.assertEqual(result["python_result"], case["expect_python"])
        for case in cases:
            with self.subTest(case=case["name"]):
                self.fresh_archive()
                self.apply_audit_case(case)
                if case["expect_python"] == "accepted":
                    with self.verify():
                        pass
                    self.assertEqual(list(self.work.iterdir()), [])
                else:
                    self.assert_verification_refused(case["expect_python"], case["message"])

    def test_source_mutation_and_removal_after_verification_are_isolated(self):
        with self.verify() as verified:
            revision = next(verified.iter_records("revision"))
            ref = archive_v2.BlobRef(**revision.payload["body"])
            path = f"objects/sha256/{ref.sha256[:2]}/{ref.sha256[2:4]}/{ref.sha256}"
            (self.archive / path).write_bytes(b"x" * ref.size_bytes)
            self.archive.rename(self.root / "source-moved")
            with verified.open_blob(ref) as stream:
                self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), ref.sha256)
            self.assertEqual(verified.get_record("revision", revision.key), revision)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_private_blob_mutations_refuse_at_consumption(self):
        for damage, code in (("missing", "io"), ("truncate", "integrity"), ("append", "integrity"),
                             ("corrupt", "integrity"), ("symlink", "io"), ("parent_symlink", "io"), ("fifo", "path")):
            with self.subTest(damage=damage):
                self.fresh_archive()
                with self.verify() as verified:
                    ref = archive_v2.BlobRef(**next(verified.iter_records("revision")).payload["body"])
                    path = verified._spool.directory / f"objects/sha256/{ref.sha256[:2]}/{ref.sha256[2:4]}/{ref.sha256}"
                    if damage == "parent_symlink":
                        parent = path.parent
                        renamed = parent.with_name(parent.name + "-moved")
                        parent.rename(renamed)
                        parent.symlink_to(renamed, target_is_directory=True)
                    elif damage in ("missing", "symlink", "fifo"):
                        path.unlink()
                        if damage == "symlink":
                            path.symlink_to(self.archive / path.relative_to(verified._spool.directory))
                        elif damage == "fifo":
                            os.mkfifo(path)
                    else:
                        path.chmod(0o600)
                        original = path.read_bytes()
                        path.write_bytes(original[:-1] if damage == "truncate" else
                                         original + b"x" if damage == "append" else b"x" * len(original))
                    with self.assertRaises(archive_v2.NotriosError) as caught:
                        with verified.open_blob(ref) as stream:
                            stream.read()
                    self.assertEqual(caught.exception.code, code)
                self.assertEqual(list(self.work.iterdir()), [])

    def test_blob_read_fault_and_repeated_use_never_reuse_validation(self):
        with self.verify() as verified:
            ref = archive_v2.BlobRef(**next(verified.iter_records("revision")).payload["body"])
            with self.assertRaises(archive_v2.NotriosError) as caught:
                with verified.open_blob(ref) as stream:
                    stream.read()
                    with mock.patch.object(stream._stream, "read", side_effect=OSError("PRIVATE-SENTINEL")):
                        with self.assertRaises(archive_v2.NotriosError) as read_error:
                            stream.read(1)
                        self.assertEqual(read_error.exception.code, "io")
                        self.assertNotIn("PRIVATE-SENTINEL", str(read_error.exception))
            self.assertEqual(caught.exception.code, "integrity")
            self.assertIn("failed", str(caught.exception))
            with verified.open_blob(ref) as stream:
                self.assertEqual(len(stream.read()), ref.size_bytes)
            path = verified._spool.directory / f"objects/sha256/{ref.sha256[:2]}/{ref.sha256[2:4]}/{ref.sha256}"
            path.chmod(0o600)
            path.write_bytes(b"x" * ref.size_bytes)
            with self.assertRaises(archive_v2.NotriosError) as caught:
                with verified.open_blob(ref) as stream:
                    stream.read()
            self.assertEqual(caught.exception.code, "integrity")
            self.assertIn("bytes changed", str(caught.exception))

    def test_large_body_is_verified_and_consumed_in_bounded_chunks(self):
        # This exceeds the frozen 16 MiB conversion-body limit; generic archive
        # verification still admits it. Conversion preflight belongs to 3b.
        records = self.envelopes()
        revision = next(r["payload"] for r in records if r["type"] == "revision")
        entry = next(e for e in self.entries if e["sha256"] == revision["body"]["sha256"])
        old_size = entry["size_bytes"]
        (self.archive / entry["location"]["path"]).unlink()
        large = b"x" * (17 * 1024 * 1024)
        digest, relative = self.put_object(large)
        entry.update(sha256=digest, size_bytes=len(large), location={"layout": "fanout", "path": relative})
        revision["body"].update(sha256=digest, size_bytes=len(large))
        self.manifest["totals"]["bytes"] += len(large) - old_size
        self.write_records(records)
        del large
        original_open = archive_v2._open_regular_file
        sizes = []
        class TrackedReader:
            def __init__(self, stream):
                self.stream = stream
            def read(self, size=-1):
                sizes.append(size)
                return self.stream.read(size)
            def __getattr__(self, name):
                return getattr(self.stream, name)
        @contextmanager
        def tracked_open(root_fd, path):
            with original_open(root_fd, path) as stream:
                yield TrackedReader(stream) if path == relative else stream
        with mock.patch.object(archive_v2, "_open_regular_file", tracked_open):
            with self.verify() as verified:
                with verified.open_blob(archive_v2.BlobRef(**revision["body"])) as stream:
                    consumed = 0
                    buffer = bytearray(65536)
                    while amount := stream.readinto(buffer):
                        consumed += amount
        self.assertEqual(consumed, 17 * 1024 * 1024)
        self.assertTrue(sizes)
        self.assertTrue(all(0 < size <= 1048576 for size in sizes), sizes)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_blob_failed_read_cannot_be_caught_and_committed(self):
        with self.verify() as verified:
            ref = archive_v2.BlobRef(**next(verified.iter_records("revision")).payload["body"])
            path = verified._spool.directory / f"objects/sha256/{ref.sha256[:2]}/{ref.sha256[2:4]}/{ref.sha256}"
            with self.assertRaises(archive_v2.NotriosError) as caught:
                with verified.open_blob(ref) as stream:
                    stream.read()
                    path.chmod(0o600)
                    with path.open("ab") as changed:
                        changed.write(b"x")
                    with self.assertRaises(archive_v2.NotriosError):
                        stream.read(1)
            self.assertEqual(caught.exception.code, "integrity")
            self.assertIn("failed", str(caught.exception))

    def test_archive_exit_closes_outstanding_blob_handles(self):
        with self.verify() as verified:
            ref = archive_v2.BlobRef(**next(verified.iter_records("revision")).payload["body"])
            private_root = str(verified._spool.directory)
            context = verified.open_blob(ref)
            stream = context.__enter__()
            stream.read()
        self.assertTrue(stream.closed)
        if Path("/proc/self/fd").exists():
            retained = []
            for fd in Path("/proc/self/fd").iterdir():
                try:
                    target = os.readlink(fd)
                except FileNotFoundError:
                    continue
                if target.startswith(private_root):
                    retained.append(target)
            self.assertEqual(retained, [], "archive-owned OS handles outlived the context")
        with self.assertRaises(archive_v2.NotriosError) as caught:
            stream.read(1)
        self.assertEqual(caught.exception.code, "io")
        with self.assertRaises(archive_v2.NotriosError):
            context.__exit__(None, None, None)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_semantic_mime_go_vectors(self):
        vectors = load_json(FIXTURE_ROOT / "semantic-mime-vectors.json")
        self.assertGreaterEqual(len(vectors), 50)
        for case in vectors:
            with self.subTest(mime=case["input"]):
                if case["accepted"]:
                    self.assertEqual(archive_v2._normalize_mime(case["input"]), case["normalized"])
                else:
                    with self.assertRaises(archive_v2.NotriosError) as caught:
                        archive_v2._normalize_mime(case["input"])
                    self.assertEqual(caught.exception.code, "format")

    def test_storage_mime_matches_go_syntax_vectors(self):
        vectors = load_json(FIXTURE_ROOT / "storage-mime-vectors.json")
        self.assertEqual(len(vectors), 22)
        for case in vectors:
            with self.subTest(mime=case["input"]):
                if case["accepted"]:
                    archive_v2._validate_storage_mime(case["input"])
                else:
                    with self.assertRaises(archive_v2.NotriosError) as caught:
                        archive_v2._validate_storage_mime(case["input"])
                    self.assertEqual(caught.exception.code, "format")


class NotriosMappingTest(unittest.TestCase):
    def setUp(self):
        self.vectors = load_json(FIXTURE_ROOT / "design-v1.json")
        self.manifest, _, self.records = read_fixture_records(PUBLICATION_ARCHIVE)
        self.database_id = self.vectors["fixture_database_id"]

    def record(self, kind, index=0, **updates):
        payload = copy.deepcopy(self.records[kind][index])
        payload.update(updates)
        return archive_v2.Record(kind, (payload["id"],), payload)

    def ident(self, kind, *parts):
        return mapping.mapped_id(self.database_id, kind, tuple(parts))

    def fixture_rows(self):
        rows = []
        for p in self.records["notebook"]:
            record = archive_v2.Record("notebook", (p["id"],), p)
            parent = self.ident("notebook", p["parent_id"]) if p.get("parent_id") else ""
            rows.append(mapping.build_notebook_row(record, item_id=self.ident("notebook", p["id"]), parent_id=parent))
        for p in self.records["document"]:
            r = next(r for r in self.records["revision"] if r["id"] == p["current_revision_id"])
            rows.append(mapping.build_note_row(archive_v2.Record("document", (p["id"],), p),
                        archive_v2.Record("revision", (r["id"],), r), item_id=self.ident("document", p["id"]),
                        parent_id=self.ident("notebook", p["notebook_id"]),
                        body=self.vectors["fixture_projected_notes"][p["id"]]["body"]))
        for p in self.records["tag"]:
            rows.append(mapping.build_tag_row(archive_v2.Record("tag", (p["id"],), p), item_id=self.ident("tag", p["id"])))
        for p in self.records["document_tag"]:
            doc = next(d for d in self.records["document"] if d["id"] == p["document_id"])
            rows.append(mapping.build_note_tag_row(item_id=self.ident("document_tag", p["document_id"], p["tag_id"]),
                        note_id=self.ident("document", p["document_id"]), tag_id=self.ident("tag", p["tag_id"]),
                        timestamp=doc["created_at"]))
        for p in self.records["resource"]:
            mime = p["blob"]["media_type"]
            rows.append(mapping.build_resource_row(archive_v2.Record("resource", (p["id"],), p),
                        item_id=self.ident("resource", p["id"]), mime=mime, extension=mapping.resource_extension(mime)))
        return rows

    def test_all_frozen_identity_and_fixture_vectors(self):
        for vector in self.vectors["id_vectors"]:
            with self.subTest(vector=vector["mapped_id"]):
                args = vector["database_id"], vector["kind"], tuple(vector["parts"])
                key = mapping.source_key(*args)
                self.assertEqual(key.hex(), vector["source_key_hex"])
                self.assertEqual(hashlib.sha256(key).hexdigest(), vector["sha256"])
                self.assertEqual(mapping.mapped_id(*args), vector["mapped_id"])
        for kind, ids in self.vectors["fixture_ids"].items():
            for source, expected in ids.items():
                self.assertEqual(self.ident(kind, source), expected)

    def test_invalid_keys_refuse_before_hashing(self):
        for args in (("db", "unknown", ("item",)), ("db", "tag", ()), ("db", "tag", ["item"]),
                     (None, "tag", ("item",)), ("db", "tag", (True,)), ("db", "tag", ("\ud800",)),
                     ("db", "document_tag", ("a", "b", "c"))):
            with self.subTest(args=args), mock.patch.object(mapping.hashlib, "sha256") as digest:
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    mapping.mapped_id(*args)
                self.assertEqual(caught.exception.code, "conversion")
                digest.assert_not_called()
        for ordinal in ("-1", "+1", "01", "1.0", "1e0", "", str(1 << 63)):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(archive_v2.NotriosError):
                    mapping.source_key("db", "document_resource", ("doc", "res", "attachment", ordinal))
        with mock.patch.object(mapping, "_MAX_COMPONENT_BYTES", 32):
            mapping.source_key("db", "tag", ("é" * 16,))
            with self.assertRaises(archive_v2.NotriosError) as caught:
                mapping.source_key("db", "tag", ("é" * 17,))
            self.assertIn("oversized", str(caught.exception))

    def test_identity_ignores_mutable_fields_and_retains_full_collision_key(self):
        record = self.record("document")
        original = self.ident("document", record.payload["id"])
        changed = dict(record.payload, current_revision_id="revision_new", notebook_id="notebook_new",
                       collection_id="collection_new", updated_at="2030-01-01T00:00:00Z", title="New title",
                       snapshot_id="snapshot_new", source_replica_id="replica_new", output_path="other.md")
        self.assertEqual(original, self.ident("document", changed["id"]))
        self.assertNotEqual(original, mapping.mapped_id("db_other", "document", record.key))
        with mock.patch.object(mapping.hashlib, "sha256") as digest:
            digest.return_value.hexdigest.return_value = "0" * 64
            first = mapping.mapped_id("db", "document", ("first",))
            second = mapping.mapped_id("db", "document", ("second",))
        self.assertEqual(first, second)
        self.assertNotEqual(mapping.source_key("db", "document", ("first",)),
                            mapping.source_key("db", "document", ("second",)))
        # 3b must register these full keys and refuse this injected collision.

    def test_timestamp_flooring_and_sqlite_datetime(self):
        for vector in self.vectors["timestamp_vectors"]:
            self.assertEqual(mapping.joplin_timestamp(vector["source"]), vector["joplin"])
        for source, expected in (("0000-02-29T00:00:00Z", "0000-02-29T00:00:00.000Z"),
                                 ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000Z"),
                                 ("9999-12-31T23:59:59.999999999-00:00", "9999-12-31T23:59:59.999Z"),
                                 ("2000-02-29T00:00:00.000999999+00:00", "2000-02-29T00:00:00.000Z"),
                                 ("2026-01-01T00:00:00.1Z", "2026-01-01T00:00:00.100Z")):
            self.assertEqual(mapping.joplin_timestamp(source), expected)
        for source in ("1900-02-29T00:00:00Z", "2026-01-01T00:00:00+01:00", "bad", None):
            with self.subTest(source=source):
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    mapping.joplin_timestamp(source)
                self.assertEqual(caught.exception.code, "conversion")
        with sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES) as db:
            db.row_factory = sqlite3.Row
            with mock.patch("sys.stdout", new=io.StringIO()):
                notesdb.create_database(db)
            rows = self.fixture_rows()
            rows.append(mapping.build_tag_row(self.record("tag", created_at="0000-02-29T00:00:00Z"), item_id="d" * 32))
            notesdb.add_joplin_notes(db, rows)
            saved = db.execute("SELECT * FROM notes ORDER BY note_id").fetchall()
            self.assertEqual(len(saved), len(rows))
            for row, source in zip(saved, rows):
                # This schema uses DATETIME, not the stdlib TIMESTAMP converter.
                self.assertEqual(row["note_internal_date"], source["note_internal_date"])
                self.assertEqual(notesdb.joplin_property_pairs(row), mapping.generated_properties(source))
                self.assertEqual(notesdb.serialize_joplin_item(row), notesdb.serialize_joplin_item(source))

    def test_complete_columns_aliases_property_order_and_privacy(self):
        common_keys = "created_time updated_time user_created_time user_updated_time encryption_cipher_text encryption_applied".split()
        specific = {
            1: "is_conflict latitude longitude altitude author source_url is_todo todo_due todo_completed source source_application application_data order markup_language is_shared".split(),
            2: ["is_shared", "application_data"],
            4: "mime filename file_extension size is_shared application_data".split(),
            5: [], 6: ["note_id", "tag_id"],
        }
        generic = {"note_type", "note_uuid", "note_parent_uuid", "note_note_uuid", "note_tag_uuid",
                   "note_original_format", "note_internal_date", "note_hash", "note_title", "note_data",
                   "note_data_format", "note_source_properties"}
        for row in self.fixture_rows():
            with self.subTest(id=row["note_uuid"]):
                kind = row["joplin_type_"]
                props = mapping.generated_properties(row)
                keys = ["id"] + (["parent_id"] if kind in (1, 2) else []) + common_keys + specific[kind] + ["user_data", "type_"]
                self.assertEqual([k for k, v in props], keys)
                self.assertTrue(all(type(k) is str and type(v) is str for k, v in props))
                self.assertEqual(row["note_source_properties"], json.dumps(props, ensure_ascii=False, separators=(",", ":")))
                self.assertEqual(set(row), set(notesdb.NOTE_COLUMNS) | set(notesdb.JOPLIN_COLUMNS))
                self.assertNotIn("note_id", row)
                for column in set(row) - generic - {"joplin_" + k for k in keys}:
                    self.assertIsNone(row[column], column)
                for name in ("id", "parent_id", "note_id", "tag_id"):
                    alias = {"id": "note_uuid", "parent_id": "note_parent_uuid", "note_id": "note_note_uuid", "tag_id": "note_tag_uuid"}[name]
                    self.assertEqual(row[alias], row["joplin_" + name])
                self.assertEqual(row["note_type"], {1: "note", 2: "folder", 4: "resource", 5: "tag", 6: ""}[kind])
                self.assertEqual(row["note_original_format"], "notrios")
                self.assertEqual(row["note_data_format"], "text/markdown")
                self.assertEqual(row["note_hash"], hashlib.sha512(row["note_data"].encode()).hexdigest())
                for key, value in props:
                    column = "joplin_" + key
                    column_type = notesdb.JOPLIN_COLUMNS[column]
                    expected = int(value) if column_type == "INTEGER" else float(value) if column_type in ("FLOAT", "REAL") else value
                    self.assertEqual(row[column], expected)
                    self.assertIs(type(row[column]), type(expected))
                self.assertEqual(dict(props)["encryption_applied"], "0")
                self.assertEqual(dict(props)["user_data"], "")
                if kind == 1:
                    self.assertEqual(dict(props)["latitude"], "0.00000000")
                    self.assertEqual(dict(props)["altitude"], "0.0000")
                    self.assertEqual(row["joplin_source_application"], "movenotes-notrios2sql")

    def test_empty_unicode_titles_and_document_times_are_preserved(self):
        document = self.record("document", created_at="2026-01-01T01:02:03.123999999Z", updated_at="2026-02-01T02:03:04Z")
        source = next(r for r in self.records["revision"] if r["id"] == document.payload["current_revision_id"])
        for title in ("", "Café 東京", "  Original title  "):
            revision = archive_v2.Record("revision", (source["id"],), dict(source, title=title, created_at="2025-01-01T00:00:00Z", message="PRIVATE-SENTINEL"))
            row = mapping.build_note_row(document, revision, item_id="a" * 32, parent_id="b" * 32, body="body\r\n  \n")
            self.assertEqual(row["note_title"], title)
            self.assertEqual(row["note_data"], "body\r\n  \n")
            self.assertEqual(row["joplin_created_time"], "2026-01-01T01:02:03.123Z")
            self.assertEqual(row["joplin_updated_time"], "2026-02-01T02:03:04.000Z")
            self.assertEqual(row["note_internal_date"], "2026-01-01 01:02:03.123")
            self.assertNotIn("PRIVATE-SENTINEL", json.dumps(row))

    def test_resource_display_names_storage_extensions_and_metadata(self):
        for resource_id, extension in self.vectors["resource_extensions"].items():
            resource = next(r for r in self.records["resource"] if r["id"] == resource_id)
            self.assertEqual(mapping.resource_extension(resource["blob"]["media_type"]), extension)
        for name, expected in (("C:\\private\\café.exe", "café.exe"), ("/private/東京.png", "東京.png"),
                               ("/private/ \x00café\x7f.txt ", "café.txt"), ("..", "attachment.png"),
                               ("", "attachment.png"), ("a/.", "attachment.png"), ("a/", "attachment.png")):
            record = self.record("resource", filename=name, metadata_json={"private": "PRIVATE-SENTINEL"},
                                 unreferenced_reason="PRIVATE-SENTINEL")
            p = dict(record.payload, blob=dict(record.payload["blob"], media_type="image/png"))
            row = mapping.build_resource_row(archive_v2.Record("resource", record.key, p), item_id="c" * 32, mime="image/png", extension="png")
            self.assertEqual((row["note_title"], row["note_data"], row["joplin_filename"]), (expected,) * 3)
            self.assertEqual(row["joplin_file_extension"], "png")
            self.assertEqual(row["joplin_size"], p["blob"]["size_bytes"])
            self.assertNotIn("PRIVATE-SENTINEL", json.dumps(row))
        self.assertEqual(mapping.resource_extension("text/plain; charset=utf-8"), "txt")
        self.assertEqual(mapping.resource_extension("application/x-unknown"), "bin")

    def test_container_and_membership_projection_defaults(self):
        notebook = self.record("notebook", name="  研究  ", created_at="2026-01-01T00:00:00Z",
                               updated_at="2026-02-01T00:00:00Z", position=123, builtin=True, icon_emoji="PRIVATE-SENTINEL")
        folder = mapping.build_notebook_row(notebook, item_id="a" * 32, parent_id="")
        self.assertEqual(folder["note_title"], "  研究  ")
        self.assertEqual(folder["note_data"], "  研究  ")
        self.assertEqual((folder["note_parent_uuid"], folder["joplin_parent_id"]), ("", ""))
        self.assertEqual(folder["joplin_created_time"], "2026-01-01T00:00:00.000Z")
        self.assertEqual(folder["joplin_updated_time"], "2026-02-01T00:00:00.000Z")
        self.assertIsNone(folder["joplin_order"])
        self.assertIsNone(folder["joplin_icon"])
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(folder))
        tag = mapping.build_tag_row(self.record("tag", name="café", created_at="2026-03-01T00:00:00Z"), item_id="b" * 32)
        self.assertEqual((tag["note_title"], tag["note_data"]), ("café", "café"))
        self.assertIsNone(tag["note_parent_uuid"])
        self.assertEqual(tag["joplin_updated_time"], "2026-03-01T00:00:00.000Z")
        membership = mapping.build_note_tag_row(item_id="c" * 32, note_id="d" * 32, tag_id="b" * 32,
                                                timestamp="2026-04-01T00:00:00Z")
        self.assertEqual((membership["note_title"], membership["note_data"], membership["note_type"]), ("", "", ""))
        self.assertEqual(membership["note_note_uuid"], "d" * 32)
        self.assertEqual(membership["note_tag_uuid"], "b" * 32)
        self.assertEqual(membership["joplin_updated_time"], "2026-04-01T00:00:00.000Z")
        expected_extensions = "image/png:png image/jpeg:jpg image/gif:gif image/webp:webp image/svg+xml:svg image/avif:avif image/bmp:bmp image/tiff:tif image/x-icon:ico text/plain:txt text/markdown:md text/csv:csv application/pdf:pdf application/json:json application/zip:zip audio/mpeg:mp3 audio/ogg:ogg audio/wav:wav video/mp4:mp4 video/webm:webm"
        for entry in expected_extensions.split():
            mime, expected = entry.split(":")
            self.assertEqual(mapping.resource_extension(mime), expected)

    def test_wrong_builder_inputs_refuse(self):
        for ident in (None, "bad", "A" * 32):
            with self.assertRaises(archive_v2.NotriosError):
                mapping.build_tag_row(self.record("tag"), item_id=ident)
        with self.assertRaises(archive_v2.NotriosError):
            mapping.build_notebook_row(self.record("notebook"), item_id="a" * 32, parent_id=None)
        with self.assertRaises(archive_v2.NotriosError):
            mapping.build_tag_row(self.record("notebook"), item_id="a" * 32)
        with self.assertRaises(archive_v2.NotriosError):
            mapping.build_resource_row(self.record("resource"), item_id="a" * 32, mime="image/png", extension="exe")
        doc = self.record("document")
        rev = self.record("revision", document_id="other_document")
        with self.assertRaises(archive_v2.NotriosError):
            mapping.build_note_row(doc, rev, item_id="a" * 32, parent_id="b" * 32, body="")


def make_text_publication(fixture, bodies=None):
    """Replace only an owned synthetic archive with a relation-free text case.

    bodies is one byte string for all notes, or a document-ID-to-bytes mapping.
    The original committed publication and its frozen vectors are never edited.
    """
    f = fixture
    records = [r for r in f.envelopes() if r["type"] in ("collection", "notebook", "document", "revision")]
    for entry in f.entries:
        if entry["kind"] == "blob":
            (f.archive / entry["location"]["path"]).unlink()
    f.entries = [e for e in f.entries if e["kind"] == "records"]
    for number, record in enumerate(r for r in records if r["type"] == "revision"):
        raw = bodies[record["payload"]["document_id"]] if isinstance(bodies, dict) else bodies
        if raw is None:
            raw = f"# Retained heading {number}\n\nPlain Unicode café 日本語.\n".encode()
        digest, relative = f.put_object(raw)
        record["payload"]["body"] = dict(sha256=digest, size_bytes=len(raw), media_type="text/markdown")
        record["payload"]["body_mime_type"] = "text/markdown"
        if not any(e["sha256"] == digest for e in f.entries):
            f.entries.append(dict(sha256=digest, kind="blob", size_bytes=len(raw), media_type="text/markdown",
                                  location=dict(layout="fanout", path=relative)))
    f.manifest["totals"].update(objects=len(f.entries), blobs=len(f.entries)-1,
                                  bytes=sum(e["size_bytes"] for e in f.entries))
    f.write_records(records)


class NotriosPublicationLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.fixture = NotriosObjectSpoolTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.destination = self.root / "published"
        self.make_text_archive()

    def make_text_archive(self, body=None):
        make_text_publication(self.fixture, body)

    def run_import(self, **kwargs):
        return importer.import_publication(self.fixture.archive, self.destination, **kwargs)

    def assert_clean(self):
        self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))

    def test_create_and_verified_unchanged_preserve_source_and_payload(self):
        before = fixture_inventory(self.fixture.archive)
        result = self.run_import()
        self.assertEqual((result.status, result.row_count, result.resource_count), ("created", 5, 0))
        payload = fixture_inventory(self.destination)
        self.assertEqual(set(payload), {"notesdb.sqlite", importer.INVENTORY, importer.COMPLETE})
        self.assertTrue((self.destination / "resources").is_dir())
        marker = load_json(self.destination / importer.COMPLETE)
        self.assertEqual(set(marker["receipt"]), {"version", "contract", "contract_schema_version", "reader_profile", "mapper",
                         "commit_sha256", "selection_manifest_sha256", "snapshot_id", "database_id", "target"})
        with sqlite3.connect(self.destination / "notesdb.sqlite") as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(connection.execute("SELECT count(*) FROM notrios_ids").fetchone()[0], 9)
            self.assertEqual(connection.execute("SELECT count(*) FROM notrios_document_resources").fetchone()[0], 0)
        created_summary = result.summary()
        result = self.run_import(expected_selection_sha256=result.selection_manifest_sha256)
        self.assertEqual(result.status, "unchanged")
        self.assertEqual(result.summary(), dict(created_summary, status="unchanged"))
        self.assertEqual(fixture_inventory(self.destination), payload)
        self.assertEqual(fixture_inventory(self.fixture.archive), before)
        self.assert_clean()

    def test_faults_never_publish_partial_output(self):
        for target in ("_preflight", "_build_payload", "_finalize_database", "_complete", "_rename_noreplace"):
            with self.subTest(target=target), mock.patch.object(importer, target, side_effect=OSError("injected failure")):
                with self.assertRaises(archive_v2.NotriosError):
                    self.run_import()
            self.assertFalse(self.destination.exists())
            self.assert_clean()
        with mock.patch.object(notesdb, "add_joplin_notes", side_effect=sqlite3.OperationalError("insertion failed")):
            with self.assertRaises(archive_v2.NotriosError):
                self.run_import()
        self.assertFalse(self.destination.exists())
        self.assert_clean()

    def test_pre_rename_failure_has_no_success_receipt(self):
        # _complete seals a receipt in the private stage before publication;
        # a failed rename must clean that stage without exposing a success
        # receipt or result tree.
        with mock.patch.object(importer, "_rename_noreplace", side_effect=OSError("injected rename failure")):
            with self.assertRaises(archive_v2.NotriosError):
                self.run_import()
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.rglob(importer.COMPLETE)), [])
        self.assert_clean()

    def test_fsync_faults_before_and_after_rename(self):
        real_sync = os.fsync
        for phase in ("payload", "inventory", "marker", "parent"):
            def fail(fd):
                path = os.readlink(f"/proc/self/fd/{fd}")
                suffix = {"payload": "notesdb.sqlite", "inventory": importer.INVENTORY, "marker": importer.COMPLETE}[phase] if phase != "parent" else None
                if (suffix and path.endswith(suffix)) or (phase == "parent" and path == str(self.root)):
                    raise OSError("injected fsync failure")
                return real_sync(fd)
            with self.subTest(phase=phase), mock.patch.object(importer.os, "fsync", fail):
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    self.run_import()
            self.assertEqual(self.destination.exists(), phase == "parent")
            if phase == "parent":
                self.assertIn("durability", str(caught.exception))
                self.assertEqual(self.run_import().status, "unchanged")
            self.assert_clean()

    def test_collision_refuses_distinct_full_keys(self):
        with mock.patch.object(mapping, "mapped_id", return_value="a" * 32):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
        self.assertEqual(caught.exception.code, "collision")
        self.assertFalse(self.destination.exists())
        self.assert_clean()

    def test_interrupted_resource_write_and_bounded_hashing(self):
        build = importer._build_payload
        def interrupted(*args):
            build(*args)
            with (args[1] / "resources" / ("a" * 32 + ".bin")).open("wb") as stream:
                stream.write(b"partial copy")
                raise OSError("resource copy interrupted")
        with mock.patch.object(importer, "_build_payload", interrupted):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
        self.assertIn("resource copy interrupted", str(caught.exception))
        self.assertFalse(self.destination.exists())
        self.assert_clean()
        self.run_import(conversion_limits=ConversionLimits(copy_chunk_bytes=7, batch_rows=1, batch_bytes=1))
        reads = []
        opening = archive_v2._open_regular_file
        class Reader:
            def __init__(self, stream):
                self.stream = stream
            def read(self, size=-1):
                reads.append(size)
                return self.stream.read(size)
            def __getattr__(self, name):
                return getattr(self.stream, name)
        @contextmanager
        def tracked(fd, name):
            with opening(fd, name) as stream:
                yield Reader(stream) if name == "notesdb.sqlite" else stream
        with mock.patch.object(archive_v2, "_open_regular_file", tracked):
            self.assertEqual(self.run_import(conversion_limits=ConversionLimits(copy_chunk_bytes=7)).status, "unchanged")
        self.assertTrue(reads)
        self.assertEqual(set(reads), {7})

    def test_unrelated_output_and_empty_directory_race_are_untouched(self):
        self.destination.mkdir()
        with self.assertRaises(archive_v2.NotriosError):
            self.run_import()
        self.assertEqual(list(self.destination.iterdir()), [])
        self.destination.rmdir()
        rename = importer._rename_noreplace
        def race(parent, source, destination):
            self.destination.mkdir()
            return rename(parent, source, destination)
        with mock.patch.object(importer, "_rename_noreplace", race):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
        self.assertEqual(caught.exception.code, "destination")
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assert_clean()

    def test_second_writer_and_stale_lock_are_never_stolen(self):
        original = importer._preflight
        def second_writer(archive, limits):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
            self.assertIn("lock exists", str(caught.exception))
            original(archive, limits)
        with mock.patch.object(importer, "_preflight", second_writer):
            self.run_import()
        lock = self.root / (".movenotes-notrios-lock-" + hashlib.sha256(self.destination.name.encode()).hexdigest())
        lock.mkdir()
        (lock / importer.OWNER).write_text('{"pid":99999999,"token":"stale"}')
        before = fixture_inventory(lock)
        with self.assertRaises(archive_v2.NotriosError):
            self.run_import()
        self.assertEqual(fixture_inventory(lock), before)

    def test_edited_completed_outputs_refuse_without_writes(self):
        for change in ("database", "receipt", "extra", "symlink", "resource", "inventory", "marker"):
            self.destination = self.root / change
            # Synthetic resource isolates lifecycle inventory on the text fixture;
            # full archive resources have separate projection and safety tests.
            build = importer._build_payload
            def with_resource(*args):
                result = build(*args)
                (args[1] / "resources" / ("a" * 32 + ".bin")).write_bytes(b"payload")
                return result
            with mock.patch.object(importer, "_build_payload", with_resource):
                self.run_import()
            if change == "database":
                with (self.destination / "notesdb.sqlite").open("ab") as stream:
                    stream.write(b"changed")
            elif change == "receipt":
                with sqlite3.connect(self.destination / "notesdb.sqlite") as database:
                    database.execute("UPDATE settings SET value='{}' WHERE name=?", (importer.RECEIPT_KEY,))
                # Re-seal so the independent SQLite receipt comparison is tested.
                (self.destination / importer.COMPLETE).unlink()
                (self.destination / importer.INVENTORY).unlink()
                with archive_v2._open_root_directory(self.destination) as fd:
                    importer._complete(fd, self.fixture.work, importer._receipt(archive_v2.Manifest.from_dict(self.fixture.manifest)), ConversionLimits())
            elif change == "extra":
                (self.destination / "notesdb.sqlite-wal").write_bytes(b"")
            elif change == "symlink":
                (self.destination / "resources" / ("a" * 32 + ".bin")).unlink()
                (self.destination / "resources" / ("a" * 32 + ".bin")).symlink_to(self.fixture.archive / "manifest.json")
            elif change == "resource":
                (self.destination / "resources" / ("a" * 32 + ".bin")).write_bytes(b"changed")
            else:
                (self.destination / (importer.INVENTORY if change == "inventory" else importer.COMPLETE)).write_bytes(b"{}\n")
            before = fixture_inventory(self.destination) if change != "symlink" else None
            with self.subTest(change=change), self.assertRaises(archive_v2.NotriosError):
                self.run_import()
            if before is not None:
                self.assertEqual(fixture_inventory(self.destination), before)
            self.assert_clean()

    def test_selection_and_source_are_checked_on_rerun(self):
        self.run_import()
        before = fixture_inventory(self.destination)
        for value in ("bad", "A" * 64, "0" * 64, False):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import(expected_selection_sha256=value)
            self.assertEqual(caught.exception.code, "selection")
        (self.fixture.archive / "manifest.json").write_bytes(b"{}")
        with self.assertRaises(archive_v2.NotriosError):
            self.run_import()
        self.assertEqual(fixture_inventory(self.destination), before)
        self.assert_clean()

    def test_conversion_bounds_and_unsupported_bodies_refuse(self):
        for field in fields(ConversionLimits):
            for value in (0, False, field.default + 1):
                with self.assertRaises(archive_v2.NotriosError):
                    ConversionLimits(**{field.name: value})
        with self.assertRaises(archive_v2.NotriosError) as caught:
            self.run_import(conversion_limits=ConversionLimits(max_body_bytes=1))
        self.assertEqual(caught.exception.code, "limit")
        for body in (b"[unrecorded](document://id)", b"\xef\xbb\xbftext", b"\x00", b"\xff"):
            self.make_text_archive(body)
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
            self.assertEqual(caught.exception.code, "conversion")
        self.assertFalse(self.destination.exists())
        self.assert_clean()

    def test_batch_limits_flush_before_oversized_single_row(self):
        batches = []
        with mock.patch.object(notesdb, "add_joplin_notes", side_effect=lambda c, rows: batches.append(list(rows))):
            batch = importer._RowBatch(None, ConversionLimits(batch_rows=2, batch_bytes=6))
            for value in ("é", "é", "é", "123456789", "x", "x"):
                batch.add({"body": value})
            batch.flush()
        self.assertEqual([len(rows) for rows in batches], [2, 1, 1, 2])
        self.assertEqual(batches[2], [{"body": "123456789"}])

    def test_owned_cleanup_does_not_hide_original_or_remove_changed_token(self):
        def fault(*args):
            stage = next(self.root.glob(".movenotes-notrios-stage-*"))
            (stage / importer.OWNER).write_text('{"token":"someone-else"}')
            raise OSError("original insertion error")
        with mock.patch.object(importer, "_build_payload", fault):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
        self.assertIn("original insertion error", str(caught.exception))
        self.assertIn("cleanup", " ".join(caught.exception.__notes__))
        self.assertEqual(len(list(self.root.glob(".movenotes-notrios-stage-*"))), 1)
        self.assertFalse(self.destination.exists())

    def test_overlap_and_symlink_paths_refuse_before_staging(self):
        for destination in (self.fixture.archive / "inside", self.root):
            with self.assertRaises(archive_v2.NotriosError):
                importer.import_publication(self.fixture.archive, destination)
        link = self.root / "linked"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(archive_v2.NotriosError):
            importer.import_publication(self.fixture.archive, link / "output")
        self.assert_clean()

    def test_unsupported_rename_has_no_fallback(self):
        with mock.patch.object(importer.ctypes, "CDLL", side_effect=AttributeError):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
        self.assertEqual(caught.exception.code, "platform")
        self.assertFalse(self.destination.exists())
        self.assert_clean()
        fake = mock.Mock(return_value=-1)
        with mock.patch.object(importer.ctypes, "CDLL", return_value=mock.Mock(renameat2=fake)), \
                mock.patch.object(importer.ctypes, "get_errno", return_value=importer.errno.EOPNOTSUPP):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.run_import()
        self.assertEqual(caught.exception.code, "platform")
        self.assertEqual(fake.call_args.args[-1], 1)
        self.assertEqual(fake.restype, importer.ctypes.c_int)
        self.assertFalse(self.destination.exists())
        self.assert_clean()


class NotriosNoteIntegrationTest(unittest.TestCase):
    """Text-only archive → staged notesdb → real vault exporter integration.

    Link translation, matching-title heading handling and generated RAW title
    preludes are the explicitly separate 3d adapter slice.
    """
    def setUp(self):
        self.fixture = NotriosObjectSpoolTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.destination = self.root / "publication"
        self.ids = load_json(FIXTURE_ROOT / "design-v1.json")["fixture_ids"]
        self.bodies = {
            "doc_child": "First paragraph 東京.\r\n\r\nIndented\ttext.  \r\n".encode(),
            "doc_duplicate": "# An independent heading\n\nDecomposed cafe\u0301.  \n".encode(),
            "doc_public": b"A body without a final newline.  ",
        }
        make_text_publication(self.fixture, self.bodies)
        records = self.fixture.envelopes()
        for record in records:
            p = record["payload"]
            if record["type"] in ("notebook", "document"):
                p.update(created_at="2019-01-02T03:04:05.123999999Z", updated_at="2020-02-03T04:05:06.987654321+00:00")
            elif record["type"] == "revision":
                p["created_at"] = "2030-06-07T08:09:10Z"
        self.fixture.write_records(records)

    def import_notes(self, **kwargs):
        return importer.import_publication(self.fixture.archive, self.destination, **kwargs)

    def rows(self):
        connection = sqlite3.connect((self.destination / "notesdb.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM notes ORDER BY note_id")]
        finally:
            connection.close()

    def export(self, name="vault", *args):
        vault = self.root / name
        vault.mkdir()
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).parent / "sql2obsidian.py"),
                                 "--input", str(self.destination), "--output", str(vault),
                                 "--no-simplify-urls", "--progress-every", "0", *args],
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.export_output = result.stdout
        return vault

    def vault_notes(self, vault):
        # The existing standard-library parser reads the generated YAML scalars;
        # bytes are decoded explicitly to retain CRLF in the body under test.
        from obsidian2sql import split_frontmatter, parse_frontmatter
        found = {}
        for path in vault.rglob("*.md"):
            if ".movenotes" in path.relative_to(vault).parts:
                continue
            frontmatter, body = split_frontmatter(path.read_bytes().decode("utf-8"))
            metadata = parse_frontmatter(frontmatter)
            found[metadata["joplin-id"]] = (path.relative_to(vault).as_posix(), metadata, body)
        return found

    def test_database_counts_hierarchy_current_title_body_and_document_dates(self):
        result = self.import_notes()
        self.assertEqual((result.row_count, result.resource_count), (5, 0))
        rows = self.rows()
        self.assertEqual([r["joplin_type_"] for r in rows], [2, 2, 1, 1, 1])
        _, _, source = read_fixture_records(self.fixture.archive)
        by_id = {r["joplin_id"]: r for r in rows}
        database_id = self.fixture.manifest["snapshot"]["database_id"]
        for notebook in source["notebook"]:
            ident = mapping.mapped_id(database_id, "notebook", (notebook["id"],))
            parent = mapping.mapped_id(database_id, "notebook", (notebook["parent_id"],)) if notebook.get("parent_id") else ""
            row = by_id[ident]
            self.assertEqual((row["note_title"], row["note_data"]), (notebook["name"], notebook["name"]))
            self.assertEqual((row["joplin_parent_id"], row["note_parent_uuid"]), (parent, parent))
        for document in source["document"]:
            ident = self.ids["document"][document["id"]]
            row = by_id[ident]
            revision = next(r for r in source["revision"] if r["id"] == document["current_revision_id"])
            expected_body = self.bodies[document["id"]]
            self.assertEqual(row["note_title"], revision["title"])
            self.assertEqual(row["note_data"].encode("utf-8"), expected_body)
            self.assertEqual(row["note_hash"], hashlib.sha512(expected_body).hexdigest())
            parent = mapping.mapped_id(database_id, "notebook", (document["notebook_id"],))
            self.assertEqual((row["joplin_parent_id"], row["note_parent_uuid"]), (parent, parent))
        for row in rows:
            self.assertEqual(row["note_uuid"], row["joplin_id"])
            self.assertEqual(row["note_original_format"], "notrios")
            self.assertEqual(row["note_internal_date"], "2019-01-02 03:04:05.123")
            for field in ("joplin_created_time", "joplin_user_created_time"):
                self.assertEqual(row[field], "2019-01-02T03:04:05.123Z")
            for field in ("joplin_updated_time", "joplin_user_updated_time"):
                self.assertEqual(row[field], "2020-02-03T04:05:06.987Z")
            for field in ("note_source_raw", "note_source_body", "note_source_filename", "note_source_sha256", "note_obsidian_raw"):
                self.assertIsNone(row[field])
        self.assertEqual([r["joplin_id"] for r in rows if r["joplin_type_"] == 1],
                         [self.ids["document"][key] for key in ("doc_child", "doc_public", "doc_duplicate")])

    def test_vault_subprocess_duplicate_titles_hierarchy_body_dates_and_bundle_hashes(self):
        self.import_notes()
        vault = self.export()
        exported = self.vault_notes(vault)
        self.assertEqual(set(exported), set(self.ids["document"].values()))
        expected_paths = {"doc_child": "Public/研究/Child 東京.md", "doc_public": "Public/Café & field notes.md",
                          "doc_duplicate": "Public/Café & field notes 2.md"}
        for key, ident in self.ids["document"].items():
            path, metadata, body = exported[ident]
            self.assertEqual(path, expected_paths[key])
            self.assertEqual(metadata["movenotes-original-format"], "notrios")
            self.assertEqual(metadata["created"], "2019-01-02T03:04:05.123Z")
            self.assertEqual(metadata["updated"], "2020-02-03T04:05:06.987Z")
            self.assertEqual(metadata["title"], "Child 東京" if key == "doc_child" else "Café & field notes")
            expected = self.bodies[key]
            if expected and not expected.endswith(b"\n"):
                expected += b"\n"  # Existing exporter final-LF convention.
            self.assertEqual(body.encode("utf-8"), expected)
        manifest = load_json(vault / ".movenotes" / "manifest.json")
        self.assertEqual((manifest["scope"], len(manifest["items"]), manifest["resource_files"]), ("full", 5, 0))
        for item in manifest["items"]:
            raw = (vault / ".movenotes" / item["raw_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
            self.assertFalse(item["exact_source_bytes"])
            if item["type"] == 1:
                final = (vault / item["obsidian_path"]).read_bytes()
                self.assertEqual(hashlib.sha256(final).hexdigest(), item["obsidian_sha256"])
        self.assertFalse((vault / importer.COMPLETE).exists())
        self.assertFalse((vault / importer.INVENTORY).exists())

    def test_selected_notebook_subprocess_omits_other_notes(self):
        self.import_notes()
        vault = self.export("selected", "--notebooks", "研究")
        notes = self.vault_notes(vault)
        child_id = self.ids["document"]["doc_child"]
        self.assertEqual(set(notes), {child_id})
        self.assertEqual(notes[child_id][0], "研究/Child 東京.md")
        manifest = load_json(vault / ".movenotes" / "manifest.json")
        self.assertEqual(manifest["scope"], "selected-notebooks")
        self.assertEqual({item["id"] for item in manifest["items"] if item["type"] == 1}, {child_id})
        self.assertFalse(any("Café" in p.name for p in vault.rglob("*.md")))

    def test_empty_title_and_empty_body_remain_distinct_from_filename_fallback(self):
        self.bodies["doc_child"] = b""
        make_text_publication(self.fixture, self.bodies)
        records = self.fixture.envelopes()
        next(r["payload"] for r in records if r["type"] == "revision" and r["payload"]["document_id"] == "doc_child")["title"] = ""
        self.fixture.write_records(records)
        self.import_notes()
        row = next(r for r in self.rows() if r["joplin_id"] == self.ids["document"]["doc_child"])
        self.assertEqual((row["note_title"], row["note_data"]), ("", ""))
        notes = self.vault_notes(self.export())
        path, metadata, body = notes[row["joplin_id"]]
        self.assertEqual(path, "Public/研究/Untitled.md")
        self.assertEqual(body, "")
        self.assertNotIn("title", metadata)

    def test_invalid_graph_refuses_before_any_payload_or_existing_output_check(self):
        for case in ("missing_parent", "cycle", "missing_notebook", "missing_revision", "wrong_revision_owner"):
            self.fixture.fresh_archive()
            make_text_publication(self.fixture)
            records = self.fixture.envelopes()
            notebooks = [r["payload"] for r in records if r["type"] == "notebook"]
            documents = [r["payload"] for r in records if r["type"] == "document"]
            if case == "missing_parent":
                notebooks[0]["parent_id"] = "missing_notebook"
            elif case == "cycle":
                notebooks[0]["parent_id"] = notebooks[1]["id"]
                notebooks[1]["parent_id"] = notebooks[0]["id"]
            elif case == "missing_notebook":
                documents[0]["notebook_id"] = "missing_notebook"
            elif case == "missing_revision":
                documents[0]["current_revision_id"] = "missing_revision"
            else:
                documents[0]["current_revision_id"] = documents[1]["current_revision_id"]
            self.fixture.write_records(records)
            with self.subTest(case=case), mock.patch.object(importer, "_build_payload") as build, \
                    mock.patch.object(importer, "_check_existing") as existing:
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    self.import_notes()
                self.assertEqual(caught.exception.code, "graph")
                build.assert_not_called()
                existing.assert_not_called()
            self.assertFalse(self.destination.exists())
            self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))

    def set_body_mime(self, mime):
        records = self.fixture.envelopes()
        for record in records:
            if record["type"] == "revision":
                record["payload"]["body"]["media_type"] = archive_v2._normalize_mime(mime)
                record["payload"]["body_mime_type"] = mime
        self.fixture.write_records(records)

    def test_semantic_utf8_markdown_mime_is_admitted(self):
        for index, mime in enumerate(("text/markdown", 'Text/Markdown; Charset="UTF-8"',
                                     "text/markdown; charset*=us-ascii''utf-8")):
            self.destination = self.root / f"mime-{index}"
            self.set_body_mime(mime)
            with self.subTest(mime=mime):
                self.import_notes()
                for row in self.rows():
                    if row["joplin_type_"] == 1:
                        self.assertIn(row["note_data"].encode(), self.bodies.values())

    def test_unsupported_mime_and_invalid_utf8_controls_refuse_before_insertion(self):
        for mime in ("text/plain", "text/html", "application/octet-stream", "text/markdown; charset=iso-8859-1",
                     "text/markdown; format=flowed"):
            self.set_body_mime(mime)
            with self.subTest(mime=mime), mock.patch.object(importer, "_build_payload") as build:
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    self.import_notes()
                self.assertEqual(caught.exception.code, "conversion")
                build.assert_not_called()
        for body in (b"\xff", b"\xef\xbb\xbftext", b"text\x00", b"text\x0b", b"text\x1f",
                     {**self.bodies, "doc_duplicate": b"late invalid body\x00"}):
            make_text_publication(self.fixture, body)
            with self.subTest(body=body), mock.patch.object(importer, "_build_payload") as build:
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    self.import_notes()
                self.assertEqual(caught.exception.code, "conversion")
                build.assert_not_called()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))

    def test_body_size_bound_is_checked_before_blob_allocation(self):
        for field in ("max_body_bytes", "max_projected_body_bytes"):
            with self.subTest(field=field), mock.patch.object(archive_v2.VerifiedArchive, "open_blob") as opening:
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    self.import_notes(conversion_limits=ConversionLimits(**{field: 1}))
                self.assertEqual(caught.exception.code, "limit")
                opening.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_notebook_only_publication_exports_without_synthetic_notes(self):
        records = [r for r in self.fixture.envelopes() if r["type"] in ("collection", "notebook")]
        self.fixture.write_records(records)
        make_text_publication(self.fixture)
        result = self.import_notes()
        self.assertEqual((result.row_count, result.resource_count), (2, 0))
        self.assertEqual([r["joplin_type_"] for r in self.rows()], [2, 2])
        vault = self.export()
        self.assertEqual(self.vault_notes(vault), {})
        manifest = load_json(vault / ".movenotes" / "manifest.json")
        self.assertEqual([item["type"] for item in manifest["items"]], [2, 2])


def retained_link(body, token, *, ident="lnk_example", source="doc_public"):
    """Independent small-fixture span/metadata builder, not a Markdown parser."""
    start = body.index(token)
    bang = token.startswith(b"!")
    label, destination = token[2 if bang else 1:-1].split(b"](", 1)
    base, separator, fragment = destination.partition(b"#")
    p = dict(id=ident, source_document_id=source, relation_type="embed" if bang else "link",
             source_format="markdown", raw_target=base.decode(), display_text=label.decode(),
             source_start_byte=start, source_end_byte=start+len(token), source_line=999, source_column=999,
             resolution_status="external" if base.lower().startswith((b"https://", b"http://")) else "resolved")
    if base.startswith(b"document://"):
        p.update(target_document_id=base.rsplit(b"/", 1)[1].decode(), target_uri=base.decode())
    elif base:
        p["target_uri"] = base.decode()
    if separator:
        p.update(anchor_type="heading", anchor_value=fragment.decode())
    return archive_v2.Record("link", (ident,), p)


class NotriosLinkProjectionTest(unittest.TestCase):
    def project(self, body, records=(), **kwargs):
        plan = links.validate_links(body, records, resolve=lambda kind, value: "a" * 32, **kwargs)
        return links.project_body(body, plan)

    def test_utf8_spans_multiple_replacements_and_unchanged_external_self(self):
        first = b"[Child](document://default/documents/doc_child#Section%20one)"
        second = b"[Again](document://default/documents/doc_child)"
        external = b"[Web](https://example.test/path?q=1#part)"
        self_link = b"[Here](#local)"
        body = "Préface 日本語\r\n".encode() + first + b"  \r\n" + external + b"\n" + self_link + b"\n" + second + b"  "
        records = [retained_link(body, token, ident=f"lnk_{number}") for number, token in enumerate((first, second, external, self_link))]
        expected = body.replace(b"document://default/documents/doc_child", b":/" + b"a" * 32)
        self.assertEqual(self.project(body, reversed(records)).encode(), expected)
        self.assertEqual(self.project(b"[Web](https://example.test/x#part)").encode(), b"[Web](https://example.test/x#part)")

    def test_lexical_protection_keeps_code_and_escaped_punctuation_exact(self):
        hidden = b"[Hidden](document://default/documents/doc_child)"
        token = b"[Active](document://default/documents/doc_child)"
        for protected in (b"```query\n"+hidden+b"\n```\n", b"  ~~~~\n"+hidden+b"\n  ~~~~~ \t\n",
                          b"    "+hidden+b"\n", b"\t"+hidden+b"\n", b"`"+hidden+b"`\n",
                          b"``one ` "+hidden+b"``\n"):
            body = protected + b"\\[ordinary\\] " + token
            with self.subTest(protected=protected):
                result = self.project(body, [retained_link(body, token)])
                self.assertEqual(result.encode(), protected + b"\\[ordinary\\] [Active](:/" + b"a"*32+b")")
                with self.assertRaises(archive_v2.NotriosError):
                    self.project(body, [retained_link(body, hidden), retained_link(body, token, ident="lnk_active")])
        unclosed = b"```\n" + hidden
        self.assertEqual(self.project(unclosed).encode(), unclosed)
        unmatched = b"` unmatched " + token
        self.assertEqual(len(list(links.scan_markdown(unmatched))), 1)
        with self.assertRaises(archive_v2.NotriosError):
            self.project(b"> ```\n> " + token + b"\n> ```", [retained_link(b"> ```\n> " + token + b"\n> ```", token)])

    def test_span_and_record_agreement_refusals(self):
        token = b"[Child](document://default/documents/doc_child#part)"
        body = "日\n".encode() + token
        good = retained_link(body, token)
        mutations = ({"source_start_byte": 1}, {"source_end_byte": 1}, {"source_start_byte": 0},
                     {"source_end_byte": len(body)+1}, {"source_end_byte": len(body)-1},
                     {"source_format": "html"}, {"relation_type": "embed"}, {"display_text": "wrong"},
                     {"raw_target": "document://default/documents/wrong"}, {"target_document_id": "wrong"},
                     {"target_resource_id": "resource_wrong"}, {"target_uri": "https://example.test"},
                     {"resolution_status": "external"}, {"anchor_type": "block"}, {"anchor_value": "wrong"})
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(archive_v2.NotriosError):
                self.project(body, [archive_v2.Record("link", good.key, {**good.payload, **change})])
        for records in ([], [good, good]):
            with self.assertRaises(archive_v2.NotriosError):
                self.project(body, records)
        plain = b"[Child](document://default/documents/doc_child)"
        p = retained_link(plain, plain)
        with self.assertRaises(archive_v2.NotriosError):
            self.project(plain, [archive_v2.Record("link", p.key, {**p.payload, "anchor_type": "heading"})])

    def test_unsupported_active_syntax_and_uri_variants_refuse(self):
        destinations = (b"relative.md", b"file:///private", b"javascript:alert", b"notrios://doc_child",
                        b"Document://default/documents/doc_child", b"document://elsewhere/documents/doc_child",
                        b"document://default:80/documents/doc_child", b"document://user@default/documents/doc_child",
                        b"document://default/documents/../doc_child", b"document://default/documents/%64oc_child",
                        b"document://default/documents/doc_child?q=1", b"#^block", b"#", b"#two#parts", b"#bad%XZ",
                        b"https://user:password@example.test", b"https:///missing", b"https://example.test:99999")
        for destination in destinations:
            body = b"[label](" + destination + b")"
            with self.subTest(destination=destination), self.assertRaises(archive_v2.NotriosError):
                self.project(body, [retained_link(body, body)])
        for body in (b"[[Local]]", b"![[Local]]", b"[ref]: ./local.md", b"[ref]", b"[text][ref]",
                     b'[label](https://example.test "title")', b"[nested [label]](https://example.test)",
                     b"[escaped\\!](https://example.test)", b"[label](<https://example.test>)",
                     b"<a href='document://default/documents/doc_child'>", b"DOCUMENT://default/documents/doc_child",
                     b"bare :/"+b"a"*32, b"![embed](document://default/documents/doc_child)"):
            with self.subTest(body=body), self.assertRaises(archive_v2.NotriosError):
                self.project(body)

    def test_self_and_external_record_agreement(self):
        for body in (b"[self](#part)", b"[web](https://example.test/#part)"):
            record = retained_link(body, body)
            for change in ({"target_document_id": "other"}, {"target_resource_id": "res_other"},
                           {"target_uri": "document://default/documents/other"}):
                with self.subTest(body=body, change=change), self.assertRaises(archive_v2.NotriosError):
                    self.project(body, [archive_v2.Record("link", record.key, {**record.payload, **change})])
        body = b"[self](#part)"
        record = retained_link(body, body)
        self.assertEqual(self.project(body, [archive_v2.Record("link", record.key,
                         {**record.payload, "target_document_id": "doc_public"})]).encode(), body)

    def test_link_fragment_and_projected_byte_bounds(self):
        token = b"[x](document://default/documents/dd)"
        record = retained_link(token, token)
        with self.assertRaises(archive_v2.NotriosError):
            self.project(token, [record], limits=ConversionLimits(max_projected_body_bytes=len(token)))
        for body, records in ((b"[x](https://example.test) [y](https://example.test)", []), (token, [record, record])):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                self.project(body, records, limits=ConversionLimits(max_links_per_note=1))
            self.assertEqual(caught.exception.code, "limit")
        body = b"[self](#long)"
        with self.assertRaises(archive_v2.NotriosError):
            self.project(body, [retained_link(body, body)], limits=ConversionLimits(max_fragment_bytes=3))

    def test_explicit_final_paths_and_filtered_labels(self):
        from pathlib import PurePosixPath
        target = "a" * 32
        body = "[A &amp; &#91;B&#93;](:/" + target + "#part%20one)\n`[code](:/" + target + ")`"
        def rewrite(path, kind=1):
            return links.rewrite_projected_links(body, note_id="b"*32, note_path=PurePosixPath("Deep/Source.md"),
                       lookup_item_type=lambda ident: kind, lookup_note_path=lambda ident: path, attachments=None)
        self.assertEqual(rewrite("Other/Café renamed 2.md"),
                         "[A &amp; &#91;B&#93;](../Other/Caf%C3%A9%20renamed%202.md#part%20one)\n`[code](:/"+target+")`")
        self.assertEqual(rewrite(None), "A \\& \\[B\\]\n`[code](:/" + target + ")`")
        for kind in (None, 2, 4):
            with self.assertRaises(archive_v2.NotriosError):
                rewrite(None, kind)


class NotriosLinkIntegrationTest(unittest.TestCase):
    setUp = NotriosNoteIntegrationTest.setUp
    import_notes = NotriosNoteIntegrationTest.import_notes
    rows = NotriosNoteIntegrationTest.rows
    export = NotriosNoteIntegrationTest.export
    vault_notes = NotriosNoteIntegrationTest.vault_notes

    def linked_archive(self):
        self.tokens = {
            "doc_public": [b"[Child](document://default/documents/doc_child#details)",
                           b"[Duplicate](document://default/documents/doc_duplicate)", b"[Here](#local)",
                           b"[Web](https://example.test/x?q=one#part)"],
            "doc_child": [b"[Back &amp; Home](document://default/documents/doc_public)"],
            "doc_duplicate": [],
        }
        self.bodies = {
            "doc_public": "# Café & field notes\n\nPréface 日本語.\n".encode() + b"\n".join(self.tokens["doc_public"])
                          + b"\n\n## local\n\n```query\n[Hidden](document://default/documents/doc_child)\n```\nWithheld item removed.\n",
            "doc_child": "# Child 東京\n\n".encode() + self.tokens["doc_child"][0] + b"\n\n## details\nTarget.\n",
            "doc_duplicate": b"# local\n\nDuplicate-title target.\n",
        }
        make_text_publication(self.fixture, self.bodies)
        records = self.fixture.envelopes()
        for source, tokens in self.tokens.items():
            for index, token in enumerate(tokens):
                record = retained_link(self.bodies[source], token, ident=f"lnk_{source}_{index}", source=source)
                records.append({"type": "link", "payload": dict(record.payload)})
        self.fixture.write_records(records)

    def projected(self, source):
        expected = self.bodies[source]
        for token in self.tokens[source]:
            replacement = token
            for key, ident in self.ids["document"].items():
                replacement = replacement.replace(f"document://default/documents/{key}".encode(), f":/{ident}".encode())
            expected = expected.replace(token, replacement)
        return expected

    def test_linked_import_and_final_vault_paths_preserve_heads_code_and_hashes(self):
        self.linked_archive()
        self.import_notes()
        for row in self.rows():
            if row["joplin_type_"] == 1:
                source = next(k for k, v in self.ids["document"].items() if v == row["joplin_id"])
                self.assertEqual(row["note_data"].encode(), self.projected(source))
        vault = self.export()
        notes = self.vault_notes(vault)
        public = notes[self.ids["document"]["doc_public"]][2]
        expected = self.bodies["doc_public"].decode().replace(self.tokens["doc_public"][0].decode(),
                      "[Child](%E7%A0%94%E7%A9%B6/Child%20%E6%9D%B1%E4%BA%AC.md#details)")
        expected = expected.replace(self.tokens["doc_public"][1].decode(), "[Duplicate](Caf%C3%A9%20%26%20field%20notes%202.md)")
        self.assertEqual(public, expected)
        self.assertEqual(notes[self.ids["document"]["doc_child"]][2],
                         self.bodies["doc_child"].decode().replace(self.tokens["doc_child"][0].decode(),
                         "[Back &amp; Home](../Caf%C3%A9%20%26%20field%20notes.md)"))
        manifest = load_json(vault / ".movenotes" / "manifest.json")
        for item in manifest["items"]:
            if item["type"] == 1:
                self.assertEqual(hashlib.sha256((vault / item["obsidian_path"]).read_bytes()).hexdigest(), item["obsidian_sha256"])

    def test_filtered_links_become_escaped_labels_with_numeric_summary(self):
        self.linked_archive()
        self.import_notes()
        vault = self.export("filtered", "--notebooks", "研究")
        notes = self.vault_notes(vault)
        self.assertEqual(set(notes), {self.ids["document"]["doc_child"]})
        body = notes[self.ids["document"]["doc_child"]][2]
        self.assertEqual(body, self.bodies["doc_child"].decode().replace(self.tokens["doc_child"][0].decode(), "Back \\& Home"))
        self.assertIn("omitted 1 link(s) to unselected notes", self.export_output)
        self.assertNotIn("Café", body)

    def test_rehashed_stale_missing_and_protected_records_refuse_without_output(self):
        for case in ("stale", "missing", "code", "wrong_target"):
            self.linked_archive()
            records = self.fixture.envelopes()
            first = next(r for r in records if r["type"] == "link")
            if case == "stale":
                first["payload"]["source_start_byte"] += 1
            elif case == "missing":
                records.remove(first)
            elif case == "wrong_target":
                first["payload"]["target_document_id"] = "doc_duplicate"
            else:
                token = b"[Hidden](document://default/documents/doc_child)"
                record = retained_link(self.bodies["doc_public"], token, ident="lnk_code")
                records.append({"type": "link", "payload": dict(record.payload)})
            self.fixture.write_records(records)
            with self.subTest(case=case), self.assertRaises(archive_v2.NotriosError) as caught:
                self.import_notes()
            self.assertEqual(caught.exception.code, "conversion")
            self.assertFalse(self.destination.exists())
            self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))

    def test_real_first_write_length_fallback_is_used_for_links(self):
        import errno
        import sql2obsidian
        self.linked_archive()
        self.import_notes()
        vault = self.root / "fallback"
        vault.mkdir()
        original = Path.write_bytes
        failed = []
        def write(path, raw):
            if path.name == "Child 東京.md" and not failed:
                failed.append(path)
                raise OSError(errno.ENAMETOOLONG, "injected component length")
            return original(path, raw)
        with mock.patch.object(Path, "write_bytes", write):
            result = sql2obsidian.main(["--input", str(self.destination), "--output", str(vault),
                                       "--no-simplify-urls", "--progress-every", "0"])
        self.assertEqual(result, 0)
        self.assertEqual(len(failed), 1)
        notes = self.vault_notes(vault)
        actual_path = notes[self.ids["document"]["doc_child"]][0]
        self.assertNotEqual(actual_path, "Public/研究/Child 東京.md")
        from urllib.parse import quote
        target = quote(actual_path.removeprefix("Public/"), safe="/")
        self.assertIn(f"[Child]({target}#details)", notes[self.ids["document"]["doc_public"]][2])

    def test_final_write_failure_has_no_completed_bundle(self):
        import sql2obsidian
        self.linked_archive()
        self.import_notes()
        vault = self.root / "failed-final"
        vault.mkdir()
        write = Path.write_bytes
        counts = Counter()
        def fail_final(path, raw):
            counts[path] += 1
            if path.suffix == ".md" and counts[path] == 2:
                raise OSError("injected final write failure")
            return write(path, raw)
        with mock.patch.object(Path, "write_bytes", fail_final), self.assertRaises(OSError):
            sql2obsidian.main(["--input", str(self.destination), "--output", str(vault), "--progress-every", "0"])
        self.assertFalse((vault / ".movenotes" / "manifest.json").exists())

    def test_generated_raw_and_reimport_remove_only_one_synthetic_title(self):
        self.linked_archive()
        self.import_notes()
        first_vault = self.export()
        before = self.vault_notes(first_vault)
        rows = {row["joplin_id"]: row for row in self.rows()}
        manifest = load_json(first_vault / ".movenotes" / "manifest.json")
        for item in manifest["items"]:
            raw = (first_vault / ".movenotes" / item["raw_path"]).read_bytes()
            if item["type"] == 1:
                row = rows[item["id"]]
                self.assertTrue(raw.startswith((row["note_title"] + "\n\n" + row["note_data"]).encode()))
        restored = self.root / "restored"
        restored.mkdir()
        run = subprocess.run([sys.executable, "-B", str(Path(__file__).parent / "joplin2sql.py"),
                              "--input", str(first_vault / ".movenotes" / "joplin-raw"),
                              "--output", str(restored), "--progress-every", "0"],
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.destination = restored
        restored_rows = self.rows()
        for row in restored_rows:
            self.assertEqual(row["note_title"], rows[row["joplin_id"]]["note_title"])
            if row["joplin_type_"] == 1:
                self.assertTrue(links.is_generated_note(row))
                self.assertEqual(links.projected_note_body(row), rows[row["joplin_id"]]["note_data"])
        after = self.vault_notes(self.export("restored-vault"))
        self.assertEqual(set(before), set(after))
        # Joplin imports RAW in filename order, so equal-date duplicate titles
        # can exchange suffixes. Each export must use its own final paths.
        import posixpath
        from urllib.parse import quote
        for source, source_id in self.ids["document"].items():
            expected = self.bodies[source].decode()
            for token in self.tokens[source]:
                if b"document://" not in token:
                    continue
                record = retained_link(self.bodies[source], token, source=source)
                target_id = self.ids["document"][record.payload["target_document_id"]]
                relative = posixpath.relpath(after[target_id][0], posixpath.dirname(after[source_id][0]))
                expected = expected.replace(token.decode(), token.decode().replace(record.payload["raw_target"], quote(relative, safe="/")))
            self.assertEqual(after[source_id][2], expected)

    def test_empty_and_multiline_titles_get_a_single_raw_prelude(self):
        self.import_notes()
        row = next(r for r in self.rows() if r["joplin_type_"] == 1)
        for title, expected in (("", "Untitled"), ("one\ntwo\rthree", "one two three")):
            generated = {**row, "note_title": title, "note_data": "\n# Real heading\n\n"}
            raw = notesdb.serialize_joplin_item(generated)
            self.assertTrue(raw.startswith((expected + "\n\n\n# Real heading\n\n").encode()))
            from joplin2sql import parse_joplin_note
            path = self.root / "generated.md"
            path.write_bytes(raw)
            parsed = parse_joplin_note(path)
            self.assertEqual(parsed["note_title"], expected)
            self.assertEqual(links.projected_note_body(parsed), generated["note_data"])
            # The actual parser is exercised through the subprocess above;
            # source format guards below ensure other producers never prefix.
            for origin in ("joplin", "obsidian"):
                other = {**generated, "note_original_format": origin}
                self.assertTrue(notesdb.serialize_joplin_item(other).startswith(b"\n# Real heading\n\n"))

    def test_direct_joplin_export_and_container_title_guards(self):
        self.linked_archive()
        self.import_notes()
        output = self.root / "direct-raw"
        output.mkdir()
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).parent / "sql2joplin.py"),
                                 "--input", str(self.destination), "--output", str(output), "--progress-every", "0"],
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        from joplin2sql import parse_joplin_note
        for row in self.rows():
            parsed = parse_joplin_note(output / (row["joplin_id"] + ".md"))
            self.assertEqual(parsed["note_title"], row["note_title"])
            if row["joplin_type_"] == 1:
                self.assertEqual(links.projected_note_body(parsed), row["note_data"])
            else:
                self.assertEqual(parsed["note_data"].rstrip("\n"), row["note_data"])
        fixture = NotriosMappingTest()
        fixture.setUp()
        tag = next(r for r in fixture.fixture_rows() if r["joplin_type_"] == 5)
        path = output / "generated-tag.md"
        path.write_bytes(notesdb.serialize_joplin_item(tag))
        parsed = parse_joplin_note(path)
        self.assertEqual(parsed["note_title"], tag["note_title"])
        self.assertEqual(parsed["note_data"].rstrip("\n"), tag["note_data"])

    def test_missing_mapped_note_refuses_even_in_filtered_export(self):
        import sql2obsidian
        self.linked_archive()
        self.import_notes()
        with sqlite3.connect(self.destination / "notesdb.sqlite") as connection:
            connection.execute("DELETE FROM notes WHERE joplin_id=?", (self.ids["document"]["doc_public"],))
        for name, extra in (("missing-all", []), ("missing-filtered", ["--notebooks", "研究"])):
            vault = self.root / name
            vault.mkdir()
            with self.subTest(name=name), self.assertRaises(archive_v2.NotriosError):
                sql2obsidian.main(["--input", str(self.destination), "--output", str(vault), "--progress-every", "0", *extra])
            self.assertFalse((vault / ".movenotes" / "manifest.json").exists())


class NotriosTagMappingIntegrationTest(unittest.TestCase):
    import_notes = NotriosNoteIntegrationTest.import_notes
    rows = NotriosNoteIntegrationTest.rows

    def setUp(self):
        NotriosNoteIntegrationTest.setUp(self)
        # Keep the fixture's original four identities and six memberships, but
        # use the already-owned text-only bodies until resource support lands.
        _, _, original = read_fixture_records(PUBLICATION_ARCHIVE)
        records = self.fixture.envelopes()
        records.extend({"type": kind, "payload": dict(payload)}
                       for kind in ("tag", "document_tag") for payload in original[kind])
        self.fixture.write_records(records)

    def loaded_tags(self):
        from sql2obsidian import load_note_tags
        connection = sqlite3.connect((self.destination / "notesdb.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return load_note_tags(connection.cursor())
        finally:
            connection.close()

    def test_tags_and_memberships_map_to_correct_sorted_titles(self):
        result = self.import_notes()
        self.assertEqual((result.status, result.row_count, result.resource_count), ("created", 15, 0))
        expected = {"doc_child": ["published", "東京"], "doc_duplicate": ["published"],
                    "doc_public": ["café", "published", "research notes"]}
        self.assertEqual(self.loaded_tags(), {self.ids["document"][key]: value for key, value in expected.items()})
        rows = self.rows()
        self.assertEqual([r["joplin_type_"] for r in rows], [2]*2 + [1]*3 + [5]*4 + [6]*6)
        _, _, source = read_fixture_records(self.fixture.archive)
        database_id = self.fixture.manifest["snapshot"]["database_id"]
        tag_rows = [r for r in rows if r["joplin_type_"] == 5]
        relation_rows = [r for r in rows if r["joplin_type_"] == 6]
        tags = sorted(source["tag"], key=lambda p: mapping.source_key(database_id, "tag", (p["id"],)))
        relations = sorted(source["document_tag"], key=lambda p: mapping.source_key(database_id, "document_tag", (p["document_id"], p["tag_id"])))
        for row, tag in zip(tag_rows, tags):
            ident = mapping.mapped_id(database_id, "tag", (tag["id"],))
            self.assertEqual((row["joplin_id"], row["note_uuid"]), (ident, ident))
            self.assertEqual((row["note_title"], row["note_data"]), (tag["name"], tag["name"]))
            self.assertIsNone(row["joplin_parent_id"])
            self.assertEqual(row["joplin_created_time"], "2026-09-05T21:17:09.000Z")
            self.assertEqual(row["joplin_updated_time"], row["joplin_created_time"])
        for row, relation in zip(relation_rows, relations):
            key = (relation["document_id"], relation["tag_id"])
            ident = mapping.mapped_id(database_id, "document_tag", key)
            note = self.ids["document"][relation["document_id"]]
            tag = mapping.mapped_id(database_id, "tag", (relation["tag_id"],))
            self.assertEqual((row["joplin_id"], row["note_uuid"]), (ident, ident))
            self.assertEqual((row["joplin_note_id"], row["note_note_uuid"]), (note, note))
            self.assertEqual((row["joplin_tag_id"], row["note_tag_uuid"]), (tag, tag))
            self.assertEqual((row["note_title"], row["note_data"]), ("", ""))
            self.assertIsNone(row["joplin_parent_id"])
            self.assertEqual(row["joplin_created_time"], "2019-01-02T03:04:05.123Z")
            self.assertEqual(row["joplin_updated_time"], row["joplin_created_time"])
        before = fixture_inventory(self.destination)
        result = self.import_notes()
        self.assertEqual((result.status, result.row_count), ("unchanged", 15))
        self.assertEqual(fixture_inventory(self.destination), before)

    def test_tag_rows_use_existing_bounded_batches(self):
        batches = []
        insert = notesdb.add_joplin_notes
        def record_batch(connection, rows):
            batches.append([row["joplin_type_"] for row in rows])
            return insert(connection, rows)
        with mock.patch.object(notesdb, "add_joplin_notes", record_batch):
            self.import_notes(conversion_limits=ConversionLimits(batch_rows=2, batch_bytes=1))
        self.assertEqual(batches, [[kind] for kind in [2]*2 + [1]*3 + [5]*4 + [6]*6])
        self.assertEqual(sum(map(len, self.loaded_tags().values())), 6)

    def test_unattached_tags_do_not_create_memberships(self):
        records = [r for r in self.fixture.envelopes() if r["type"] != "document_tag"]
        self.fixture.write_records(records)
        self.assertEqual(self.import_notes().row_count, 9)
        self.assertEqual(self.loaded_tags(), {})
        self.assertEqual(Counter(r["joplin_type_"] for r in self.rows()), {1: 3, 2: 2, 5: 4})

    def test_finalization_refuses_wrong_membership_targets_aliases_and_counts(self):
        finalize = importer._finalize_database
        changes = (
            "joplin_tag_id='missing_tag',note_tag_uuid='missing_tag'",
            "note_note_uuid='wrong_alias'",
            "joplin_note_id=(SELECT joplin_id FROM notes WHERE joplin_type_=2 LIMIT 1),"
            "note_note_uuid=(SELECT joplin_id FROM notes WHERE joplin_type_=2 LIMIT 1)",
            "joplin_type_=5",
        )
        for change in changes:
            def corrupt(connection, expected_counts, expected_relations=0):
                connection.execute("UPDATE notes SET " + change + " WHERE note_id=(SELECT min(note_id) FROM notes WHERE joplin_type_=6)")
                return finalize(connection, expected_counts, expected_relations)
            with self.subTest(change=change), mock.patch.object(importer, "_finalize_database", corrupt):
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    self.import_notes()
                self.assertEqual(caught.exception.code, "integrity")
            self.assertFalse(self.destination.exists())
            self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))


class NotriosTagRoundTripTest(unittest.TestCase):
    import_notes = NotriosNoteIntegrationTest.import_notes
    rows = NotriosNoteIntegrationTest.rows
    export = NotriosNoteIntegrationTest.export
    vault_notes = NotriosNoteIntegrationTest.vault_notes
    loaded_tags = NotriosTagMappingIntegrationTest.loaded_tags

    def setUp(self):
        NotriosTagMappingIntegrationTest.setUp(self)
        self.names = ["café", "cafe\u0301", "東京 研究", "research notes",
                      'quoted "double" and \'single\'', r"path\branch: [draft] #2026",
                      "true", "same title", "same title", "inside\ttab"]
        self.memberships = {"doc_public": list(range(len(self.names))), "doc_child": [2, 3, 7], "doc_duplicate": [8]}
        records = self.fixture.envelopes()
        prototype = next(r["payload"] for r in records if r["type"] == "tag")
        records = [r for r in records if r["type"] not in ("tag", "document_tag")]
        records.extend({"type": "tag", "payload": {**prototype, "id": f"tag_case_{index:02}", "name": name}}
                       for index, name in enumerate(self.names))
        records.extend({"type": "document_tag", "payload": {"document_id": document, "tag_id": f"tag_case_{index:02}"}}
                       for document, indexes in self.memberships.items() for index in indexes)
        self.fixture.write_records(records)
        self.expected = {self.ids["document"][document]: sorted(self.names[i] for i in indexes)
                         for document, indexes in self.memberships.items()}

    def reimport_vault(self, vault, name):
        destination = self.root / name
        destination.mkdir()
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).parent / "obsidian2sql.py"),
                                 "--input", str(vault), "--output", str(destination), "--progress-every", "0"],
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.destination = destination

    def assert_vault_tag_text(self, vault):
        from obsidian2sql import split_frontmatter
        notes = self.vault_notes(vault)
        self.assertEqual(set(notes), set(self.expected))
        for item_id, (path, metadata, _) in notes.items():
            self.assertEqual(metadata["tags"], self.expected[item_id])
            frontmatter, _ = split_frontmatter((vault / path).read_bytes().decode("utf-8"))
            # Exported JSON string scalars are a YAML-compatible spelling. Read
            # these independently of the importer's frontmatter parser too.
            scalars = [line[4:] for line in frontmatter.split("\n") if line.startswith("  - ")]
            self.assertTrue(all(value.startswith('"') for value in scalars))
            self.assertEqual([json.loads(value) for value in scalars], self.expected[item_id])

    def tag_identity_rows(self):
        return {row["joplin_id"]: (row["joplin_type_"], row["note_title"] if row["joplin_type_"] == 5 else "",
                                  row["joplin_note_id"], row["joplin_tag_id"])
                for row in self.rows() if row["joplin_type_"] in (5, 6)}

    def test_bundle_round_trip_retains_names_identities_and_membership_multiplicity(self):
        self.assertEqual(self.import_notes().row_count, 29)
        self.assertEqual(self.loaded_tags(), self.expected)
        identities = self.tag_identity_rows()
        duplicate_ids = {item_id for item_id, row in identities.items() if row[:2] == (5, "same title")}
        self.assertEqual(len(duplicate_ids), 2)
        public_id = self.ids["document"]["doc_public"]
        self.assertEqual({row[3] for row in identities.values() if row[0] == 6 and row[2] == public_id} & duplicate_ids,
                         duplicate_ids)
        self.assertEqual(self.loaded_tags()[public_id].count("same title"), 2)
        vault = self.export("tag-vault")
        self.assert_vault_tag_text(vault)
        self.reimport_vault(vault, "restored-tags")
        self.assertEqual(self.loaded_tags(), self.expected)
        self.assertEqual(self.tag_identity_rows(), identities)
        self.assert_vault_tag_text(self.export("restored-tag-vault"))

    def test_native_yaml_import_retains_text_and_exact_vault_bytes(self):
        self.import_notes()
        vault = self.export("native-tags", "--no-preserve-joplin")
        self.assert_vault_tag_text(vault)
        before = {path: (vault / path).read_bytes() for path, _, _ in self.vault_notes(vault).values()}
        self.reimport_vault(vault, "native-restored")
        # Native Obsidian identities are keyed by tag name. The default bundle
        # test above, not this name-based path, proves distinct source identities.
        self.assertEqual({key: set(values) for key, values in self.loaded_tags().items()},
                         {key: set(values) for key, values in self.expected.items()})
        restored = self.export("native-reexport", "--no-preserve-joplin")
        after = {path: (restored / path).read_bytes() for path, _, _ in self.vault_notes(restored).values()}
        self.assertEqual(after, before)
        self.assert_vault_tag_text(restored)

    def test_selected_notebook_keeps_only_its_tag_memberships_through_bundle(self):
        self.import_notes()
        vault = self.export("selected-tags", "--notebooks", "研究")
        child_id = self.ids["document"]["doc_child"]
        expected = {child_id: self.expected[child_id]}
        self.assertEqual({key: metadata["tags"] for key, (_, metadata, _) in self.vault_notes(vault).items()}, expected)
        self.reimport_vault(vault, "selected-restored")
        self.assertEqual(self.loaded_tags(), expected)
        rows = self.rows()
        self.assertEqual(sum(row["joplin_type_"] == 6 for row in rows), 3)
        self.assertEqual(sorted(row["note_title"] for row in rows if row["joplin_type_"] == 5), expected[child_id])

    def test_rehashed_malformed_and_duplicate_memberships_refuse_in_verification(self):
        baseline = self.fixture.envelopes()
        cases = {"duplicate_pair": "integrity", "duplicate_tag_id": "integrity",
                 "missing_document": "json", "missing_tag": "json", "unknown_field": "json",
                 "null_document": "json", "numeric_tag": "json", "invalid_document": "format",
                 "invalid_tag": "format", "unknown_document": "graph", "unknown_tag": "graph"}
        for case, code in cases.items():
            records = copy.deepcopy(baseline)
            relation = next(r for r in records if r["type"] == "document_tag")
            p = relation["payload"]
            if case == "duplicate_pair":
                records.append(copy.deepcopy(relation))
            elif case == "duplicate_tag_id":
                tag = copy.deepcopy(next(r for r in records if r["type"] == "tag"))
                tag["payload"]["name"] = "Different bytes under the same identity"
                records.append(tag)
            elif case == "missing_document":
                del p["document_id"]
            elif case == "missing_tag":
                del p["tag_id"]
            elif case == "unknown_field":
                p["id"] = "unexpected_relation_id"
            elif case == "null_document":
                p["document_id"] = None
            elif case == "numeric_tag":
                p["tag_id"] = 42
            elif case == "invalid_document":
                p["document_id"] = "bad/document"
            elif case == "invalid_tag":
                p["tag_id"] = ""
            elif case == "unknown_document":
                p["document_id"] = "missing_document"
            else:
                p["tag_id"] = "missing_tag"
            self.fixture.write_records(records)
            with self.subTest(case=case), mock.patch.object(importer, "_preflight") as preflight, \
                    mock.patch.object(importer, "_build_payload") as build:
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    self.import_notes()
                self.assertEqual(caught.exception.code, code)
                preflight.assert_not_called()
                build.assert_not_called()
            self.assertFalse(self.destination.exists())
            self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))


if __name__ == "__main__":
    unittest.main()


class NotriosSchema28Test(unittest.TestCase):
    """Real schema-28 publications, with no producer dependency at test time."""

    rows = NotriosNoteIntegrationTest.rows
    export = NotriosNoteIntegrationTest.export
    vault_notes = NotriosNoteIntegrationTest.vault_notes

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="movenotes-schema28-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / "publication"
        self.fixtures = FIXTURE_ROOT / "schema28"

    def test_producer_fixtures_and_original_are_fully_verified(self):
        for fixture, schema in ((PUBLICATION_ROOT, 27),
                                (self.fixtures / "publication-loose", 28),
                                (self.fixtures / "publication-text", 28)):
            with self.subTest(fixture=fixture.name, schema=schema):
                expected = load_json(fixture / "expected.json")
                before = fixture_inventory(fixture / "archive")
                self.assertEqual(before, expected["archive_files"])
                with archive_v2.verify_archive(fixture / "archive", work_dir=self.root) as verified:
                    self.assertEqual(verified.manifest.compatibility["source_schema_version"], schema)
                    self.assertEqual(dict(verified.counts), expected["counts"])
                    self.assertEqual(verified.manifest.commit_sha256, expected["commit_sha256"])
                    collections = list(verified.iter_records("collection"))
                    self.assertEqual(len(collections), 1)
                    self.assertEqual("capabilities" in collections[0].payload, schema == 27)
                self.assertEqual(fixture_inventory(fixture / "archive"), before)
                self.assertEqual(list(self.root.iterdir()), [])
                for name in ("verify", "publish-run"):
                    report = load_json(fixture / "reports" / (name + ".json"))
                    if name == "publish-run":
                        report = report["report"]
                    self.assertEqual(report["commit_sha256"], expected["commit_sha256"])
                self.assertEqual(load_json(fixture / "reports/compatibility.json")["decision"], "accept")

    def test_real_text_publication_conversion_noop_and_vault_links(self):
        import posixpath
        from urllib.parse import quote
        fixture = self.fixtures / "publication-text"
        source = fixture / "archive"
        expected = load_json(fixture / "expected.json")
        result = importer.import_publication(source, self.destination,
                    expected_selection_sha256=expected["selection_manifest_sha256"])
        self.assertEqual((result.status, result.row_count, result.resource_count), ("created", 15, 0))
        before = fixture_inventory(self.destination)
        self.assertEqual(importer.import_publication(source, self.destination).status, "unchanged")
        self.assertEqual(fixture_inventory(self.destination), before)
        ids = {source_id: mapping.mapped_id(expected["database_id"], "document", (source_id,))
               for source_id in ("doc_public", "doc_child", "doc_duplicate")}
        rows = {r["joplin_id"]: r for r in self.rows() if r["joplin_type_"] == 1}
        self.assertEqual(set(rows), set(ids.values()))
        bodies = {ident: (FIXTURE_ROOT / "seed-text-v1/notes" / (ident + ".md")).read_text().split("\n---\n\n", 1)[1]
                  for ident in ids}
        for ident, body in bodies.items():
            projected = body
            for target, item_id in ids.items():
                projected = projected.replace("document://default/documents/" + target, ":/" + item_id)
            self.assertEqual(rows[ids[ident]]["note_data"], projected)
        vault = self.export()
        notes = self.vault_notes(vault)
        self.assertEqual(set(notes), set(ids.values()))
        tags = {"doc_public": ["café", "published", "research notes"],
                "doc_child": ["published", "東京"], "doc_duplicate": ["published"]}
        for ident, body in bodies.items():
            path, metadata, actual = notes[ids[ident]]
            self.assertEqual(metadata["tags"], tags[ident])
            self.assertTrue(path.startswith("Public/研究/" if ident == "doc_child" else "Public/"))
            for target in ids:
                relative = posixpath.relpath(notes[ids[target]][0], posixpath.dirname(path))
                body = body.replace("document://default/documents/" + target, quote(relative, safe="/"))
            self.assertEqual(actual, body)
        self.assertNotEqual(notes[ids["doc_public"]][0], notes[ids["doc_duplicate"]][0])
        for item in load_json(vault / ".movenotes/manifest.json")["items"]:
            if item["type"] == 1:
                self.assertEqual(hashlib.sha256((vault / item["obsidian_path"]).read_bytes()).hexdigest(), item["obsidian_sha256"])

    def test_real_resource_publication_converts(self):
        result = importer.import_publication(self.fixtures / "publication-loose/archive", self.destination)
        self.assertEqual((result.row_count, result.resource_count), (18, 3))

    def test_current_producer_differential_cases(self):
        specs = load_json(FIXTURE_ROOT / "schema28-audit-cases.json")
        report = load_json(self.fixtures / "verifier-audit.json")
        fixture = self.fixtures / "publication-loose"
        generation = load_json(fixture / "generation.json")
        for field in ("producer_commit", "cli_sha256"):
            self.assertEqual(report[field], generation[field])
        self.assertEqual(report["fixture_commit_sha256"], load_json(fixture / "expected.json")["commit_sha256"])
        self.assertEqual(report["case_spec_sha256"], hashlib.sha256((FIXTURE_ROOT / "schema28-audit-cases.json").read_bytes()).hexdigest())
        self.assertEqual([r["name"] for r in report["results"]], [s["name"] for s in specs])
        case = NotriosObjectSpoolTest()
        case.fixture_source = fixture / "archive"
        case.setUp()
        self.addCleanup(case.doCleanups)
        for spec, result in zip(specs, report["results"]):
            with self.subTest(case=spec["name"]):
                self.assertTrue(result["matched"])
                self.assertEqual(result["go_accepted"], spec["expect_go"])
                self.assertEqual(result["python_result"], spec["expect_python"])
                case.fresh_archive()
                case.apply_audit_case(spec)
                if spec["expect_python"] == "accepted":
                    with case.verify():
                        pass
                else:
                    case.assert_verification_refused(spec["expect_python"], spec["message"])
                self.assertEqual(list(case.work.iterdir()), [])


class NotriosResourceStorageTest(unittest.TestCase):
    """Storage-only slice: link projection/admission stay gated until 5b."""

    def setUp(self):
        self.fixture = NotriosObjectSpoolTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    @staticmethod
    def unprojected_body(archive, document, revision, limits, resolve):
        # Exercise staging independently of the explicitly unfinished 5b path.
        return importer._body(archive, revision, limits)

    def build(self, verified, stage):
        stage.mkdir()
        with mock.patch.object(importer, "_project_note", self.unprojected_body):
            return importer._build_payload(verified, stage, importer._receipt(verified.manifest),
                                           ConversionLimits(copy_chunk_bytes=7, batch_rows=1, batch_bytes=1))

    def test_real_resources_have_exact_bytes_rows_and_bounded_reads(self):
        with self.fixture.verify() as verified:
            stage = self.root / "payload"
            reads = []
            opening = verified.open_blob

            @contextmanager
            def tracked(ref):
                with opening(ref) as source:
                    class Reader:
                        def read(self, size=-1):
                            reads.append(size)
                            return source.read(size)
                    yield Reader()

            with mock.patch.object(verified, "open_blob", tracked):
                self.assertEqual(self.build(verified, stage), (18, 3))
            self.assertTrue(reads)
            self.assertEqual(set(reads), {7})
            with sqlite3.connect(stage / "notesdb.sqlite") as conn:
                conn.row_factory = sqlite3.Row
                rows = {r["joplin_id"]: dict(r) for r in conn.execute("SELECT * FROM notes WHERE joplin_type_=4")}
                self.assertIn("relation_id", [r[1] for r in conn.execute("PRAGMA table_info(notrios_document_resources)")])
                self.assertEqual(conn.execute("SELECT count(*) FROM notrios_document_resources").fetchone()[0], 4)
            expected_files = set()
            for record in verified.iter_records("resource"):
                ref = archive_v2.BlobRef(**record.payload["blob"])
                ident = mapping.mapped_id(verified.manifest.snapshot["database_id"], "resource", record.key)
                suffix = mapping.resource_extension(ref.media_type)
                filename = ident + "." + suffix
                expected_files.add(filename)
                raw = (stage / "resources" / filename).read_bytes()
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (ref.size_bytes, ref.sha256))
                wanted = mapping.build_resource_row(record, item_id=ident, mime=ref.media_type, extension=suffix)
                for key, value in wanted.items():
                    self.assertEqual(rows[ident][key], value, key)
            self.assertEqual({p.name for p in (stage / "resources").iterdir()}, expected_files)

    def test_safe_display_names_extensionless_and_shared_blob_identities(self):
        records = self.fixture.envelopes()
        resources = [r["payload"] for r in records if r["type"] == "resource"]
        for resource, name in zip(resources, ("README", "../../folder\\安全.txt", "..")):
            resource["filename"] = name
        duplicate = copy.deepcopy(resources[0])
        duplicate["id"] = "res_shared_bytes"
        records.append({"type": "resource", "payload": duplicate})
        relation = copy.deepcopy(next(r["payload"] for r in records if r["type"] == "document_resource"))
        relation["resource_id"] = duplicate["id"]
        records.append({"type": "document_resource", "payload": relation})
        self.fixture.write_records(records)
        with self.fixture.verify() as verified:
            stage = self.root / "payload"
            self.assertEqual(self.build(verified, stage), (19, 4))
            with sqlite3.connect(stage / "notesdb.sqlite") as conn:
                names = [r[0] for r in conn.execute("SELECT joplin_filename FROM notes WHERE joplin_type_=4")]
            self.assertEqual(names.count("README"), 2)
            self.assertIn("安全.txt", names)
            self.assertTrue(any(n.startswith("attachment.") for n in names))
            files = list((stage / "resources").iterdir())
            self.assertEqual(len(files), 4)
            self.assertTrue(all(importer._RESOURCE.fullmatch(p.name) for p in files))
            self.assertEqual(sum(hashlib.sha256(p.read_bytes()).hexdigest() == duplicate["blob"]["sha256"] for p in files), 2)

    def test_copy_rejects_existing_files_and_bad_stream_hash_or_size(self):
        directory = self.root / "resources"
        directory.mkdir()
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        limits = ConversionLimits(copy_chunk_bytes=2)
        ref = archive_v2.BlobRef(hashlib.sha256(b"good").hexdigest(), 4, "application/octet-stream")
        target = directory / ("a" * 32 + ".bin")
        target.write_bytes(b"existing different bytes")
        archive = mock.Mock()
        with self.assertRaises(archive_v2.NotriosError) as caught:
            importer._copy_resource(archive, ref, fd, target.name, limits)
        self.assertEqual(caught.exception.code, "collision")
        self.assertEqual(target.read_bytes(), b"existing different bytes")
        archive.open_blob.assert_not_called()
        for index, raw in enumerate((b"bad!", b"go", b"good-more")):
            with self.subTest(raw=raw):
                archive.open_blob.return_value = io.BytesIO(raw)
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    importer._copy_resource(archive, ref, fd, f"{index:032x}.bin", limits)
                self.assertEqual(caught.exception.code, "integrity")
        empty = archive_v2.BlobRef(hashlib.sha256(b"").hexdigest(), 0, "application/octet-stream")
        archive.open_blob.return_value = io.BytesIO(b"")
        importer._copy_resource(archive, empty, fd, "b" * 32 + ".bin", limits)
        self.assertEqual((directory / ("b" * 32 + ".bin")).read_bytes(), b"")

    def test_resource_copy_faults_leave_no_completed_import(self):
        destination = self.root / "publication"
        copying = importer._copy_resource
        for failure in ("read", "write", "fsync"):
            calls = []
            def fail(archive, ref, fd, name, limits):
                calls.append(name)
                if len(calls) != 2:
                    return copying(archive, ref, fd, name, limits)
                if failure == "fsync":
                    with mock.patch.object(importer.os, "fsync", side_effect=OSError("resource fsync failed")):
                        return copying(archive, ref, fd, name, limits)
                if failure == "write":
                    opening = os.fdopen
                    def short_writer(file_fd, mode, *args, **kwargs):
                        stream = opening(file_fd, mode, *args, **kwargs)
                        if mode != "wb":
                            return stream
                        class Writer:
                            def __enter__(self):
                                return self
                            def __exit__(self, *exc):
                                stream.close()
                            def write(self, chunk):
                                return stream.write(chunk[:1])
                        return Writer()
                    with mock.patch.object(importer.os, "fdopen", short_writer):
                        return copying(archive, ref, fd, name, limits)
                @contextmanager
                def broken(_ref):
                    class Reader:
                        first = True
                        def read(self, size):
                            if self.first:
                                self.first = False
                                return b"x"
                            raise OSError("resource read interrupted")
                    yield Reader()
                with mock.patch.object(archive, "open_blob", broken):
                    return copying(archive, ref, fd, name, limits)
            with self.subTest(failure=failure), \
                    mock.patch.object(importer, "_preflight"), \
                    mock.patch.object(importer, "_project_note", self.unprojected_body), \
                    mock.patch.object(importer, "_copy_resource", fail):
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    importer.import_publication(self.fixture.archive, destination)
                self.assertEqual(caught.exception.code, "io")
                self.assertEqual(len(calls), 2)
                self.assertFalse(destination.exists())
                self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))


class NotriosReceiptPropagationTest(unittest.TestCase):
    export = NotriosNoteIntegrationTest.export
    reimport_vault = NotriosTagRoundTripTest.reimport_vault

    def setUp(self):
        self.fixture = NotriosObjectSpoolTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.destination = self.root / "publication"
        importer.import_publication(self.fixture.archive, self.destination)
        expected = load_json(PUBLICATION_ROOT / "expected.json")
        self.receipt = dict(version=1, contract="notrios-archive-v2", contract_schema_version=1,
                            reader_profile="movenotes-publication-loose-v1", mapper="movenotes-notrios-v1",
                            commit_sha256=expected["commit_sha256"],
                            selection_manifest_sha256=expected["selection_manifest_sha256"],
                            snapshot_id=expected["snapshot_id"], database_id=expected["database_id"],
                            target="publication_handoff")

    def run_script(self, script, source, output, *args):
        return subprocess.run(
            [sys.executable, "-B", str(Path(__file__).parent / script), "--input", str(source),
             "--output", str(output), "--progress-every", "0", *args],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_opt_in_preserves_digests_without_notes_bundle_or_search_content(self):
        vault = self.export("receipt-vault", "--include-notrios-receipt")
        sidecar = vault / notrios_receipt.VAULT_PATH
        self.assertEqual(load_json(sidecar), self.receipt)
        self.assertNotIn(str(self.root), sidecar.read_text())
        manifest = load_json(vault / ".movenotes/manifest.json")
        self.assertEqual(len([r for r in manifest["items"] if r["type"] == 4]), 3)
        for path in vault.rglob("*"):
            if path.is_file() and path != sidecar:
                for digest in (self.receipt["commit_sha256"], self.receipt["selection_manifest_sha256"]):
                    self.assertNotIn(digest.encode(), path.read_bytes(), str(path))
        import obsidian2site
        for hidden in (False, True):
            notes, assets = obsidian2site._scan_vault(vault, hidden)
            self.assertEqual(len(notes), 3)
            self.assertEqual(len(assets), 3)
            self.assertNotIn(sidecar, notes + assets)
        plain, included = self.root / "site-plain", self.root / "site-receipt"
        for output, flags in ((plain, ()), (included, ("--include-notrios-receipt",))):
            result = self.run_script("obsidian2site.py", vault, output, "--include-hidden", *flags)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((plain / notrios_receipt.SITE_PATH).exists())
        self.assertEqual(load_json(included / notrios_receipt.SITE_PATH), self.receipt)
        # Project landing pages contain generation timestamps. Compare actual
        # note pages and search inputs byte-for-byte, then check all templates
        # and content for receipt exclusion independently of those timestamps.
        for directory in ("content/notes", "server"):
            left, right = fixture_inventory(plain / directory), fixture_inventory(included / directory)
            if directory == "content/notes":
                left.pop("_index.md")
                right.pop("_index.md")
            self.assertEqual(left, right)
        for directory in ("content", "layouts"):
            for path in (included / directory).rglob("*"):
                if path.is_file():
                    for digest in (self.receipt["commit_sha256"], self.receipt["selection_manifest_sha256"]):
                        self.assertNotIn(digest.encode(), path.read_bytes(), str(path))
        for path in (included / "static").rglob("*"):
            if path.is_file() and path != included / notrios_receipt.SITE_PATH:
                self.assertNotIn(self.receipt["commit_sha256"].encode(), path.read_bytes())
        self.reimport_vault(vault, "receipt-reimport")
        with sqlite3.connect(self.destination / "notesdb.sqlite") as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM notes WHERE joplin_type_=4").fetchone()[0], 3)
            self.assertIsNone(connection.execute("SELECT value FROM settings WHERE name=?",
                                               (notrios_receipt.RECEIPT_KEY,)).fetchone())

    def test_opt_out_removes_stale_receipts_and_filtered_export_is_explicit(self):
        plain = self.export("plain-vault", "--no-preserve-joplin")
        self.assertFalse((plain / notrios_receipt.VAULT_PATH).exists())
        missing_site = self.root / "missing-receipt-site"
        result = self.run_script("obsidian2site.py", plain, missing_site, "--include-notrios-receipt")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing_site.exists())
        vault = self.export("filtered-receipt-vault", "--notebooks", "研究",
                            "--no-preserve-joplin", "--include-notrios-receipt")
        self.assertEqual(load_json(vault / notrios_receipt.VAULT_PATH), self.receipt)
        self.assertFalse((vault / ".movenotes/manifest.json").exists())
        site = self.root / "regenerated-site"
        result = self.run_script("obsidian2site.py", vault, site, "--include-notrios-receipt")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_script("obsidian2site.py", vault, site)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((site / notrios_receipt.SITE_PATH).exists())
        result = self.run_script("sql2obsidian.py", self.destination, vault,
                                 "--no-preserve-joplin", "--notebooks", "研究")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((vault / notrios_receipt.VAULT_PATH).exists())

    def test_invalid_settings_refuse_without_propagating_arbitrary_content(self):
        cases = [dict(self.receipt, source_path="PRIVATE-PATH-SENTINEL"),
                 dict(self.receipt, version=True), dict(self.receipt, database_id="/private/source"),
                 dict(self.receipt, commit_sha256="A" * 64), dict(self.receipt, mapper="future"),
                 "x" * (notrios_receipt.MAX_BYTES + 1)]
        for index, value in enumerate(cases):
            with self.subTest(index=index):
                with sqlite3.connect(self.destination / "notesdb.sqlite") as connection:
                    connection.execute("UPDATE settings SET value=? WHERE name=?",
                                       (json.dumps(value), notrios_receipt.RECEIPT_KEY))
                vault = self.root / f"invalid-settings-{index}"
                vault.mkdir()
                result = self.run_script("sql2obsidian.py", self.destination, vault, "--include-notrios-receipt")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("PRIVATE-PATH-SENTINEL", result.stdout + result.stderr)
                self.assertEqual(list(vault.iterdir()), [])

    def test_invalid_and_symlink_vault_receipts_refuse_before_site_generation(self):
        vault = self.export("invalid-sidecar-vault", "--include-notrios-receipt")
        path = vault / notrios_receipt.VAULT_PATH
        good = json.dumps(self.receipt)
        cases = [good[:-1] + ', "version":1}', json.dumps(dict(self.receipt, extra="PRIVATE-PATH-SENTINEL")),
                 " " * (notrios_receipt.MAX_BYTES + 1)]
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                path.write_text(raw)
                site = self.root / f"invalid-sidecar-site-{index}"
                result = self.run_script("obsidian2site.py", vault, site, "--include-notrios-receipt")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("PRIVATE-PATH-SENTINEL", result.stdout + result.stderr)
                self.assertFalse(site.exists())
        outside = self.root / "outside-receipt"
        outside.write_text(good)
        path.unlink()
        path.symlink_to(outside)
        site = self.root / "symlink-receipt-site"
        result = self.run_script("obsidian2site.py", vault, site, "--include-notrios-receipt")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(site.exists())
        self.assertEqual(outside.read_text(), good)

    def test_sidecar_replace_failure_preserves_existing_bytes(self):
        vault = self.export("atomic-receipt-vault", "--include-notrios-receipt")
        before = (vault / notrios_receipt.VAULT_PATH).read_bytes()
        with mock.patch.object(notrios_receipt.os, "replace", side_effect=OSError("injected replacement failure")):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                notrios_receipt.write(vault, notrios_receipt.VAULT_PATH, self.receipt)
        self.assertEqual(caught.exception.code, "receipt")
        self.assertEqual((vault / notrios_receipt.VAULT_PATH).read_bytes(), before)
        self.assertFalse(list((vault / ".movenotes").glob(".notrios-receipt-*")))


class NotriosCLITest(unittest.TestCase):
    def setUp(self):
        self.fixture = NotriosObjectSpoolTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.destination = self.root / "published"
        self.expected = load_json(PUBLICATION_ROOT / "expected.json")

    def cli(self, *extra, output=None):
        return subprocess.run(
            [sys.executable, "-B", str(Path(__file__).parent / "notrios2sql.py"),
             "--input", str(self.fixture.archive), "--output", str(output or self.destination), *extra],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def assert_refused(self, result, code=1):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("phase: complete", result.stderr)
        self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))

    @staticmethod
    def phase_lines(result):
        return [line for line in result.stderr.splitlines() if line.startswith("phase: ")]

    def test_cli_create_and_identical_rerun_have_only_allowlisted_json(self):
        source_before = fixture_inventory(self.fixture.archive)
        expected = {
            "status": "created", "commit_sha256": self.expected["commit_sha256"],
            "selection_manifest_sha256": self.expected["selection_manifest_sha256"],
            "row_count": 18, "resource_count": 3,
        }
        result = self.cli("--expected-selection-sha256", self.expected["selection_manifest_sha256"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(result.stdout.count("\n"), 1)
        self.assertEqual(self.phase_lines(result), [
            "phase: verify", "phase: preflight", "phase: stage",
            "phase: staged rows=18 resources=3", "phase: seal", "phase: publish",
            "phase: complete rows=18 resources=3",
        ])
        self.assertNotIn(str(self.destination), result.stdout)
        before = fixture_inventory(self.destination)
        result = self.cli("--expected-selection-sha256", self.expected["selection_manifest_sha256"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(expected, status="unchanged"))
        self.assertEqual(self.phase_lines(result), [
            "phase: verify", "phase: preflight", "phase: verify-existing",
            "phase: verified-existing rows=18 resources=3",
            "phase: complete rows=18 resources=3",
        ])
        self.assertEqual(fixture_inventory(self.destination), before)
        self.assertEqual(fixture_inventory(self.fixture.archive), source_before)

    def test_cli_help_is_quiet_and_describes_only_safe_contract(self):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).parent / "notrios2sql.py"), "--help"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("--input", result.stdout)
        self.assertIn("--output", result.stdout)
        self.assertIn("--expected-selection-sha256", result.stdout)
        self.assertIn("No overwrite or merge", result.stdout)
        help_text = " ".join(result.stdout.split())
        self.assertIn("stdout contains one JSON summary line", help_text)
        self.assertIn("phase/count progress and errors use stderr", help_text)
        self.assertIn("Usage errors exit 2 and import errors exit 1", help_text)
        self.assertNotIn("--overwrite", result.stdout)
        self.assertNotIn("--merge", result.stdout)
        self.assertFalse(self.destination.exists())

    def test_cli_digest_mismatch_and_changed_source_refuse_without_output_changes(self):
        self.assert_refused(self.cli("--expected-selection-sha256", "0" * 64))
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.cli().returncode, 0)
        before = fixture_inventory(self.destination)
        self.assert_refused(self.cli("--expected-selection-sha256", "0" * 64))
        records = self.fixture.envelopes()
        notebook = next(r["payload"] for r in records if r["type"] == "notebook")
        notebook["name"] = "Changed publication notebook"
        self.fixture.write_records(records)
        result = self.cli()
        self.assert_refused(result)
        self.assertIn("receipt", result.stderr)
        self.assertEqual(fixture_inventory(self.destination), before)

    def test_cli_conflicting_and_edited_destinations_are_not_overwritten(self):
        self.destination.mkdir()
        sentinel = self.destination / "unrelated"
        sentinel.write_bytes(b"existing bytes")
        before = fixture_inventory(self.destination)
        self.assert_refused(self.cli())
        self.assertEqual(fixture_inventory(self.destination), before)
        completed = self.root / "completed"
        self.assertEqual(self.cli(output=completed).returncode, 0)
        resource = next((completed / "resources").iterdir())
        resource.write_bytes(b"edited bytes")
        before = fixture_inventory(completed)
        self.assert_refused(self.cli(output=completed))
        self.assertEqual(fixture_inventory(completed), before)

    def test_cli_usage_and_import_errors_have_no_success_summary(self):
        for extra in (("--overwrite",), ("--merge",), ("--input-extra", "x"),
                      ("--expected-selection-sha256", "BAD"), ("--max-blob-bytes", "100")):
            with self.subTest(extra=extra):
                self.assert_refused(self.cli(*extra), code=2)
                self.assertFalse(self.destination.exists())
        self.assert_refused(self.cli(output=self.root / "missing-parent" / "output"))
        sealing_script = """
import sys
from unittest import mock
import notrios2sql
with mock.patch.object(notrios2sql, '_complete', side_effect=OSError('injected sealing failure')):
    raise SystemExit(notrios2sql.main(sys.argv[1:]))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", sealing_script, "--input", str(self.fixture.archive),
             "--output", str(self.destination)],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assert_refused(result)
        self.assertIn("injected sealing failure", result.stderr)
        self.assertNotIn("phase: complete", result.stderr)
        self.assertFalse(self.destination.exists())

        preflight_script = """
import sys
from unittest import mock
import notrios2sql
from notrios_archive import NotriosError
with mock.patch.object(notrios2sql, '_preflight', side_effect=NotriosError('conversion', 'injected preflight failure')):
    raise SystemExit(notrios2sql.main(sys.argv[1:]))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", preflight_script, "--input", str(self.fixture.archive),
             "--output", str(self.destination)],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assert_refused(result)
        self.assertIn("injected preflight failure", result.stderr)
        self.assertNotIn("phase: complete", result.stderr)
        self.assertFalse(self.destination.exists())

        durability_script = """
import sys
from pathlib import Path
from unittest import mock
import notrios2sql
destination = Path(sys.argv[sys.argv.index('--output') + 1])
original = notrios2sql.os.fsync
def fail_parent_sync(fd):
    if destination.is_dir():
        raise OSError('injected parent durability failure')
    return original(fd)
with mock.patch.object(notrios2sql.os, 'fsync', fail_parent_sync):
    raise SystemExit(notrios2sql.main(sys.argv[1:]))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", durability_script, "--input", str(self.fixture.archive),
             "--output", str(self.destination)],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assert_refused(result)
        self.assertIn("durability", result.stderr)
        self.assertNotIn("phase: complete", result.stderr)
        self.assertTrue((self.destination / importer.COMPLETE).exists())

    def test_cli_cleanup_failure_after_publication_has_no_success_result(self):
        script = """
import sys
from unittest import mock
import notrios2sql
original = notrios2sql._OwnedDirectory.remove
def fail_work_cleanup(self, parent_fd):
    if self.name.startswith('.movenotes-notrios-work-'):
        raise OSError('injected owned cleanup failure')
    return original(self, parent_fd)
with mock.patch.object(notrios2sql._OwnedDirectory, 'remove', fail_work_cleanup):
    raise SystemExit(notrios2sql.main(sys.argv[1:]))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, "--input", str(self.fixture.archive),
             "--output", str(self.destination)],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("owned cleanup failed", result.stderr)
        self.assertIn("injected owned cleanup failure", result.stderr)
        self.assertNotIn("phase: complete", result.stderr)
        self.assertTrue((self.destination / importer.COMPLETE).exists())
        self.assertTrue(list(self.root.glob(".movenotes-notrios-work-*")))


class NotriosResourceSafetyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = NotriosObjectSpoolTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.destination = self.root / "publication"

    def assert_unpublished_and_clean(self):
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))

    def test_unreachable_resource_refuses_before_payload_creation(self):
        records = [r for r in self.fixture.envelopes() if not (
            r["type"] == "document_resource" and r["payload"]["resource_id"] == "res_sidecar")]
        self.fixture.write_records(records)
        before = fixture_inventory(self.fixture.archive)
        with mock.patch.object(importer, "_build_payload") as build:
            with self.assertRaises(archive_v2.NotriosError) as caught:
                importer.import_publication(self.fixture.archive, self.destination)
        self.assertEqual(caught.exception.code, "publication")
        self.assertIn("not reachable", str(caught.exception))
        build.assert_not_called()
        self.assertEqual(fixture_inventory(self.fixture.archive), before)
        self.assert_unpublished_and_clean()

    def test_private_resource_mutation_at_use_never_completes(self):
        before = fixture_inventory(self.fixture.archive)
        outside = self.root / "outside-sentinel"
        outside.write_bytes(b"must remain unchanged")
        copying = importer._copy_resource
        for damage in ("same-size bytes", "symlink"):
            calls = []
            def mutate(archive, ref, directory_fd, filename, limits):
                calls.append(filename)
                if len(calls) == 2:
                    relative = archive._spool.connection.execute(
                        "SELECT path FROM objects WHERE sha256=?", (ref.sha256,)
                    ).fetchone()[0]
                    private = archive._spool.directory / relative
                    if damage == "symlink":
                        private.unlink()
                        private.symlink_to(outside)
                    else:
                        private.chmod(0o600)
                        with private.open("r+b") as stream:
                            first = stream.read(1)
                            self.assertTrue(first)
                            stream.seek(0)
                            stream.write(bytes([first[0] ^ 1]))
                return copying(archive, ref, directory_fd, filename, limits)
            with self.subTest(damage=damage), mock.patch.object(importer, "_copy_resource", mutate), \
                    mock.patch.object(importer, "_complete") as complete:
                with self.assertRaises(archive_v2.NotriosError) as caught:
                    importer.import_publication(self.fixture.archive, self.destination)
                self.assertEqual(caught.exception.code, "integrity" if damage == "same-size bytes" else "io")
                self.assertEqual(len(calls), 2)
                complete.assert_not_called()
            self.assertEqual(outside.read_bytes(), b"must remain unchanged")
            self.assertEqual(fixture_inventory(self.fixture.archive), before)
            self.assert_unpublished_and_clean()

    def test_abrupt_resource_write_requires_explicit_stale_state_recovery(self):
        before = fixture_inventory(self.fixture.archive)
        # Exit inside the real resource writer, bypassing Python finally blocks.
        # Only this disposable child and its owned temporary tree are affected.
        script = r'''
import os
from pathlib import Path
import sys
from unittest import mock
import notrios2sql as importer
copying, fdopen = importer._copy_resource, os.fdopen
def interrupt(archive, ref, directory_fd, filename, limits):
    def opening(fd, mode, *args, **kwargs):
        stream = fdopen(fd, mode, *args, **kwargs)
        if mode != "wb":
            return stream
        class Writer:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                stream.close()
            def write(self, data):
                stream.write(data[:1])
                stream.flush()
                os._exit(73)
        return Writer()
    with mock.patch.object(importer.os, "fdopen", opening):
        return copying(archive, ref, directory_fd, filename, limits)
with mock.patch.object(importer, "_copy_resource", interrupt):
    importer.import_publication(Path(sys.argv[1]), Path(sys.argv[2]))
'''
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(self.fixture.archive), str(self.destination)],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
        self.assertFalse(self.destination.exists())
        lock, = self.root.glob(".movenotes-notrios-lock-*")
        owner = load_json(lock / importer.OWNER)
        stage, work = self.root / owner["stage"], self.root / owner["work"]
        for path in (stage, work):
            self.assertEqual(load_json(path / importer.OWNER)["token"], owner["token"])
        partial, = (stage / "resources").iterdir()
        self.assertEqual(partial.stat().st_size, 1)
        self.assertFalse((stage / importer.COMPLETE).exists())
        stale = {path.name: fixture_inventory(path) for path in (lock, stage, work)}
        with self.assertRaises(archive_v2.NotriosError) as caught:
            importer.import_publication(self.fixture.archive, self.destination)
        self.assertIn("lock exists", str(caught.exception))
        for path in (lock, stage, work):
            self.assertEqual(fixture_inventory(path), stale[path.name])
        # Simulate the documented operator procedure after confirming child exit:
        # inspect matching ownership, move these exact entries aside, then retry.
        quarantine = self.root / "inspected-stale-state"
        quarantine.mkdir()
        for path in (stage, work, lock):
            path.rename(quarantine / path.name)
        self.assertEqual(importer.import_publication(self.fixture.archive, self.destination).status, "created")
        self.assertEqual(importer.import_publication(self.fixture.archive, self.destination).status, "unchanged")
        for name, inventory in stale.items():
            self.assertEqual(fixture_inventory(quarantine / name), inventory)
        self.assertEqual(fixture_inventory(self.fixture.archive), before)
        self.assertFalse(list(self.root.glob(".movenotes-notrios-*")))


class NotriosResourceProjectionTest(unittest.TestCase):
    rows = NotriosNoteIntegrationTest.rows
    export = NotriosNoteIntegrationTest.export
    vault_notes = NotriosNoteIntegrationTest.vault_notes
    reimport_vault = NotriosTagRoundTripTest.reimport_vault

    def setUp(self):
        self.fixture = NotriosObjectSpoolTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.destination = self.root / "publication"
        self.vectors = load_json(FIXTURE_ROOT / "design-v1.json")
        self.ids = self.vectors["fixture_ids"]

    def add_resource(self, source_id, filename, mime, raw, *, document_id, ordinal):
        """Add a resource to this test's owned archive copy and rehash it."""
        digest, relative = self.fixture.put_object(raw)
        return self.add_resource_blob(source_id, filename, mime, digest, len(raw), relative,
                                      document_id=document_id, ordinal=ordinal)

    def add_resource_blob(self, source_id, filename, mime, digest, size, relative, *, document_id, ordinal):
        """Add a resource whose blob has already been streamed into the copy."""
        self.fixture.entries.append({
            "sha256": digest, "kind": "blob", "size_bytes": size,
            "media_type": mime,
            "location": {"layout": "fanout", "path": relative},
        })
        self.fixture.manifest["totals"]["objects"] += 1
        self.fixture.manifest["totals"]["blobs"] += 1
        self.fixture.manifest["totals"]["bytes"] += size
        records = self.fixture.envelopes()
        original = next(r["payload"] for r in records if r["type"] == "resource")
        resource = copy.deepcopy(original)
        resource.update(id=source_id, filename=filename, mime_type=mime,
                        blob={"sha256": digest, "size_bytes": size, "media_type": mime})
        records.append({"type": "resource", "payload": resource})
        relation = next(r["payload"] for r in records if r["type"] == "document_resource")
        related = copy.deepcopy(relation)
        related.update(document_id=document_id, resource_id=source_id,
                       relation_type="attachment", ordinal=ordinal)
        records.append({"type": "document_resource", "payload": related})
        self.fixture.write_records(records)
        return mapping.mapped_id(self.vectors["fixture_database_id"], "resource", (source_id,))

    @staticmethod
    def attachment_digest(path):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def wiki_target(body):
        match = re.search(r"!\[\[(.*?)\]\]", body)
        if match is None:
            raise AssertionError("expected an Obsidian wiki embed")
        return match.group(1)

    def test_full_publication_frozen_bodies_relations_vault_and_noop(self):
        result = importer.import_publication(self.fixture.archive, self.destination)
        self.assertEqual((result.row_count, result.resource_count), (18, 3))
        for row in self.rows():
            if row["joplin_type_"] == 1:
                source = next(k for k, v in self.ids["document"].items() if v == row["joplin_id"])
                self.assertEqual(row["note_data"], self.vectors["fixture_projected_notes"][source]["body"])
        with sqlite3.connect(self.destination / "notesdb.sqlite") as conn:
            relations = conn.execute("SELECT note_id,resource_id,relation_type,ordinal FROM notrios_document_resources").fetchall()
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notrios_preserved_resources'"
            ).fetchone())
            expected = [(self.ids["document"][r["document_id"]], self.ids["resource"][r["resource_id"]],
                         r["relation_type"], r["ordinal"]) for r in load_json(PUBLICATION_ROOT / "expected.json")["document_resources"]]
            self.assertEqual(set(relations), set(expected))
        before = fixture_inventory(self.destination)
        self.assertEqual(importer.import_publication(self.fixture.archive, self.destination).status, "unchanged")
        self.assertEqual(fixture_inventory(self.destination), before)
        vault = self.export()
        manifest = load_json(vault / ".movenotes/manifest.json")
        self.assertEqual(set(manifest["attachments"]), set(self.ids["resource"].values()))
        self.assertEqual(len(list((vault / "attachments").iterdir())), 3)
        expected_resources = load_json(PUBLICATION_ROOT / "expected.json")["resources"]
        for source, ident in self.ids["resource"].items():
            raw = (vault / manifest["attachments"][ident]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected_resources[source]["sha256"])
        notes = self.vault_notes(vault)
        public = notes[self.ids["document"]["doc_public"]][2]
        child = notes[self.ids["document"]["doc_child"]][2]
        image = Path(manifest["attachments"][self.ids["resource"]["res_image"]]).name
        self.assertIn(f"![[{image}]]", public)
        self.assertIn(f"![[{image}]]", child)
        self.assertIn("- [related.bin](../attachments/related.bin)", public)
        self.assertIn("Download [field notes](../attachments/field%20notes.txt)", public)
        for item in manifest["items"]:
            if item["type"] == 1:
                self.assertEqual(hashlib.sha256((vault / item["obsidian_path"]).read_bytes()).hexdigest(), item["obsidian_sha256"])
        self.reimport_vault(vault, "restored")
        restored = self.export("restored-vault")
        restored_manifest = load_json(restored / ".movenotes/manifest.json")
        self.assertEqual(set(restored_manifest["attachments"]), set(self.ids["resource"].values()))
        self.assertEqual(restored_manifest["attachments"], manifest["attachments"])
        self.assertEqual(len(list((restored / "attachments").iterdir())), 3)
        for source, ident in self.ids["resource"].items():
            raw = (restored / restored_manifest["attachments"][ident]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected_resources[source]["sha256"])
        self.assertIn("## Attachments", self.vault_notes(restored)[self.ids["document"]["doc_public"]][2])
        original_items = {item["id"]: item for item in manifest["items"] if item["type"] == 1}
        restored_items = {item["id"]: item for item in restored_manifest["items"] if item["type"] == 1}
        for item_id, item in original_items.items():
            self.assertEqual((vault / item["obsidian_path"]).read_bytes(),
                             (restored / restored_items[item_id]["obsidian_path"]).read_bytes())
        edited_vault = self.root / "edited-vault"
        shutil.copytree(vault, edited_vault)
        public_path = edited_vault / original_items[self.ids["document"]["doc_public"]]["obsidian_path"]
        public_path.write_text(public_path.read_text(encoding="utf-8") + "\nUser edit\n", encoding="utf-8")
        self.reimport_vault(edited_vault, "edited-restored")
        edited = self.export("edited-restored-vault")
        self.assertIn("User edit", self.vault_notes(edited)[self.ids["document"]["doc_public"]][2])
        edited_manifest = load_json(edited / ".movenotes/manifest.json")
        edited_item = next(item for item in edited_manifest["items"]
                           if item["id"] == self.ids["document"]["doc_public"])
        self.assertEqual((edited / edited_item["obsidian_path"]).read_bytes(), public_path.read_bytes())
        self.reimport_vault(vault, "row-missing-restored")
        with sqlite3.connect(self.destination / "notesdb.sqlite") as conn:
            conn.execute("DELETE FROM notes WHERE joplin_id=?", (self.ids["resource"]["res_image"],))
        missing_restored = self.root / "row-missing-restored-vault"
        missing_restored.mkdir()
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).parent / "sql2obsidian.py"),
                                 "--input", str(self.destination), "--output", str(missing_restored)],
                                capture_output=True, text=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing mapped resource row", result.stdout + result.stderr)

    def test_selected_notebook_and_missing_resource(self):
        importer.import_publication(self.fixture.archive, self.destination)
        vault = self.export("child-vault", "--notebooks", "研究")
        manifest = load_json(vault / ".movenotes/manifest.json")
        image = self.ids["resource"]["res_image"]
        self.assertEqual(set(manifest["attachments"]), {image})
        self.assertEqual({i["id"] for i in manifest["items"] if i["type"] == 4}, {image})
        self.assertEqual(len(list((vault / "attachments").iterdir())), 1)
        (self.destination / "resources" / (image + ".png")).unlink()
        with self.assertRaises(archive_v2.NotriosError):
            importer.import_publication(self.fixture.archive, self.destination)
        (self.root / "missing-vault").mkdir()
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).parent / "sql2obsidian.py"),
                                 "--input", str(self.destination), "--output", str(self.root / "missing-vault")],
                                capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing mapped resource file", result.stdout + result.stderr)
        self.assertFalse((self.root / "missing-vault/.movenotes/manifest.json").exists())
        row_missing = self.root / "row-missing-publication"
        importer.import_publication(self.fixture.archive, row_missing)
        with sqlite3.connect(row_missing / "notesdb.sqlite") as conn:
            conn.execute("DELETE FROM notes WHERE joplin_id=?", (image,))
        row_missing_vault = self.root / "row-missing-vault"
        row_missing_vault.mkdir()
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).parent / "sql2obsidian.py"),
                                 "--input", str(row_missing), "--output", str(row_missing_vault)],
                                capture_output=True, text=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mapped link has no supported note target", result.stdout + result.stderr)
        self.assertFalse((row_missing_vault / ".movenotes/manifest.json").exists())
        self.reimport_vault(vault, "child-restored")
        child_restored = self.export("child-restored-vault", "--notebooks", "研究")
        child_manifest = load_json(child_restored / ".movenotes/manifest.json")
        self.assertEqual(child_manifest["attachments"], manifest["attachments"])
        self.assertEqual({item["id"] for item in child_manifest["items"] if item["type"] == 4}, {image})

    def test_receipt_and_summary_use_frozen_digests_and_allowlisted_fields(self):
        expected = load_json(PUBLICATION_ROOT / "expected.json")
        result = importer.import_publication(self.fixture.archive, self.destination)
        expected_summary = {
            "status": "created",
            "commit_sha256": expected["commit_sha256"],
            "selection_manifest_sha256": expected["selection_manifest_sha256"],
            "row_count": 18,
            "resource_count": 3,
        }
        self.assertEqual(result.summary(), expected_summary)
        self.assertEqual(set(result.summary()), {
            "status", "commit_sha256", "selection_manifest_sha256", "row_count", "resource_count",
        })
        self.assertNotIn("destination", result.summary())
        self.assertIsNot(result.summary(), result.summary())
        self.assertEqual(json.loads(json.dumps(result.summary(), ensure_ascii=False)), expected_summary)
        changed = result.summary()
        changed["status"] = "tampered"
        changed["commit_sha256"] = "0" * 64
        changed["row_count"] = 0
        self.assertEqual(result.summary(), expected_summary)

        expected_receipt = {
            "version": 1,
            "contract": "notrios-archive-v2",
            "contract_schema_version": 1,
            "reader_profile": "movenotes-publication-loose-v1",
            "mapper": "movenotes-notrios-v1",
            "commit_sha256": expected["commit_sha256"],
            "selection_manifest_sha256": expected["selection_manifest_sha256"],
            "snapshot_id": expected["snapshot_id"],
            "database_id": expected["database_id"],
            "target": "publication_handoff",
        }
        marker = load_json(self.destination / importer.COMPLETE)
        self.assertEqual(set(marker), {
            "version", "receipt", "inventory_sha256", "inventory_size_bytes", "file_count",
        })
        self.assertEqual(marker["receipt"], expected_receipt)
        with sqlite3.connect(self.destination / "notesdb.sqlite") as connection:
            saved = connection.execute("SELECT value FROM settings WHERE name=?", (importer.RECEIPT_KEY,)).fetchone()
        self.assertIsNotNone(saved)
        self.assertEqual(json.loads(saved[0]), expected_receipt)
        self.assertEqual(saved[0], json.dumps(expected_receipt, ensure_ascii=False, separators=(",", ":")))

    def test_post_rename_durability_failure_keeps_receipt_without_success_result(self):
        expected = load_json(PUBLICATION_ROOT / "expected.json")
        expected_receipt = {
            "version": 1,
            "contract": "notrios-archive-v2",
            "contract_schema_version": 1,
            "reader_profile": "movenotes-publication-loose-v1",
            "mapper": "movenotes-notrios-v1",
            "commit_sha256": expected["commit_sha256"],
            "selection_manifest_sha256": expected["selection_manifest_sha256"],
            "snapshot_id": expected["snapshot_id"],
            "database_id": expected["database_id"],
            "target": "publication_handoff",
        }
        real_sync = os.fsync

        def fail_parent_sync(fd):
            if os.readlink(f"/proc/self/fd/{fd}") == str(self.root):
                raise OSError("injected post-rename fsync failure")
            return real_sync(fd)

        with mock.patch.object(importer.os, "fsync", fail_parent_sync):
            with self.assertRaises(archive_v2.NotriosError) as caught:
                importer.import_publication(self.fixture.archive, self.destination)
        self.assertIn("durability", str(caught.exception))
        self.assertTrue(self.destination.is_dir())
        marker = load_json(self.destination / importer.COMPLETE)
        self.assertEqual(marker["receipt"], expected_receipt)
        with sqlite3.connect(self.destination / "notesdb.sqlite") as connection:
            saved = connection.execute("SELECT value FROM settings WHERE name=?", (importer.RECEIPT_KEY,)).fetchone()
        self.assertEqual(json.loads(saved[0]), marker["receipt"])
        self.assertEqual(importer.import_publication(self.fixture.archive, self.destination).status, "unchanged")

    def test_shared_bytes_with_distinct_semantic_mime_stay_distinct(self):
        records = self.fixture.envelopes()
        original = next(r["payload"] for r in records if r["type"] == "resource" and r["payload"]["id"] == "res_image")
        twin = copy.deepcopy(original)
        twin.update(id="res_binary_twin", filename="same bytes.bin", mime_type="application/octet-stream")
        twin["blob"]["media_type"] = "application/octet-stream"
        records.append({"type": "resource", "payload": twin})
        relation = copy.deepcopy(next(r["payload"] for r in records if r["type"] == "document_resource" and
                                      r["payload"]["document_id"] == "doc_child"))
        relation.update(resource_id="res_binary_twin", relation_type="attachment", ordinal=1)
        records.append({"type": "document_resource", "payload": relation})
        self.fixture.write_records(records)
        result = importer.import_publication(self.fixture.archive, self.destination)
        self.assertEqual((result.row_count, result.resource_count), (19, 4))
        twin_id = mapping.mapped_id(self.vectors["fixture_database_id"], "resource", ("res_binary_twin",))
        vault = self.export("twin-vault", "--notebooks", "研究")
        manifest = load_json(vault / ".movenotes/manifest.json")
        self.assertEqual(set(manifest["attachments"]), {self.ids["resource"]["res_image"], twin_id})
        image_bytes = (vault / manifest["attachments"][self.ids["resource"]["res_image"]]).read_bytes()
        twin_bytes = (vault / manifest["attachments"][twin_id]).read_bytes()
        self.assertEqual(image_bytes, twin_bytes)
        self.assertTrue(manifest["attachments"][twin_id].endswith(".bin"))
        child = self.vault_notes(vault)[self.ids["document"]["doc_child"]][2]
        self.assertIn("## Attachments", child)
        self.assertIn("same%20bytes.bin", child)

    def test_duplicate_unicode_attachment_names_resolve_after_bundle_and_filter(self):
        records = self.fixture.envelopes()
        image = next(r["payload"] for r in records if r["type"] == "resource" and r["payload"]["id"] == "res_image")
        image["filename"] = "café & [chart]#.png"
        self.fixture.write_records(records)
        twin_id = self.add_resource(
            "res_duplicate_name", "café & [chart]#.png", "image/png", b"distinct png bytes",
            document_id="doc_child", ordinal=7,
        )
        image_id = self.ids["resource"]["res_image"]
        importer.import_publication(self.fixture.archive, self.destination)
        vault = self.export("duplicate-unicode-vault")
        manifest = load_json(vault / ".movenotes/manifest.json")
        paths = {ident: vault / relative for ident, relative in manifest["attachments"].items()}
        self.assertTrue({image_id, twin_id}.issubset(paths))
        self.assertNotEqual(paths[image_id].name, paths[twin_id].name)
        self.assertEqual(paths[image_id].name, "café & chart.png")
        self.assertEqual(paths[twin_id].name, "café & chart 2.png")
        public = self.vault_notes(vault)[self.ids["document"]["doc_public"]][2]
        self.assertIn("![[", public, public)
        self.assertEqual(self.wiki_target(public), paths[image_id].name)
        child_relative, _, child = self.vault_notes(vault)[self.ids["document"]["doc_child"]]
        href = next(value for value in re.findall(r"\]\(([^)]+)\)", child)
                    if "attachments/" in value)
        self.assertIn("caf%C3%A9%20%26%20chart%202.png", href)
        self.assertIn("café &amp; &#91;chart&#93;#.png", child)
        self.assertEqual((vault / PurePosixPath(child_relative).parent /
                          unquote(href)).resolve(), paths[twin_id].resolve())
        self.assertEqual(self.attachment_digest(paths[image_id]),
                         load_json(PUBLICATION_ROOT / "expected.json")["resources"]["res_image"]["sha256"])
        self.assertEqual(paths[twin_id].read_bytes(), b"distinct png bytes")
        self.reimport_vault(vault, "duplicate-unicode-restored")
        restored = self.export("duplicate-unicode-restored-vault")
        restored_manifest = load_json(restored / ".movenotes/manifest.json")
        self.assertEqual(restored_manifest["attachments"], manifest["attachments"])
        for ident, relative in manifest["attachments"].items():
            self.assertEqual((vault / relative).read_bytes(), (restored / restored_manifest["attachments"][ident]).read_bytes())
        filtered = self.export("duplicate-unicode-filtered", "--notebooks", "研究")
        filtered_manifest = load_json(filtered / ".movenotes/manifest.json")
        self.assertEqual(set(filtered_manifest["attachments"]), {image_id, twin_id})
        filtered_path = filtered / filtered_manifest["attachments"][twin_id]
        # Reimported snapshot metadata keeps the previously allocated name,
        # even though this filtered export writes a smaller note set.
        self.assertEqual(filtered_path.name, "café & chart 2.png")
        self.assertEqual(filtered_path.read_bytes(), b"distinct png bytes")

    def test_zero_and_large_opaque_attachments_stream_exact_bytes(self):
        zero_id = self.add_resource("res_zero", "empty [file].bin", "application/octet-stream", b"",
                                    document_id="doc_public", ordinal=20)
        block = bytes(range(251)) * 4096
        chunks = 9
        digest = hashlib.sha256()
        for _ in range(chunks):
            digest.update(block)
        large_size = len(block) * chunks
        self.assertGreater(large_size, 8 * 1024 * 1024)
        large_digest = digest.hexdigest()
        relative = f"objects/sha256/{large_digest[:2]}/{large_digest[2:4]}/{large_digest}"
        target = self.fixture.archive / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            for _ in range(chunks):
                handle.write(block)
        large_id = self.add_resource_blob("res_large", "large.dat", "application/octet-stream",
                                          large_digest, large_size, relative,
                                          document_id="doc_public", ordinal=21)
        reads = []
        original_read = archive_v2._CheckedBlob.read
        def tracked_read(stream, size=-1):
            if stream._ref.sha256 == large_digest:
                reads.append(size)
            return original_read(stream, size)
        with mock.patch.object(archive_v2._CheckedBlob, "read", tracked_read):
            importer.import_publication(self.fixture.archive, self.destination)
        self.assertTrue(reads)
        self.assertGreater(len(reads), 2)
        self.assertTrue(all(size == importer.DEFAULT_CONVERSION_LIMITS.copy_chunk_bytes for size in reads))
        with sqlite3.connect(self.destination / "notesdb.sqlite") as connection:
            self.assertEqual(connection.execute(
                "SELECT joplin_size FROM notes WHERE joplin_id=?", (large_id,)
            ).fetchone()[0], large_size)
        self.assertEqual(self.attachment_digest(self.destination / "resources" / (large_id + ".bin")), large_digest)
        vault = self.export("large-attachments-vault")
        manifest = load_json(vault / ".movenotes/manifest.json")
        self.assertEqual((vault / manifest["attachments"][zero_id]).stat().st_size, 0)
        large_path = vault / manifest["attachments"][large_id]
        self.assertEqual(large_path.stat().st_size, large_size)
        self.assertEqual(self.attachment_digest(large_path), large_digest)
        self.assertEqual(self.attachment_digest(
            vault / ".movenotes" / "joplin-raw" / "resources" / (large_id + ".bin")
        ), large_digest)
        self.reimport_vault(vault, "large-attachments-restored")
        restored = self.export("large-attachments-restored-vault")
        restored_manifest = load_json(restored / ".movenotes/manifest.json")
        self.assertEqual((restored / restored_manifest["attachments"][zero_id]).stat().st_size, 0)
        self.assertEqual(self.attachment_digest(
            restored / restored_manifest["attachments"][large_id]
        ), large_digest)

    def test_attachment_order_dedup_escaping_empty_body_and_limits(self):
        a, b = "a" * 32, "b" * 32
        attachments = [links.Attachment(a, "A&[x]<y>\\z", "unknown", 9),
                       links.Attachment(b, "B", "other", 2), links.Attachment(a, "A&[x]<y>\\z", "other", 1)]
        plan = links.validate_links(b"", [], resolve=lambda *args: a)
        projected = links.project_body(b"", plan, related_resources=attachments)
        self.assertEqual(projected, "\n\n## Attachments\n\n- [A&amp;&#91;x&#93;&lt;y&gt;&#92;z](:/" + a + ")\n- [B](:/" + b + ")\n")
        for limits in (ConversionLimits(max_resource_relations_per_note=2),
                       ConversionLimits(max_projected_body_bytes=len(projected.encode())-1),
                       ConversionLimits(max_links_per_note=1)):
            with self.subTest(limits=limits), self.assertRaises(archive_v2.NotriosError) as caught:
                plan = links.validate_links(b"", [], resolve=lambda *args: a, limits=limits)
                links.project_body(b"", plan, related_resources=attachments)
            self.assertEqual(caught.exception.code, "limit")
        with self.assertRaises(archive_v2.NotriosError) as caught:
            importer.import_publication(self.fixture.archive, self.destination,
                conversion_limits=ConversionLimits(max_resource_relations_per_note=1))
        self.assertEqual(caught.exception.code, "limit")
        self.assertFalse(self.destination.exists())

    def test_protected_resource_ids_do_not_copy_or_rewrite(self):
        resource_id = "a" * 32
        body = ("```markdown\n![chart](:/" + resource_id + ")\n```\n"
                "and `[chart](:/" + resource_id + ")`")
        lookup_type = mock.Mock()
        attachments = mock.Mock()
        self.assertEqual(links.rewrite_projected_links(
            body, note_id="b" * 32, note_path=PurePosixPath("nested/note.md"),
            lookup_item_type=lookup_type, lookup_note_path=mock.Mock(), attachments=attachments), body)
        lookup_type.assert_not_called()
        attachments.vault_name.assert_not_called()

    def test_rehashed_resource_link_without_owning_relation_refuses(self):
        records = self.fixture.envelopes()
        records = [r for r in records if not (r["type"] == "document_resource" and
                   r["payload"]["document_id"] == "doc_public" and r["payload"]["resource_id"] == "res_image")]
        self.fixture.write_records(records)
        with self.fixture.verify():
            pass  # The shared resource is still reachable from the child note.
        with self.assertRaises(archive_v2.NotriosError) as caught:
            importer.import_publication(self.fixture.archive, self.destination)
        self.assertEqual(caught.exception.code, "conversion")
        self.assertIn("no document-resource relation", str(caught.exception))
        self.assertFalse(self.destination.exists())


class NotriosSiteTagTest(unittest.TestCase):
    setUp = NotriosSchema28Test.setUp
    export = NotriosNoteIntegrationTest.export
    vault_notes = NotriosNoteIntegrationTest.vault_notes

    def test_written_tags_and_generated_words_through_real_site_generation(self):
        import obsidian2site
        source = self.fixtures / "publication-text/archive"
        importer.import_publication(source, self.destination)
        vault = self.export()
        vault_tags = {path: metadata["tags"] for path, metadata, _ in self.vault_notes(vault).values()}
        self.assertEqual(sorted(vault_tags.values()),
                         sorted([["café", "published", "research notes"],
                                 ["published", "東京"], ["published"]]))
        for cap in (None, 1):
            with self.subTest(taxonomy_cap=cap):
                site = self.root / ("site-default" if cap is None else "site-capped")
                command = [sys.executable, "-B", str(Path(__file__).parent / "obsidian2site.py"),
                           "--input", str(vault), "--output", str(site), "--progress-every", "0"]
                if cap is not None:
                    command.extend(["--max-taxonomy-tags", str(cap)])
                result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                search = {r["url"]: r for r in read_fixture_jsonl(site / "server/search-source.jsonl")}
                self.assertEqual(len(search), 3)
                observed_paths = set()
                for path in (site / "content/notes").rglob("*.md"):
                    if path.name == "_index.md":
                        continue
                    metadata = json.loads(path.read_text().split("\n", 1)[0])
                    source_path = metadata["movenotes_source_path"]
                    observed_paths.add(source_path)
                    written = vault_tags[source_path]
                    row = search[metadata["url"]]
                    self.assertEqual(row["tags"], written)
                    self.assertEqual(metadata.get("tags", []), written if cap is None else ["published"])
                    self.assertNotIn("préface", row["tags"])
                    self.assertNotIn("préface", metadata.get("tags", []))
                self.assertEqual(observed_paths, set(vault_tags))
                # Prove generated words were indexed, not silently disabled.
                for tag, count in (("préface", 1), ("research notes", 1), ("published", 3)):
                    bucket = f"{obsidian2site._tag_posting_bucket(tag):03x}"
                    postings = load_json(site / "static/movenotes/tag-postings" / (bucket + ".json"))
                    self.assertEqual(len(postings[tag]), count)
                    if tag == "préface":
                        body_rows = [r for r in search.values() if "préface" in r["body"].casefold()]
                        self.assertEqual(len(body_rows), 1)
                        self.assertEqual(postings[tag], [body_rows[0]["id"]])


class CollectionCapabilitiesOptionalTest(unittest.TestCase):
    """`capabilities` is accepted and never required on a collection record.

    Notrios wrote the same five words -- documents, search, resources, links,
    graph -- on every collection, so the array said nothing about the collection
    it was attached to, and v0.8 H16 stopped writing it. This verifier had it in
    the required half of the payload, so it would have refused every archive
    written after that change. The order mattered: this had to accept the
    absence before Notrios stopped writing it.
    """

    def _collection(self, **overrides):
        payload = {
            "id": "col_kkkkkkkkkkkkkkkkkkkkkkkkkk",
            "name": "Joplin export, January 2026",
            "settings_json": {},
            "created_at": "2026-01-01T00:00:00Z",
        }
        payload.update(overrides)
        return payload

    def test_record_without_capabilities_is_accepted(self):
        archive_v2._typed_record("collection", self._collection(), archive_v2.DEFAULT_LIMITS)

    def test_record_with_capabilities_is_still_accepted(self):
        archive_v2._typed_record(
            "collection",
            self._collection(capabilities=("documents", "graph", "links", "resources", "search")),
            archive_v2.DEFAULT_LIMITS)

    def test_unsorted_capabilities_are_still_refused_when_present(self):
        with self.assertRaises(archive_v2.NotriosError):
            archive_v2._typed_record(
                "collection",
                self._collection(capabilities=("search", "documents")),
                archive_v2.DEFAULT_LIMITS)

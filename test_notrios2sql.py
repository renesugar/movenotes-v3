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
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import notrios_archive as archive_v2
import notrios_mapping as mapping
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
        value = copy.deepcopy(self.base)
        value["compatibility"].update(source_schema_version=28, maximum_schema_version=99)
        self.parse(value)  # A future source/maximum is not a future-reader ceiling.

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
        self.archive = copy_publication(self.root / f"archive-{self.case}")
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


if __name__ == "__main__":
    unittest.main()

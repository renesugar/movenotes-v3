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
    """2b byte/index gates only; payload schema and graph tests start in 2d."""

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


if __name__ == "__main__":
    unittest.main()

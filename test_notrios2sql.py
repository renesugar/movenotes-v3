#!/usr/bin/env python3
"""Offline Notrios fixture baselines and manifest-admission tests.

The helpers read only the small, trusted synthetic fixture. They are not the
strict archive verifier and must not be used to admit untrusted publications.
Future mutation tests should copy the archive before changing any bytes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import copy
from dataclasses import FrozenInstanceError, fields
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
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
        with mock.patch.object(archive_v2, "read_bounded_json", side_effect=AssertionError("oversized file read")):
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


if __name__ == "__main__":
    unittest.main()

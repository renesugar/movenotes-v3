#!/usr/bin/env python3
"""Offline Notrios fixture baselines; no importer implementation is required.

The helpers read only the small, trusted synthetic fixture. They are not the
strict archive verifier and must not be used to admit untrusted publications.
Future mutation tests should copy the archive before changing any bytes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()

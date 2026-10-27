#!/usr/bin/env python3
"""Generate the tiny publication fixture with a pinned, unmodified Notrios CLI.

Development-only: this is neither an archive reader for users nor the future
Python verifier. Its assertions are deliberately specific to the synthetic seed.
Work directories are retained on failure for diagnosis; existing paths refuse.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess


PIN = "bdecfeda00e582d5aa6170d15b37ba27c9656f1d"
SOURCE = Path(__file__).resolve().parent
PUBLIC_IDS = {"doc_public", "doc_duplicate", "doc_child"}
EXPECTED_COUNTS = {
    "collections": 1, "notebooks": 2, "search_notebooks": 0, "tags": 4,
    "documents": 3, "revisions": 3, "document_tags": 6, "resources": 3,
    "document_resources": 4, "links": 8, "provenance": 0, "source_bundles": 0,
}
FORBIDDEN = [
    "doc_private", "doc_draft", "res_hidden", "PRIVATE_TITLE_SENTINEL_1B",
    "PRIVATE_BODY_SENTINEL_1B", "DRAFT_TITLE_SENTINEL_1B",
    "DRAFT_BODY_SENTINEL_1B", "PRIVATE_RESOURCE_SENTINEL_1B",
    "HISTORY_ONLY_SENTINEL_1B", "No Such Fixture Note",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_time(value: str) -> datetime:
    # Notrios stores SQLite CURRENT_TIMESTAMP text as UTC and exports RFC3339.
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inventory(path: Path) -> dict:
    return {
        file.relative_to(path).as_posix(): {"sha256": digest(file.read_bytes()), "size_bytes": file.stat().st_size}
        for file in sorted(path.rglob("*")) if file.is_file()
    }


def source_audit(db: Path) -> dict:
    # The CLI alone writes the disposable library. SQL is only an independent
    # readback proving that excluded notes/resources and old history existed.
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        documents = [dict(row) for row in conn.execute(
            "SELECT id, notebook_id, current_revision_id, created_at, updated_at "
            "FROM documents ORDER BY id"
        )]
        revisions = dict(conn.execute(
            "SELECT document_id, count(*) FROM document_revisions GROUP BY document_id"
        ))
        resources = [row[0] for row in conn.execute("SELECT id FROM resources ORDER BY id")]
        history = conn.execute(
            "SELECT count(*) FROM document_revisions WHERE body LIKE ?",
            ("%HISTORY_ONLY_SENTINEL_1B%",),
        ).fetchone()[0]
        require(revisions.get("doc_public") == 2 and history == 1, "source must contain old history")
        require({row["id"] for row in documents} == PUBLIC_IDS | {"doc_private", "doc_draft"}, "source note set")
        require(set(resources) == {"res_image", "res_text", "res_sidecar", "res_hidden"}, "source resource set")
        return {"documents": documents, "revision_counts": revisions, "resource_ids": resources,
                "historical_sentinel_revisions": history, "schema_version": conn.execute("PRAGMA user_version").fetchone()[0]}


def check_publication(archive: Path, plan: dict, run: dict, audit: dict) -> dict:
    """Check known tiny output, independently of the producer's success report."""
    manifest = json.loads((archive / "manifest.json").read_bytes())
    report = run["report"]
    require(manifest["snapshot"]["target"] == "publication_handoff", "publication target")
    require(manifest["counts"] == EXPECTED_COUNTS, f"unexpected counts: {manifest['counts']}")
    require(report["verified"] is True and report["full_backup"] is False, "verified projection required")
    require(report["skipped_rewrites"] == report["cleared_link_targets"] == 0, "unhandled rewrite")
    require(report["rewritten_links"] == 3 and report["rewritten_documents"] == 1, "rewrite counts")
    require(report["counts"] == EXPECTED_COUNTS and report["selected_documents"] == 3, "run counts")
    require(plan["plan"]["counts"]["selected_documents"] == 3, "nonempty reviewed selection")
    require(manifest["commit_sha256"] == report["commit_sha256"], "commit/report mismatch")
    require(manifest["snapshot"]["selection_manifest_sha256"] == report["selection_manifest_sha256"]
            == plan["plan"]["manifest_sha256"], "reviewed digest mismatch")
    require(manifest["totals"].get("packs", 0) == 0, "fixture must be loose")

    def object_bytes(entry: dict) -> bytes:
        require(entry["location"]["layout"] == "fanout", "fanout required")
        sha = entry["sha256"]
        relative = f"objects/sha256/{sha[:2]}/{sha[2:4]}/{sha}"
        require(entry["location"]["path"] == relative, "hash path mismatch")
        raw = (archive / relative).read_bytes()
        require(len(raw) == entry["size_bytes"] and digest(raw) == sha, "object hash/size mismatch")
        return raw

    entries = {}
    records = defaultdict(list)
    for chunk in manifest["index"]:
        raw = object_bytes(chunk)
        require(raw.endswith(b"\n"), "index LF")
        lines = raw[:-1].split(b"\n")
        require(len(lines) == chunk["entries"], "index entry count")
        for line in lines:
            entry = json.loads(line)
            require(entry["sha256"] not in entries, "duplicate object")
            entries[entry["sha256"]] = entry
            payload = object_bytes(entry)
            if entry["kind"] == "records":
                require(payload.endswith(b"\n"), "records LF")
                for record_line in payload[:-1].split(b"\n"):
                    envelope = json.loads(record_line)
                    records[envelope["type"]].append(envelope["payload"])
            else:
                require(entry["kind"] == "blob", "unexpected object kind")
    require(list(entries) == sorted(entries), "index ordering")
    plural = {"document_tag": "document_tags", "document_resource": "document_resources",
              "search_notebook": "search_notebooks", "source_bundle": "source_bundles",
              "provenance": "provenance"}
    counts = Counter({plural.get(kind, kind + "s"): len(rows) for kind, rows in records.items()})
    require(all(counts[key] == value for key, value in EXPECTED_COUNTS.items()), "decoded counts")
    require(manifest["totals"]["objects"] == len(entries), "object totals")
    require(manifest["totals"]["bytes"] == sum(entry["size_bytes"] for entry in entries.values()), "byte totals")
    for file in archive.rglob("*"):
        if file.is_file():
            raw = file.read_bytes()
            require(all(needle.encode() not in raw for needle in FORBIDDEN), f"excluded sentinel in {file.name}")

    docs = {row["id"]: row for row in records["document"]}
    require(set(docs) == PUBLIC_IDS, "published note set")
    revisions = {row["document_id"]: row for row in records["revision"]}
    notebooks = {row["id"]: row for row in records["notebook"]}
    names = {row["name"]: row for row in notebooks.values()}
    require(set(names) == {"Public", "研究"} and names["研究"]["parent_id"] == names["Public"]["id"], "notebook hierarchy")
    tag_names = {row["id"]: row["name"] for row in records["tag"]}
    tags = defaultdict(list)
    for row in records["document_tag"]:
        tags[row["document_id"]].append(tag_names[row["tag_id"]])
    expected_tags = {"doc_public": ["café", "published", "research notes"],
                     "doc_duplicate": ["published"], "doc_child": ["published", "東京"]}
    source_docs = {row["id"]: row for row in audit["documents"]}
    notes = {}
    for ident in sorted(PUBLIC_IDS):
        seed = SOURCE / ("update-v1" if ident == "doc_public" else "seed-v1") / "notes" / f"{ident}.md"
        body = seed.read_text(encoding="utf-8").split("\n---\n\n", 1)[1]
        if ident == "doc_public":
            for before, after in [
                ("[withheld note](document://default/documents/doc_private)", "withheld note"),
                ("[unpublished](document://default/documents/doc_draft)", "unpublished"),
                ("[missing label](No Such Fixture Note)", "missing label"),
            ]:
                require(body.count(before) == 1, "seed rewrite expectation")
                body = body.replace(before, after)
        revision = revisions[ident]
        actual_body = object_bytes(entries[revision["body"]["sha256"]])
        require(actual_body == body.encode(), f"published body changed unexpectedly: {ident}")
        require(docs[ident]["current_revision_id"] == revision["id"] == source_docs[ident]["current_revision_id"], "current revision ownership")
        require(all(utc_time(docs[ident][field]) == utc_time(source_docs[ident][field])
                    for field in ["created_at", "updated_at"]), "source timestamps changed")
        require(docs[ident].get("deleted_at", "") == "" and revision["metadata_json"] == {}, "publication state")
        require(sorted(tags[ident]) == expected_tags[ident], f"tag mismatch: {ident}")
        title = "Child 東京" if ident == "doc_child" else "Café & field notes"
        require(revision["title"] == title, f"title mismatch: {ident}")
        require(docs[ident]["notebook_id"] == names["研究" if ident == "doc_child" else "Public"]["id"], "note parent")
        notes[ident] = {"title": title, "body": body, "body_sha256": digest(actual_body),
                        "tags": expected_tags[ident], "notebook_path": "Public/研究" if ident == "doc_child" else "Public",
                        "current_revision_id": revision["id"], "created_at": docs[ident]["created_at"],
                        "updated_at": docs[ident]["updated_at"]}

    resources = {}
    for resource in records["resource"]:
        ident = resource["id"]
        source = next((SOURCE / "seed-v1/resources").glob(ident + "__*"))
        raw = object_bytes(entries[resource["blob"]["sha256"]])
        require(raw == source.read_bytes(), "attachment bytes changed")
        resources[ident] = {"filename": resource["filename"], "mime_type": resource["mime_type"],
                            "sha256": digest(raw), "size_bytes": len(raw)}
    require(set(resources) == {"res_image", "res_text", "res_sidecar"}, "resource selection")
    links = []
    for link in records["link"]:
        body = notes[link["source_document_id"]]["body"].encode()
        span = body[link["source_start_byte"]:link["source_end_byte"]]
        require(link["raw_target"].encode() in span and span.startswith((b"[", b"![")), "link offset mismatch")
        require(link.get("context", "") == "" and link["resolution_status"] in {"resolved", "external"}, "retained link state")
        links.append(link)
    require(any(link.get("target_document_id") == "doc_child" for link in links), "child link absent")
    require(any(link["resolution_status"] == "external" for link in links), "external link absent")
    self_links = [link for link in links if link["display_text"] == "this section"]
    require(len(self_links) == 1, "self-anchor absent")
    self_link = self_links[0]
    require(self_link["raw_target"] == "" and self_link["target_document_id"] == "doc_public"
            and self_link["anchor_type"] == "heading" and self_link["anchor_value"] == "details",
            "self-anchor representation")
    require(notes["doc_public"]["body"].encode()[self_link["source_start_byte"]:self_link["source_end_byte"]]
            == b"[this section](#details)", "self-anchor span")
    require(not any(link.get("target_resource_id") == "res_sidecar" for link in links), "sidecar must be relation-only")
    return {"fixture_version": 1, "producer_commit": PIN,
            "commit_sha256": manifest["commit_sha256"],
            "selection_manifest_sha256": manifest["snapshot"]["selection_manifest_sha256"],
            "snapshot_id": manifest["snapshot"]["id"], "database_id": manifest["snapshot"]["database_id"],
            "counts": EXPECTED_COUNTS, "totals": manifest["totals"], "notes": notes,
            "resources": resources, "notebooks": records["notebook"],
            "document_resources": records["document_resource"], "retained_links": links,
            "forbidden_in_archive": FORBIDDEN, "archive_files": inventory(archive)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notriosctl", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path, help="new disposable directory, retained for diagnosis")
    parser.add_argument("--output", required=True, type=Path, help="new fixture directory; existing output refuses")
    args = parser.parse_args()
    binary, work, output = args.notriosctl.resolve(), args.work_dir.resolve(), args.output.resolve()
    require(not work.exists() and not output.exists(), "work and output must both be new paths")
    require(work not in output.parents and output not in work.parents, "work and output must not overlap")
    build_info = subprocess.check_output(["go", "version", "-m", str(binary)], text=True)
    require(f"vcs.revision={PIN}\n" in build_info and "vcs.modified=false\n" in build_info, "CLI must be built from the clean pinned revision")
    work.mkdir(parents=True)
    (work / "logs").mkdir()
    (work / "empty-config.yaml").write_text("# Explicit fixture-only configuration; all roots follow --db.\n")
    for name in ["seed-v1", "update-v1"]:
        shutil.copytree(SOURCE / name, work / name)
    shared = ["--config", str(work / "empty-config.yaml"), "--db", str(work / "library/notes.sqlite"),
              "--asset-store", str(work / "library/assets")]
    publish_flags = shared + ["--profiles", str(work / "library/publish-profiles.json"), "--profile", "fixture"]
    reports = {}
    commands = []

    def run(name: str, arguments: list[str]) -> dict:
        print(f"{name}...", flush=True)
        result = subprocess.run([str(binary), *arguments], cwd=work, capture_output=True, text=True, timeout=120)
        log = {"argv": [str(binary), *arguments], "exit_code": result.returncode,
               "stdout": result.stdout, "stderr": result.stderr}
        write_json(work / "logs" / (name + ".json"), log)
        require(result.returncode == 0, f"{name} failed: {result.stderr}")
        value = json.loads(result.stdout)
        reports[name] = value
        commands.append({"stage": name, "argv": log["argv"], "exit_code": 0, "stderr": result.stderr})
        return value

    initial = run("import-initial", ["import", "archive", *shared, str(work / "seed-v1")])
    require(initial["notes_imported"] == 5 and initial["resources_created"] == 4, "initial import counts")
    updated = run("import-update", ["import", "archive", *shared, str(work / "update-v1")])
    require(updated["notes_updated"] == 1, "must create a historical revision")
    audit = source_audit(work / "library/notes.sqlite")
    public_notebook = next(row["notebook_id"] for row in audit["documents"] if row["id"] == "doc_public")
    run("profile-save", ["publish", "profile", "save", *shared, "--profiles", str(work / "library/publish-profiles.json"),
                         "--name", "fixture", "--target", "publication_handoff", "--notebooks", public_notebook, "--link-action", "plain_text"])
    plan = run("plan", ["publish", "plan", *publish_flags])
    require(plan["plan"]["counts"]["selected_documents"] == 3, "reviewed selection must have three public notes")
    archive = work / "publication"
    published = run("publish-run", ["publish", "run", *publish_flags, "--reviewed-plan", plan["plan"]["manifest_sha256"], str(archive)])
    compatibility = run("compatibility", ["compatibility", "archive-v2", "--reader", "previous-loose-v2", str(archive)])
    require(compatibility["decision"] == "accept", "loose declaration must be accepted")
    verified = run("verify", ["verify", "archive-v2", str(archive)])
    expected = check_publication(archive, plan, published, audit)
    require(verified["commit_sha256"] == expected["commit_sha256"] and verified["counts"] == EXPECTED_COUNTS, "independent verification report mismatch")

    def sanitize(value):
        if isinstance(value, str):
            return value.replace(str(work), "<work>").replace(str(binary), "<notriosctl>")
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if isinstance(value, dict):
            return {key: sanitize(item) for key, item in value.items()}
        return value

    output.mkdir(parents=True)
    shutil.copytree(archive, output / "archive")
    (output / "reports").mkdir()
    for name, report in reports.items():
        write_json(output / "reports" / (name + ".json"), sanitize(report))
    write_json(output / "expected.json", expected)
    write_json(output / "source-audit.json", audit)
    write_json(output / "generation.json", {
        "producer_commit": PIN, "cli_sha256": digest(binary.read_bytes()),
        "build_info": build_info.replace(str(binary), "<notriosctl>"),
        "seed_files": inventory(SOURCE / "seed-v1"), "update_files": inventory(SOURCE / "update-v1"),
        "generator_sha256": digest(Path(__file__).read_bytes()), "commands": sanitize(commands),
        "sanitization": "Only work-directory and executable paths in reports/commands are replaced; archive bytes are unchanged.",
        "reproduction": "Fresh generation is semantically equivalent, not byte-identical: Notrios chooses IDs and timestamps.",
    })
    require(inventory(output / "archive") == expected["archive_files"], "fixture copy changed archive bytes")
    print(f"Fixture verified and saved to {output}")
    print(f"commit_sha256={expected['commit_sha256']}")
    print(f"selection_manifest_sha256={expected['selection_manifest_sha256']}")


if __name__ == "__main__":
    main()

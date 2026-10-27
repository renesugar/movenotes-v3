#!/usr/bin/env python3
"""Generate a sanitized titled-link handoff through the released producer CLI.

S43b: Notrios v1.0.0 (J43) keeps a link's title when its Obsidian importer
rewrites the destination. Only the CLI writes the disposable source library or
archive. Existing output and work directories refuse; failed work remains
available for diagnosis. Assertions read raw archive bytes, independently of
the movenotes verifier and link scanner.
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import generate_publication as original

PIN = "2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a"
TAG = "v1.0.0"
SOURCE = Path(__file__).resolve().parent
VAULT = SOURCE / "vault-titled-v1"
DOC = "document://default/documents/doc_obsidian_public_"
# The producer's rewritten bodies, title bytes copied after the canonical URI.
TITLED = [
    f'[Child]({DOC}deep_child "Child title")',
    f"[Other]({DOC}other_note 'Other title')",
    f"[Again]({DOC}deep_child#details (Section title))",
    f'[Tabbed]({DOC}deep_child\t"Tab title")',
    f'[Café]({DOC}deep_child "Titre é 東京 [x] (y)")',
    f'[Blank]({DOC}deep_child "")',
    '![shot](resource://default/resources/res_obsidian_public_shot "Photo title")',
    '[Web](https://example.test/x "Web title")',
    f"[Plain]({DOC}deep_child)",
    '[Here](#home "Self title")',
    f'[Home]({DOC}home "Home title")',
]
ABSENT = ["PRIVATE-BODY-SENTINEL", "WITHHELD-TITLE-SENTINEL", "Private/Secret.md", "doc_obsidian_private"]
COUNTS = {"collections": 1, "notebooks": 2, "search_notebooks": 0, "tags": 3, "documents": 3, "revisions": 3,
          "document_tags": 4, "resources": 1, "document_resources": 1, "links": 11, "provenance": 0,
          "source_bundles": 0}
TAGS = [("titled", "home"), ("titled", "deep_child"), ("café", "home"), ("東京", "other_note"),
        ("private-only", None)]


def archive_bytes(archive):
    return b"".join(path.read_bytes() for path in sorted(archive.rglob("*")) if path.is_file())


def generate(binary, work, output, build_info):
    work.mkdir(parents=True)
    (work / "empty.yaml").write_text("# Isolated synthetic fixture configuration.\n")
    shutil.copytree(VAULT, work / "vault")
    shared = ["--config", str(work / "empty.yaml"), "--db", str(work / "library/notes.sqlite"),
              "--asset-store", str(work / "library/assets")]
    profiles = ["--profiles", str(work / "library/profiles.json")]
    commands, reports = [], {}

    def run(name, arguments, report=True):
        print(name, flush=True)
        result = subprocess.run([str(binary), *arguments], cwd=work, capture_output=True,
                                text=True, timeout=120)
        original.write_json(work / (name + ".json"), {"argv": arguments,
                            "stdout": result.stdout, "stderr": result.stderr,
                            "exit_code": result.returncode})
        original.require(result.returncode == 0, f"{name}: {result.stderr}")
        commands.append({"stage": name, "argv": [str(binary), *arguments],
                         "exit_code": result.returncode})
        if report:
            reports[name] = json.loads(result.stdout)
            return reports[name]
        return None

    run("import-obsidian", ["import", "obsidian", *shared, str(work / "vault")])
    for number, (tag, document) in enumerate(TAGS):
        # The private-only tag sits on the withheld note, so it must not publish.
        target = "doc_obsidian_private_secret" if document is None else "doc_obsidian_public_" + document
        run(f"tag-{number}", ["tags", "add", *shared, "--tag", tag, "--document", target], report=False)
    db = work / "library/notes.sqlite"
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    original.require(schema == 28, "source database must be schema 28")
    run("profile-save", ["publish", "profile", "save", *shared, *profiles, "--name", "fixture",
                         "--target", "publication_handoff",
                         "--notebooks", "nb_obsidian_public,nb_obsidian_public_deep",
                         "--link-action", "plain_text"])
    flags = [*shared, *profiles, "--profile", "fixture"]
    plan = run("plan", ["publish", "plan", *flags])
    archive = work / "archive"
    published = run("publish-run", ["publish", "run", *flags, "--reviewed-plan",
                                    plan["plan"]["manifest_sha256"], str(archive)])
    compatibility = run("compatibility", ["compatibility", "archive-v2", "--reader", "current-v2", str(archive)])
    verified = run("verify", ["verify", "archive-v2", str(archive)])
    manifest = json.loads((archive / "manifest.json").read_bytes())
    original.require(compatibility["decision"] == "accept", "producer compatibility refusal")
    original.require(manifest["compatibility"]["source_schema_version"] == 28 and
                     manifest["compatibility"]["minimum_schema_version"] == 12 and
                     manifest["compatibility"]["maximum_schema_version"] == 28, "schema declaration")
    original.require(manifest["snapshot"]["target"] == "publication_handoff", "target")
    original.require(manifest["commit_sha256"] == verified["commit_sha256"] == published["report"]["commit_sha256"], "commit agreement")
    original.require(manifest["snapshot"]["selection_manifest_sha256"] == plan["plan"]["manifest_sha256"]
                     == published["report"]["selection_manifest_sha256"], "selection agreement")
    original.require(manifest["counts"] == verified["counts"] == COUNTS, f"counts {manifest['counts']}")
    original.require(published["report"]["rewritten_links"] == 1 and published["report"]["skipped_rewrites"] == 0,
                     "exactly one withheld rewrite, none skipped")
    contents = archive_bytes(archive)
    for token in TITLED:
        original.require(contents.count(token.encode()) == 1, f"titled token missing: {token!r}")
    original.require(b"Withheld Secret." in contents, "withheld link rewritten to its label")
    for sentinel in ABSENT:
        original.require(sentinel.encode() not in contents, f"excluded content published: {sentinel}")
    original.require(b"private-only" not in contents, "withheld note's tag published")
    expected = {"counts": COUNTS, "archive_files": original.inventory(archive),
                "commit_sha256": manifest["commit_sha256"],
                "selection_manifest_sha256": manifest["snapshot"]["selection_manifest_sha256"],
                "database_id": manifest["snapshot"]["database_id"], "snapshot_id": manifest["snapshot"]["id"],
                "producer_commit": PIN, "producer_tag": TAG, "titled_tokens": TITLED,
                "absent": ABSENT,
                # Records the differential audit's injected references must name.
                "audit_targets": {"document": "doc_obsidian_public_home",
                                  "resource": "res_obsidian_public_shot"}}

    def sanitize(value):
        if isinstance(value, str):
            return value.replace(str(work), "<work>").replace(str(binary), "<notriosctl>")
        if isinstance(value, list):
            return [sanitize(v) for v in value]
        if isinstance(value, dict):
            return {k: sanitize(v) for k, v in value.items()}
        return value

    output.mkdir(parents=True)
    shutil.copytree(archive, output / "archive")
    (output / "reports").mkdir()
    for name, report in reports.items():
        original.write_json(output / "reports" / (name + ".json"), sanitize(report))
    original.write_json(output / "expected.json", expected)
    original.write_json(output / "generation.json", {
        "producer_commit": PIN, "producer_tag": TAG, "cli_sha256": original.digest(binary.read_bytes()),
        "build_info": build_info.replace(str(binary), "<notriosctl>"),
        "vault_files": original.inventory(VAULT),
        "generator_sha256": original.digest(Path(__file__).read_bytes()),
        "helper_sha256": original.digest(Path(original.__file__).read_bytes()),
        "commands": sanitize(commands),
        "reproduction": "Fresh IDs/timestamps differ; compare semantic expectations. Archive bytes are unmodified.",
    })
    original.require(original.inventory(output / "archive") == expected["archive_files"], "copy changed bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notriosctl", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    binary, work, output = args.notriosctl.resolve(), args.work_dir.resolve(), args.output.resolve()
    original.require(not work.exists() and not output.exists(), "new work/output paths required")
    original.require(work not in output.parents and output not in work.parents, "overlapping paths")
    info = subprocess.check_output(["go", "version", "-m", str(binary)], text=True)
    original.require(f"vcs.revision={PIN}\n" in info and "vcs.modified=false\n" in info, "clean pinned binary required")
    generate(binary, work / "publication-titled", output / "publication-titled", info)


if __name__ == "__main__":
    main()

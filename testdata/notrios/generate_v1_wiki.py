#!/usr/bin/env python3
"""Generate a publication with resolved wiki links through the released producer CLI.

W1: Notrios v1.0.0 stores a resolved wiki link with its canonical target,
`[[document://default/documents/<id>|alias]]`, and records it as a resolved
`obsidian-wikilink`. This fixture holds every such form a movenotes import maps:
plain, aliased, to a heading, embedded, and to an attachment. Only the CLI
writes the disposable source library or archive. Existing output and work
directories refuse; failed work remains available for diagnosis. Assertions
read raw archive bytes, independently of the movenotes verifier and link
scanner.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import generate_publication as original
from generate_v1_titled import PIN, TAG, archive_bytes

SOURCE = Path(__file__).resolve().parent
VAULT = SOURCE / "vault-wiki-v1"
DOC = "document://default/documents/doc_obsidian_public_"
RES = "resource://default/resources/res_obsidian_public_"
# The producer's body: each resolved wiki link holds its target's canonical URI.
BODY_LINES = [
    f"Plain [[{DOC}other_note]], aliased [[{DOC}other_note|shown & text]], to a heading "
    f"[[{DOC}deep_child#Café Section]] and aliased [[{DOC}deep_child#details|Details]].",
    f"By path [[{DOC}deep_child]], by file name [[{DOC}other_note]], titled [[{DOC}r_d_notes]], "
    "to itself [[#Links]] and to nothing Nowhere.",
    f"Embedded note ![[{DOC}other_note]], image ![[{RES}shot]], captioned ![[{RES}shot|caption]], "
    f"file [[{RES}doc]] and embedded file ![[{RES}doc]].",
    f"Markdown [Child]({DOC}deep_child#details) as before.",
]
# What a movenotes import must write in their place: Joplin links, as
# obsidian2sql.py writes for a wiki link. `{source ID}` is that note's or
# attachment's mapped ID.
PROJECTED_LINES = [
    "Plain [Other Note](:/{doc_obsidian_public_other_note}), aliased [shown &amp; text]"
    "(:/{doc_obsidian_public_other_note}), to a heading [Child](:/{doc_obsidian_public_deep_child}"
    "#Caf%C3%A9%20Section) and aliased [Details](:/{doc_obsidian_public_deep_child}#details).",
    "By path [Child](:/{doc_obsidian_public_deep_child}), by file name [Other Note]"
    "(:/{doc_obsidian_public_other_note}), titled [R&amp;D Notes](:/{doc_obsidian_public_r_d_notes}), "
    "to itself [[#Links]] and to nothing Nowhere.",
    "Embedded note [Other Note](:/{doc_obsidian_public_other_note}), image ![shot.png]"
    "(:/{res_obsidian_public_shot}), captioned ![caption](:/{res_obsidian_public_shot}), file [doc.pdf]"
    "(:/{res_obsidian_public_doc}) and embedded file ![doc.pdf](:/{res_obsidian_public_doc}).",
    "Markdown [Child](:/{doc_obsidian_public_deep_child}#details) as before.",
]
# And what the vault export writes for them: relative paths, Obsidian's own.
VAULT_LINES = [
    "Plain [Other Note](Other%20Note.md), aliased [shown &amp; text](Other%20Note.md), to a heading "
    "[Child](Deep/Child.md#Caf%C3%A9%20Section) and aliased [Details](Deep/Child.md#details).",
    "By path [Child](Deep/Child.md), by file name [Other Note](Other%20Note.md), titled "
    "[R&amp;D Notes](R%26D%20Notes.md), to itself [[#Links]] and to nothing Nowhere.",
    "Embedded note [Other Note](Other%20Note.md), image ![[shot.png]], captioned ![[shot.png]], "
    "file [doc.pdf](../attachments/doc.pdf) and embedded file [doc.pdf](../attachments/doc.pdf).",
    "Markdown [Child](Deep/Child.md#details) as before.",
]
COUNTS = {"collections": 1, "notebooks": 2, "search_notebooks": 0, "tags": 0, "documents": 4, "revisions": 4,
          "document_tags": 0, "resources": 2, "document_resources": 2, "links": 14, "provenance": 0,
          "source_bundles": 0}
STATUSES = {"resolved": 14}
WIKI_LINKS = 13
NOTEBOOKS = "nb_obsidian_public,nb_obsidian_public_deep"


def generate(binary, work, output, build_info):
    work.mkdir(parents=True)
    (work / "empty.yaml").write_text("# Isolated synthetic fixture configuration.\n")
    shutil.copytree(VAULT, work / "vault")
    shared = ["--config", str(work / "empty.yaml"), "--db", str(work / "library/notes.sqlite"),
              "--asset-store", str(work / "library/assets")]
    profiles = ["--profiles", str(work / "library/profiles.json")]
    commands, reports = [], {}

    def run(name, arguments):
        print(name, flush=True)
        result = subprocess.run([str(binary), *arguments], cwd=work, capture_output=True,
                                text=True, timeout=120)
        original.write_json(work / (name + ".json"), {"argv": arguments,
                            "stdout": result.stdout, "stderr": result.stderr,
                            "exit_code": result.returncode})
        original.require(result.returncode == 0, f"{name}: {result.stderr}")
        commands.append({"stage": name, "argv": [str(binary), *arguments],
                         "exit_code": result.returncode})
        reports[name] = json.loads(result.stdout)
        return reports[name]

    run("import-obsidian", ["import", "obsidian", *shared, str(work / "vault")])
    db = work / "library/notes.sqlite"
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    original.require(schema == 28, "source database must be schema 28")
    run("profile-save", ["publish", "profile", "save", *shared, *profiles, "--name", "fixture",
                         "--target", "publication_handoff", "--notebooks", NOTEBOOKS,
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
    original.require(manifest["snapshot"]["target"] == "publication_handoff", "target")
    original.require(manifest["commit_sha256"] == verified["commit_sha256"] == published["report"]["commit_sha256"], "commit agreement")
    original.require(manifest["snapshot"]["selection_manifest_sha256"] == plan["plan"]["manifest_sha256"]
                     == published["report"]["selection_manifest_sha256"], "selection agreement")
    original.require(manifest["counts"] == verified["counts"] == COUNTS, f"counts {manifest['counts']}")
    report = published["report"]
    original.require(report["rewritten_links"] == 1 and report["skipped_rewrites"] == 0
                     and report["cleared_link_targets"] == 0,
                     "plain_text rewrites only the unresolved [[Nowhere]] to its text")
    contents = archive_bytes(archive)
    for line in BODY_LINES:
        original.require(contents.count(line.encode()) == 1, f"body line missing: {line!r}")
    statuses, formats = Counter(), Counter()
    for line in contents.split(b"\n"):
        if line.startswith(b'{"type":"link"'):
            payload = json.loads(line)["payload"]
            statuses[payload["resolution_status"]] += 1
            formats[payload["source_format"]] += 1
    original.require(dict(statuses) == STATUSES, f"link statuses {dict(statuses)}")
    original.require(formats["obsidian-wikilink"] == WIKI_LINKS, f"link formats {dict(formats)}")
    expected = {"counts": COUNTS, "archive_files": original.inventory(archive),
                "commit_sha256": manifest["commit_sha256"],
                "selection_manifest_sha256": manifest["snapshot"]["selection_manifest_sha256"],
                "database_id": manifest["snapshot"]["database_id"], "snapshot_id": manifest["snapshot"]["id"],
                "producer_commit": PIN, "producer_tag": TAG, "body_lines": BODY_LINES,
                "projected_lines": PROJECTED_LINES, "vault_lines": VAULT_LINES, "link_statuses": STATUSES,
                "wiki_links": WIKI_LINKS}

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
    for name, value in reports.items():
        original.write_json(output / "reports" / (name + ".json"), sanitize(value))
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
    generate(binary, work / "publication-wiki", output / "publication-wiki", info)


if __name__ == "__main__":
    main()

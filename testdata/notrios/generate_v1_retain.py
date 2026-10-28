#!/usr/bin/env python3
"""Generate a `retain` link-action handoff through the released producer CLI.

R2: with `--link-action retain`, Notrios v1.0.0 keeps every link's bytes in a
published body. A link it could not resolve keeps its record, unresolved or
ambiguous, and a link to a note the publication leaves out keeps its canonical
URI with a `target_excluded` record. Only the CLI writes the disposable source
library or archive. Existing output and work directories refuse; failed work
remains available for diagnosis. Assertions read raw archive bytes,
independently of the movenotes verifier and link scanner.
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
VAULT = SOURCE / "vault-retain-v1"
WITHHELD = "document://default/documents/doc_obsidian_private_hidden_plan"
# The producer's body, every link's bytes kept: canonical URIs where it
# resolved a link, the destination as written everywhere else.
BODY_LINES = [
    f'Withheld [Plan]({WITHHELD} "WITHHELD-TITLE-SENTINEL"), [[{WITHHELD}]], [[{WITHHELD}|alias text]], '
    f"[[{WITHHELD}#Heading]] and ![[{WITHHELD}]].",
    "Stale [gone](document://default/documents/doc_no_such_note).",
    "Kept [file](file:///C:/Users/x/report.pdf), [tel](tel:+15551234567), ![data](data:image/png;base64,AAAA), "
    '[missing](Missing.md), [rel](notes/x.txt "Rel title"), [js](javascript:void(0)), '
    "[app](joplin://x-callback-url/openNote?id=1), [drive](C:\\Users\\x\\a.txt), [[Dup]] and [[No Such Note]].",
    "External [mail](mailto:someone@example.com) and [web](http://example.com/).",
    "Resolved [Other](document://default/documents/doc_obsidian_public_other).",
]
# What a movenotes import must write in their place.
PROJECTED_LINES = [
    "Withheld Plan, [redacted], alias text, [redacted] and [redacted].",
    "Stale gone.",
    BODY_LINES[2],
    BODY_LINES[3],
    None,  # The resolved link's destination is mapped, as on every route.
]
ABSENT = ["WITHHELD-BODY-SENTINEL", "Private/Hidden Plan.md"]
COUNTS = {"collections": 1, "notebooks": 3, "search_notebooks": 0, "tags": 0, "documents": 4, "revisions": 4,
          "document_tags": 0, "resources": 0, "document_resources": 0, "links": 19, "provenance": 0,
          "source_bundles": 0}
STATUSES = {"target_excluded": 5, "unresolved": 10, "ambiguous": 1, "external": 2, "resolved": 1}
NOTEBOOKS = "nb_obsidian_public,nb_obsidian_public_a,nb_obsidian_public_b"


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
                         "--link-action", "retain"])
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
    original.require(report["rewritten_links"] == 0 and report["skipped_rewrites"] == 0
                     and report["cleared_link_targets"] == STATUSES["target_excluded"],
                     "retain rewrites nothing and clears each withheld target")
    contents = archive_bytes(archive)
    for line in BODY_LINES:
        original.require(contents.count(line.encode()) == 1, f"body line missing: {line!r}")
    for sentinel in ABSENT:
        original.require(sentinel.encode() not in contents, f"excluded content published: {sentinel}")
    statuses = Counter()
    for line in contents.split(b"\n"):
        if line.startswith(b'{"type":"link"'):
            statuses[json.loads(line)["payload"]["resolution_status"]] += 1
    original.require(dict(statuses) == STATUSES, f"link statuses {dict(statuses)}")
    expected = {"counts": COUNTS, "archive_files": original.inventory(archive),
                "commit_sha256": manifest["commit_sha256"],
                "selection_manifest_sha256": manifest["snapshot"]["selection_manifest_sha256"],
                "database_id": manifest["snapshot"]["database_id"], "snapshot_id": manifest["snapshot"]["id"],
                "producer_commit": PIN, "producer_tag": TAG, "body_lines": BODY_LINES,
                "projected_lines": PROJECTED_LINES, "link_statuses": STATUSES,
                "withheld_links": STATUSES["target_excluded"] + 1, "withheld_uri": WITHHELD, "absent": ABSENT}

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
    generate(binary, work / "publication-retain", output / "publication-retain", info)


if __name__ == "__main__":
    main()

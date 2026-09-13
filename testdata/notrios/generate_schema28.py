#!/usr/bin/env python3
"""Generate two sanitized schema-28 handoffs through the pinned producer CLI.

Only the CLI writes the disposable source library or archive. Existing output
and work directories refuse; failed work remains available for diagnosis.
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import generate_publication as original

PIN = "7662fdd5b55d6f34f14874f70ba6db9f9e7676ac"
SOURCE = Path(__file__).resolve().parent


def generate(binary, work, output, text_only, build_info):
    work.mkdir(parents=True)
    (work / "empty.yaml").write_text("# Isolated synthetic fixture configuration.\n")
    seed = SOURCE / ("seed-text-v1" if text_only else "seed-v1")
    shutil.copytree(seed, work / "seed")
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
                         "exit_code": result.returncode, "stderr": result.stderr})
        reports[name] = json.loads(result.stdout)
        return reports[name]

    run("import-initial", ["import", "archive", *shared, str(work / "seed")])
    if not text_only:
        shutil.copytree(SOURCE / "update-v1", work / "update")
        run("import-update", ["import", "archive", *shared, str(work / "update")])
    db = work / "library/notes.sqlite"
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
        notebook = conn.execute("SELECT notebook_id FROM documents WHERE id='doc_public'").fetchone()[0]
        original.require(schema == 28, "source database must be schema 28")
    audit = {"schema_version": schema} if text_only else original.source_audit(db)
    run("profile-save", ["publish", "profile", "save", *shared, *profiles, "--name", "fixture",
                         "--target", "publication_handoff", "--notebooks", notebook,
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
    if text_only:
        counts = dict(original.EXPECTED_COUNTS, resources=0, document_resources=0, links=5)
        original.require(manifest["counts"] == verified["counts"] == counts, "text counts")
        original.require(published["report"]["skipped_rewrites"] == published["report"]["rewritten_links"] == 0, "text rewrites")
        expected = {"counts": counts, "archive_files": original.inventory(archive),
                    "commit_sha256": manifest["commit_sha256"],
                    "selection_manifest_sha256": manifest["snapshot"]["selection_manifest_sha256"],
                    "database_id": manifest["snapshot"]["database_id"], "snapshot_id": manifest["snapshot"]["id"]}
    else:
        expected = original.check_publication(archive, plan, published, audit)
    expected["producer_commit"] = PIN
    # Inspect actual records without changing or rehashing any producer bytes.
    collections = []
    for descriptor in manifest["index"]:
        for line in (archive / descriptor["location"]["path"]).read_bytes().split(b"\n"):
            if not line:
                continue
            entry = json.loads(line)
            if entry["kind"] == "records":
                for raw in (archive / entry["location"]["path"]).read_bytes().split(b"\n"):
                    if raw:
                        record = json.loads(raw)
                        if record["type"] == "collection":
                            collections.append(record["payload"])
    original.require(len(collections) == 1 and "capabilities" not in collections[0], "collection omission")

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
    original.write_json(output / "source-audit.json", audit)
    original.write_json(output / "generation.json", {
        "producer_commit": PIN, "cli_sha256": original.digest(binary.read_bytes()),
        "build_info": build_info.replace(str(binary), "<notriosctl>"),
        "seed_files": original.inventory(seed),
        "update_files": {} if text_only else original.inventory(SOURCE / "update-v1"),
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
    for name, text_only in (("publication-loose", False), ("publication-text", True)):
        generate(binary, work / name, output / name, text_only, info)


if __name__ == "__main__":
    main()

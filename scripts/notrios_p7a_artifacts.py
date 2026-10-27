#!/usr/bin/env python3
"""Inventory a private P7a run for future cleanup decisions; never delete files.

Only relative generated-output paths are recorded. This is an inventory, not
permission to delete: running processes, future comparisons, and references
from other runs must be checked before cleanup. Sizes are logical bytes, not
exclusive physical disk usage (hard links, sparse files and WAL may differ).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import time


def category(name, is_dir):
    if name in {"vault", "raw", "preserved", "tiny", "media"}:
        return "generated_inputs", "Synthetic inputs or timing outputs; consult launch arguments to distinguish."
    if name.startswith("python-") or name.startswith("go-") and name.endswith("-assets"):
        return "generated_library", "Disposable imported SQLite library/assets; needed for unchanged-run reproduction."
    if name == "notrios-source" or name == "notrios-source.tar" or name == "notriosctl-profile":
        return "rebuildable_tool", "Pinned exported source, instrumented build or source archive; recreate from recorded pin and harness."
    if name.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm")):
        return "generated_library", "Disposable producer database; keep its WAL/SHM with it until all readers/writers close."
    if name.endswith((".prof", ".cpu", ".heap")):
        return "profile_evidence", "Detailed profiler evidence; retain until candidate evaluation and summary review finish."
    if is_dir:
        return "stage_evidence", "Per-command logs or generated stage outputs; inspect launch manifest before cleanup."
    return "summary_evidence", "Run manifest, notification, aggregate results, logs or other supporting evidence."


def inventory(root):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("run root must be a directory")
    entries = []
    totals = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs.sort(); files.sort()
        path = Path(current)
        rel = path.relative_to(root).as_posix()
        direct_bytes = direct_files = symlinks = 0
        for name in files:
            if path == root and name in {"ARTIFACT_MANIFEST.json", "ARTIFACT_MANIFEST.json.tmp"}:
                continue
            info = (path/name).lstat()
            if stat.S_ISREG(info.st_mode):
                direct_files += 1
                direct_bytes += info.st_size
            elif stat.S_ISLNK(info.st_mode):
                symlinks += 1
        for name in list(dirs):
            if (path/name).is_symlink():
                dirs.remove(name)
                symlinks += 1
        kind, purpose = category(rel.split("/")[0], True)
        entry = dict(path=rel, kind=kind, purpose=purpose, direct_files=direct_files,
                     direct_logical_bytes=direct_bytes, ignored_symlinks=symlinks,
                     tree_files=direct_files, tree_logical_bytes=direct_bytes)
        entries.append(entry); totals[rel] = entry
    for entry in reversed(entries[1:]):
        parent = Path(entry["path"]).parent.as_posix()
        totals[parent]["tree_files"] += entry["tree_files"]
        totals[parent]["tree_logical_bytes"] += entry["tree_logical_bytes"]
    top_files = []
    for path in sorted(root.iterdir()):
        if path.name.startswith("ARTIFACT_MANIFEST.json") or path.is_symlink() or not path.is_file():
            continue
        kind, purpose = category(path.name, False)
        top_files.append(dict(path=path.name, logical_bytes=path.stat().st_size, kind=kind, purpose=purpose))
    notification = root/"notification.json"
    state = "unknown_or_incomplete"
    if notification.is_file():
        try:
            state = json.loads(notification.read_text()).get("status", state)
        except (ValueError, OSError):
            pass
    return dict(schema_version=1, created_unix=time.time(), run_status=state,
                size_definition="logical bytes; not exclusive physical disk allocation",
                deletion_authorized=False,
                cleanup_conditions=[
                    "Confirm all run readers/writers have exited; a notification alone is not a process check.",
                    "Keep manifests, terminal status, aggregate evidence and accepted pins/hashes.",
                    "Confirm no downstream baseline/candidate/resume job references this run.",
                    "Rebuildable tools and generated libraries can be candidates after comparison acceptance, not original source data.",
                    "This command never deletes files; obtain separate cleanup authorization."
                ],
                total_files=totals["."]["tree_files"], total_logical_bytes=totals["."]["tree_logical_bytes"],
                directories=entries, top_level_files=top_files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True)
    args = parser.parse_args()
    for value in args.root:
        root = Path(value).resolve(strict=True)
        result = inventory(root)
        temporary = root/"ARTIFACT_MANIFEST.json.tmp"
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
        temporary.chmod(0o600)
        temporary.replace(root/"ARTIFACT_MANIFEST.json")
        print(json.dumps({k:result[k] for k in ("run_status", "total_files", "total_logical_bytes")}))


if __name__ == "__main__":
    main()

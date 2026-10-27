#!/usr/bin/env python3
"""Create disposable P7c source variants from the reviewed P7b candidate.

P7b's candidate combines two performance changes with two correctness fixes.
This script makes the effects measurable without adding a production flag:
every output is a complete source tree, and the importer is run from that
tree.  The C01/C02 collision fixes are retained in every variant.

The input tree is read only.  The output must not already exist.  No source
tree is deleted by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


VARIANTS = ("base", "f02", "f04", "both")
FORMAT = "movenotes-p7c-source-variants-v1"


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in {".git", "__pycache__"})
        for name in sorted(files):
            path = Path(current) / name
            if path.name.endswith(".pyc") or path.is_symlink():
                continue
            digest.update(b"F\0")
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def _function_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


_P7B2_MARKER = (
    "        notesdb.create_database(sqlconn, create_indexes=False)\n"
    "        # Every batch looks up its item IDs before inserting;"
)


def _has_p7b2_index(obsidian: str) -> bool:
    """P7b2 creates joplinididx with a new database, which subsumes F02."""
    return _P7B2_MARKER in obsidian


def _without_f02(obsidian: str) -> str:
    # Anchored to the folder repair it serves: since P7b2 the same call also
    # appears where a new database is created, and that one must stay.
    repair = "        notesdb.populate_missing_note_folders(sqlconn)\n"
    marker = "        notesdb.ensure_joplin_id_index(sqlconn)\n" + repair
    return _replace_once(obsidian, marker, repair, "F02 call")


def _without_f04(candidate: str, reference: str) -> str:
    start_marker = "def _native_rows(\n"
    end_marker = "def main(argv: list[str]) -> int:\n"
    candidate_block = _function_block(candidate, start_marker, end_marker)
    reference_block = _function_block(reference, start_marker, end_marker)
    if "list[tuple[Path, str]]" not in candidate_block:
        raise ValueError("candidate does not contain the expected F04 tuple inventory")
    if "list[tuple[Path, str]]" in reference_block:
        raise ValueError("reference already contains the F04 tuple inventory")
    return _replace_once(candidate, candidate_block, reference_block, "F04 function")


def _copy_source(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
    )


def prepare(source: Path, reference: Path, output: Path) -> dict[str, object]:
    source = source.resolve()
    reference = reference.resolve()
    output = output.resolve()
    if not (source / "obsidian2sql.py").is_file():
        raise ValueError(f"not a movenotes source tree: {source}")
    if not (reference / "obsidian2sql.py").is_file():
        raise ValueError(f"not a movenotes reference tree: {reference}")
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=output.name + ".tmp-", dir=output.parent))
    try:
        variants: dict[str, dict[str, object]] = {}
        for name in VARIANTS:
            variant = temporary / name
            _copy_source(source, variant)
            obsidian_path = variant / "obsidian2sql.py"
            candidate_text = obsidian_path.read_text(encoding="utf-8")
            if name in {"base", "f04"}:
                candidate_text = _without_f02(candidate_text)
            if name in {"base", "f02"}:
                reference_text = (reference / "obsidian2sql.py").read_text(encoding="utf-8")
                candidate_text = _without_f04(candidate_text, reference_text)
            obsidian_path.write_text(candidate_text, encoding="utf-8")
            variants[name] = {
                "path": str(output / name),
                "source_sha256": tree_sha256(variant),
                "f02_early_joplin_id_index": name in {"f02", "both"},
                "f04_relative_path_reuse": name in {"f04", "both"},
                "collision_fixes_retained": True,
                "p7b2_new_database_joplin_id_index": _has_p7b2_index(candidate_text),
            }
        metadata: dict[str, object] = {
            "format": FORMAT,
            "status": "complete",
            "input_source": str(source),
            "input_source_sha256": tree_sha256(source),
            "reference_source": str(reference),
            "reference_source_sha256": tree_sha256(reference),
            "variants": variants,
            "notes": {
                "base": "P7b C01/C02 correctness fixes only",
                "f02": "C01/C02 plus early joplin_id index",
                "f04": "C01/C02 plus retained normalized relative paths",
                "both": "C01/C02 plus F02 and F04",
                "p7b2": "Where p7b2_new_database_joplin_id_index is true, every "
                "variant indexes item IDs before the first batch, so F02's "
                "removal no longer changes behaviour: base matches f02 and f04 "
                "matches both.",
            },
        }
        (temporary / "SOURCE_VARIANTS.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output)
        return metadata
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument(
        "--reference-source",
        type=Path,
        required=True,
        help="P7b pre-candidate source containing the original _native_rows implementation",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    metadata = prepare(args.candidate_source, args.reference_source, args.output)
    print("P7C_SOURCE_VARIANTS_COMPLETE", json.dumps(metadata, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

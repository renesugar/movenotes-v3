#!/usr/bin/env python3
"""Copy a deterministic recipe-vault Markdown subset to a private volume.

The source is read only. Markdown files are selected by normalized relative
POSIX path, copied with ``copy2`` so source mtimes remain intact, and written
under their original directories. Small metadata/configuration files are
copied when present; arbitrary non-Markdown data is excluded unless it has a
configuration-like name. A private manifest records source and destination
hashes, counts, byte totals and the full selected path list.
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


FORMAT = "movenotes-p7c-recipe-subset-v1"
CONFIG_NAMES = {".obsidian"}
CONFIG_BASENAMES = {
    "config.json",
    "metadata.json",
    "settings.json",
    "vault.json",
    "config.toml",
    "metadata.toml",
    "settings.toml",
    "config.yaml",
    "config.yml",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_files(root: Path) -> list[Path]:
    return sorted(
        (
            path.relative_to(root)
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.as_posix(),
    )


def _is_config(path: Path) -> bool:
    # A preservation bundle under .movenotes is importer input and must not
    # be copied into this native-vault subset. Only an Obsidian config tree or
    # an explicitly named root-level configuration file is eligible.
    if ".movenotes" in path.parts:
        return False
    return any(part in CONFIG_NAMES for part in path.parts) or (
        path.parent == Path(".") and path.name.lower() in CONFIG_BASENAMES
    )


def build_subset(source: Path, output: Path, limit: int) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    if output.exists():
        raise FileExistsError(output)
    if limit < 1:
        raise ValueError("limit must be positive")

    all_files = _relative_files(source)
    if any(".movenotes" in path.parts for path in all_files):
        raise ValueError("source contains a .movenotes preservation bundle; native subset selection refused")
    markdown = [path for path in all_files if path.suffix.lower() == ".md"]
    selected_markdown = markdown[:limit]
    selected_markdown_set = set(selected_markdown)
    metadata_files = [
        path for path in all_files
        if path not in selected_markdown_set and _is_config(path)
    ]
    selected = sorted(set(selected_markdown + metadata_files), key=lambda path: path.as_posix())
    temporary = Path(tempfile.mkdtemp(prefix=output.name + ".tmp-", dir=output.parent))
    old_umask = os.umask(0o077)
    try:
        for relative in selected:
            destination = temporary / "vault" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination, follow_symlinks=False)
        source_entries = []
        destination_entries = []
        for relative in selected:
            source_path = source / relative
            destination_path = temporary / "vault" / relative
            source_entries.append({
                "path": relative.as_posix(),
                "bytes": source_path.stat().st_size,
                "sha256": sha256_file(source_path),
                "kind": "markdown" if relative in selected_markdown_set else "metadata/config",
                "mtime_ns": source_path.stat().st_mtime_ns,
            })
            destination_entries.append({
                "path": relative.as_posix(),
                "bytes": destination_path.stat().st_size,
                "sha256": sha256_file(destination_path),
                "mtime_ns": destination_path.stat().st_mtime_ns,
            })
        metadata: dict[str, object] = {
            "format": FORMAT,
            "status": "complete",
            "source_root": str(source),
            "destination_root": str(output / "vault"),
            "full_markdown_count": len(markdown),
            "full_markdown_bytes": sum((source / path).stat().st_size for path in markdown),
            "selected_markdown_count": len(selected_markdown),
            "selected_markdown_bytes": sum((source / path).stat().st_size for path in selected_markdown),
            "metadata_config_count": len(metadata_files),
            "selected_file_count": len(selected),
            "selected_file_bytes": sum((source / path).stat().st_size for path in selected),
            "source_files": source_entries,
            "destination_files": destination_entries,
        }
        manifest = temporary / "SUBSET_MANIFEST.json"
        manifest.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, output)
        return metadata
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        os.umask(old_umask)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args(argv)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    result = build_subset(args.source, args.output, args.limit)
    compact = {
        key: result[key]
        for key in (
            "format",
            "source_root",
            "destination_root",
            "full_markdown_count",
            "full_markdown_bytes",
            "selected_markdown_count",
            "selected_markdown_bytes",
            "metadata_config_count",
            "selected_file_count",
            "selected_file_bytes",
        )
    }
    print("P7C_RECIPE_SUBSET_COMPLETE", json.dumps(compact, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

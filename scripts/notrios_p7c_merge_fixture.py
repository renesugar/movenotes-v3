#!/usr/bin/env python3
"""Create a disjoint, metadata-free Obsidian merge fixture for P7c.

The fixture deliberately contains no YAML frontmatter, tags or explicit
Joplin IDs. Its directory prefix is disjoint from the synthetic preserved
seed, so a prepared-seed merge measures folder/index work without turning an
unrelated dataset collision into an importer failure. The manifest is kept
outside the importer input directory.
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


FORMAT = "movenotes-p7c-disjoint-merge-fixture-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_fixture(output: Path, count: int = 10) -> dict[str, object]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if count < 1:
        raise ValueError("count must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=output.name + ".tmp-", dir=output.parent))
    old_umask = os.umask(0o077)
    try:
        vault = temporary / "vault"
        paths: list[dict[str, object]] = []
        for index in range(count):
            relative = Path(f"p7c-disjoint-{index:02d}") / "nested" / f"note-{index:06d}.md"
            path = vault / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            # No frontmatter, tags, wiki links or explicit IDs. The content
            # remains a valid small Markdown note and the path itself is the
            # only identity input.
            path.write_text(
                f"# P7c disjoint merge note {index}\n\n"
                "Prepared-seed merge measurement.\n",
                encoding="utf-8",
            )
            paths.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)})
        manifest: dict[str, object] = {
            "format": FORMAT,
            "status": "complete",
            "destination_root": str(output),
            "vault": str(output / "vault"),
            "count": count,
            "files": paths,
        }
        (temporary / "MERGE_FIXTURE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        os.umask(old_umask)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args(argv)
    result = build_fixture(args.output, args.count)
    print(
        "P7C_MERGE_FIXTURE_COMPLETE",
        json.dumps({key: result[key] for key in ("format", "vault", "count")}, sort_keys=True),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

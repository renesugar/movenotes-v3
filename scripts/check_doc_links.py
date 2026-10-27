#!/usr/bin/env python3
"""Check that every relative link in the repository's documentation resolves.

A link resolves when its file or directory exists inside the repository and,
when it names a ``#fragment``, that fragment is a heading anchor of the target
document (GitHub's slug rules) or an explicit ``id``/``name`` there. Links with
a scheme (``https:``, ``mailto:``, Joplin's ``:/id``) are not checked. A link
that leaves the repository, or starts with ``/``, is refused: it resolves only
on one machine, or only on a web server.

Documentation is every tracked Markdown file except fixture data: under
``sample/`` and ``testdata/`` only ``README.md`` files are documentation, the
rest are note bytes the tests pin. Links inside code spans and fenced code are
text, not links. Standard library only.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DATA_DIRS = ("sample/", "testdata/")

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
_INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*(<[^>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
_REFERENCE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>\n]*>|\S+)")
_HTML_ID = re.compile(r"""<[a-zA-Z][^>]*\s(?:id|name)\s*=\s*["']([^"']+)["']""")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def documentation_files(root: Path) -> list[Path]:
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
                            check=True, capture_output=True).stdout.decode("utf-8").split("\0")
    files = []
    for name in filter(None, listed):
        if name.startswith(DATA_DIRS) and Path(name).name != "README.md":
            continue
        files.append(root / name)
    return sorted(files)


def _plain_heading(text: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("`", "").replace("*", "")


def slug(text: str) -> str:
    """GitHub's heading anchor: lowercase, keep letters, marks, numbers, ``_``, ``-`` and spaces."""
    kept = "".join(ch for ch in _plain_heading(text).lower()
                   if ch in " -" or unicodedata.category(ch)[0] in "LMN" or unicodedata.category(ch) == "Pc")
    return kept.replace(" ", "-")


def _lines_outside_fences(text: str):
    fence = None
    for number, line in enumerate(text.split("\n"), 1):
        match = _FENCE.match(line)
        if fence:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) \
                    and not line.strip()[len(match.group(1)):].strip():
                fence = None
            continue
        if match:
            fence = match.group(1)
            continue
        yield number, line


def anchors(path: Path) -> set[str]:
    found, counts = set(), {}
    for _, line in _lines_outside_fences(path.read_text(encoding="utf-8")):
        found.update(_HTML_ID.findall(line))
        heading = _HEADING.match(line)
        if heading:
            base = slug(heading.group(2))
            n = counts.get(base, 0)
            counts[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
    return found


def links(path: Path):
    for number, line in _lines_outside_fences(path.read_text(encoding="utf-8")):
        prose = _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)
        targets = [m.group(1) for m in _INLINE_LINK.finditer(prose)]
        reference = _REFERENCE.match(prose)
        if reference:
            targets.append(reference.group(1))
        for target in targets:
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            yield number, target


def check(root: Path, files: list[Path]) -> list[str]:
    problems, cache = [], {}
    root = root.resolve()
    for path in files:
        where = path.relative_to(root)
        for number, target in links(path):
            if not target or _SCHEME.match(target) or target.startswith(":/"):
                continue
            location, _, fragment = target.partition("#")
            if location.startswith("/"):
                problems.append(f"{where}:{number}: site-absolute link {target}")
                continue
            resolved = (path.parent / unquote(location)).resolve() if location else path
            try:
                resolved.relative_to(root)
            except ValueError:
                problems.append(f"{where}:{number}: link leaves the repository: {target}")
                continue
            if not resolved.exists():
                problems.append(f"{where}:{number}: no such file: {target}")
                continue
            if fragment and resolved.is_file() and resolved.suffix == ".md":
                if resolved not in cache:
                    cache[resolved] = anchors(resolved)
                if unquote(fragment) not in cache[resolved]:
                    problems.append(f"{where}:{number}: no heading for #{fragment} in {resolved.relative_to(root)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    args = parser.parse_args(argv)
    files = documentation_files(args.root)
    problems = check(args.root, files)
    for problem in problems:
        print(problem)
    print(f"checked {len(files)} document(s): {len(problems)} broken link(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

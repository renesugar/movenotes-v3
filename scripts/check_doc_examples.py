#!/usr/bin/env python3
"""Check that the documentation's examples are registered, and run them.

Every fenced block in ``README.md`` and ``docs/**/*.md`` must have an entry in
``docs/examples.json`` naming its page, ordinal, heading, language and the
SHA-256 of its text, and one state:

``executed``
    Run by this check, so by the unit gate. Needs only Python.
``tools``
    Needs Hugo, Go, ``npx``, ``notriosctl`` (from ``$NOTRIOSCTL``) or the
    Ledger theme (``$LEDGER_THEME``, else ``~/projects/hugo-theme-ledger``).
    Run with ``--with-tools``; an example whose tool is missing is reported as
    skipped and fails the run, so it is never counted as passed.
``unverified``
    Not run, for the recorded ``reason``: a synopsis, recorded output, a
    fragment, or a command that changes something outside its temporary home.

A changed, unregistered or stale entry is refused before anything runs, so an
edited example has to be re-run and re-registered in the commit that edits it;
``--list`` prints the current fences to register from.

Examples run with ``bash -euo pipefail`` from the repository root, as a reader
runs them from a checkout. Each page's runnable examples run in page order,
and those naming the same ``home`` share one temporary ``$HOME`` (and XDG
directories), so a later example uses what an earlier one wrote. A page's
``homes`` say what each home is seeded with: ``seed`` copies a repository path
to a path under the home, and ``setup`` runs shell commands first. A page's or
an example's ``substitute`` replaces a placeholder, such as
``<the reviewed plan's manifest_sha256>``, with a value; ``{port}`` in a
value stands for a free port chosen for the run. An example with ``cwd``
starts in that directory of its home, where an earlier example left the reader.
An example with ``serves`` starts a server: it passes when that URL answers,
and is then stopped. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
from urllib.parse import urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = "docs/examples.json"
STATES = ("executed", "tools", "unverified")
TOOLS = ("hugo", "go", "npx", "notriosctl", "ledger-theme")
DEFAULT_TIMEOUT = 600
SERVE_TIMEOUT = 120

_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$")


def documentation_files(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", "README.md", "docs/*.md"],
        check=True, capture_output=True).stdout.decode("utf-8").split("\0")
    return sorted({name for name in listed if name and (root / name).is_file()})


def fences(text: str) -> list[dict]:
    """Each fenced block's opening line, heading, language and body, in page order."""
    found, heading, fence = [], "", None
    for number, line in enumerate(text.split("\n"), 1):
        match = _FENCE.match(line)
        if fence is not None:
            marker = fence["marker"]
            if match and match.group(2)[0] == marker[0] and len(match.group(2)) >= len(marker) \
                    and not match.group(3).strip():
                fence = None
                continue
            indent = fence["indent"]
            fence["lines"].append(line[min(indent, len(line) - len(line.lstrip(" "))):])
            continue
        if match and not (match.group(2)[0] == "`" and "`" in match.group(3)):
            fence = {"line": number, "heading": heading, "marker": match.group(2),
                     "indent": len(match.group(1)), "language": match.group(3).strip().split(" ")[0],
                     "lines": []}
            found.append(fence)
            continue
        title = _HEADING.match(line)
        if title:
            heading = title.group(1)
    for ordinal, block in enumerate(found, 1):
        block["ordinal"] = ordinal
        block["body"] = "".join(f"{line}\n" for line in block.pop("lines"))
        block["sha256"] = hashlib.sha256(block["body"].encode("utf-8")).hexdigest()
        del block["marker"], block["indent"]
    return found


def collect(root: Path) -> dict[str, list[dict]]:
    pages = {}
    for page in documentation_files(root):
        blocks = fences((root / page).read_text(encoding="utf-8"))
        if blocks:
            pages[page] = blocks
    return pages


def _entry_problems(page: str, spec: dict, entry: dict, root: Path) -> list[str]:
    where = f"{page} example {entry.get('ordinal')}"
    state = entry.get("state")
    problems = []
    if state not in STATES:
        return [f"{where}: state must be one of {', '.join(STATES)}, not {state!r}"]
    if state == "unverified":
        if not str(entry.get("reason", "")).strip():
            problems.append(f"{where}: an unverified example needs a reason")
        return problems
    tools = entry.get("tools", [])
    if state == "tools" and not tools:
        problems.append(f"{where}: a tools example names the tools it needs")
    if state == "executed" and tools:
        problems.append(f"{where}: an executed example needs no tools; make it a tools example")
    problems += [f"{where}: unknown tool {tool!r}" for tool in tools if tool not in TOOLS]
    home = entry.get("home", "default")
    if home != "default" and home not in spec.get("homes", {}):
        problems.append(f"{where}: no home {home!r} on the page")
    if "cwd" in entry and not str(entry["cwd"]).startswith("~/"):
        problems.append(f"{where}: cwd is a directory of the home, written ~/…")
    return problems


def check_registry(root: Path, registry: dict, pages: dict[str, list[dict]]) -> list[str]:
    problems = []
    registered = registry.get("pages", {})
    for page, blocks in pages.items():
        spec = registered.get(page, {})
        entries = {entry.get("ordinal"): entry for entry in spec.get("examples", [])}
        for block in blocks:
            where = f"{page}:{block['line']}: example {block['ordinal']}"
            entry = entries.pop(block["ordinal"], None)
            if entry is None:
                problems.append(f"{where} ({block['heading']}) is not registered in {REGISTRY}")
                continue
            changed = [key for key in ("heading", "language", "sha256") if entry.get(key) != block[key]]
            if changed:
                problems.append(f"{where} ({block['heading']}) changed: {', '.join(changed)} differ from "
                                f"{REGISTRY}; re-run it and register it again")
                continue
            problems += _entry_problems(page, spec, entry, root)
        problems += [f"{page}: stale entry for example {ordinal}: the page has no such fence"
                     for ordinal in sorted(entries, key=str)]
    for page in sorted(set(registered) - set(pages)):
        problems.append(f"{page}: stale entry: no fenced example on that page")
    for page, spec in registered.items():
        if page not in pages:
            continue
        for name, home in spec.get("homes", {}).items():
            for source in home.get("seed", {}).values():
                if not (root / source).exists():
                    problems.append(f"{page}: home {name!r} seeds from {source}, which does not exist")
        bodies = {block["ordinal"]: block["body"] for block in pages[page]}
        runnable = [entry for entry in spec.get("examples", []) if entry.get("state") in ("executed", "tools")]
        for key in spec.get("substitute", {}):
            if not any(key in bodies.get(entry.get("ordinal"), "") for entry in runnable):
                problems.append(f"{page}: substitution {key!r} matches no runnable example")
        for entry in runnable:
            for key in entry.get("substitute", {}):
                if key not in bodies.get(entry.get("ordinal"), ""):
                    problems.append(f"{page} example {entry['ordinal']}: substitution {key!r} is not in it")
    return problems


def available_tools() -> dict[str, str | None]:
    found = {name: shutil.which(name) for name in ("hugo", "go", "npx")}
    notriosctl = os.environ.get("NOTRIOSCTL")
    found["notriosctl"] = notriosctl if notriosctl and os.access(notriosctl, os.X_OK) else None
    theme = Path(os.environ.get("LEDGER_THEME") or Path("~/projects/hugo-theme-ledger").expanduser())
    found["ledger-theme"] = str(theme) if (theme / "theme.toml").is_file() or (theme / "layouts").is_dir() else None
    return found


def _tool_environment(tools: dict[str, str | None]) -> dict[str, str]:
    """Caches that stay outside the temporary home, so a build does not download them again."""
    env = {}
    if tools.get("go"):
        listed = subprocess.run([tools["go"], "env", "GOMODCACHE", "GOCACHE", "GOPATH"],
                                capture_output=True, text=True).stdout.split("\n")
        for key, value in zip(("GOMODCACHE", "GOCACHE", "GOPATH"), listed):
            if value:
                env[key] = os.environ.get(key, value)
    npm_cache = Path("~/.npm").expanduser()
    if tools.get("npx") and npm_cache.is_dir():
        env["npm_config_cache"] = os.environ.get("npm_config_cache", str(npm_cache))
    return env


class Home:
    def __init__(self, root: Path, base: Path, name: str, spec: dict, tools: dict, cache_env: dict):
        self.path = base / name
        bin_dir = base / f"{name}.bin"
        bin_dir.mkdir(parents=True)
        self.path.mkdir()
        if tools.get("notriosctl"):
            (bin_dir / "notriosctl").symlink_to(tools["notriosctl"])
        if tools.get("ledger-theme"):
            (self.path / "projects").mkdir()
            (self.path / "projects" / "hugo-theme-ledger").symlink_to(tools["ledger-theme"])
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("XDG_", "GO")) and key not in ("HOME", "PWD", "OLDPWD", "CDPATH")}
        self.env.update(cache_env)
        self.env.update({
            "HOME": str(self.path), "PYTHONDONTWRITEBYTECODE": "1",
            "XDG_CONFIG_HOME": str(self.path / ".config"), "XDG_DATA_HOME": str(self.path / ".local/share"),
            "XDG_STATE_HOME": str(self.path / ".local/state"), "XDG_CACHE_HOME": str(self.path / ".cache"),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        })
        for target, source in spec.get("seed", {}).items():
            destination = self.path / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            if (root / source).is_dir():
                shutil.copytree(root / source, destination, symlinks=True)
            else:
                shutil.copy2(root / source, destination)
        self.setup = spec.get("setup", [])


def _shell(script: str, cwd: Path, env: dict, timeout: int):
    return subprocess.run(["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", script],
                          cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, errors="replace", timeout=timeout)


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _port_in_use(url: str) -> bool:
    parts = urlsplit(url)
    with socket.socket() as probe:
        try:
            probe.bind((parts.hostname or "127.0.0.1", parts.port or 80))
        except OSError:
            return True
    return False


def _serve(script: str, cwd: Path, env: dict, url: str, timeout: int) -> tuple[bool, str]:
    if _port_in_use(url):
        return False, f"the port of {url} is in use before the example starts; substitute {{port}} for it"
    with tempfile.TemporaryFile("w+", errors="replace") as log:
        process = subprocess.Popen(["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", script],
                                   cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True)
        deadline, served = time.monotonic() + timeout, False
        try:
            while time.monotonic() < deadline and process.poll() is None:
                if _answers(url):
                    served = True
                    break
                time.sleep(0.25)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        log.seek(0)
        output = log.read()
    if served:
        return True, output
    reason = f"exited with status {process.returncode}" if process.returncode not in (None, -signal.SIGTERM) \
        else f"did not answer {url} within {timeout}s"
    return False, f"{reason}\n{output}"


def _tail(output: str, lines: int = 40) -> str:
    kept = output.rstrip("\n").split("\n")[-lines:]
    return "".join(f"    {line}\n" for line in kept)


def run_examples(root: Path, registry: dict, pages: dict[str, list[dict]], with_tools: bool,
                 only: set[str] | None, report) -> dict[str, int]:
    tools = available_tools() if with_tools else {}
    cache_env = _tool_environment(tools) if with_tools else {}
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    states = ("executed", "tools") if with_tools else ("executed",)
    for page, spec in registry.get("pages", {}).items():
        if only and page not in only:
            continue
        blocks = {block["ordinal"]: block for block in pages.get(page, [])}
        runnable = [entry for entry in spec.get("examples", []) if entry.get("state") in states]
        if not runnable:
            continue
        with tempfile.TemporaryDirectory(prefix="movenotes-examples-") as base:
            homes, broken, missing_before = {}, {}, None
            for entry in runnable:
                block = blocks[entry["ordinal"]]
                where = f"{page}:{block['line']} example {block['ordinal']}"
                missing = [tool for tool in entry.get("tools", []) if not tools.get(tool)]
                name = entry.get("home", "default")
                after_skip = missing_before and entry["state"] == "tools"
                if missing or after_skip or name in broken:
                    counts["skipped"] += 1
                    why = (f"missing {', '.join(missing)}" if missing else
                           f"after skipped example {missing_before}" if after_skip else broken[name])
                    report(f"SKIP {where}: {why}")
                    if missing and entry["state"] == "tools":
                        missing_before = missing_before or block["ordinal"]
                    continue
                if name not in homes:
                    homes[name] = Home(root, Path(base), name, spec.get("homes", {}).get(name, {}),
                                       tools, cache_env)
                    for command in homes[name].setup:
                        result = _shell(command, root, homes[name].env, DEFAULT_TIMEOUT)
                        if result.returncode:
                            broken[name] = f"setup of home {name!r} failed"
                            report(f"FAIL {page}: setup of home {name!r} exited {result.returncode}: {command}\n"
                                   + _tail(result.stdout + result.stderr))
                            break
                    if name in broken:
                        counts["failed"] += 1
                        continue
                script, serves = block["body"], entry.get("serves", "")
                substitutions = {**spec.get("substitute", {}), **entry.get("substitute", {})}
                port = str(_free_port()) if "{port}" in "".join(substitutions.values()) + serves else None
                for key, value in substitutions.items():
                    script = script.replace(key, value.replace("{port}", port) if port else value)
                serves = serves.replace("{port}", port) if port else serves
                cwd = homes[name].path / entry["cwd"][2:] if entry.get("cwd") else root
                timeout = int(entry.get("timeout", DEFAULT_TIMEOUT))
                started = time.monotonic()
                try:
                    if serves:
                        passed, output = _serve(script, cwd, homes[name].env, serves,
                                                int(entry.get("timeout", SERVE_TIMEOUT)))
                    else:
                        result = _shell(script, cwd, homes[name].env, timeout)
                        passed, output = result.returncode == 0, \
                            f"exited with status {result.returncode}\n{result.stdout}{result.stderr}"
                except subprocess.TimeoutExpired as error:
                    passed, output = False, f"timed out after {timeout}s\n{error.stdout or ''}{error.stderr or ''}"
                elapsed = time.monotonic() - started
                if passed:
                    counts["passed"] += 1
                    report(f"PASS {where} ({elapsed:.1f}s)")
                else:
                    counts["failed"] += 1
                    report(f"FAIL {where} ({block['heading']}): " + _tail(output).lstrip())
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--with-tools", action="store_true",
                        help="also run the examples that need Hugo, Go, npx, notriosctl or the theme")
    parser.add_argument("--registry-only", action="store_true", help="check the registry; run nothing")
    parser.add_argument("--page", action="append", help="run only this page's examples (repeatable)")
    parser.add_argument("--list", action="store_true",
                        help="print every fence as a registry entry, with its state if registered")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    pages = collect(root)
    registry_path = root / REGISTRY
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    if args.list:
        registered = registry.get("pages", {})
        listing = {}
        for page, blocks in pages.items():
            known = {entry.get("ordinal"): entry for entry in registered.get(page, {}).get("examples", [])}
            listing[page] = [{**known.get(block["ordinal"], {}), "line": block["line"],
                              **{key: block[key] for key in ("ordinal", "heading", "language", "sha256")}}
                             for block in blocks]
        print(json.dumps(listing, ensure_ascii=False, indent=2))
        return 0
    problems = check_registry(root, registry, pages)
    for problem in problems:
        print(problem)
    entries = [entry for spec in registry.get("pages", {}).values() for entry in spec.get("examples", [])]
    tally = {state: sum(entry.get("state") == state for entry in entries) for state in STATES}
    print(f"{sum(len(blocks) for blocks in pages.values())} fenced example(s) in {len(pages)} page(s): "
          f"{tally['executed']} executed, {tally['tools']} need tools, {tally['unverified']} unverified; "
          f"{len(problems)} registry problem(s)", file=sys.stderr)
    if problems:
        return 1
    if args.registry_only:
        return 0
    if args.with_tools:
        for tool, where in available_tools().items():
            print(f"tool {tool}: {where or 'missing'}", file=sys.stderr)
    counts = run_examples(root, registry, pages, args.with_tools, set(args.page or ()),
                          lambda line: print(line, flush=True))
    print(f"ran {sum(counts.values())} example(s): {counts['passed']} passed, {counts['failed']} failed, "
          f"{counts['skipped']} skipped", file=sys.stderr)
    return 1 if counts["failed"] or counts["skipped"] else 0


if __name__ == "__main__":
    sys.exit(main())

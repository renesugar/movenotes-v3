#!/usr/bin/env python3
"""Resumed 7c corpus trials: sequential, checkpointed, aggregate-only evidence.

Each expensive command is a *stage* with its own directory, checkpoint, GNU
time record, logs and aggregate output measurement.  A stage's directory name
carries a fingerprint of its command and inputs: the producer binary's hash,
the hashes of the repository files it runs, and the digests of the upstream
outputs or source inventory it reads.  A completed stage is reused only when
its fingerprint matches; a changed input gets a fresh directory and the old
one is kept.  An unfinished stage's files are archived before a retry.

Private paths live only in the work root (``config.json``, checkpoints and
logs).  Measurements and ``summary.json`` hold counts, byte totals, digests,
times and peak RSS, never a path, title or note text.

usage:
  notrios_7c_trials.py setup ROOT --notriosctl BIN --expected-sha256 HEX
      --theme DIR --source joplin=DIR --source recipe-raw=DIR --source recipe-vault=DIR
  notrios_7c_trials.py producer ROOT [--route NAME ...]
  notrios_7c_trials.py pipeline ROOT --tier bounded|full [--route NAME ...]
  notrios_7c_trials.py live-site ROOT --tier bounded|full [--route NAME ...]
  notrios_7c_trials.py recovery ROOT [--route joplin]
  notrios_7c_trials.py compare ROOT
  notrios_7c_trials.py summary ROOT
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import inspect
import json
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = Path(__file__).resolve()
ROUTES = {
    # route: (notriosctl importer, extra import arguments)
    "joplin": ("joplin-raw", []),
    "recipe-raw": ("joplin-raw", ["--batch-size", "500"]),
    "recipe-vault": ("obsidian", ["--batch-size", "500"]),
}
BOUNDED_DOCUMENTS = 1000
MIN_FREE_BYTES = 20 * 1024**3
TIME_FORMAT = '{"wall_seconds":%e,"user_seconds":%U,"system_seconds":%S,"max_rss_kib":%M,"exit":%x}'


class StageFailed(RuntimeError):
    def __init__(self, name: str, returncode: int) -> None:
        super().__init__(f"{name} exited {returncode}")
        self.name = name
        self.returncode = returncode


# ---------------------------------------------------------------- utilities

def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_time(path: Path) -> dict[str, object]:
    """GNU time's record. A failed or signalled command gets a status line first."""
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    record = next((json.loads(line) for line in reversed(lines) if line.startswith("{")), {})
    notes = [line for line in lines if not line.startswith("{")]
    return {**record, "notes": notes} if notes else record


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def measure(path: Path) -> dict[str, object]:
    """Files, bytes and one digest over relative names and bytes; no names kept."""
    if not path.exists() and not path.is_symlink():
        return {"exists": False, "file_count": 0, "byte_count": 0, "sha256": None}
    if path.is_symlink():
        return {"exists": True, "symlink": True, "file_count": 0, "byte_count": 0, "sha256": None}
    if path.is_file():
        return {"exists": True, "file_count": 1, "byte_count": path.stat().st_size,
                "sha256": file_sha256(path)}
    files = size = 0
    digest = hashlib.sha256()
    for base, dirs, names in os.walk(path, followlinks=False):
        dirs.sort()
        for name in sorted(names):
            current = Path(base) / name
            relative = current.relative_to(path).as_posix().encode("utf-8", "surrogateescape")
            if current.is_symlink() or not current.is_file():
                digest.update(b"special\0" + relative + b"\0")
                continue
            length = current.stat().st_size
            files += 1
            size += length
            digest.update(relative + b"\0" + str(length).encode("ascii") + b"\0")
            digest.update(bytes.fromhex(file_sha256(current)))
    return {"exists": True, "file_count": files, "byte_count": size, "sha256": digest.hexdigest()}


_CONSUMER_CACHE: dict[tuple[str, ...], dict[str, str]] = {}


def consumer_hashes(modules: tuple[str, ...], child: str | None = None) -> dict[str, str]:
    """SHA-256 of every repository file the named modules load.

    Found by importing them in a child interpreter, so the set follows the code
    rather than a hand-kept list.  A stage that runs one of this harness's child
    commands also covers that child's source, and only that: an edit elsewhere
    in the harness must not discard a finished multi-hour conversion.
    """
    if child is not None:
        hashes = dict(consumer_hashes(modules))
        source = "".join(inspect.getsource(function) for function in _CHILD_SOURCES[child]())
        hashes[f"harness:{child}"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return hashes
    if modules not in _CONSUMER_CACHE:
        probe = (
            "import json,sys\nsys.path.insert(0,sys.argv[1])\n"
            "for name in sys.argv[2:]: __import__(name)\n"
            "root=sys.argv[1]\n"
            "print(json.dumps(sorted({m.__file__ for m in list(sys.modules.values())"
            " if getattr(m,'__file__',None) and m.__file__.startswith(root+'/')})))"
        )
        files = json.loads(subprocess.run(
            [sys.executable, "-B", "-c", probe, str(REPO), *modules],
            check=True, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        ).stdout)
        hashes = {Path(name).relative_to(REPO).as_posix(): file_sha256(Path(name)) for name in files}
        _CONSUMER_CACHE[modules] = hashes
    return _CONSUMER_CACHE[modules]


def source_inventory(source: Path) -> dict[str, object]:
    """Aggregate inventory of a read-only source tree: what the producer read."""
    started = time.time()
    result = measure(source)
    result["seconds"] = round(time.time() - started, 3)
    return result


# ------------------------------------------------------------------- stages

class Trials:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.config = _read_json(self.root / "config.json")
        self.binary = Path(self.config["notriosctl"])
        self.empty_config = self.root / "empty-config.yaml"
        self._binary_checked = False

    def check_binary(self) -> str:
        if not self._binary_checked:
            actual = file_sha256(self.binary)
            if actual != self.config["notriosctl_sha256"]:
                raise SystemExit("the producer binary's SHA-256 differs from the one set up")
            self._binary_checked = True
        return self.config["notriosctl_sha256"]

    def stage(
        self,
        key: str,
        argv: list[str],
        *,
        inputs: dict[str, object],
        outputs: dict[str, str],
        mkdirs: tuple[str, ...] = (),
        cwd: str | None = None,
        required: bool = True,
    ) -> Path:
        """Run one stage, or reuse it when its fingerprint matches a completed run.

        ``argv``, ``outputs``, ``mkdirs`` and ``cwd`` may contain ``{stage}``,
        replaced by the stage directory; the fingerprint covers the template, so
        it does not depend on the directory it names.
        """
        fingerprint = _digest({"argv": argv, "inputs": inputs, "outputs": outputs, "cwd": cwd})
        folder = self.root / f"{key}-{fingerprint[:12]}"
        expand = lambda text: text.replace("{stage}", str(folder))  # noqa: E731
        command = [expand(word) for word in argv]
        checkpoint = folder / "checkpoint.json"
        folder.mkdir(parents=True, exist_ok=True)
        if checkpoint.exists():
            previous = _read_json(checkpoint)
            if previous.get("status") == "complete" and previous.get("returncode") == 0:
                if previous.get("fingerprint") != fingerprint:
                    raise SystemExit(f"{key}: checkpoint fingerprint differs from its directory")
                print(f"{key}: reused", flush=True)
                self._mark_current(key, folder)
                return folder
            pid = previous.get("pid")
            if previous.get("status") == "running" and pid:
                try:
                    os.kill(int(pid), 0)
                except ProcessLookupError:
                    pass
                else:
                    raise SystemExit(f"{key}: process {pid} from an earlier run is still alive")
            self._archive_attempt(folder)
        free = shutil.disk_usage(self.root).free
        if free < MIN_FREE_BYTES:
            raise SystemExit(f"{key}: {free} bytes free, {MIN_FREE_BYTES} required")
        for directory in mkdirs:
            Path(expand(directory)).mkdir(parents=True, exist_ok=True)
        state = {"status": "running", "fingerprint": fingerprint, "key": key, "argv": command,
                 "inputs": inputs, "started": time.time(), "pid": None,
                 "disk_free_before_bytes": free}
        _write_json(checkpoint, state)
        print(f"{key}: running", flush=True)
        with (folder / "stdout.log").open("wb") as out, (folder / "stderr.log").open("wb") as err:
            process = subprocess.Popen(
                ["/usr/bin/time", "-f", TIME_FORMAT, "-o", str(folder / "time.json"), *command],
                cwd=expand(cwd) if cwd else self.root, stdout=out, stderr=err,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            state["pid"] = process.pid
            _write_json(checkpoint, state)
            returncode = process.wait()
        finished = time.time()
        timing = _read_time(folder / "time.json")
        measurement = {
            "key": key,
            "returncode": returncode,
            "elapsed_seconds": round(finished - state["started"], 3),
            "time": timing,
            "disk_free_before_bytes": free,
            "disk_free_after_bytes": shutil.disk_usage(self.root).free,
            "outputs": {label: measure(Path(expand(path))) for label, path in outputs.items()},
        }
        _write_json(folder / "measurement.json", measurement)
        state.update(status="complete" if returncode == 0 else "failed",
                     returncode=returncode, finished=finished)
        _write_json(checkpoint, state)
        print(f"{key}: exit {returncode}", flush=True)
        if returncode == 0:
            self._mark_current(key, folder)
        if returncode and required:
            raise StageFailed(key, returncode)
        return folder

    def _mark_current(self, key: str, folder: Path) -> None:
        """Name the stage directory later stages read: the last completed or reused one."""
        _write_json(self.root / f"{key}.current.json", {"folder": folder.name})

    def current(self, key: str) -> Path:
        pointer = self.root / f"{key}.current.json"
        if not pointer.exists():
            raise SystemExit(f"{key}: no completed stage yet")
        folder = pointer.parent / _read_json(pointer)["folder"]
        state = _read_json(folder / "checkpoint.json")
        if state.get("status") != "complete" or state.get("returncode") != 0:
            raise SystemExit(f"{key}: the current stage is not complete")
        return folder

    @staticmethod
    def _archive_attempt(folder: Path) -> None:
        """Move an unfinished or failed attempt aside, keeping all of it."""
        attempts = folder / "attempts"
        attempts.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        destination = attempts / stamp
        suffix = 1
        while destination.exists():
            suffix += 1
            destination = attempts / f"{stamp}-{suffix}"
        destination.mkdir()
        for entry in list(folder.iterdir()):
            if entry.name != "attempts":
                entry.rename(destination / entry.name)

    @staticmethod
    def output_digest(folder: Path, label: str) -> str:
        return _read_json(folder / "measurement.json")["outputs"][label]["sha256"]

    # ------------------------------------------------------------ producer

    def producer(self, route: str) -> Path:
        importer, extra = ROUTES[route]
        source = Path(self.config["sources"][route])
        print(f"{route}: inventorying the source...", flush=True)
        inventory = source_inventory(source)
        inventory_dir = self.root / "inventories"
        inventory_dir.mkdir(exist_ok=True)
        _write_json(inventory_dir / f"{route}.json", inventory)
        argv = [str(self.binary), "import", importer, "--config", str(self.empty_config),
                "--db", "{stage}/library/notes.sqlite", "--asset-store", "{stage}/library/assets",
                *extra, str(source)]
        return self.stage(
            f"{route}/producer-import", argv,
            inputs={"producer": self.check_binary(), "source": inventory["sha256"]},
            outputs={"library": "{stage}/library"}, mkdirs=("{stage}/library",),
        )

    def library(self, route: str) -> Path:
        """The current producer stage for a route, without re-inventorying its source."""
        return self.current(f"{route}/producer-import")

    # ------------------------------------------------------------ pipeline

    def _selection(self, database: Path, tier: str) -> tuple[list[str], int, str]:
        uri = database.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            if connection.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
                raise SystemExit("a producer job is still running")
            total = connection.execute(
                "SELECT count(*) FROM documents WHERE deleted_at IS NULL").fetchone()[0]
            if tier == "bounded":
                ids = [row[0] for row in connection.execute(
                    "SELECT id FROM documents WHERE deleted_at IS NULL ORDER BY id LIMIT ?",
                    (BOUNDED_DOCUMENTS,))]
                return ["--documents", ",".join(ids)], min(total, BOUNDED_DOCUMENTS), "first-ids"
            notebooks = [row[0] for row in connection.execute("SELECT id FROM notebooks ORDER BY id")]
            orphans = [row[0] for row in connection.execute(
                "SELECT id FROM documents WHERE deleted_at IS NULL AND notebook_id IS NULL ORDER BY id")]
        selection = []
        if notebooks:
            selection += ["--notebooks", ",".join(notebooks)]
        if orphans:
            selection += ["--documents", ",".join(orphans)]
        return selection, total, f"all-notebooks-plus-{len(orphans)}-unfiled"

    def pipeline(self, route: str, tier: str) -> dict[str, Path]:
        producer = self.library(route)
        database = producer / "library" / "notes.sqlite"
        assets = producer / "library" / "assets"
        produced = self.output_digest(producer, "library")
        binary = self.check_binary()
        selection, expected, description = self._selection(database, tier)
        shared = ["--config", str(self.empty_config), "--db", str(database), "--asset-store", str(assets)]
        base = f"{route}/{tier}"
        stages: dict[str, Path] = {}

        stages["profile"] = self.stage(
            f"{base}/profile",
            [str(self.binary), "publish", "profile", "save", *shared,
             "--profiles", "{stage}/profiles.json", "--name", tier,
             "--target", "publication_handoff", "--link-action", "plain_text", *selection],
            inputs={"producer": binary, "library": produced, "selection": _digest(selection)},
            outputs={"profiles": "{stage}/profiles.json"},
        )
        profiles = ["--profiles", str(stages["profile"] / "profiles.json"), "--profile", tier]
        stages["plan"] = self.stage(
            f"{base}/plan", [str(self.binary), "publish", "plan", *shared, *profiles, "--detail-limit", "0"],
            inputs={"producer": binary, "profiles": self.output_digest(stages["profile"], "profiles")},
            outputs={"plan": "{stage}/stdout.log"},
        )
        plan = json.loads((stages["plan"] / "stdout.log").read_text(encoding="utf-8"))["plan"]
        counts = plan["counts"]
        if plan["target"] != "publication_handoff" or counts["included_source_bundles"] != 0:
            raise SystemExit(f"{base}: the plan is not a source-bundle-free publication handoff")
        if counts["selected_documents"] != expected:
            raise SystemExit(f"{base}: the plan selects {counts['selected_documents']} of {expected} documents")
        review = {"counts": counts, "library_documents_selected_of": expected,
                  "selection": description, "plan_sha256": plan["manifest_sha256"]}
        _write_json(stages["plan"] / "review.json", review)
        selection_sha = plan["manifest_sha256"]

        stages["publish"] = self.stage(
            f"{base}/publish",
            [str(self.binary), "publish", "run", *shared, *profiles,
             "--reviewed-plan", selection_sha, "{stage}/archive"],
            inputs={"producer": binary, "plan": selection_sha}, outputs={"archive": "{stage}/archive"},
        )
        archive = stages["publish"] / "archive"
        archived = self.output_digest(stages["publish"], "archive")
        stages["producer-verify"] = self.stage(
            f"{base}/producer-verify", [str(self.binary), "verify", "archive-v2", str(archive)],
            inputs={"producer": binary, "archive": archived}, outputs={},
        )
        python = [sys.executable, "-B", str(HARNESS)]
        stages["python-verify"] = self.stage(
            f"{base}/python-verify", [*python, "verify-child", str(archive), "{stage}/work"],
            inputs={"consumer": consumer_hashes(("notrios_archive",), "verify-child"), "archive": archived},
            outputs={"counts": "{stage}/stdout.log"}, mkdirs=("{stage}/work",),
        )
        stages["convert"] = self.stage(
            f"{base}/convert",
            [*python, "convert-child", str(archive), "{stage}/converted", selection_sha,
             "{stage}/conversion-phases.jsonl"],
            inputs={"consumer": consumer_hashes(("notrios2sql",), "convert-child"), "archive": archived},
            outputs={"converted": "{stage}/converted", "phases": "{stage}/conversion-phases.jsonl"},
        )
        converted = stages["convert"] / "converted"
        stages["vault-export"] = self.stage(
            f"{base}/vault-export",
            [sys.executable, "-B", str(REPO / "sql2obsidian.py"), "--input", str(converted),
             "--output", "{stage}/vault", "--include-notrios-receipt", "--no-simplify-urls"],
            inputs={"consumer": consumer_hashes(("sql2obsidian",)),
                    "converted": self.output_digest(stages["convert"], "converted")},
            outputs={"vault": "{stage}/vault"}, mkdirs=("{stage}/vault",),
        )
        vault = stages["vault-export"] / "vault"
        exported = self.output_digest(stages["vault-export"], "vault")
        stages["asset-check"] = self.stage(
            f"{base}/asset-check",
            [*python, "asset-check-child", str(archive), str(converted), str(vault),
             "{stage}/work", "{stage}/asset-check.json"],
            inputs={"consumer": consumer_hashes(("notrios_archive", "notrios_mapping"), "asset-check-child"),
                    "archive": archived, "vault": exported},
            outputs={"result": "{stage}/asset-check.json"}, mkdirs=("{stage}/work",),
        )
        theme = Path(self.config["theme"])
        stages["site-generate"] = self.stage(
            f"{base}/site-generate",
            [sys.executable, "-B", str(REPO / "obsidian2site.py"), "--input", str(vault),
             "--output", "{stage}/site", "--ledger-theme", str(theme), "--search-backend", "bluge",
             "--include-notrios-receipt", "--base-url", "/"],
            inputs={"consumer": consumer_hashes(("obsidian2site",)), "vault": exported,
                    "theme": self.config["theme_revision"]},
            outputs={"site": "{stage}/site"},
        )
        site = stages["site-generate"] / "site"
        generated = self.output_digest(stages["site-generate"], "site")
        stages["hugo"] = self.stage(
            f"{base}/hugo",
            ["hugo", "--source", str(site), "--destination", str(site / "public"),
             "--cacheDir", str(self.root / "hugo-cache"), "--gc", "--minify"],
            inputs={"hugo": self.config["hugo_version"], "site": generated},
            outputs={"public": str(site / "public")},
        )
        built = self.output_digest(stages["hugo"], "public")
        stages["validate"] = self.stage(
            f"{base}/validate",
            [sys.executable, "-B", "-c",
             "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import obsidian2site;"
             "obsidian2site._validate_built_search_backend(Path(sys.argv[2]),'bluge',progress_every=0)",
             str(REPO), str(site)],
            inputs={"consumer": consumer_hashes(("obsidian2site",)), "public": built}, outputs={},
        )
        server = site / "server"
        stages["server-tidy"] = self.stage(
            f"{base}/server-tidy", ["go", "mod", "tidy"],
            inputs={"go": self.config["go_version"], "site": generated},
            outputs={"go.sum": str(server / "go.sum")}, cwd=str(server),
        )
        stages["server-build"] = self.stage(
            f"{base}/server-build",
            ["go", "build", "-o", "movenotes-site-server", "./cmd/movenotes-site-server"],
            inputs={"go": self.config["go_version"], "site": generated,
                    "go.sum": self.output_digest(stages["server-tidy"], "go.sum")},
            outputs={"binary": str(server / "movenotes-site-server")}, cwd=str(server),
        )
        stages["search-index"] = self.stage(
            f"{base}/search-index",
            [str(server / "movenotes-site-server"), "-source", str(server / "search-source.jsonl"),
             "-index", str(server / "bluge-index"), "-index-only"],
            inputs={"server": self.output_digest(stages["server-build"], "binary"), "site": generated},
            outputs={"index": str(server / "bluge-index")}, cwd=str(server),
        )
        return stages

    def live_site(self, route: str, tier: str) -> Path:
        site_stage = self._only(f"{route}/{tier}", "site-generate")
        index_stage = self._only(f"{route}/{tier}", "search-index")
        site = site_stage / "site"
        return self.stage(
            f"{route}/{tier}/live-site",
            [sys.executable, "-B", str(HARNESS), "live-site-child", str(site), "{stage}/live-site.json"],
            inputs={"index": self.output_digest(index_stage, "index"),
                    "consumer": consumer_hashes((), "live-site-child")},
            outputs={"result": "{stage}/live-site.json"},
        )

    def recovery(self, route: str) -> Path:
        publish = self._only(f"{route}/bounded", "publish")
        convert = self._only(f"{route}/bounded", "convert")
        return self.stage(
            f"{route}/bounded/recovery",
            [sys.executable, "-B", str(HARNESS), "recovery-child", str(publish / "archive"),
             "{stage}/work", self.output_digest(convert, "converted"), "{stage}/recovery.json"],
            inputs={"consumer": consumer_hashes(("notrios2sql",), "recovery-child"),
                    "archive": self.output_digest(publish, "archive"),
                    "converted": self.output_digest(convert, "converted")},
            outputs={"result": "{stage}/recovery.json"}, mkdirs=("{stage}/work",),
        )

    def compare(self) -> Path:
        raw, vault, joplin = (self.library(route) for route in ("recipe-raw", "recipe-vault", "joplin"))
        publications = {label: self._only(f"{route}/bounded", "publish")
                        for label, route in (("joplin", "joplin"), ("raw", "recipe-raw"),
                                             ("vault", "recipe-vault"))}
        revision = f"notrios v1.0.0 {self.config['notriosctl_revision']}"
        argv = [sys.executable, "-B", str(REPO / "notrios_c7c.py"),
                "--raw-db", str(raw / "library" / "notes.sqlite"),
                "--vault-db", str(vault / "library" / "notes.sqlite"),
                "--joplin-db", str(joplin / "library" / "notes.sqlite"),
                "--raw-source-root", self.config["sources"]["recipe-raw"],
                "--vault-root", self.config["sources"]["recipe-vault"],
                "--output", "{stage}/comparison",
                "--raw-revision", revision, "--vault-revision", revision]
        for label, folder in publications.items():
            argv += ["--publication", f"{label}={folder / 'archive'}"]
        return self.stage(
            "comparison", argv,
            inputs={"consumer": consumer_hashes(("notrios_c7c",)),
                    "libraries": [self.output_digest(folder, "library") for folder in (raw, vault, joplin)],
                    "publications": {label: self.output_digest(folder, "archive")
                                     for label, folder in publications.items()}},
            outputs={"result": "{stage}/comparison/result.json"},
        )

    def _only(self, base: str, name: str) -> Path:
        return self.current(f"{base}/{name}")

    # ------------------------------------------------------------- summary

    def summary(self) -> dict[str, object]:
        """Every stage's aggregate facts, without a path: what may be committed."""
        stages = []
        for checkpoint in sorted(self.root.rglob("checkpoint.json")):
            folder = checkpoint.parent
            if "attempts" in folder.relative_to(self.root).parts:
                continue
            state = _read_json(checkpoint)
            if "key" not in state:
                continue
            pointer = self.root / f"{state['key']}.current.json"
            current = pointer.exists() and _read_json(pointer)["folder"] == folder.name
            entry = {"key": state["key"], "fingerprint": state["fingerprint"][:12], "current": current,
                     "status": state["status"], "returncode": state.get("returncode")}
            if (folder / "measurement.json").exists():
                measured = _read_json(folder / "measurement.json")
                entry.update(time=measured["time"], elapsed_seconds=measured["elapsed_seconds"],
                             outputs=measured["outputs"])
            for name in ("review.json", "asset-check.json", "live-site.json", "recovery.json"):
                if (folder / name).exists():
                    entry[name.removesuffix(".json")] = _read_json(folder / name)
            if (folder / "conversion-phases.jsonl").exists():
                entry["conversion_phases"] = [
                    json.loads(line) for line in
                    (folder / "conversion-phases.jsonl").read_text(encoding="utf-8").splitlines()
                ]
            attempts = folder / "attempts"
            entry["archived_attempts"] = len(list(attempts.iterdir())) if attempts.is_dir() else 0
            stages.append(entry)
        inventories = {
            path.stem: _read_json(path) for path in sorted((self.root / "inventories").glob("*.json"))
        } if (self.root / "inventories").is_dir() else {}
        result = {"format": "movenotes-7c-trials-summary-v1",
                  "producer": {"sha256": self.config["notriosctl_sha256"],
                               "revision": self.config["notriosctl_revision"]},
                  "inventories": inventories, "stages": stages}
        _write_json(self.root / "summary.json", result)
        return result


# --------------------------------------------------------------- children

def verify_child(archive: str, work: str) -> int:
    sys.path.insert(0, str(REPO))
    from notrios_archive import verify_archive
    with verify_archive(Path(archive), work_dir=Path(work)) as verified:
        print(json.dumps(dict(verified.counts), sort_keys=True))
    return 0


def convert_child(archive: str, destination: str, selection_sha: str, phase_log: str) -> int:
    import resource
    from contextlib import redirect_stdout
    sys.path.insert(0, str(REPO))
    from notrios2sql import import_publication
    started = time.monotonic()

    def rss() -> int:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
        return 0

    with Path(phase_log).open("w", encoding="utf-8") as log:
        def progress(phase: str, **counts: object) -> None:
            log.write(json.dumps({"phase": phase, "elapsed_seconds": round(time.monotonic() - started, 3),
                                  "rss_kib": rss(),
                                  "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                  **counts}) + "\n")
            log.flush()

        with redirect_stdout(sys.stderr):
            result = import_publication(Path(archive), Path(destination),
                                        expected_selection_sha256=selection_sha, progress=progress)
        progress("complete", row_count=result.row_count, resource_count=result.resource_count)
    print(json.dumps(result.summary(), sort_keys=True))
    return 0


def _set_digest(values: list[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        digest.update(value.encode("ascii") + b"\n")
    return digest.hexdigest()


def asset_check_child(archive: str, converted: str, vault: str, work: str, output: str) -> int:
    """Exact bytes and reachable sets, archive -> converted database -> vault."""
    sys.path.insert(0, str(REPO))
    import notrios_mapping as mapping
    from notrios_archive import BlobRef, verify_archive

    def hashed(stream) -> tuple[int, str]:  # noqa: ANN001
        digest, size = hashlib.sha256(), 0
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            digest.update(chunk)
        return size, digest.hexdigest()

    resources: dict[str, BlobRef] = {}
    reachable: set[str] = set()
    declared, actual = [], []
    with verify_archive(Path(archive), work_dir=Path(work)) as verified:
        database_id = verified.manifest.snapshot["database_id"]
        for record in verified.iter_records("resource"):
            ref = BlobRef(**record.payload["blob"])
            resources[record.key[0]] = ref
            declared.append(f"{ref.sha256}:{ref.size_bytes}")
            with verified.open_blob(ref) as stream:
                size, digest = hashed(stream)
            if (size, digest) != (ref.size_bytes, ref.sha256):
                raise SystemExit("archive resource bytes differ from their declarations")
            actual.append(f"{digest}:{size}")
        for record in verified.iter_records("document_resource"):
            reachable.add(record.payload["resource_id"])
    if set(resources) != reachable:
        raise SystemExit("publication resource set and reachable resource set differ")
    mapped = {source: mapping.mapped_id(database_id, "resource", (source,)) for source in resources}
    converted_path = Path(converted)
    uri = (converted_path / "notesdb.sqlite").resolve().as_uri() + "?immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        converted_ids = {row[0] for row in connection.execute(
            "SELECT joplin_id FROM notes WHERE joplin_type_=4")}
        relation_ids = {row[0] for row in connection.execute(
            "SELECT resource_id FROM notrios_document_resources")}
    if relation_ids != set(mapped.values()) or not set(mapped.values()) <= converted_ids:
        raise SystemExit("converted reachable resource set differs from the publication")
    converted_actual = []
    for source, ref in resources.items():
        path = converted_path / "resources" / f"{mapped[source]}.{mapping.resource_extension(ref.media_type)}"
        if path.is_symlink() or not path.is_file():
            raise SystemExit("a converted resource file is missing")
        with path.open("rb") as stream:
            size, digest = hashed(stream)
        if (size, digest) != (ref.size_bytes, ref.sha256):
            raise SystemExit("converted resource bytes differ from the publication")
        converted_actual.append(f"{digest}:{size}")
    manifest = json.loads((Path(vault) / ".movenotes" / "manifest.json").read_text(encoding="utf-8"))
    attachments = manifest.get("attachments", {})
    if set(attachments) != set(mapped.values()):
        raise SystemExit("vault attachment set differs from the publication")
    vault_actual = []
    for source, ref in resources.items():
        path = Path(vault) / attachments[mapped[source]]
        if path.is_symlink() or not path.is_file():
            raise SystemExit("a vault attachment file is missing")
        with path.open("rb") as stream:
            size, digest = hashed(stream)
        if (size, digest) != (ref.size_bytes, ref.sha256):
            raise SystemExit("vault attachment bytes differ from the publication")
        vault_actual.append(f"{digest}:{size}")
    result = {
        "status": "ok", "exact_bytes": True, "reachable_sets_equal": True,
        "archive_resources": len(resources), "archive_reachable_resources": len(reachable),
        "archive_declared_bytes": sum(ref.size_bytes for ref in resources.values()),
        "archive_declared_set_sha256": _set_digest(declared),
        "archive_actual_set_sha256": _set_digest(actual),
        "converted_resources": len(converted_ids), "converted_reachable_resources": len(relation_ids),
        "converted_actual_set_sha256": _set_digest(converted_actual),
        "vault_attachments": len(attachments), "vault_actual_set_sha256": _set_digest(vault_actual),
    }
    _write_json(Path(output), result)
    print(json.dumps(result, sort_keys=True))
    return 0


def _get(port: int, path: str) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def live_site_child(site: str, output: str) -> int:
    """Serve the built site on loopback and check health, pages and a tag count."""
    import urllib.parse
    site_path = Path(site)
    server = site_path / "server"
    tags: dict[str, int] = {}
    rows = 0
    with (server / "search-source.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            rows += 1
            # Normalised as the index stores them: trimmed and lowercased.
            for tag in {tag.strip().lower() for tag in json.loads(line).get("tags") or [] if tag.strip()}:
                tags[tag] = tags.get(tag, 0) + 1
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [str(server / "movenotes-site-server"), "-site", str(site_path / "public"),
         "-source", str(server / "search-source.jsonl"), "-index", str(server / "bluge-index"),
         "-listen", f"127.0.0.1:{port}"],
        cwd=server, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 120
        while True:
            try:
                health, _ = _get(port, "/api/health")
                if health == 200:
                    break
            except OSError:
                pass
            if time.monotonic() > deadline or process.poll() is not None:
                raise SystemExit("the site server did not become healthy")
            time.sleep(0.5)
        home, _ = _get(port, "/")
        result: dict[str, object] = {"status": "ok", "health": health, "home": home,
                                     "search_source_rows": rows, "distinct_tags": len(tags)}
        if tags:
            # The most used tag, ties broken by name, so the check is repeatable.
            tag, expected = min(tags.items(), key=lambda item: (-item[1], item[0]))
            status, body = _get(port, "/api/search?" + urllib.parse.urlencode({"tag": tag}))
            answer = json.loads(body)
            hits = answer.get("results") or []
            page = None
            if hits:
                page, _ = _get(port, urllib.parse.urlsplit(hits[0]["url"]).path or "/")
            result.update(search_status=status, tag_rows_expected=expected,
                          tag_total=answer.get("total"), first_result_page=page)
            if status != 200 or answer.get("total") != expected or page != 200:
                result["status"] = "failed"
        if health != 200 or home != 200:
            result["status"] = "failed"
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    _write_json(Path(output), result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


def recovery_child(archive: str, work: str, expected_digest: str, output: str) -> int:
    """Kill a conversion after its payload is built, then recover only by token.

    A rerun must refuse the stale lock; cleanup checks the ownership token of
    every directory it removes; a fresh conversion must match the bounded
    tier's output, and an unchanged rerun must leave it as it is.
    """
    work_path = Path(work)
    destination = work_path / "converted"
    source_before = measure(Path(archive))
    killer = (
        "import os,sys,signal\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\n"
        "import notrios2sql\noriginal=notrios2sql._build_payload\n"
        "def interrupted(*args):\n    original(*args)\n    os.kill(os.getpid(), signal.SIGKILL)\n"
        "notrios2sql._build_payload=interrupted\n"
        "notrios2sql.import_publication(Path(sys.argv[2]),Path(sys.argv[3]))\n"
    )
    killed = subprocess.run([sys.executable, "-B", "-c", killer, str(REPO), archive, str(destination)],
                            cwd=work_path, capture_output=True)
    result: dict[str, object] = {"killed_exit": killed.returncode,
                                 "destination_absent_after_kill": not destination.exists()}
    convert = [sys.executable, "-B", "-c",
               "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import notrios2sql;"
               "print(notrios2sql.import_publication(Path(sys.argv[2]),Path(sys.argv[3])).summary())",
               str(REPO), archive, str(destination)]
    stale = subprocess.run(convert, cwd=work_path, capture_output=True)
    result["stale_lock_rerun_exit"] = stale.returncode
    locks = [entry for entry in work_path.iterdir() if entry.name.startswith(".movenotes-notrios-lock-")]
    removed = 0
    for lock in locks:
        if lock.is_symlink() or not lock.is_dir():
            raise SystemExit("the stale lock is not a real directory")
        owner = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
        token = owner.get("token")
        if type(token) is not str or len(token) != 48 or any(c not in "0123456789abcdef" for c in token):
            raise SystemExit("the stale lock's token is malformed")
        for field, prefix in (("stage", ".movenotes-notrios-stage-"), ("work", ".movenotes-notrios-work-")):
            name = owner.get(field)
            if name != prefix + token:
                raise SystemExit("a stale directory is not named for the lock's token")
            directory = work_path / name
            if directory.exists():
                if directory.is_symlink() or not directory.is_dir():
                    raise SystemExit("a stale directory is not a real directory")
                if json.loads((directory / "owner.json").read_text(encoding="utf-8")).get("token") != token:
                    raise SystemExit("a stale directory's token differs")
                shutil.rmtree(directory)
                removed += 1
        shutil.rmtree(lock)
        removed += 1
    result["token_checked_directories_removed"] = removed
    fresh = subprocess.run(convert, cwd=work_path, capture_output=True)
    result["fresh_rerun_exit"] = fresh.returncode
    after_fresh = measure(destination)
    result["fresh_matches_bounded_conversion"] = after_fresh["sha256"] == expected_digest
    unchanged = subprocess.run(convert, cwd=work_path, capture_output=True)
    result["unchanged_rerun_exit"] = unchanged.returncode
    result["unchanged_rerun_left_output_unchanged"] = measure(destination)["sha256"] == after_fresh["sha256"]
    result["source_unchanged"] = measure(Path(archive))["sha256"] == source_before["sha256"]
    result["leftover_private_directories"] = sum(
        1 for entry in work_path.iterdir() if entry.name.startswith(".movenotes-notrios-"))
    ok = (killed.returncode == -signal.SIGKILL and result["destination_absent_after_kill"]
          and stale.returncode != 0 and locks and fresh.returncode == 0
          and result["fresh_matches_bounded_conversion"] and unchanged.returncode == 0
          and result["unchanged_rerun_left_output_unchanged"] and result["source_unchanged"]
          and result["leftover_private_directories"] == 0)
    result["status"] = "ok" if ok else "failed"
    _write_json(Path(output), result)
    print(json.dumps(result, sort_keys=True))
    return 0 if ok else 1


# The functions each child command runs, for its stage's fingerprint.
_CHILD_SOURCES = {
    "verify-child": lambda: [verify_child],
    "convert-child": lambda: [convert_child],
    "asset-check-child": lambda: [asset_check_child, _set_digest, _write_json],
    "live-site-child": lambda: [live_site_child, _get, _write_json],
    "recovery-child": lambda: [recovery_child, measure, file_sha256, _write_json],
}


# --------------------------------------------------------------------- CLI

def setup(root: Path, args: argparse.Namespace) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    sources = dict(item.split("=", 1) for item in args.source)
    if set(sources) != set(ROUTES):
        raise SystemExit(f"give one --source for each of {', '.join(ROUTES)}")
    binary = Path(args.notriosctl)
    if file_sha256(binary) != args.expected_sha256:
        raise SystemExit("the producer binary's SHA-256 is not the expected one")
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    copied = bin_dir / "notriosctl"
    if not copied.exists():
        shutil.copy2(binary, copied)
    if file_sha256(copied) != args.expected_sha256:
        raise SystemExit("the copied producer binary's SHA-256 differs")
    build = subprocess.run(["go", "version", "-m", str(copied)], check=True, capture_output=True, text=True).stdout
    revision = next(line.split("=", 1)[1] for line in build.splitlines() if "vcs.revision=" in line)
    theme = Path(args.theme).resolve()
    config = {
        "notriosctl": str(copied), "notriosctl_sha256": args.expected_sha256,
        "notriosctl_revision": revision.strip(),
        "sources": {route: str(Path(path).resolve()) for route, path in sources.items()},
        "theme": str(theme),
        "theme_revision": subprocess.run(["git", "-C", str(theme), "rev-parse", "HEAD"], check=True,
                                         capture_output=True, text=True).stdout.strip(),
        "hugo_version": subprocess.run(["hugo", "version"], check=True, capture_output=True,
                                       text=True).stdout.strip(),
        "go_version": subprocess.run(["go", "version"], check=True, capture_output=True,
                                     text=True).stdout.strip(),
    }
    _write_json(root / "config.json", config)
    empty = root / "empty-config.yaml"
    if not empty.exists():
        empty.write_text("# Isolated local acceptance; explicit database and asset roots.\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in config.items() if key != "sources"}, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    setup_parser = commands.add_parser("setup")
    setup_parser.add_argument("root", type=Path)
    setup_parser.add_argument("--notriosctl", required=True)
    setup_parser.add_argument("--expected-sha256", required=True)
    setup_parser.add_argument("--theme", required=True)
    setup_parser.add_argument("--source", action="append", default=[], metavar="ROUTE=DIR")
    for name in ("producer", "pipeline", "live-site", "recovery", "compare", "summary"):
        sub = commands.add_parser(name)
        sub.add_argument("root", type=Path)
        if name in ("producer", "pipeline", "live-site", "recovery"):
            sub.add_argument("--route", action="append", choices=list(ROUTES))
        if name in ("pipeline", "live-site"):
            sub.add_argument("--tier", required=True, choices=("bounded", "full"))
    for name, count in (("verify-child", 2), ("convert-child", 4), ("asset-check-child", 5),
                        ("live-site-child", 2), ("recovery-child", 4)):
        sub = commands.add_parser(name)
        sub.add_argument("values", nargs=count)
    args = parser.parse_args(argv)
    children = {"verify-child": verify_child, "convert-child": convert_child,
                "asset-check-child": asset_check_child, "live-site-child": live_site_child,
                "recovery-child": recovery_child}
    if args.command in children:
        return children[args.command](*args.values)
    if args.command == "setup":
        setup(args.root, args)
        return 0
    trials = Trials(args.root)
    routes = getattr(args, "route", None) or list(ROUTES)
    failures = []
    try:
        if args.command == "producer":
            for route in routes:
                trials.producer(route)
        elif args.command == "pipeline":
            for route in routes:
                try:
                    trials.pipeline(route, args.tier)
                except StageFailed as failure:
                    # Independent routes continue; this route's later stages
                    # are skipped and the failure is in its checkpoint.
                    failures.append(str(failure))
        elif args.command == "live-site":
            for route in routes:
                try:
                    trials.live_site(route, args.tier)
                except StageFailed as failure:
                    failures.append(str(failure))
        elif args.command == "recovery":
            for route in getattr(args, "route", None) or ["joplin"]:
                trials.recovery(route)
        elif args.command == "compare":
            trials.compare()
    except StageFailed as failure:
        failures.append(str(failure))
    finally:
        trials.summary()
    for failure in failures:
        print(f"FAILED: {failure}", flush=True)
    print("7C_TRIALS_COMPLETE", json.dumps({"command": args.command, "failures": failures}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Sequential P7a baseline profiling; private outputs, no production mutations.

Run with --output on the disk under study. The pinned Go source is exported
to a disposable directory; its CLI receives only an opt-in profiler wrapper.
This measures baselines, not speedups. Child SQL counters retain categories,
never statement text or source content. Failures preserve all prior stages.
"""
from __future__ import annotations

import argparse
from collections import Counter
import cProfile
import hashlib
import importlib
import json
import os
from pathlib import Path
import pstats
import resource
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
PIN = "7662fdd5b55d6f34f14874f70ba6db9f9e7676ac"


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def inventory(root):
    digest = hashlib.sha256()
    count = size = 0
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(data).digest())
            count += 1
            size += len(data)
    return dict(files=count, bytes=size, sha256=digest.hexdigest())


def child(args):
    sys.path.insert(0, str(ROOT))
    module = importlib.import_module(args.module)
    counts = Counter()
    touched = Counter()
    real_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            if sql.lstrip().upper().startswith("UPDATE"):
                touched["update_rows"] += max(cursor.rowcount, 0)
            return cursor

    def connect(*a, **kw):
        kw["factory"] = Connection
        connection = real_connect(*a, **kw)
        connection.set_trace_callback(lambda sql: counts.update([sql.lstrip().split(None, 1)[0].upper()]))
        return connection

    sqlite3.connect = connect
    profiler = cProfile.Profile()
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.monotonic()
    status = "failed"
    try:
        profiler.enable()
        code = module.main(["--input", args.source, "--output", args.destination,
                            "--batch-size", "500", "--progress-every", "0"])
        if code:
            raise RuntimeError(f"import returned {code}")
        status = "complete"
    finally:
        profiler.disable()
        after = resource.getrusage(resource.RUSAGE_SELF)
        profiler.dump_stats(args.profile)
        stats = pstats.Stats(profiler)
        rows = []
        for (filename, line, name), (cc, nc, tt, ct, callers) in stats.stats.items():
            if filename.startswith(str(ROOT)) or any(x in name for x in ("execute", "compress", "stat", "read", "encode", "loads")):
                rows.append(dict(file=Path(filename).name, line=line, function=name,
                                 calls=nc, self_seconds=tt, cumulative_seconds=ct))
        write_json(Path(args.summary), dict(status=status, wall_seconds=time.monotonic()-started,
                   user_seconds=after.ru_utime-before.ru_utime, system_seconds=after.ru_stime-before.ru_stime,
                   max_rss_kib=after.ru_maxrss, input_blocks=after.ru_inblock-before.ru_inblock,
                   output_blocks=after.ru_oublock-before.ru_oublock, sql=dict(counts), touched=dict(touched),
                   functions=sorted(rows, key=lambda x:x["cumulative_seconds"], reverse=True)))


GO_PROFILE = '''package main
import ("os"; "runtime"; "runtime/pprof")
func p7aProfile() func() {
 path := os.Getenv("MOVENOTES_P7A_CPU")
 if path == "" { return func() {} }
 f, err := os.Create(path); if err != nil { panic(err) }
 if err = pprof.StartCPUProfile(f); err != nil { panic(err) }
 return func() { pprof.StopCPUProfile(); f.Close()
  if path := os.Getenv("MOVENOTES_P7A_HEAP"); path != "" {
   h, err := os.Create(path); if err != nil { panic(err) }
   runtime.GC(); if err = pprof.WriteHeapProfile(h); err != nil { panic(err) }; h.Close()
  }
 }
}
'''


def generate(vault, count, resources=False):
    vault.mkdir()
    for i in range(count):
        directory = vault / f"group-{i % 10:02}" / "nested"
        directory.mkdir(parents=True, exist_ok=True)
        metadata = "".join(f"extra_{j}: plain value {j}\n" for j in range(24 if i % 3 == 0 else 2))
        body = ("Ingredient quantity and preparation. Unicode café.\n" * (40 if i % 4 else 400))
        if i % 5 == 0:
            body += f"\n[[note-{(i + 10) % count:06}]] and [external](https://example.invalid/item).\n"
        if resources:
            body += f"\n![asset](../../assets/asset-{i % 32:02}.bin)\n"
        (directory / f"note-{i:06}.md").write_text(
            f'---\ntitle: "Generated note {i}"\ntags:\n  - tag-{i % 17}\n'
            + metadata + "---\n\n" + body, encoding="utf-8")
    if resources:
        (vault / "assets").mkdir()
        for i in range(32):
            (vault / "assets" / f"asset-{i:02}.bin").write_bytes(bytes([i]) * 65536)


def run(args):
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.umask(0o077)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    manifest = dict(status="running", started=time.time(), pin=args.pin, notes=args.notes,
                    python=sys.version, source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in ROOT.glob("*.py")}, stages=[], initial_disk_free=shutil.disk_usage(output).free)
    write_json(output / "manifest.json", manifest)

    def command(label, argv, cwd=None, extra_env=None):
        if shutil.disk_usage(output).free < 2 * 1024**3:
            raise RuntimeError("less than 2 GiB free")
        directory = output / label
        directory.mkdir()
        item = dict(label=label, argv=list(map(str, argv)), started=time.time(), status="running")
        manifest["stages"].append(item)
        write_json(output / "manifest.json", manifest)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.run(argv, cwd=cwd, env=dict(env, **(extra_env or {})), stdout=stdout, stderr=stderr)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        item.update(status="complete" if process.returncode == 0 else "failed", returncode=process.returncode,
                    wall_seconds=time.time()-item["started"], user_seconds=after.ru_utime-before.ru_utime,
                    system_seconds=after.ru_stime-before.ru_stime,
                    # This is a cumulative child high-water, not per-command peak.
                    child_high_water_rss_kib=after.ru_maxrss, disk_free=shutil.disk_usage(output).free)
        write_json(output / "manifest.json", manifest)
        if process.returncode:
            raise RuntimeError(f"{label} failed; see private logs")
        return directory

    def py_profile(label, module, source, destination):
        destination.mkdir(exist_ok=True)
        command(label, [sys.executable, "-B", str(Path(__file__).resolve()), "child", "--module", module,
                 "--source", str(source), "--destination", str(destination),
                 "--profile", str(output / (label + ".prof")), "--summary", str(output / (label + ".json"))])

    try:
        vault = output / "vault"
        generate(vault, args.notes)
        native = output / "python-native"
        py_profile("py-native-fresh", "obsidian2sql", vault, native)
        py_profile("py-native-unchanged", "obsidian2sql", vault, native)
        tiny = output / "tiny"
        generate(tiny, 10)
        # Distinct paths ensure this is a merge, not a content collision.
        for directory in list(tiny.iterdir()):
            directory.rename(directory.with_name("merge-" + directory.name))
        raw = output / "raw"
        raw.mkdir()
        command("export-raw", [sys.executable, "-B", str(ROOT / "sql2joplin.py"), "--input", str(native),
                              "--output", str(raw), "--no-simplify-urls"])
        rawdb = output / "python-raw"
        py_profile("py-raw-fresh", "joplin2sql", raw, rawdb)
        py_profile("py-raw-unchanged", "joplin2sql", raw, rawdb)
        preserved = output / "preserved"
        preserved.mkdir()
        command("export-preserved", [sys.executable, "-B", str(ROOT / "sql2obsidian.py"), "--input", str(rawdb),
                                    "--output", str(preserved), "--no-simplify-urls"])
        py_profile("py-native-small-merge", "obsidian2sql", tiny, native)
        preserveddb = output / "python-preserved"
        py_profile("py-preserved-fresh", "obsidian2sql", preserved, preserveddb)
        py_profile("py-preserved-unchanged", "obsidian2sql", preserved, preserveddb)
        media = output / "media"
        generate(media, min(args.notes, 200), resources=True)
        mediadb = output / "python-media"
        py_profile("py-media-fresh", "obsidian2sql", media, mediadb)
        py_profile("py-media-unchanged", "obsidian2sql", media, mediadb)
        manifest["inputs"] = {name:inventory(output/name) for name in ("vault", "raw", "preserved", "tiny", "media")}
        write_json(output / "manifest.json", manifest)
        if args.notrios_source:
            archive = output / "notrios-source.tar"
            command("archive-pin", ["git", "-C", args.notrios_source, "archive", "--output", str(archive), args.pin])
            source = output / "notrios-source"
            source.mkdir()
            with tarfile.open(archive) as tar:
                tar.extractall(source, filter="data")
            main = source / "cmd/notriosctl/main.go"
            text = main.read_text()
            assert text.count("func main() {") == 1
            main.write_text(text.replace("func main() {", "func main() {\n stopP7a := p7aProfile(); defer stopP7a()", 1))
            (main.parent / "p7a_profile.go").write_text(GO_PROFILE)
            binary = output / "notriosctl-profile"
            command("go-build", ["go", "build", "-o", str(binary), "./cmd/notriosctl"], cwd=source)
            for route, data in (("joplin-raw", raw), ("obsidian", vault)):
                for mode in ("fresh", "unchanged"):
                    label = "go-" + route + "-" + mode
                    db = output / ("go-" + route + ".sqlite")
                    command(label, [str(binary), "import", route, "--db", str(db), "--asset-store",
                                    str(output / ("go-" + route + "-assets")), "--batch-size", "500", str(data)],
                            extra_env={"MOVENOTES_P7A_CPU":str(output / (label + ".cpu")),
                                       "MOVENOTES_P7A_HEAP":str(output / (label + ".heap"))})
                    command(label + "-cpu", ["go", "tool", "pprof", "-top", "-nodecount=35", str(binary), str(output / (label + ".cpu"))])
        manifest.update(status="complete", finished=time.time())
    except BaseException as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, finished=time.time())
        raise
    finally:
        write_json(output / "manifest.json", manifest)
        write_json(output / "notification.json", {k:manifest[k] for k in ("status", "started", "finished")})


def timing(args):
    """Uninstrumented sanity baselines against already-generated inputs."""
    base = Path(args.inputs).resolve()
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.umask(0o077)
    results = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("MOVENOTES_P7A_CPU", None)
    env.pop("MOVENOTES_P7A_HEAP", None)
    status = "failed"
    try:
        for module, data in (("obsidian2sql", "vault"), ("joplin2sql", "raw"), ("obsidian2sql", "preserved")):
            dest = output / data
            dest.mkdir()
            argv = [sys.executable, "-B", str(ROOT/(module+".py")), "--input", str(base/data),
                    "--output", str(dest), "--batch-size", "500", "--progress-every", "0"]
            started = time.time()
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            with (output/(data+".log")).open("wb") as log:
                result = subprocess.run(argv, stdout=log, stderr=log, env=env)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            results.append(dict(route=data, wall_seconds=time.time()-started, returncode=result.returncode,
                                user_seconds=after.ru_utime-before.ru_utime, system_seconds=after.ru_stime-before.ru_stime))
            write_json(output/"results.json", results)
            if result.returncode:
                raise RuntimeError(f"{data} failed")
        status = "complete"
    finally:
        write_json(output/"notification.json",dict(status=status, results=results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("run")
    p.add_argument("--output", required=True)
    p.add_argument("--notes", type=int, default=2000)
    p.add_argument("--notrios-source")
    p.add_argument("--pin", default=PIN)
    p = sub.add_parser("timing")
    p.add_argument("--inputs", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("child")
    for key in ("module", "source", "destination", "profile", "summary"):
        p.add_argument("--"+key, required=True)
    args = parser.parse_args()
    if args.action == "run":
        if args.notes < 20:
            parser.error("at least 20 notes required")
        run(args)
    elif args.action == "timing":
        timing(args)
    else:
        child(args)


if __name__ == "__main__":
    main()

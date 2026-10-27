#!/usr/bin/env python3
"""Development-only differential audit on bounded, synthetic fixture copies.

Normal regression tests read the case specifications and never require Go.
The optional memory worker measures the Python verifier, excluding construction.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import resource
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import notrios_archive as archive_v2
from test_notrios2sql import FIXTURE_ROOT, NotriosObjectSpoolTest, fixture_inventory, load_json


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def memory_worker(tags, blob_bytes):
    if not 0 <= tags <= 9000 or not 0 < blob_bytes <= 64 << 20:
        raise ValueError('memory fixtures require 0..9000 extra tags and 1..64 MiB of blob bytes')
    case = NotriosObjectSpoolTest()
    case.setUp()
    try:
        records = case.envelopes()
        for n in range(tags):
            records.append({'type': 'tag', 'payload': {'id': f'audit_tag_{n:06}', 'name': 'Tag ' + str(n) + 'x' * 256,
                                                      'created_at': '2026-01-01T00:00:00Z'}})
        revision = next(r['payload'] for r in records if r['type'] == 'revision')
        entry = next(e for e in case.entries if e['sha256'] == revision['body']['sha256'])
        old_path, old_size = case.archive / entry['location']['path'], entry['size_bytes']
        temporary = case.root / 'large-body'
        digest = hashlib.sha256()
        remaining = blob_bytes
        with temporary.open('wb') as stream:
            block = b'x' * (1 << 20)
            while remaining:
                chunk = block[:min(remaining, len(block))]
                stream.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        sha = digest.hexdigest()
        path = f'objects/sha256/{sha[:2]}/{sha[2:4]}/{sha}'
        (case.archive / path).parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(case.archive / path)
        old_path.unlink()
        entry.update(sha256=sha, size_bytes=blob_bytes, location={'layout': 'fanout', 'path': path})
        revision['body'].update(sha256=sha, size_bytes=blob_bytes)
        case.manifest['totals']['bytes'] += blob_bytes - old_size
        case.write_records(records)
        del records, revision, block, chunk
        gc.collect()
        tracemalloc.start()
        start = time.monotonic()
        with case.verify() as verified:
            tag_count = sum(1 for _ in verified.iter_records('tag'))
            consumed = 0
            with verified.open_blob(archive_v2.BlobRef(sha, blob_bytes, 'text/markdown')) as stream:
                buffer = bytearray(65536)
                while size := stream.readinto(buffer):
                    consumed += size
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {'extra_tags': tags, 'tag_count': tag_count, 'blob_bytes': blob_bytes,
                'consumed_bytes': consumed, 'python_peak_bytes': peak,
                'process_max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'elapsed_seconds': round(time.monotonic() - start, 3), 'temporary_state_removed': not list(case.work.iterdir())}
    finally:
        case.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notriosctl', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--fixture', type=Path, default=FIXTURE_ROOT / 'publication-loose',
                        help='fixture directory containing archive/ and generation.json')
    parser.add_argument('--cases', type=Path, default=FIXTURE_ROOT / 'verifier-audit-cases.json')
    parser.add_argument('--memory-worker', nargs=2, type=int, metavar=('TAGS', 'BLOB_BYTES'))
    args = parser.parse_args()
    if args.memory_worker:
        print(json.dumps(memory_worker(*args.memory_worker)))
        return
    if not args.notriosctl or not args.output:
        parser.error('--notriosctl and --output are required')
    binary = args.notriosctl.resolve()
    generation = load_json(args.fixture / 'generation.json')
    digest = file_hash(binary)
    if digest != generation['cli_sha256']:
        parser.error('CLI must be the exact pinned synthetic-fixture producer binary')
    specs = args.cases
    results = []
    for spec in load_json(specs):
        case = NotriosObjectSpoolTest()
        case.fixture_source = args.fixture / 'archive'
        case.audit_targets = load_json(args.fixture / 'expected.json').get('audit_targets')
        case.setUp()
        try:
            case.apply_audit_case(spec)
            before = fixture_inventory(case.archive)
            go = subprocess.run([str(binary), 'verify', 'archive-v2', str(case.archive)],
                                capture_output=True, text=True, timeout=60)
            code, message = 'accepted', ''
            try:
                with case.verify():
                    pass
            except archive_v2.NotriosError as error:
                code, message = error.code, str(error)
            matched = (code == spec['expect_python'] and spec['message'] in message
                       and (go.returncode == 0) == spec['expect_go'])
            if fixture_inventory(case.archive) != before or list(case.work.iterdir()):
                raise AssertionError('audit changed input or leaked temporary state')
            result = {'name': spec['name'], 'go_accepted': go.returncode == 0, 'python_result': code,
                      'python_message': message, 'go_message': go.stderr.strip().replace(str(case.archive), '<archive>'),
                      'matched': matched}
            results.append(result)
            if not matched:
                print(json.dumps(result), file=sys.stderr)
        finally:
            case.doCleanups()
    report = {'producer_commit': generation['producer_commit'], 'cli_sha256': digest,
              'fixture_commit_sha256': load_json(args.fixture / 'archive/manifest.json')['commit_sha256'],
              'runner_sha256': file_hash(Path(__file__)),
              'case_spec_sha256': file_hash(specs),
              'verifier_source_sha256': file_hash(ROOT / 'notrios_archive.py'), 'results': results}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if not all(r['matched'] for r in results):
        raise SystemExit(1)
    print(f'{len(results)} differential cases matched the frozen expectations.')


if __name__ == '__main__':
    main()

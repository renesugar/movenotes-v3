# Notrios verifier audit — slice 2e

The loose publication verifier was audited against Notrios commit
`bdecfeda00e582d5aa6170d15b37ba27c9656f1d`, using the exact CLI binary recorded by
the [synthetic publication generator](../../testdata/notrios/publication-loose/generation.json).
The audit covers archive admission and verified-byte consumption. Database
conversion, body limits and Markdown span/target translation remain in Step 3.
The final regression run passed all 166 tests (63 focused Notrios tests) in
76.097 seconds on 2026-09-07.

The [consumer contract](../../docs/notrios-import-contract.md) and
[frozen design](../../docs/notrios-import-design.md) remain authoritative.

## Differential results

All 47 cases matched their declared outcomes: six shared acceptances, 24 shared
refusals and 17 intentional consumer refusals that the general Notrios verifier
accepts. The [case specifications](../../testdata/notrios/verifier-audit-cases.json)
and [captured results](../../testdata/notrios/verifier-audit.json) bind the cases to the
producer commit, CLI hash and Python verifier source hash. Each mutation is made
in a disposable copy, with record counts, object/index hashes and manifest
checksums regenerated. Both verifiers leave the input unchanged.

| Evidence | Result |
|---|---|
| Real publication, reverse record order, legacy zero blob counts, noncanonical storage hints, optional capabilities, resource metadata | Both accept. |
| Duplicate declarations, missing endpoints, wrong current-revision owner, unused blobs, notebook cycles, blob size/MIME disagreement, unknown fields and boolean integer fields | Both refuse. Python also asserts the intended error family and reason. |
| Revision ID reused across owners, retained history, unreachable resources, revision metadata, collection settings and deleted documents | Notrios accepts its general format; the publication consumer refuses as specified. |
| Link context, withheld status, external file URI and multiple internal targets | The consumer enforces the publication link gates absent from the general verifier. Actual body spans and target agreement remain conversion checks. |
| Missing/null integer fields, empty optional parent ID and null blob counts | The consumer refuses Go zero-value decoding allowances explicitly excluded by its strict shape rules. |
| Search notebooks, provenance and source bundles | The general verifier accepts valid records; this publication profile refuses their nonzero counts. |

The prior 56 [Go MIME vectors](../../testdata/notrios/semantic-mime-vectors.json)
remain passing regression evidence for parameter normalization, including
RFC2231 decoding and non-UTF-8 decoded bytes. The complete offline tests retain
the manifest, JSON, byte-limit, inventory, shape, graph and publication mutation
coverage from slices 2a–2d. The Go comparison is a selected mutation matrix, not
an exhaustive equivalence proof; the consumer deliberately implements a narrower
profile.

## Consumption and lifetime fixes

Two reproduced defects were fixed:

- After a verified EOF, a later failed read could be caught by the caller and
  leave the context reporting successful consumption. Read/check failures now
  remain latched, and normal context exit refuses even if the caller caught the
  original exception.
- Retaining a blob context beyond archive exit kept its file and directory
  descriptors alive. The archive now owns and closes outstanding blob streams.
  Directory descriptors are released once the regular file is pinned, before
  yielding a consumer handle. A Linux `/proc/self/fd` regression verifies that
  no archive-owned descriptors remain after exit.

Additional regressions prove that source modification and relocation after
verification cannot change consumed bytes or record lookups. Missing, truncated,
appended, corrupt, symlinked and FIFO private copies refuse at consumption;
repeated opens reauthenticate the bytes. Injected I/O faults do not disclose
raw exception text. Partial consumption refuses and temporary state is removed.

A 17 MiB current body passes generic verification and streams through bounded
reads. It exceeds the frozen 16 MiB conversion-body ceiling; enforcing that
conversion refusal remains a Step 3 preflight responsibility.

## Boundedness evidence

Static review against the pinned `scanIndex`, `addRecord`,
`validateContainers`, `reconcile`, MIME and filesystem rules confirmed:

- Object/record reads, JSON decoding and insert buffers retain the existing
  byte/count caps. Copies use at most 1 MiB chunks; the larger-body consumption
  regression uses 64 KiB reads and checks the actual underlying read requests.
- Record identity and endpoint reconciliation use SQLite keys and indexed
  joins. Collection scope is bounded by 1,000 entries. Each notebook parent walk
  holds at most 32 IDs; it does not materialize the whole notebook tree.
- Ordered record iteration fetches one row at a time. Blob hashes are checked
  while consuming the private file. SQLite retains its 8 MiB page-cache target
  and disk-backed temporary storage.

The [memory observations](../../testdata/notrios/verifier-memory.json) were collected
in separate Python processes. Tracing begins after synthetic fixture creation
and covers verification, ordered tag iteration and 64 KiB blob consumption.
The cases contain 504 tags/1 MiB of body bytes and 8,004 tags/32 MiB of body bytes.
Python peak allocation stays below 3 MiB in both. The recorded process maximum
RSS also includes fixture construction and SQLite/native allocations, so it is
not an isolated verifier measurement. These samples support the bounded design
at the measured sizes; they do not establish a maximum RSS for the registry's
largest archives.

## Reproduce

The development-only runner uses the fixture-generation CLI binary (its hash is
checked), operates only on temporary synthetic copies, and invokes
`verify archive-v2`. Ordinary unit tests read the frozen cases/results and do
not invoke Go or Notrios.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/audit_verifier.py \
  --notriosctl /path/to/the/fixture-generation/notriosctl \
  --output /tmp/verifier-audit.json
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/audit_verifier.py \
  --memory-worker 500 1048576
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/audit_verifier.py \
  --memory-worker 8000 33554432
```

Compare acceptance/error families and case hashes. A Go diagnostic may identify
a different first failing notebook in a cycle because its map iteration order
is unspecified. Memory timings and peaks are observations, not byte-identical
reproduction targets.

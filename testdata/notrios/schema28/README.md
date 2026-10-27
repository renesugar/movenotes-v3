# Schema-28 publication evidence — S28b

Generated on 2026-09-13 with the clean Notrios checkout at
`7662fdd5b55d6f34f14874f70ba6db9f9e7676ac`, Go 1.27.0, Linux amd64, CGO enabled.
Both archives are unmodified output of real import/profile/plan/publish commands
against new, disposable synthetic databases. No private library was opened.
The older schema-27 fixture and its frozen audit/vector data remain unchanged.

| Handoff | Contents | Archive commit SHA-256 | Reviewed selection SHA-256 |
|---|---|---|---|
| [publication-loose](publication-loose/) | 3 notes, 2 notebooks, 4 tags, 6 tag memberships, 3 resources, 4 resource relations, 8 links | `c1cebd8da881cc30cf921ae903b6816ddb3a859280f3f3c6dc69073f1f20e8d4` | `9e06e07e6e57499f1f11577d2aefc8f97fc7370ceeb04f3dac2d17f38cabd97f` |
| [publication-text](publication-text/) | 3 notes, 2 notebooks, 4 tags, 6 tag memberships, 5 links, no resources | `f288ed94a0b9b9340eef4f7022a9f219664cc227e003a7a9c52b8fbf22ece9f7` | `5f3c3babe711c2bfd4b7f2603f5ec5cb9cb22032f2eedab97d98e5a147719c03` |

Pass only each `archive/` directory to the consumer. Reports, source readbacks,
inventories and this README are evidence outside the archive, not public content.
Each `generation.json` records the binary hash, Go build metadata, generator and
helper hashes, input inventories and sanitized command arrays. `expected.json`
binds the copied archive inventory and both digests. Fresh generation chooses
new identities/timestamps; it is semantically reproducible, not byte-identical.

Both source databases have SQLite schema 28. Both manifests declare source 28,
minimum 12 and maximum 28, with archive format version 2 and the same five base
capabilities. Collection records omit their former `capabilities` field. The
private `documents_fts_rowid` table never becomes portable archive state.

The resource fixture reuses the original invented source/update inputs and
independent publication assertions, including historical/private sentinels,
three withheld-link rewrites, exact attachment bytes and zero skipped rewrites.
The [resource-free input](../seed-text-v1/) is a separate archive-v1 seed with
Unicode, duplicate titles, nested notebooks, explicit tags, document links,
an external URL and a self-anchor. Its archive-v2 output was never patched to
remove resources or change the schema version.

## Verification and integration

The producer's current reader accepts and fully verifies both new publications.
Python fully verifies both and the original schema-27 publication. The current
producer also accepts and verifies that original archive; see
[original-schema27-check.json](original-schema27-check.json).

[verifier-audit.json](verifier-audit.json) records all **56** differential cases
against the new resource fixture and exact generation binary. The
[case specifications](../schema28-audit-cases.json) retain the original 47
expectations and add six schema-bound cases plus three present-array cases.
The new fixture itself exercises absent collection capabilities. Results:
**9 shared acceptances, 30 shared refusals, 17 documented consumer-only
refusals**, with no unexpected disagreement. The stricter publication/metadata
rules remain those described in the [original audit](../../../plans/v3.37/001-verifier-audit.md).
No memory benchmark was repeated for this compatibility change.

`NotriosSchema28Test` checks the immutable fixture inventories and producer
reports, replays the current audit cases offline, converts the real text handoff
to 15 rows, confirms an identical rerun leaves the output inventory unchanged,
and runs the real vault exporter. Expected source bodies, tags and mapped note
links are checked independently; vault links use actual duplicate-title paths
and bundle hashes cover finalized files. At the S28b milestone, the
resource-bearing archive refused conversion before publication; resource mapping
and the public CLI were still later work. Slices 5 and 6 subsequently enabled
both. The historical S28b evidence below retains its original validation scope.

The [7a offline CLI-to-vault regression](../README.md#offline-publication-to-vault-acceptance-7a)
now exercises this resource-bearing publication with the supported importer and
vault exporter, including attachments and explicit receipt propagation.

Validation on 2026-09-13: all 17 focused tests passed in 6.644 seconds; all
230 tests across the five regression modules passed in 101.920 seconds with
localhost sockets permitted. Both runs used `PYTHONDONTWRITEBYTECODE=1` and
`python3 -B`. The differential runner reported all 56 expectations matched.

## Reproduce

Use a clean checkout at the pin above. From that Notrios checkout:

```bash
GOCACHE=/tmp/movenotes-s28b-go-cache go build -o /tmp/movenotes-s28b-notriosctl ./cmd/notriosctl
```

From the movenotes repository root (choose new work/output paths):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/generate_schema28.py \
  --notriosctl /tmp/movenotes-s28b-notriosctl \
  --work-dir /tmp/movenotes-s28b-regeneration \
  --output /tmp/movenotes-s28b-fixtures
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/audit_verifier.py \
  --notriosctl /tmp/movenotes-s28b-notriosctl \
  --fixture /tmp/movenotes-s28b-fixtures/publication-loose \
  --cases testdata/notrios/schema28-audit-cases.json \
  --output /tmp/movenotes-s28b-audit.json
/tmp/movenotes-s28b-notriosctl compatibility archive-v2 testdata/notrios/publication-loose/archive
/tmp/movenotes-s28b-notriosctl verify archive-v2 testdata/notrios/publication-loose/archive
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  tests.test_notrios2sql.NotriosManifestTest \
  tests.test_notrios2sql.CollectionCapabilitiesOptionalTest \
  tests.test_notrios2sql.NotriosSchema28Test
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  tests/test_movenotes.py tests/test_image_resources.py tests/test_obsidian2sql.py \
  tests/test_obsidian2site.py tests/test_notrios2sql.py
```

The generator refuses a binary without the exact clean VCS pin. The audit
runner checks its binary hash against the selected fixture's generation record.
For a rebuilt binary with different build metadata, generate a fresh fixture
and audit that pair instead of editing the committed hash. Normal unit tests
need neither Go nor a Notrios executable; the full regression suite needs
localhost sockets for its existing HTTP fixtures.

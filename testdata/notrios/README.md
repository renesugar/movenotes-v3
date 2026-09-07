# Synthetic Notrios publication fixture

Slice 1b fixture, generated on 2026-09-05 by an unmodified Notrios CLI built from
commit `bdecfeda00e582d5aa6170d15b37ba27c9656f1d` (Go 1.27.0, Linux amd64,
CGO enabled). No real notebooks, user profile, service, network import or private
dataset was used. All names, bodies, attachments and privacy sentinels are
invented test data.

## Contents

| Path | Purpose |
|---|---|
| [seed-v1/](seed-v1/) | Hand-authored **archive-v1 input** for the real Notrios importer: five notes, three notebooks and four resources. |
| [update-v1/](update-v1/) | Second v1 import updates `doc_public`, leaving an old revision in the disposable library. |
| [generate_publication.py](generate_publication.py) | Development-only CLI orchestration, independent fixture-specific assertions and evidence capture. No database writes through Python. |
| [publication-loose/archive/](publication-loose/archive/) | The **unmodified archive-v2 publication output** from `publish run`; pass this directory to a verifier or future importer. |
| [expected.json](publication-loose/expected.json) | Both digests, exact file inventory/hashes, expected bodies/tags/paths, resource bytes, relations and retained link records. |
| [source-audit.json](publication-loose/source-audit.json) | Read-only SQL evidence that all five source notes, four source resources and the old revision existed before publishing. |
| [generation.json](publication-loose/generation.json) | CLI build metadata/hash, generator/input hashes and the actual command argument arrays with exit codes. |
| [reports/](publication-loose/reports/) | Import, profile-save, plan, publication, compatibility and verification JSON results. |
| [design-v1.json](design-v1.json) | Slice 1c mapper framing/hash vectors, exact projected fixture bodies, resource extensions, timestamp and explicit final-path examples; specified in [the implementation design](../../NOTRIOS_IMPORT_DESIGN.md). These describe future code, not importer test results. |

Only `archive/` is the handoff. The surrounding reports and expectations are test
evidence and include synthetic withheld IDs on purpose; they must never be
copied inside the archive or treated as publishable content. Adding a README or
report inside `archive/` would violate its exact inventory.

The v1 inputs are not valid inputs to the future archive-v2 importer. They seed
the real producer without constructing v2 records, indexes or checksums by hand.
The generator never patches or rehashes producer output to make assertions pass.

## Frozen output

Archive `commit_sha256`:

```text
b998f2fc889fa382cab7a3332663da5b9852de50696e065032ee7c7e168eba26
```

Reviewed `snapshot.selection_manifest_sha256`:

```text
54f69f1fbc7c75d1077c67d59b524bf3ec81166d10c57024f416ec7638317cb0
```

| Record type | Count |
|---|---:|
| Collection | 1 |
| Notebook | 2 |
| Document / current revision | 3 / 3 |
| Tag / document-tag | 4 / 6 |
| Resource / document-resource | 3 / 4 |
| Retained link | 8 |
| Search notebook / provenance / source bundle | 0 / 0 / 0 |

There are six blobs, one records object and one index chunk, plus `manifest.json`
(nine regular files in the archive). `totals.objects` is seven; index chunks and
the manifest are excluded from that field. See `expected.json` for exact byte
totals rather than filesystem allocation size.

The selection contains `doc_public`, `doc_duplicate` and `doc_child`.
`doc_public` and `doc_duplicate` share the title `Café & field notes` in `Public`;
the child is `Child 東京` under `Public/研究`. Tags include `research notes`,
`café` and `東京`. This exercises title collisions, nested paths, Unicode,
spaces in tag names and multiple tag memberships.

`res_image` is a valid synthetic one-pixel RGBA PNG named `café chart.png`,
referenced by two notes. `res_text` is a UTF-8 file named `field notes.txt`;
Notrios emits MIME `text/plain; charset=utf-8`. `res_sidecar` is a small binary
attachment with a document-resource relation but **no inline link**. All three
publication blob contents equal their source resource files byte-for-byte.

The run reports three rewritten links in one document, zero skipped rewrites,
zero cleared targets, `verified=true` and `full_backup=false`. The private note
is outside the notebook selection; the draft is inside it and excluded by tag.
The private-only resource and old revision body are also withheld. The generator
scans every archived file for all excluded IDs/title/body/resource/history
sentinels, while checking that the selected bodies and attachments actually
exist. This is not an empty-selection privacy test.

## Observations needed by slice 1c

- The three rewritten spans become exactly `withheld note`, `unpublished` and
  `missing label`. The remaining body bytes, external URL, query fence and
  included links match the independent source expectations.
- Link offsets are **UTF-8 byte offsets** into the published body. Unicode
  appears before links, and rewrites shorten earlier spans. Every retained span
  was checked against the resulting body.
- `raw_target` excludes a fragment. The child-section record has a document
  target plus `anchor_type="heading"`, `anchor_value="details"`. The self-link
  `[this section](#details)` has `raw_target=""`, `target_document_id="doc_public"`
  and the same anchor fields. Do not require a missing target ID for self-links.
  These match `internal/markdownlinks/parser.go:decorateCandidate`/`splitAnchor`.
- The planner labels resource links `classification="external"` even though
  their archive link records are `resolution_status="resolved"` with resource
  target IDs. Planner classification counts are not archive link-status counts:
  this fixture has four planner external classifications but one actual HTTP(S)
  external link. Use verified record targets for translation.
- Source SQLite times use `YYYY-MM-DD HH:MM:SS`; export normalizes the same UTC
  instant to RFC3339. The generator compares instants and saves the emitted
  timestamps, rather than requiring identical timestamp spellings.
- Revision `message` is nonempty (`import from Notrios archive` or
  `import update from Notrios archive`). The exporter retains it as described in
  the contract; downstream public metadata must not copy it automatically.
- No nonempty revision metadata or source provenance/bundles were seeded. Their
  absence is checked, but this fixture does not prove stripping of populated
  fields. It also does not exercise Trash, redaction policy, packed objects or
  hostile input. Those remain separate future cases.

These observations refine implementation expectations; they do not implement
the 1c mapping design or the 1d regression module.

## Reproduce a candidate

From the movenotes repository root, with a clean Notrios checkout at the pin,
a Go toolchain and C compiler capable of building that checkout:

```bash
fixture_build=$(mktemp -d /tmp/movenotes-notrios-fixture.XXXXXX)
notrios_repo=~/projects/notrios

git -C "$notrios_repo" rev-parse HEAD
git -C "$notrios_repo" status --short
(
  cd "$notrios_repo"
  GOCACHE="$fixture_build/go-cache" go build -mod=readonly \
    -o "$fixture_build/notriosctl" ./cmd/notriosctl
)

PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/generate_publication.py \
  --notriosctl "$fixture_build/notriosctl" \
  --work-dir "$fixture_build/work" \
  --output "$fixture_build/candidate"

"$fixture_build/notriosctl" verify archive-v2 "$fixture_build/candidate/archive"
```

The build uses ordinary Notrios dependencies, not additional Python packages.
The generator checks embedded VCS revision and `vcs.modified=false`; the existing
repository binary was older and was not used. It supplies an explicit empty
configuration and disposable `--db`, `--asset-store` and `--profiles` paths, then:

1. Imports `seed-v1` and `update-v1` through the real CLI and audits the source.
2. Saves a `publication_handoff` profile selecting the actual Public notebook ID
   recursively with `plain_text` handling and default private-tag exclusions.
3. Runs `publish plan`, checks the expected selected count, and supplies its
   `plan.manifest_sha256` to `publish run --reviewed-plan`.
4. Runs `compatibility archive-v2 --reader previous-loose-v2` and the complete
   `verify archive-v2` operation, without `--no-verify`.
5. Checks exact known bodies, attachment bytes, source history/current-revision
   ownership, counts, tags, links, sentinels and digest agreement, then copies
   the unchanged publication into the new fixture output.

Both work and output paths must be new and non-overlapping. A failed generation
retains its disposable library and raw logs in the work directory; use a new work
path to rerun. No automatic replacement of the committed fixture is provided.
Review a successful candidate before deliberately replacing the fixture and its
expectations together. This process is only for the committed synthetic inputs,
not unattended review of real publication plans.

Fresh generation is **semantically reproducible, not byte-identical**: Notrios
chooses database, replica, notebook, tag, revision and snapshot IDs, along with
timestamps. Those affect both digests. Compare stable note/resource identities,
expected bodies/tags/hierarchy and counts across candidates. The committed
fixture's exact digests and file hashes remain fixed regression expectations.

Reports preserve producer values except that absolute work-directory and CLI
paths become `<work>` and `<notriosctl>`. Raw reports remain under the disposable
work directory. No archive bytes are sanitized or modified after publication.

## Slice 1b verification

The committed archive passed production compatibility and verification, the
generator's independent fixture assertions, and verification again from its
final repository location. Input, generator and archive hashes are recorded in
`generation.json`/`expected.json`. The Notrios checkout remained unchanged.
Only fixture-generation checks were run; the importer does not exist yet and
the existing application runtime was not changed. Next plan item: **1c**.

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
| [manifest-vectors.json](manifest-vectors.json) / [manifest_vectors.go](manifest_vectors.go) | Slice 2a semantic manifest bytes/digests and their independent Go standard-library oracle. Includes serializer-only cases that the loose-publication reader must refuse. |
| [storage-mime-vectors.json](storage-mime-vectors.json) / [storage_mime_vectors.go](storage_mime_vectors.go) | Slice 2b Go-generated MIME syntax acceptance cases for noncanonical storage hints. These do not establish canonical record/reference MIME equality. |
| [semantic-mime-vectors.json](semantic-mime-vectors.json) / [semantic_mime_vectors.go](semantic_mime_vectors.go) | Slice 2d normalization oracle: 56 Go 1.27.0 cases matching the pinned Notrios `normalizeMediaType` rule, including quoting, duplicate parameters, RFC2231 continuations, invalid percent sequences, raw decoded bytes and length bounds. Tests read the frozen output without Go. |
| [verifier-audit-cases.json](verifier-audit-cases.json), [verifier-audit.json](verifier-audit.json), [verifier-memory.json](verifier-memory.json) / [audit_verifier.py](audit_verifier.py) | Slice 2e: pinned-CLI differential results, boundedness observations and a development-only reproducer. See the [audit](../../NOTRIOS_VERIFIER_AUDIT.md) for the scope and two lifetime fixes. |

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

These observations inform the frozen 1c mapping design and the offline 1d
baseline assertions. They do not establish runtime importer acceptance.

## Offline baseline checks — slice 1d

From the movenotes repository root, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.NotriosPublicationFixtureTest
```

The nine baseline tests use only Python's standard library and committed
synthetic data. They do not invoke Notrios, Go, a network service, the fixture
generator or any future importer module. Each test copies only `archive/` into
its own temporary directory, which is cleaned up even after a failed assertion.
The suite checks exact file inventory/hashes, decoded counts, saved digest
agreement, selected notes/tags/hierarchy, seed-derived rewritten bodies, resource
bytes and associations, retained UTF-8 link spans, excluded sentinels, and design
vector shape/fixture linkage. Mapper behavior and hostile-input verification
remain assigned to later slices.

[test_notrios2sql.py](../../test_notrios2sql.py) exposes `copy_publication` for a
new caller-owned destination, `fixture_inventory` for exact small-file hashes,
and `read_fixture_records` for reading the known fixture's records. Future
mutation tests must change the copy, never the committed archive. These helpers
are deliberately fixture-specific, not an alternate archive verifier.

## Text-only integration checks — slice 3c

Run the staged notebook/note and vault-export integration cases:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.NotriosNoteIntegrationTest
```

`make_text_publication` derives a relation-free archive in an owned temporary
copy, replaces body objects, and recomputes object/index/manifest declarations.
It never edits the committed publication. The tests compare imported document
IDs to the frozen vectors and check notebook hierarchy, current revision titles,
document-owned dates, body bytes, insertion order and generic aliases. The real
`sql2obsidian.py` subprocess covers duplicate/empty titles, Unicode paths, selected
notebooks, notebook-only exports, YAML dates and final preservation-bundle hashes.
Database checks retain CRLF, trailing whitespace and missing final LF; vault
checks account for the existing exporter's final-LF convention.

Rehashed invalid graphs, unsupported MIME, malformed UTF-8, forbidden controls
and an invalid last note must refuse before payload insertion. Body size ceilings
must refuse before opening a body stream. Semantic MIME cases retain canonical
blob references while varying the revision's MIME spelling.

These are development tests of the library entry point, not a public importer
CLI. Step 3d owns matching-title heading handling, generated RAW title preludes,
RAW round trips and link adaptation. Tag mapping and round trips are covered by
4a/4b below; resource integration follows later.

## Link projection and exporter checks — slice 3d

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.NotriosLinkProjectionTest test_notrios2sql.NotriosLinkIntegrationTest
```

The projection tests use independently constructed byte spans and full expected
bodies. They cover UTF-8 offsets, ordered replacements, code protection, escaped
punctuation, record/URI/fragment agreement, missing and overlapping records,
unrecorded HTTP(S) links, unsupported syntax, and per-note count/byte ceilings.
Link records inside protected code refuse even when their byte spans are exact.

Integration cases derive owned note-link archives from the synthetic fixture.
They exercise the actual vault and Joplin exporters, matching-title headings,
Unicode/duplicate filenames, selected notebooks and escaped omitted-link labels.
An injected first-write `ENAMETOOLONG` verifies that links use the returned
fallback path; an injected final-write error verifies that no completed bundle
is written. Bundle hashes cover finalized Markdown. Generated RAW carries one
synthetic title prelude, which reimport removes without stripping the real body.
Joplin's import ordering can exchange duplicate-title suffixes, so round-trip
checks validate each export's own path map rather than requiring stable suffixes.

The original full fixture still requires resource conversion and refuses at
this milestone. Resource links and relation-only attachment projection remain
explicitly unsupported until Step 5; these tests do not certify every renderer's
heading-slug behavior. No public importer CLI is exposed.

## Tag mapping checks — slice 4a

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.NotriosTagMappingIntegrationTest
```

The owned text-only archive retains the original fixture's four tag identities
and six memberships. The tests check `load_note_tags` against explicit expected
lists for each note, complete mapped aliases, insertion order, tag-created dates
and document-created membership dates. They also exercise tiny batch limits,
unattached tags, unchanged reruns, and injected wrong aliases, membership targets
and item-type counts that must refuse before publication. Resources still refuse;
Step 4b below covers the broader name/YAML/reimport and malformed-membership matrix.

## Tag-name and YAML round trips — slice 4b

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.NotriosTagRoundTripTest
```

The owned test archive has ten tag identities and fourteen memberships, including
two distinct IDs named `same title` on one note. Names exercise composed and
decomposed Unicode, Japanese, spaces, tabs, quotes, backslashes, punctuation and
the string `true`. Tests independently decode the exported quoted YAML scalars
and run the real `obsidian2sql.py` and `sql2obsidian.py` subprocesses.

The default preservation bundle must retain tag identities and membership
multiplicity through reimport and re-export. Native import without a bundle uses
the existing name-based tag identities; its checks cover the tag text and exact
vault bytes, not retention of distinct Notrios IDs. A selected-notebook round trip
must contain only its tags and memberships. Eleven rehashed mutations cover
duplicate pairs/IDs, missing or extra fields, wrong types, malformed IDs and
missing targets; all must refuse during archive verification before conversion.

## Manifest admission checks — slice 2a

Run all current Notrios tests, including the nine fixture baselines:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.py
```

The 2a cases exercise `ArchiveLimits`, strict byte/depth-bounded JSON, exact
manifest field/type checks, immutable `Manifest` values, Go semantic commit
hashing, reader/schema/capability gates and publication/loose-layout admission.
`read_manifest` opens only the manifest through no-follow directory handles;
the positive and refusal tests work without an objects directory. A valid
manifest is **not** a verified archive: index/record/blob checks start in 2b,
and no importer CLI is enabled by 2a.

The six committed digest vectors were produced with Go 1.27.0. Their oracle
copies all seven struct definitions verbatim from the pinned producer's
`internal/archivev2/format.go` and `index.go`, clears the commit field, then
calls Go `json.Marshal` and SHA-256, as `ComputeCommitSHA256` does. It has no
Notrios package dependency. Tests compare exact semantic bytes as well as
digests, including Unicode/HTML/control escaping, absent versus zero optional
fields, nonzero pack fields, optional capabilities and an ignored commit value.
Unicode IDs and packed locations in the serializer-only vectors are not reader
admission positives. Tests also vary input whitespace and object-key order.

Recompute a candidate using only a Go toolchain, without replacing the golden:

```bash
GOCACHE=/tmp/movenotes-notrios-vector-cache go run testdata/notrios/manifest_vectors.go \
  < testdata/notrios/manifest-vectors.json > /tmp/movenotes-manifest-vectors.candidate.json
cmp testdata/notrios/manifest-vectors.json /tmp/movenotes-manifest-vectors.candidate.json
```

Review a discrepancy against the pinned struct definitions and encoding behavior;
do not regenerate expected digests from the Python implementation under test.
Ordinary tests consume the committed vectors and do not need Go installed.

## Object and index checkpoint — slice 2b

`NotriosObjectSpoolTest` adds twelve tests to the same offline test command.
They exercise an internal `_stage_archive_objects(root, work_dir=..., limits=...)`
context, not a supported importer or complete verifier. The context yields only
after all declared bytes, index structure, record envelope counts and exact source
file inventory have passed. Typed payload fields, record identities, references,
notebook trees, used blobs and publication semantics remain for 2d/2e.

The yielded private `_ObjectSpool` has `directory`, `manifest` and `connection`.
Its SQLite `objects` table holds index/records/blob descriptors; `records` holds
one exact LF-terminated raw envelope per row, indexed by type and object/line;
`source_files` holds the observed inventory for indexed joins. Checked source
bytes are copied under their original fanout paths and made read-only inside a
private temporary directory. The context closes SQLite and removes only that
owned directory on success or exception. Neither its connection nor paths may
outlive the context. There is deliberately no `VerifiedArchive` result yet.

Source files open through held directory descriptors with symlink following
disabled. Copy reads are capped at 1 MiB; JSONL reads are capped before decoding,
including LF in the byte ceiling. SQLite insert buffers stop at 1000 rows or
32 MiB of encoded values (one oversized, individually bounded row is inserted
alone), with an 8 MiB SQLite page cache and disk-backed temporary tables.
The tests lower those limits to exercise actual chunking and flushes. This is
evidence of bounded operations, not a whole-pipeline RSS measurement.

Tests also cover cross-chunk ordering with descending descriptor hashes,
missing/corrupt/truncated index, record and blob files, rehashed malformed
JSONL, record-count disagreement, invalid field types/paths/packing, symlinks,
FIFOs, unexpected/extra files and cleanup after injected failure. Valid empty
fanout directories and legacy all-zero blob `record_counts` remain positives.
Broader hostile mutations and exact boundary cases remain the 2c assignment.

The 22 MIME syntax cases were independently generated with Go 1.27.0 using
`mime.ParseMediaType` plus the pinned producer's 255-byte/nonempty-base gate.
They include duplicate equal/conflicting parameters, quoting and escapes,
extended values, Unicode whitespace and noncanonical hints. Go accepts equal
duplicate parameters and ignores undecodable extended values at the parsing
stage; do not substitute a blanket duplicate-parameter refusal. Canonical MIME
serialization and semantic reference equality are separate 2d work.

To recompute a candidate without replacing the golden:

```bash
GOCACHE=/tmp/movenotes-notrios-vector-cache go run testdata/notrios/storage_mime_vectors.go \
  < testdata/notrios/storage-mime-vectors.json > /tmp/movenotes-storage-mime.candidate.json
cmp testdata/notrios/storage-mime-vectors.json /tmp/movenotes-storage-mime.candidate.json
```

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

After reviewing a regenerated candidate, replace `publication-loose/` and its
reports/expectations together; do not update hashes merely to silence a failure.
The generator does not rewrite `design-v1.json`: deliberately refresh its
fixture-linked database ID, digests, mapped IDs and projected bodies against the
frozen 1c rules, retaining the independent generic ID vectors. Review those
changes, run the offline command above, then commit the fixture and matching
expectations together. Regeneration requires the producer tools; ordinary
baseline testing does not.

Reports preserve producer values except that absolute work-directory and CLI
paths become `<work>` and `<notriosctl>`. Raw reports remain under the disposable
work directory. No archive bytes are sanitized or modified after publication.

## Slice 1b verification

The committed archive passed production compatibility and verification, the
generator's independent fixture assertions, and verification again from its
final repository location. Input, generator and archive hashes are recorded in
`generation.json`/`expected.json`. The Notrios checkout remained unchanged.
Only fixture-generation checks were run in 1b; the importer did not exist and
the existing application runtime was not changed. Slices 1c and 1d subsequently
added the frozen design and offline baselines described above.

## Reproduce the semantic MIME vectors

Run `go run testdata/notrios/semantic_mime_vectors.go < testdata/notrios/semantic-mime-vectors.json` from the repository root with Go 1.27.0. Its output must match the committed JSON byte-for-byte. This development-only oracle follows the pinned producer’s parse/length/format sequence; it does not rewrite the publication fixture.

## Schema-28 compatibility — S28b

The separately pinned [schema-28 evidence](schema28/README.md) adds real
resource-bearing and resource-free publications, a 56-case differential audit,
and offline conversion/no-op/vault regressions. The original schema-27 archive,
expected values and audit results above remain historical evidence.

## Vault-to-site tag semantics — slice 4c

[The tag review](../../NOTRIOS_TAG_REVIEW.md) traces the real schema-28 text
publication through vault export and site generation. `NotriosSiteTagTest`
checks default and capped taxonomy against search-source tags and the posting
index. Generated words remain outside both tag fields; capped written tags
remain searchable through Bluge and Browse Tags.

## Resource storage checks — slice 5a

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.NotriosResourceStorageTest
```

These four tests exercise the real verifier and staged resource storage. They
check exact hashes/sizes/metadata, seven-byte reads and one-row/one-byte batch
budgets, Unicode/path-like and extensionless display names, separate IDs with
shared bytes, empty blobs and collision/hash/size refusal. Read, short-write and
fsync failures during the second resource leave no completed output or owned
stage behind. All mutations use disposable copies; original fixtures are intact.

These tests isolate storage and copy failures. At the 5a milestone production
admission still refused resources; slice 5b removes that temporary gate together
with resource link and association projection. The public CLI remains Step 6.

## Resource links and vault attachments — slice 5b

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_notrios2sql.NotriosResourceProjectionTest
```

The full publication is compared against the frozen projected-body vectors and
source resource hashes. Checks cover mapped associations, the relation-only
attachment suffix, nested note paths, shared resources, distinct semantic MIME
types sharing bytes, selected notebooks and exact attachment paths/bytes through
preservation-bundle reimport. Both unchanged and edited native snapshots retain
their exact note bytes. Missing resource files/rows and missing owning relations
refuse; protected code IDs remain inert. Attachment ordering, label escaping,
deduplication and conversion limits have direct checks. The real schema-28 full
publication also converts through the internal API.

## Attachment byte regressions — slice 5c

The same `NotriosResourceProjectionTest` class adds disposable resource fixtures
with duplicate Unicode names, Markdown-sensitive punctuation, empty bytes and
a larger opaque blob. Filename checks resolve the generated attachment links to
actual files, compare source bytes/hashes independently, and verify preserved
names through bundle reimport and filtered export. Existing filename sanitization
handles wiki-link delimiters; these cases require no runtime change.

The larger resource checks track its importer read requests and independently
hash exported bytes in chunks. No large fixture or generated output is committed.

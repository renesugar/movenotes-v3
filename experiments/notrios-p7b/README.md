# P7b disposable Notrios candidates

This directory records candidates tested against the disposable current Notrios
export only. It does not promote that source revision into the pinned producer
used by acceptance imports.

## G08: line/column prefix index

**Rejected for this slice.** The completed Go comparison found regressions of
about 31% for no-link input and 46% for one long line. The patch remains here
as reproducible exploratory evidence only; do not promote or apply it.

`g08-line-column-prefix.patch` applies to the exported Notrios source at
`f478da7f1065d95d47cf21612833cef991bb8255` (schema 28). It constructs newline
byte offsets once per `markdownlinks.Extract` call, then finds each candidate's
line with binary search and its column with `utf8.RuneCountInString`. Markdown
candidates remain before wikilinks; candidate context, overlap handling and
invalid UTF-8 column semantics are unchanged.

Focused validation:

```bash
GOCACHE=/tmp/movenotes-p7b-go-cache go test ./internal/markdownlinks
```

The later long batch must run `GOCACHE=/tmp/movenotes-p7b-go-cache go test ./...`
and benchmark this candidate as a separate baseline/candidate source tree.

## G01: batch-scoped link/block INSERT statements

Deferred. `rebuildDocumentLinksLocked` and `rebuildDocumentBlocksLocked` are
used by regular document saves and by `RebuildImportDocumentLinksBatch`; they
run under callers' transactions with rollback guarantees. The current
`execPreparedLocked` finalizes each statement. A cache on `SQLiteStore` would
outlive transactions and complicate mutex, close and error cleanup; a safe
transaction-scoped statement owner needs a separate, reviewed design. No G01
patch is included in this P7b candidate.

Apply the patch from the Notrios repository root:

```bash
git apply /path/to/movenotes-v3/experiments/notrios-p7b/g08-line-column-prefix.patch
```

The benchmark source is installed identically in both disposable baseline and
candidate trees, so its presence is not part of the comparison.

`parser_benchmark_test.go` is an identical benchmark source for both exported
Notrios trees. Copy it to `internal/markdownlinks/` in each tree before running:

```bash
cp /path/to/movenotes-v3/experiments/notrios-p7b/parser_benchmark_test.go internal/markdownlinks/
GOCACHE=/tmp/movenotes-p7b-go-cache go test -run '^$' -bench BenchmarkExtractLineLayouts -benchmem ./internal/markdownlinks
```

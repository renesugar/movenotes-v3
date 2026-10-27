# Testing

| Module | Purpose |
|---|---|
| `tests/test_movenotes.py` | End-to-end verification suite (see below)            |
| `tests/test_image_resources.py` | Image localization and quarantine regressions   |
| `tests/test_obsidian2sql.py` | Obsidian import regressions                         |
| `tests/test_obsidian2site.py` | Hugo/Bluge/Pagefind site generation regressions    |
| `tests/test_notrios2sql.py` | Notrios verification, import, vault and site regressions |
| `tests/test_notrios_7c.py` | Tests for the corpus trial harness in `scripts/`      |
| `tests/test_docs.py`    | Documentation link checks (`scripts/check_doc_links.py`) |
| `tests/test_doc_examples.py` | Documentation examples are registered and run (`scripts/check_doc_examples.py`) |

`sample/` contains a small two-source Joplin RAW dataset covering nested
notebooks, duplicate titles, titles needing sanitization, image and PDF
attachments, tags, a duplicate note, an orphan resource, and every link
variety. The verification suite imports it, exercises every script, and
checks byte-for-byte Joplin round trips, unknown/future and duplicate
properties, CRLF input, property whitespace, collision rejection, schema
migration, structured Obsidian property mapping, the embedded lossless
preservation bundle, and performance regressions for indexed/batched
source-fingerprint lookups, dependency traversal, filename deduplication,
attachment-directory indexing, Twitter media fallback lookup, and bulk
image-link replacement:

```
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests/test_movenotes.py tests/test_image_resources.py \
  tests/test_obsidian2sql.py tests/test_obsidian2site.py tests/test_notrios2sql.py tests/test_notrios_7c.py \
  tests/test_docs.py tests/test_doc_examples.py
```

The tests run the scripts as subprocesses, so both the variable and `-B` are
needed: `-B` covers only the test process, and a `__pycache__` left by an
earlier run can shadow the script under test.

`tests/test_notrios2sql.py` checks the Notrios importer against committed synthetic
publications under `testdata/notrios/`, made with real Notrios commands:
verification and its refusals, the import and its reruns, links, attachments,
and the vault and site built from the result. It needs no Notrios binary.
`tests/test_notrios_7c.py` tests the corpus trial harness in `scripts/`, and
`tests/test_docs.py` checks that every relative link and `#anchor` in the
documentation resolves, and `tests/test_doc_examples.py` that every example in
the README and `docs/` is registered in `docs/examples.json`, and runs those
that need only Python against `sample/` and `testdata/`. The examples that need
Hugo, Go, `npx` or `notriosctl` run with
`scripts/check_doc_examples.py --with-tools`; `AGENTS.md` describes the
registry under
[Documentation examples](../AGENTS.md#documentation-examples).

The image-resource suite uses a local HTTP server to verify successful
retrieval, HEAD fallback, redirect MIME changes, byte-signature mismatches,
stop lists, malformed data URIs, deterministic deduplication, quarantine
selection, replacement reuse, and both export paths. The eight modules contain
329 tests and use only the standard library.
On environments where the combined
notebook-filtering class stalls during subprocess cleanup, each test method can
be run independently; the conversion commands themselves complete normally.

`docs/performance-review.md` records the reviewed complexity changes and a local
synthetic benchmark. Results depend on hardware, storage, item size, and the
state of the destination database; they are regression evidence rather than a
runtime guarantee.

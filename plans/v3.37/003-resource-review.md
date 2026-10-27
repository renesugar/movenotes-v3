# Notrios resource safety review — slice 5d

Reviewed the resource path at baseline `22929c8`, including slices 5a–5c.
The review found no required runtime change within the frozen importer boundary.
Three additional integration tests cover orphan-resource refusal, private-copy
mutation immediately before resource consumption, and abrupt process exit
during a real resource write. Validation results are recorded in the
[plan](000-notrios-import-plan.md) and its
[execution ledger](notrios-import-ledger.json).

## Reachability and projection

[`notrios_archive._reconcile_records`](../../notrios_archive.py) checks record
endpoints, blob hash/size references, and the absence of unreferenced blobs.
Every resource must have an included document-resource relation; the reference
target index supports these joins. This establishes membership in the supplied
publication, not independent authorization to publish its content.

[`notrios2sql._project_note`](../../notrios2sql.py) obtains each note's bounded relation
set through indexed lookups. [`notrios_links.validate_links`](../../notrios_links.py)
requires each retained inline resource link to agree with its target and have
an owning relation. `project_body` emits each remaining resource once, following
the frozen ordinal/type/ID order. All original relations remain in the auxiliary
table, with mapped endpoints checked before database commit. No relation anchor
or arbitrary resource metadata is copied into note content.

The new orphan-resource test removes the sidecar's only relation and rehashes
the disposable archive. Verification refuses before payload construction.
Existing projection tests cover a resource still reachable from another note
but lacking the inline link's owning relation, filtered exports, and inert code
references. Source fixture bodies and resource hashes remain independent oracles.

## Rehashing at use and confined writes

The archive verifier copies admitted objects into private work files with size
and SHA-256 checks. `VerifiedArchive.open_blob` opens a regular private file
without following symlinks and returns a fresh `_CheckedBlob` for each use.
Size/hash validation must reach authenticated EOF; caught read failures remain
latched and partial consumption refuses.

`_copy_resource` reads bounded chunks through that interface and independently
checks the written size/hash. It creates only mapped-ID/MIME-extension names
relative to the held resource-directory descriptor, using `O_EXCL|O_NOFOLLOW`.
Display filenames cannot select storage paths. Short writes refuse, and each
resource is flushed and fsynced before publication can proceed.

The new consumption test changes the second resource's private copy after
verification: same-size byte corruption fails at authenticated consumption;
replacing it with a symlink refuses at open. Neither reaches completion, the
earlier resource copy is cleaned with the owned stage, source bytes remain
unchanged, and an outside sentinel remains untouched. Existing storage tests
also demonstrate that an existing resource filename is not overwritten.

Resource payload writes stay inside the owned stage. The design separately
allows private verifier/inventory work and ownership records in the owned
sibling work/lock directories. This is not a claim of literally zero writes
outside the stage directory.

## Publication and interruption recovery

`import_publication` rejects overlapping trees and symlink path components,
acquires an exclusive destination lock, and builds in a private stage. Database
commit/close and resource completion precede the inventory and completion marker.
The payload is rescanned and fsynced before `renameat2(RENAME_NOREPLACE)`;
an unrelated destination winner is not replaced. A parent-directory fsync
failure after rename reports uncertain durability and retains the complete
destination rather than deleting it.

Ordinary exceptions remove only directories whose identity and ownership match.
The new subprocess test uses `os._exit(73)` inside the actual resource writer
after flushing one byte. This bypasses Python cleanup: no final destination or
stage completion marker exists, but the hidden stage/work/lock remain. A retry
refuses without modifying that state. After confirming child exit and matching
owner tokens, the test moves those exact entries into a quarantine directory;
a fresh import succeeds and a subsequent import returns `unchanged`. Quarantined
bytes and source input remain unchanged throughout recovery.

This is process-interruption evidence, not a physical power-loss test. Existing
lifecycle tests cover copy/read/fsync failures, no-replace races, stale locks,
ownership mismatch, edited completed output, and pre/post-rename failures.
The identical-output path hashes the actual inventory and opens SQLite with
`mode=ro&immutable=1`, avoiding writes to an existing completed database.

## Limits of this conclusion

- Publication requires Linux no-replace rename and file/directory fsync support.
- Stale state is never automatically resumed, stolen or deleted. Recovery needs
  an operator to establish that no writer remains and inspect exact ownership.
- Noncooperating same-user mutation of owned paths is outside the frozen threat
  boundary; this review does not certify adversarial parent-directory races.
- The atomic guarantee covers importer output. Vault export remains
  nontransactional and must be rerun into a fresh directory after interruption.
- Checks preserve supplied publication membership and byte integrity; they do
  not certify producer redaction, arbitrary Markdown privacy, every renderer,
  or actual storage hardware durability.

## Reproduction

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  test_notrios2sql.NotriosResourceSafetyTest \
  test_notrios2sql.NotriosResourceStorageTest \
  test_notrios2sql.NotriosPublicationLifecycleTest
```

All fixtures and abrupt-exit artifacts are created in disposable test directories.
No production archive, worker process, or external file is used as a fault target.

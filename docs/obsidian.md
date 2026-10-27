# Obsidian vaults

Import an Obsidian vault into SQLite, export SQLite as a vault, and the lossless round trips between Joplin and Obsidian.

## Import an Obsidian vault into SQLite

```
mkdir -p ~/notes_sqlite

python3 -B obsidian2sql.py \
  --input  ~/obsidian_vault \
  --output ~/notes_sqlite
```

The importer handles two vault kinds:

1. A vault produced by `sql2obsidian.py` contains
   `.movenotes/manifest.json` and `.movenotes/joplin-raw/`. The importer uses
   that bundle as the authoritative Joplin source, preserving auxiliary item
   types, unknown properties, original RAW bytes, and resources. The visible
   Obsidian paths and bytes are also recorded in SQLite.
2. A native Obsidian vault has no Joplin preservation bundle. Markdown notes,
   nested folders, tags, attachments, and other vault files are converted to
   deterministic Joplin-compatible rows. Exact note bytes, arbitrary YAML
   frontmatter, original paths, and non-Markdown file bytes are retained.

Native Obsidian snapshots are compressed into a namespaced value in Joplin's
`application_data` property. This lets the snapshot survive
SQLite → Joplin RAW → SQLite. No third-party YAML library is required: the
converter reads only mapped fields such as `title`, `tags`, `created`,
`updated`, and movenotes' structured `joplin-properties`; the exact original
frontmatter remains authoritative for restoration.

Large vaults use deterministic IDs, batched inserts, indexed collision checks,
one-pass directory discovery, and periodic progress. Options include
`--batch-size`, `--progress-every`, and `--verbose`.

### A damaged preservation bundle

If the vault has a `.movenotes` preservation bundle that cannot be imported,
`obsidian2sql.py` refuses it before it touches the output, rather than quietly
importing the vault as a native one and dropping what the bundle preserves. It
refuses a bundle in any of these cases:

- `manifest.json` is not valid JSON. The error gives the line, column and byte,
  and says so when the file ends mid-document, which is what an interrupted
  export leaves.
- `manifest.json` is not a preservation manifest.
- `manifest.json` is a version this release does not read.
- `joplin-raw/` or `export.json` is present with no manifest, which means an
  export that did not finish.

The error says that nothing was imported and lists the next steps as complete
commands, built from the command that failed. The steps are:

1. Restore `manifest.json` from a backup and rerun the same command. For a
   newer manifest version, update movenotes first.
2. Import the Joplin RAW copy with `joplin2sql.py`. This is lossless for the
   export but leaves out Obsidian edits made since.
3. Rerun with `--ignore-preservation` to import the vault as plain Obsidian
   notes. This keeps the edits but drops the Joplin-only items and properties.
4. Export the source library again into a new directory and import that.

For step 4 the directory is a suggestion, labelled as one. The source library
and the export's options come from the bundle's `export.json`. Vaults
exported before it existed get a named placeholder instead, with a line saying
what to put there.

`--ignore-preservation` also imports a vault with a valid bundle as a native
vault.

## Export SQLite to an Obsidian vault

```
mkdir -p ~/obsidian_vault

python3 -B sql2obsidian.py \
  --input  ~/notes_sqlite \
  --output ~/obsidian_vault
```

Open `~/obsidian_vault` in Obsidian with `Open folder as vault`.

To export only a subset of notebooks — for example, to publish public notes
as a website with Quartz while keeping private notebooks out of the vault
entirely — pass `--notebooks` with comma-separated notebook titles (the
flag may also be repeated):

```
mkdir -p ~/public_vault

python3 -B sql2obsidian.py \
  --notebooks "Blog,Recipes" \
  --input  ~/notes_sqlite \
  --output ~/public_vault
```

Each named notebook and all its subnotebooks are exported; each selected
notebook becomes a top-level vault directory, so a nested notebook's parent
names are not exposed. Only attachments and preservation records belonging to
the selected subset are copied. A name that doesn't match any notebook is an
error, so a typo can't silently publish the wrong notes.

Notebooks become vault subdirectories (nesting preserved) and notes become
`Title.md` files. Obsidian identifies notes by file name rather than by the
unique ids Joplin uses, so titles are sanitized for the filesystem and
duplicate titles within a folder are deduplicated (`Title.md`,
`Title 2.md`, ...). File-name limits are enforced in UTF-8 bytes, and an
`ENAMETOOLONG` write is retried with a deterministic shortened name instead of
aborting a large export. Attachments are copied to an `attachments` folder under
their human-readable names; Joplin resource links are rewritten to
wiki-style embeds (`![[photo.png]]`) for images and relative markdown links
for other files. Each note gets YAML front matter with Obsidian-friendly
`title`, `created`, `updated`, `source-url`, and `tags` properties. Every source
property is also retained in legacy flat `joplin-*` fields and in a structured
`joplin` object. The exact ordered property list, including duplicate keys, is
stored as the directly parseable `joplin-properties` array; the older
`joplin-properties-json` string remains for compatibility. These structured
values are convenient to read through the Obsidian Local REST API (disable
front matter with `--no-frontmatter`).

The vault also contains `.movenotes/joplin-raw/`, a lossless Joplin RAW copy of
all exported items and raw resource files, plus `.movenotes/manifest.json`
with Joplin-to-Obsidian path mappings and SHA-256 checksums. This preservation
bundle keeps non-note items, ignored properties and the original Markdown body
available even though the visible Obsidian note is renamed, has front matter,
and has rewritten links. Pass `--no-preserve-joplin` only when this recovery
copy is not wanted.

An export removes any previous bundle before it writes a note, so a re-export
that stops part way never leaves an old bundle describing notes it no longer
matches. It then writes `.movenotes/export.json`, recording the source library
and the options that shape the vault, so that `obsidian2sql.py` can print the
command to export it again. The path is recorded without the user's name:

- Under the home directory it is written as `~/...`.
- Elsewhere, each path segment equal to the user name is written as `$USER`, as
  in `/run/media/$USER/HD2/library`.

Both are expanded for whoever reads the record. The manifest is written last,
to a temporary file that is renamed into place, so an interrupted export leaves
no manifest rather than a truncated one. URL-only links in visible Obsidian notes are still
simplified by default; use `--no-simplify-urls` to retain their original syntax.

## Lossless round-trip workflows

### Joplin → Obsidian → Joplin

```
mkdir -p ~/notes_sqlite ~/vault ~/notes_sqlite_2 ~/joplin_raw_2

python3 -B joplin2sql.py   --input ~/joplin_raw --output ~/notes_sqlite
python3 -B sql2obsidian.py --input ~/notes_sqlite --output ~/vault
python3 -B obsidian2sql.py --input ~/vault --output ~/notes_sqlite_2
python3 -B sql2joplin.py   --input ~/notes_sqlite_2 --output ~/joplin_raw_2
```

`sql2obsidian.py` writes a `.movenotes/joplin-raw/` recovery copy and a
manifest containing note paths, visible-note SHA-256 values, and attachment
mappings. `obsidian2sql.py` prefers that recovery copy, so an unmodified vault
returns to byte-identical Joplin RAW items and resources. If a visible note was
edited in a current-format vault, its exact Obsidian snapshot is carried in
`application_data` while the Joplin body receives the edited Markdown.

### Obsidian → Joplin → Obsidian

```
mkdir -p ~/notes_sqlite ~/joplin_raw ~/notes_sqlite_2 ~/vault_2

python3 -B obsidian2sql.py --input ~/vault --output ~/notes_sqlite
python3 -B sql2joplin.py   --input ~/notes_sqlite --output ~/joplin_raw
python3 -B joplin2sql.py   --input ~/joplin_raw --output ~/notes_sqlite_2
python3 -B sql2obsidian.py --input ~/notes_sqlite_2 --output ~/vault_2
```

For native vaults, exact Markdown bytes and original paths are stored both in
SQLite and in compressed movenotes metadata inside Joplin `application_data`.
Non-Markdown vault files, including attachment and `.obsidian` files, are
represented as resources with their original paths. When the generated Joplin
body is unchanged, `sql2obsidian.py` restores the original note and file bytes
exactly. Empty vault directories are represented by path-carrying folder rows and are
recreated on export.

If notes are intentionally edited in Joplin, the exporter falls back to a
normal generated Obsidian note rather than overwriting the edit with an older
snapshot.

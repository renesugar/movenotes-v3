# Images

## Localize embedded and remote images

`images2resources.py` edits Markdown note bodies in the SQLite database before
export. It converts inline base64 `data:image/...;base64,...` images and
HTTP(S) Markdown image links into Joplin resource links (`![alt](:/id)`), saves
the validated image bytes in the SQLite directory's `resources/` folder, and
adds resource rows to the database. The existing exporters then produce local
Joplin resources or Obsidian attachments automatically.

```
python3 -B images2resources.py \
  --input  ~/notes_sqlite \
  --config ~/notes_sqlite/movenotes-images.ini
```

The script remains dependency-free. It periodically reports
`processed X of Y note(s)` (the interval is controlled by
`--progress-every`). Remote images are fetched concurrently
with the standard library. Each URL receives a HEAD request first; redirects
are inspected hop-by-hop, then a bounded GET is made. The declared MIME type is
checked against the URL/original response on redirects and against the actual
file signature after download. Non-image responses, MIME changes, malformed
base64, oversize images, network errors, private-network destinations, and
stop-listed domains are left unchanged.

The default configuration path is
`<input>/movenotes-images.ini`; it is created automatically. See
`movenotes-images.example.ini` for all settings. `stop_domains` accepts comma-
or whitespace-separated domains and also blocks subdomains. SVG conversion is
disabled by default because SVG may contain active content. Private, loopback,
link-local, reserved, and other non-public addresses are also blocked by
default; only enable `allow_private_networks` for a trusted local service.

A Markdown report is written to
`<input>/images2resources-report.md` by default. It has separate sections for
links that could not be converted, links intentionally not converted, and
malformed embedded images. Every issue includes the note title, source Markdown
filename/item ID, line number, a preview, and a machine-readable metadata
comment.

To quarantine selected failures, edit the report and change their checkboxes to
`[x]`, then run:

```
python3 -B quarantinelinks.py \
  --input  ~/notes_sqlite \
  --report ~/notes_sqlite/images2resources-report.md \
  --config ~/notes_sqlite/movenotes-images.ini
```

Only checked, exact occurrences are replaced. The replacement is stored as a
normal local resource so both exporters handle it. Pass `--replacement-image`
to use a custom image; otherwise a built-in “Image removed” SVG is created.
The resource ID, local file path, and MIME type are written back to the
configuration and reused on later runs rather than adding duplicate placeholders. The managed
comment and all three values are rewritten together when any value is missing.
Set `quarantine_domains` in the `[quarantine]` section to replace every remote
Markdown image from those domains (and their subdomains); in that mode
`--report` is optional.

Existing local links, Joplin `:/resource` links, Obsidian embeds, and image-like
text inside fenced or inline code are not changed or reported.

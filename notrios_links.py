"""Bounded lexical Markdown projection for the Notrios publication profile.

This deliberately narrow grammar refuses ambiguous active syntax. Protected
code and bytes outside validated destinations remain unchanged.
"""
from array import array
from dataclasses import dataclass, fields
import html
from pathlib import PurePosixPath
import posixpath
import re
import string
from urllib.parse import quote, urlsplit

from notrios_archive import NotriosError


@dataclass(frozen=True)
class ConversionLimits:
    max_body_bytes: int = 16777216
    max_projected_body_bytes: int = 33554432
    max_links_per_note: int = 10000
    max_resource_relations_per_note: int = 10000
    max_fragment_bytes: int = 1024
    batch_rows: int = 1000
    batch_bytes: int = 33554432
    copy_chunk_bytes: int = 1048576

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 0 < value <= field.default:
                raise NotriosError("limit", f"invalid conversion limit: {field.name}")


DEFAULT_CONVERSION_LIMITS = ConversionLimits()

_INTERNAL = rb"document://|resource://|notrios://|:/[0-9a-f]{32}"
_INTERESTING = re.compile(rb"!?\[|" + _INTERNAL, re.I)
_INLINE = re.compile(rb"(!?)\[([^\[\]\\\r\n]*)\]\(([^()\\\s<>]+)\)")
_DOCUMENT = re.compile(rb"document://default/documents/([a-z0-9][a-z0-9_.:-]{1,127})\Z")
_RESOURCE = re.compile(rb"resource://default/resources/([a-z0-9][a-z0-9_.:-]{1,127})\Z")
_MAPPED = re.compile(rb":/([0-9a-f]{32})(?:#(.*))?\Z")
_CODE_MASK = bytes(c if c in (10, 13) else 32 for c in range(256))


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    bang: bool
    label: bytes
    destination: bytes
    base: bytes
    fragment: bytes | None
    destination_start: int
    destination_end: int


@dataclass(frozen=True)
class LinkPlan:
    tokens: tuple[Token, ...]
    replacements: tuple[tuple[int, int, bytes], ...]
    max_projected_body_bytes: int
    inline_resources: tuple[str, ...] = ()
    max_links: int = 10000
    max_resource_relations: int = 10000


@dataclass(frozen=True)
class Attachment:
    resource_id: str
    filename: str
    relation_type: str
    ordinal: int


def _refuse(message):
    raise NotriosError("conversion", message)


def _protected_body(body):
    visible = bytearray(body)
    def protect(start, end):
        # Preserve line boundaries for subsequent lexical checks.
        visible[start:end] = body[start:end].translate(_CODE_MASK)
    fence = None
    ambiguous = False
    for line in re.finditer(rb"[^\n]*(?:\n|$)", body):
        raw = line[0].rstrip(b"\r\n")
        if fence is not None:
            protect(*line.span())
            closing = re.fullmatch(rb" {0,3}(`+|~+)[ \t]*", raw)
            if closing and closing[1][:1] == fence[0] and len(closing[1]) >= fence[1]:
                fence = None
            continue
        opening = re.match(rb" {0,3}(`{3,}|~{3,})(.*)\Z", raw)
        if opening and not (opening[1][:1] == b"`" and b"`" in opening[2]):
            fence = (opening[1][:1], len(opening[1]))
            protect(*line.span())
        elif raw.startswith((b"\t", b"    ")):
            protect(*line.span())
        elif re.match(rb" {0,3}(?:>[ \t]*|[-+*] +|[0-9]+[.)] +).*?(?:`{3,}|~{3,})", raw):
            ambiguous = True
    # Compact run arrays keep unmatched delimiter work linear, without a large
    # Python object per byte or repeatedly rescanning unmatched suffixes.
    starts, ends = array("I"), array("I")
    for run in re.finditer(rb"`+", visible):
        starts.append(run.start())
        ends.append(run.end())
    following = array("I", [len(starts)]) * len(starts)
    last = {}
    for index in range(len(starts) - 1, -1, -1):
        length = ends[index] - starts[index]
        following[index] = last.get(length, len(starts))
        last[length] = index
    index = 0
    while index < len(starts):
        start = starts[index]
        slash = start
        while slash and visible[slash - 1] == 92:
            slash -= 1
        closing = following[index]
        if (start - slash) % 2 == 0 and closing < len(starts):
            protect(start, ends[closing])
            index = closing + 1
        else:
            index += 1
    for escaped in re.finditer(rb"\\[!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~]", bytes(visible)):
        visible[escaped.start():escaped.end()] = b"  "
    if ambiguous and re.search(_INTERNAL, body, re.I):
        _refuse("ambiguous container/fence syntax with an internal target")
    return visible


def scan_markdown(body: bytes):
    """Yield complete active tokens with authoritative UTF-8 byte offsets."""
    visible = _protected_body(body)
    position = 0
    while found := _INTERESTING.search(visible, position):
        token = _INLINE.match(visible, found.start())
        if token is None or visible[token.start():token.end()] != body[token.start():token.end()]:
            _refuse("unsupported or unaccounted active link syntax")
        destination = token[3]
        base, separator, fragment = destination.partition(b"#")
        yield Token(token.start(), token.end(), bool(token[1]), token[2], destination,
                    base, fragment if separator else None, token.start(3), token.end(3))
        position = token.end()


def _fragment(fragment, limits):
    if fragment is None:
        return
    if not fragment or len(fragment) > limits.max_fragment_bytes:
        _refuse("invalid or oversized heading fragment")
    try:
        value = fragment.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("fragment is not UTF-8")
    if (value.startswith("^") or "#" in value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or re.search(rb"%(?![0-9A-Fa-f]{2})", fragment)):
        _refuse("unsupported heading fragment")


def _target(token, limits):
    _fragment(token.fragment, limits)
    if match := _DOCUMENT.fullmatch(token.base):
        if token.bang:
            _refuse("document embeds are unsupported")
        return "document", match[1].decode("ascii")
    if token.base == b"" and token.fragment is not None:
        if token.bang:
            _refuse("self-anchor embeds are unsupported")
        return "self", None
    if match := _RESOURCE.fullmatch(token.base):
        if token.fragment is not None:
            _refuse("resource fragments are unsupported")
        return "resource", match[1].decode("ascii")
    try:
        value = token.destination.decode("utf-8")
        parsed = urlsplit(value)
        valid = (parsed.scheme.lower() in ("http", "https") and bool(parsed.hostname)
                 and parsed.username is None and parsed.password is None and "\\" not in value
                 and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value))
        parsed.port
    except (ValueError, UnicodeDecodeError):
        valid = False
    if not valid:
        _refuse("unsupported link destination")
    return "external", None


def validate_links(body: bytes, records, *, resolve, limits=DEFAULT_CONVERSION_LIMITS, resource_ids=()):
    """Reconcile bounded archived spans with active tokens before projection."""
    if len(body) > limits.max_body_bytes:
        raise NotriosError("limit", "body exceeds conversion limit")
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("body is not UTF-8")
    tokens = []
    for token in scan_markdown(body):
        if len(tokens) >= limits.max_links_per_note:
            raise NotriosError("limit", "active link count exceeds limit")
        tokens.append(token)
    retained = []
    for record in records:
        if len(retained) >= limits.max_links_per_note:
            raise NotriosError("limit", "archived link count exceeds limit")
        if record.kind != "link":
            _refuse("link validation requires link records")
        retained.append(record.payload)
    retained.sort(key=lambda p: (p["source_start_byte"], p["source_end_byte"], p["id"]))
    by_start = {token.start: token for token in tokens}
    accounted, replacements, previous, owner = set(), [], 0, None
    related, inline_resources = set(), set()
    for count, ident in enumerate(resource_ids, 1):
        if count > limits.max_resource_relations_per_note:
            raise NotriosError("limit", "resource relation count exceeds limit")
        related.add(ident)
    for p in retained:
        start, end = p["source_start_byte"], p["source_end_byte"]
        if (not 0 <= start < end <= len(body) or start < previous
                or body[start] & 0xc0 == 0x80 or end < len(body) and body[end] & 0xc0 == 0x80):
            _refuse("invalid, overlapping or non-UTF-8 link span")
        previous = end
        token = by_start.get(start)
        if token is None or token.end != end:
            _refuse("archived link does not match a complete active token")
        source_id = p["source_document_id"]
        if owner is not None and owner != source_id:
            _refuse("link records have different source documents")
        owner = source_id
        if (p["source_format"] != "markdown" or p["relation_type"] != ("embed" if token.bang else "link")
                or p["raw_target"] != token.base.decode("utf-8")
                or "display_text" in p and p["display_text"] != token.label.decode("utf-8")):
            _refuse("link record disagrees with active token")
        if token.fragment is None:
            if p.get("anchor_type") or p.get("anchor_value"):
                _refuse("fragment-free link has anchor metadata")
        elif p.get("anchor_type") != "heading" or p.get("anchor_value") != token.fragment.decode("utf-8"):
            _refuse("heading fragment disagrees with link record")
        kind, target_id = _target(token, limits)
        if kind in ("document", "resource"):
            target_field = "target_document_id" if kind == "document" else "target_resource_id"
            other_field = "target_resource_id" if kind == "document" else "target_document_id"
            if (p["resolution_status"] != "resolved" or p.get(target_field) != target_id
                    or other_field in p or "target_uri" in p and p["target_uri"] != token.base.decode()):
                _refuse(kind + " target disagrees with link record")
            mapped = resolve(kind, target_id)
            if not re.fullmatch(r"[0-9a-f]{32}", mapped):
                _refuse("resolver did not return a mapped identity")
            if kind == "resource":
                if mapped not in related:
                    _refuse("resource link has no document-resource relation")
                inline_resources.add(mapped)
            destination = b":/" + mapped.encode() + (b"#" + token.fragment if token.fragment is not None else b"")
            replacements.append((token.destination_start, token.destination_end, destination))
        elif kind == "self":
            if (p["resolution_status"] != "resolved" or p.get("target_document_id", source_id) != source_id
                    or "target_resource_id" in p or p.get("target_uri", "") not in ("", f"document://default/documents/{source_id}")):
                _refuse("self-anchor target disagrees with link record")
        elif (p["resolution_status"] != "external" or "target_document_id" in p or "target_resource_id" in p
              or "target_uri" in p and p["target_uri"] != token.base.decode("utf-8")):
            _refuse("external target disagrees with link record")
        accounted.add(start)
    for token in tokens:
        kind, _ = _target(token, limits)
        if kind != "external" and token.start not in accounted:
            _refuse("active internal link has no retained record")
    return LinkPlan(tuple(tokens), tuple(replacements), limits.max_projected_body_bytes,
                    tuple(sorted(inline_resources)), limits.max_links_per_note, limits.max_resource_relations_per_note)


def _replace(body, replacements, maximum):
    size = len(body) + sum(len(value) - (end - start) for start, end, value in replacements)
    if size > maximum:
        raise NotriosError("limit", "projected body exceeds conversion limit")
    result, previous = bytearray(), 0
    for start, end, value in replacements:
        result.extend(body[previous:start])
        result.extend(value)
        previous = end
    result.extend(body[previous:])
    return result.decode("utf-8")


def _attachment_label(label):
    for before, after in (("&", "&amp;"), ("[", "&#91;"), ("]", "&#93;"),
                          ("<", "&lt;"), (">", "&gt;"), ("\\", "&#92;")):
        label = label.replace(before, after)
    return label


def project_body(body: bytes, plan: LinkPlan, *, related_resources=()):
    missing = {}
    inline = set(plan.inline_resources)
    for count, attachment in enumerate(related_resources, 1):
        if count > plan.max_resource_relations:
            raise NotriosError("limit", "resource relation count exceeds limit")
        if attachment.resource_id in inline:
            continue
        key = (attachment.ordinal, attachment.relation_type.encode("utf-8"), attachment.resource_id)
        previous = missing.get(attachment.resource_id)
        if previous is None or key < previous[0]:
            missing[attachment.resource_id] = (key, attachment.filename)
    projected = _replace(body, plan.replacements, plan.max_projected_body_bytes)
    if not missing:
        return projected
    if len(plan.tokens) + len(missing) > plan.max_links:
        raise NotriosError("limit", "projected link count exceeds limit")
    suffix = ["\n\n## Attachments\n\n"]
    size = len(projected.encode("utf-8")) + len(suffix[0])
    for (_, _, ident), label in sorted(missing.values()):
        label = _attachment_label(label)
        line = f"- [{label}](:/{ident})\n"
        size += len(line.encode("utf-8"))
        if size > plan.max_projected_body_bytes:
            raise NotriosError("limit", "projected body exceeds conversion limit")
        suffix.append(line)
    return projected + "".join(suffix)


def is_generated_note(row):
    return (row["joplin_type_"] == 1 and row["joplin_source"] == "movenotes-notrios"
            and row["joplin_source_application"] == "movenotes-notrios2sql")


def projected_note_body(row):
    body = row["note_data"] or ""
    if row["note_original_format"] == "notrios":
        return body
    # Generated RAW contains exactly one title line and one empty separator.
    # Never strip further blank lines or a matching heading in the real body.
    prelude = re.match(r"[^\r\n]*(?:\r\n\r\n|\n\n|\r\r)", body)
    if prelude is None:
        _refuse("generated RAW note lacks its title separator")
    return body[prelude.end():]


def rewrite_projected_links(body: str, *, note_id: str, note_path: PurePosixPath,
                            lookup_item_type, lookup_note_path, attachments):
    """Resolve mapped note links using actual vault paths, never titles.

    The caller's path callback may return None only for a filtered-out note;
    it owns counting those omissions and refusing missing unfiltered paths.
    """
    raw = body.encode("utf-8")
    limits = DEFAULT_CONVERSION_LIMITS
    if len(raw) > limits.max_projected_body_bytes:
        raise NotriosError("limit", "projected body exceeds conversion limit")
    replacements = []
    for count, token in enumerate(scan_markdown(raw), 1):
        if count > limits.max_links_per_note:
            raise NotriosError("limit", "projected link count exceeds limit")
        match = _MAPPED.fullmatch(token.destination)
        if match is None:
            kind, _ = _target(token, limits)
            if kind not in ("external", "self"):
                _refuse("unmapped internal link in projected note")
            continue
        _fragment(token.fragment, limits)
        item_id = match[1].decode("ascii")
        item_type = lookup_item_type(item_id)
        if item_type == 4:
            if token.fragment is not None or attachments is None:
                _refuse("invalid mapped resource target")
            name = attachments.vault_name(item_id, required=True)
            if name is None:
                _refuse("missing mapped resource")
            if token.bang and attachments.is_image(item_id):
                replacements.append((token.start, token.end, f"![[{name}]]".encode("utf-8")))
            else:
                relative = posixpath.relpath("attachments/" + name, start=str(note_path.parent))
                label = token.label or _attachment_label(name).encode("utf-8")
                replacements.append((token.start, token.end,
                    b"[" + label + b"](" + quote(relative, safe="/-._~").encode("ascii") + b")"))
            continue
        if item_type != 1 or token.bang:
            _refuse("mapped link has no supported note target")
        path = lookup_note_path(item_id)
        if path is None:
            label = html.unescape(token.label.decode("utf-8"))
            label = "".join("\\" + c if c in string.punctuation else c for c in label)
            replacements.append((token.start, token.end, label.encode("utf-8")))
        else:
            relative = posixpath.relpath(str(path), start=str(note_path.parent))
            destination = quote(relative, safe="/-._~").encode("ascii")
            if token.fragment is not None:
                destination += b"#" + token.fragment
            replacements.append((token.destination_start, token.destination_end, destination))
    return _replace(raw, replacements, limits.max_projected_body_bytes)

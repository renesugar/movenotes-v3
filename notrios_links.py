"""Bounded lexical Markdown projection for the Notrios publication profile.

Inline links are recognised the way the producer's own parser recognises them,
so every span it records is a token here. Any other bracket is prose. Internal
targets are the only bytes that change, and an internal target anywhere outside
a token refuses. Protected code and every other byte remain unchanged.
"""
from array import array
import bisect
from dataclasses import dataclass, fields
import html
from pathlib import PurePosixPath
import posixpath
import re
import string
from urllib.parse import quote, unquote_to_bytes

from notrios_archive import NotriosError, UNRESOLVED_LINK_STATUSES


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
# An optional title after the destination is copied, never parsed (S43a): the
# producer writes back the author's own bytes, so all three delimiters occur.
# It stays on one line and excludes backslashes and backticks, so escapes and
# code spans cannot move its end; an unescaped closing delimiter ends it.
_TITLE = rb"[ \t]+(?:\"[^\"\\`\r\n]*\"|'[^'\\`\r\n]*'|\([^()\\`\r\n]*\))[ \t]*"
# The exact destination grammar an internal target must use, so its bytes can
# be replaced in place (C7a). The label is matched separately, as the producer
# matches it.
_STRICT_DESTINATION = re.compile(rb"([^()\\\s<>]+)(" + _TITLE + rb")?")
_TITLE_REFUSED = re.compile(rb"[\x00-\x08\x0b-\x1f\x7f]|" + _INTERNAL, re.I)
_INTERNAL_ANYWHERE = re.compile(_INTERNAL, re.I)
# A Joplin HTML image whose source the producer rewrote to its resource URI
# (and, in a projected note, the mapped form written back). It carries no link
# record, only the note's attachment relation.
_HTML_IMAGE = re.compile(rb"<img\b[^<>]*?[ \t\r\n]src[ \t]*=[ \t]*([\"'])("
                         rb"resource://default/resources/[a-z0-9][a-z0-9_.:-]{1,127}|:/[0-9a-f]{32})\1[^<>]*>", re.I)
# Go's unicode.IsSpace, which the producer's strings.TrimSpace uses.
_GO_SPACE = "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a" \
            "\u2028\u2029\u202f\u205f\u3000"
_DOCUMENT = re.compile(rb"document://default/documents/([a-z0-9][a-z0-9_.:-]{1,127})\Z")
_RESOURCE = re.compile(rb"resource://default/resources/([a-z0-9][a-z0-9_.:-]{1,127})\Z")
_MAPPED = re.compile(rb":/([0-9a-f]{32})(?:#(.*))?\Z")
# An internal target in a destination position that no token covers, because
# its label holds escaped brackets the producer's parser stops at; the producer
# rewrote it at import and recorded no link (C7d). Only the bytes up to the
# closing parenthesis are taken, without a title.
_BARE = re.compile(rb"(document://default/documents/[a-z0-9][a-z0-9_.:-]{1,127}(?:#[^()\\\s<>]*)?"
                   rb"|resource://default/resources/[a-z0-9][a-z0-9_.:-]{1,127}"
                   rb"|:/[0-9a-f]{32}(?:#[^()\\\s<>]*)?)\)")
_CODE_MASK = bytes(c if c in (10, 13) else 32 for c in range(256))
# A recorded wiki link the import replaces (R2, W1): one line, and no
# backtick, so blanking it cannot change which bytes are code.
_WITHHELD_WIKI = re.compile(rb"!?\[\[[^\[\]\n`]+\]\]")
# The producer's plain_text placeholder for a link with no text (replacementFor).
_REDACTED = b"[redacted]"


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
    # Bytes between the destination and the closing parenthesis: separating
    # whitespace and the delimited title, or empty when there is no title.
    title_suffix: bytes = b""
    # An HTML image source: start..end is the attribute value alone.
    html: bool = False
    # An unrecorded internal destination (_BARE): start..end is the
    # destination alone, and the label is unknown.
    bare: bool = False


@dataclass(frozen=True)
class LinkPlan:
    tokens: tuple[Token, ...]
    replacements: tuple[tuple[int, int, bytes], ...]
    max_projected_body_bytes: int
    inline_resources: tuple[str, ...] = ()
    max_links: int = 10000
    max_resource_relations: int = 10000
    withheld_links: int = 0


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
    ambiguous = None
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
        elif ambiguous is None and re.match(rb" {0,3}(?:>[ \t]*|[-+*] +|[0-9]+[.)] +).*?(?:`{3,}|~{3,})", raw):
            ambiguous = line.start()
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
    # A fence inside a container changes only what follows it, so an internal
    # target before the first such line is read the same either way (C7d).
    if ambiguous is not None and _INTERNAL_ANYWHERE.search(body, ambiguous):
        _refuse("ambiguous container/fence syntax with an internal target")
    return visible


def _angle_close(text, open_):
    """The producer's angleClose: the ``>`` closing ``<`` at open_, on one line."""
    index = open_ + 1
    while index < len(text):
        char = text[index]
        if char in (10, 60):  # newline, "<"
            return None
        if char == 92:  # a backslash escapes the next byte
            index += 1
        elif char == 62:
            return index
        index += 1
    return None


def _close_paren(body, start):
    """The producer's closeParen: balanced, escape-aware, ending at the line.

    Unbalanced parentheses fall back to the first ``)``, as the producer does.
    """
    depth, first = 0, None
    index = start
    while index < len(body):
        char = body[index]
        if char == 10:
            break
        if char == 92:
            if index + 1 < len(body) and body[index + 1] == 10:
                break
            index += 1
        elif char == 40:
            depth += 1
        elif char == 41:
            if first is None:
                first = index
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return first


def _target_end(body, start):
    if start < len(body) and body[start] == 60:
        bracket = _angle_close(body, start)
        if bracket is not None and (end := _close_paren(body, bracket + 1)) is not None:
            return end
    return _close_paren(body, start)


def _destination(region, offset):
    """Split a link's parenthesised bytes as the producer's markdownDestination.

    Returns the destination's start and end offsets in the body.
    """
    text = region.decode("utf-8")
    stripped = text.strip(_GO_SPACE)
    lead = len(text[:len(text) - len(text.lstrip(_GO_SPACE))].encode("utf-8"))
    start = offset + lead
    raw = stripped.encode("utf-8")
    if raw.startswith(b"<") and (bracket := _angle_close(raw, 0)) is not None:
        inner = raw[1:bracket].decode("utf-8")
        inner_lead = len(inner.encode("utf-8")) - len(inner.lstrip(_GO_SPACE).encode("utf-8"))
        value = inner.strip(_GO_SPACE).encode("utf-8")
        return start + 1 + inner_lead, start + 1 + inner_lead + len(value)
    space = min((i for i in (raw.find(b" "), raw.find(b"\t")) if i > 0), default=None)
    if space is not None:
        value = raw[:space].decode("utf-8").strip(_GO_SPACE).encode("utf-8")
        return start, start + len(value)
    return start, start + len(raw)


def _inline_at(visible, body, start):
    """Match one inline link or image at start exactly as the producer does.

    The label runs to the first ``]`` on its line and the destination to the
    parenthesis that closes it. An internal target must also use the strict
    destination grammar, so its bytes can be replaced in place; anything else
    is an external token whose bytes stay as they are.
    """
    bang = visible[start] == 33
    open_ = start + bang
    text = open_ + 1
    while text < len(body) and body[text] not in (93, 10):
        text += 1
    if text + 1 >= len(body) or body[text] != 93 or body[text + 1] != 40:
        return None
    end = _target_end(body, text + 2)
    if end is None or end == text + 2:
        return None
    label = body[open_ + 1:text]
    if _INTERNAL_ANYWHERE.search(body, text + 2, end):
        strict = _STRICT_DESTINATION.fullmatch(visible, text + 2, end)
        if strict is None or visible[text + 2:end] != body[text + 2:end]:
            _refuse("unsupported or unaccounted active link syntax")
        destination_start, destination_end = strict.span(1)
    else:
        destination_start, destination_end = _destination(body[text + 2:end], text + 2)
    destination = body[destination_start:destination_end]
    if destination.startswith(b"[["):
        # A wiki link written where an href belongs names nothing; the
        # producer keeps all of its bytes as the target (J37).
        base, fragment = destination, None
    else:
        base, separator, fragment = destination.partition(b"#")
        fragment = fragment if separator else None
    return Token(start, end + 1, bang, label, destination, base, fragment,
                 destination_start, destination_end, body[destination_end:end])


def scan_markdown(body: bytes):
    """Yield complete active tokens with authoritative UTF-8 byte offsets.

    A bracket that does not start a token is prose, and scanning resumes just
    after it, so a token inside it is still found. An internal target that is
    not inside a token's destination or a recognised HTML image source refuses,
    wherever it is: reference definitions, wiki links and other unsupported
    forms cannot hide one. The one exception is a strict internal destination
    directly after ``](`` that no token covers (_BARE). Wiki links are text
    (C7d).
    """
    visible = _protected_body(body)
    images = {match.start(2): match for match in _HTML_IMAGE.finditer(visible)
              if visible[match.start():match.end()] == body[match.start():match.end()]}
    position = 0
    while found := _INTERESTING.search(visible, position):
        start = found.start()
        if visible[start] in (33, 91):  # "!" or "["
            token = _inline_at(visible, body, start)
            if token is not None:
                # A title is inert text, so it must not hide an internal target
                # from link accounting or carry controls into rendered attributes.
                if _TITLE_REFUSED.search(token.title_suffix):
                    _refuse("unsupported link title")
                yield token
                position = token.end
                continue
            position = start + 1
            continue
        image = images.get(start)
        if image is None:
            bare = _BARE.match(body, start)
            if (bare is None or body[start - 2:start] != b"](" or visible[start - 1] != 40
                    or visible[start:bare.end()] != body[start:bare.end()]):
                _refuse("unsupported or unaccounted active link syntax")
            end = bare.end(1)
            destination = body[start:end]
            base, separator, fragment = destination.partition(b"#")
            yield Token(start, end, False, b"", destination, base, fragment if separator else None,
                        start, end, bare=True)
            position = end
            continue
        value = image[2]
        yield Token(start, image.end(2), True, b"", value, value, None, start, image.end(2), html=True)
        position = image.end(2)


def _protected_record_token(body, start, end, visible):
    """The token for an archived span that starts inside protected code.

    The producer scans code, so it records links there that this scanner
    protects. Such a span is read with the producer's grammar over the raw
    bytes, and must be exactly one link holding no internal target, external
    or a self-anchor; its bytes are never changed (C7d). Any other unmatched
    span refuses.
    """
    if visible is None:
        visible = _protected_body(body)
    if visible[start] == body[start] or _INTERNAL_ANYWHERE.search(body, start, end):
        _refuse("archived link does not match a complete active token")
    token = _inline_at(body, body, start)
    if token is None or token.end != end:
        _refuse("archived link does not match a complete active token")
    return token, visible


def _bare_record_token(body, start, end, bare):
    """The token for a record whose span ends at an unrecorded-form destination.

    The producer's label ends at the first ``]``, escaped or not, so it can
    record a link this scanner reads as a bare destination (_BARE). The span
    must be that label and destination exactly; the token takes its bounds.
    """
    bang = body[start] == 33
    label_start = start + bang + 1
    if (body[start + bang] != 91 or not label_start <= bare.start - 2 or bare.end + 1 != end
            or b"\n" in body[label_start:bare.start - 2]):
        _refuse("archived link does not match a complete active token")
    return Token(start, end, bang, body[label_start:bare.start - 2], bare.destination, bare.base, bare.fragment,
                 bare.destination_start, bare.destination_end, bare=True)


def _wiki_record(body, start, end, p, token_starts):
    """A wiki link the producer recorded is kept as text, as an unrecorded one
    is (C7d): Obsidian resolves it by title. Its span must be one wiki link on
    one line, holding the recorded target, no internal target and no token."""
    span = body[start:end]
    first = bisect.bisect_left(token_starts, start)
    if (not re.fullmatch(rb"!?\[\[[^\[\]\n]+\]\]", span) or _INTERNAL_ANYWHERE.search(span)
            or p["raw_target"].encode("utf-8") not in span
            or first < len(token_starts) and token_starts[first] < end):
        _refuse("archived link does not match a complete active token")


def _wiki_text(text):
    """A wiki link's alias or its target's name as a Markdown label (W1).

    It stays on one line, and every byte that could end the label, escape its
    bracket, open code or start HTML is an entity, which renders the same."""
    text = re.sub(r"[\r\n]+", " ", text)
    return _attachment_label(text).replace("`", "&#96;").encode("utf-8")


def _wiki_link(body, start, end, p, *, resolve, label, related, inline_resources, limits):
    """The Markdown link that replaces a resolved wiki link to a published note
    or attachment (W1), as obsidian2sql.py writes one for Joplin: the alias, or
    the target's title or file name, as the label, and the heading kept. A
    note embed becomes a link; an attachment embed stays an embed."""
    span = body[start:end]
    if not _WITHHELD_WIKI.fullmatch(span):
        _refuse("archived link does not match a complete active token")
    bang = span[0] == 33
    target, aliased, alias = span[2 + bang:-2].partition(b"|")
    base, anchored, fragment = target.partition(b"#")
    document, resource = _DOCUMENT.fullmatch(base), _RESOURCE.fullmatch(base)
    kind, match = ("document", document) if document else ("resource", resource)
    field = "target_document_id" if document else "target_resource_id"
    other = "target_resource_id" if document else "target_document_id"
    if (match is None or p["resolution_status"] != "resolved" or p.get(field) != match[1].decode("ascii")
            or other in p or p["raw_target"] != base.decode("utf-8")
            or p.get("target_uri", p["raw_target"]) != p["raw_target"]):
        _refuse(kind + " target disagrees with link record")
    if (p["relation_type"] != ("embed" if bang else "link")
            or p.get("display_text", "") != (alias if aliased else target).decode("utf-8")):
        _refuse("link record disagrees with active token")
    if (p.get("anchor_type") or "", p.get("anchor_value") or "") != _record_anchor(fragment if anchored else None):
        _refuse("link anchor disagrees with link record")
    mapped = resolve(kind, match[1].decode("ascii"))
    if not re.fullmatch(r"[0-9a-f]{32}", mapped):
        _refuse("resolver did not return a mapped identity")
    destination = b":/" + mapped.encode()
    if kind == "resource":
        if anchored:
            _refuse("resource fragments are unsupported")
        if mapped not in related:
            _refuse("resource link has no document-resource relation")
        inline_resources.add(mapped)
    elif fragment:
        # Obsidian's heading text, encoded as a Markdown link's fragment is.
        if fragment.startswith(b"^"):
            _refuse("unsupported heading fragment")
        destination += b"#" + quote(fragment, safe="-._~!$&'*+,;=:@/?").encode("ascii")
        _fragment(destination.partition(b"#")[2], limits)
    text = alias.decode("utf-8").strip(_GO_SPACE) if aliased else ""
    if not text:
        if label is None:
            _refuse("resolved wiki link has no label source")
        text = label(kind, match[1].decode("ascii")).strip(_GO_SPACE) or "Untitled"
    prefix = b"!" if bang and kind == "resource" else b""
    return prefix + b"[" + _wiki_text(text) + b"](" + destination + b")"


def _withheld(p):
    """Whether a record's link is one the import replaces with its text (R2).

    A `retain` publication keeps the bytes of a link to a note or attachment it
    leaves out, and records it as ``target_excluded``; a link to an internal
    target that does not exist arrives as unresolved. Either names something a
    reader must not see, so the import does what the producer's ``plain_text``
    does to it.
    """
    status = p["resolution_status"]
    raw = p["raw_target"].encode("utf-8")
    withheld = status == "target_excluded" or status in UNRESOLVED_LINK_STATUSES and bool(
        _INTERNAL_ANYWHERE.search(raw) or _INTERNAL_ANYWHERE.search(unquote_to_bytes(raw)))
    if withheld and ("target_document_id" in p or "target_resource_id" in p):
        _refuse("withheld link record names a target")
    return withheld


def _withheld_text(label):
    """The producer's plain_text replacement: the link's text, or the
    placeholder when it has none. A text that is itself an internal URI, as an
    unaliased wiki link's is, would name the target, so it gets the placeholder
    too."""
    if not label.decode("utf-8").strip(_GO_SPACE) or _INTERNAL_ANYWHERE.search(label):
        return _REDACTED
    return label


def _record_anchor(fragment):
    """The anchor the producer records for a fragment (splitAnchor)."""
    if not fragment:
        return "", ""
    value = fragment.decode("utf-8")
    return ("block", value[1:]) if value.startswith("^") else ("heading", value)


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
    if match := _DOCUMENT.fullmatch(token.base):
        _fragment(token.fragment, limits)
        if token.bang:
            _refuse("document embeds are unsupported")
        return "document", match[1].decode("ascii")
    if token.base == b"" and token.fragment is not None:
        _fragment(token.fragment, limits)
        if token.bang:
            _refuse("self-anchor embeds are unsupported")
        return "self", None
    if match := _RESOURCE.fullmatch(token.base):
        if token.fragment is not None:
            _refuse("resource fragments are unsupported")
        return "resource", match[1].decode("ascii")
    # Every other destination is copied as found, whatever its scheme (C7d):
    # file:, mailto: and tel: name things outside the library, and the
    # importer resolves none of them. Heading-fragment rules are for internal
    # targets only. A destination naming an internal target in any other form,
    # percent-encoded included, is not external.
    if _INTERNAL_ANYWHERE.search(token.destination) or _INTERNAL_ANYWHERE.search(unquote_to_bytes(token.destination)):
        _refuse("unsupported link destination")
    return "external", None


def validate_links(body: bytes, records, *, resolve, limits=DEFAULT_CONVERSION_LIMITS, resource_ids=(), label=None):
    """Reconcile bounded archived spans with active tokens before projection.

    *label* names a note or attachment, by kind and source ID, for a resolved
    wiki link that has no alias (W1).
    """
    if len(body) > limits.max_body_bytes:
        raise NotriosError("limit", "body exceeds conversion limit")
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("body is not UTF-8")
    retained = []
    for record in records:
        if len(retained) >= limits.max_links_per_note:
            raise NotriosError("limit", "archived link count exceeds limit")
        if record.kind != "link":
            _refuse("link validation requires link records")
        retained.append(record.payload)
    retained.sort(key=lambda p: (p["source_start_byte"], p["source_end_byte"], p["id"]))
    # A withheld or resolved wiki link holds its internal target, which the
    # scanner refuses outside a token, so it is blanked for the scan and
    # replaced below. The span checks in the loop still run on it.
    scanned, visible = body, None
    for p in retained:
        start, end = p["source_start_byte"], p["source_end_byte"]
        if (p["source_format"] == "obsidian-wikilink" and 0 <= start < end <= len(body)
                and (_withheld(p) or _INTERNAL_ANYWHERE.search(body, start, end))):
            if visible is None:
                visible, scanned = _protected_body(body), bytearray(body)
            if visible[start:end] != body[start:end]:
                _refuse("withheld link inside protected code")
            # Not spaces: a blanked span at the start of a line would read as
            # an indented code block, hiding what follows from the scan (W1).
            # Like the "[" or "!" it replaces, "x" opens no code or container.
            scanned[start:end] = b"x" * (end - start)
    tokens = []
    for token in scan_markdown(bytes(scanned)):
        if len(tokens) >= limits.max_links_per_note:
            raise NotriosError("limit", "active link count exceeds limit")
        tokens.append(token)
    by_start = {token.start: token for token in tokens}
    token_starts = sorted(by_start)
    bare_by_end = {token.end: token for token in tokens if token.bare}
    accounted, replacements, previous, owner = set(), [], 0, None
    related, inline_resources, withheld = set(), set(), set()
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
        if p["source_format"] == "obsidian-wikilink":
            if _withheld(p):
                span, text = body[start:end], p.get("display_text", "").encode("utf-8")
                if (not _WITHHELD_WIKI.fullmatch(span) or p["raw_target"].encode("utf-8") not in span
                        or text not in span):
                    _refuse("archived link does not match a complete active token")
                replacements.append((start, end, _withheld_text(text)))
                withheld.add(start)
            elif _INTERNAL_ANYWHERE.search(body, start, end):
                replacements.append((start, end, _wiki_link(
                    body, start, end, p, resolve=resolve, label=label, related=related,
                    inline_resources=inline_resources, limits=limits)))
            else:
                _wiki_record(body, start, end, p, token_starts)
            accounted.add(start)
            continue
        token = by_start.get(start)
        protected = False
        if token is None or token.end != end:
            if (bare := bare_by_end.get(end - 1)) is not None and bare.start > start:
                token = _bare_record_token(body, start, end, bare)
                accounted.add(bare.start)
            else:
                token, visible = _protected_record_token(body, start, end, visible)
                protected = True
                # An active token inside the span ending with it is this
                # link read from a later bracket; the record accounts for it.
                inner = bisect.bisect_right(token_starts, start)
                if inner < len(token_starts) and token_starts[inner] < end and by_start[token_starts[inner]].end == end:
                    accounted.add(token_starts[inner])
        source_id = p["source_document_id"]
        if owner is not None and owner != source_id:
            _refuse("link records have different source documents")
        owner = source_id
        if (p["source_format"] != "markdown" or p["relation_type"] != ("embed" if token.bang else "link")
                or p["raw_target"] != token.base.decode("utf-8")
                or "display_text" in p and p["display_text"] != token.label.decode("utf-8")):
            _refuse("link record disagrees with active token")
        if (p.get("anchor_type") or "", p.get("anchor_value") or "") != _record_anchor(token.fragment):
            _refuse("link anchor disagrees with link record")
        if _withheld(p):
            # The whole link becomes its text, so its destination's grammar
            # does not matter; code is never changed.
            if protected:
                _refuse("withheld link inside protected code")
            replacements.append((start, end, _withheld_text(token.label)))
            withheld.add(start)
            accounted.add(start)
            continue
        kind, target_id = _target(token, limits)
        if protected and kind not in ("external", "self"):
            _refuse("internal link record inside protected code")
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
        elif p["resolution_status"] == "resolved":
            # The producer matched a non-internal destination to a note or an
            # attachment by name. The destination is copied as written, like
            # any other non-internal one; the match is not applied (C7d).
            if ("target_document_id" in p) == ("target_resource_id" in p):
                _refuse("external target disagrees with link record")
        elif (p["resolution_status"] not in ("external", *UNRESOLVED_LINK_STATUSES)
              or "target_document_id" in p or "target_resource_id" in p
              or "target_uri" in p and p["target_uri"] != token.base.decode("utf-8")):
            # An unresolved link naming no internal target is copied as
            # written, like an external one (R2).
            _refuse("external target disagrees with link record")
        accounted.add(start)
    for token in tokens:
        if token.start in withheld:
            continue
        if token.html:
            # The producer records an HTML image's resource as an attachment
            # relation and no link span, so the relation is what accounts for it.
            if (match := _RESOURCE.fullmatch(token.base)) is None:
                _refuse("HTML image source is not a published resource")
            mapped = resolve("resource", match[1].decode("ascii"))
            if not re.fullmatch(r"[0-9a-f]{32}", mapped):
                _refuse("resolver did not return a mapped identity")
            if mapped not in related:
                _refuse("HTML image resource has no document-resource relation")
            inline_resources.add(mapped)
            replacements.append((token.destination_start, token.destination_end, b":/" + mapped.encode()))
            continue
        if token.bare:
            if token.start in accounted:
                continue
            # Mapped back to the Joplin form the producer replaced; a target
            # missing from the publication refuses in resolve.
            kind, target_id = _target(token, limits)
            if kind not in ("document", "resource"):
                _refuse("unsupported or unaccounted active link syntax")
            mapped = resolve(kind, target_id)
            if not re.fullmatch(r"[0-9a-f]{32}", mapped):
                _refuse("resolver did not return a mapped identity")
            if kind == "resource":
                if mapped not in related:
                    _refuse("resource link has no document-resource relation")
                inline_resources.add(mapped)
            destination = b":/" + mapped.encode() + (b"#" + token.fragment if token.fragment is not None else b"")
            replacements.append((token.destination_start, token.destination_end, destination))
            continue
        kind, _ = _target(token, limits)
        if kind != "external" and token.start not in accounted:
            _refuse("active internal link has no retained record")
    replacements.sort()
    return LinkPlan(tuple(tokens), tuple(replacements), limits.max_projected_body_bytes,
                    tuple(sorted(inline_resources)), limits.max_links_per_note, limits.max_resource_relations_per_note,
                    len(withheld))


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
        if token.html:
            # The tag stays HTML, as the native export keeps one: only the
            # source becomes the attachment's path relative to the note (H1).
            name = None
            if (match is not None and match[2] is None and attachments is not None
                    and lookup_item_type(match[1].decode("ascii")) == 4):
                name = attachments.vault_name(match[1].decode("ascii"), required=True)
            if name is None:
                _refuse("HTML image has no mapped resource")
            destination = quote(posixpath.relpath("attachments/" + name, start=str(note_path.parent)),
                                safe="/-._~").encode("ascii")
            replacements.append((token.destination_start, token.destination_end, destination))
            continue
        if match is None:
            kind, _ = _target(token, limits)
            if kind not in ("external", "self"):
                _refuse("unmapped internal link in projected note")
            continue
        _fragment(token.fragment, limits)
        item_id = match[1].decode("ascii")
        item_type = lookup_item_type(item_id)
        if token.bare:
            # Only the destination is known, so only it changes. A note left
            # out of the vault keeps its `:/id`, as a native export keeps one.
            if item_type == 4:
                if token.fragment is not None or attachments is None:
                    _refuse("invalid mapped resource target")
                name = attachments.vault_name(item_id, required=True)
                if name is None:
                    _refuse("missing mapped resource")
                destination = quote(posixpath.relpath("attachments/" + name, start=str(note_path.parent)),
                                    safe="/-._~").encode("ascii")
            elif item_type == 1:
                path = lookup_note_path(item_id)
                if path is None:
                    continue
                destination = quote(posixpath.relpath(str(path), start=str(note_path.parent)),
                                    safe="/-._~").encode("ascii")
                if token.fragment is not None:
                    destination += b"#" + token.fragment
            else:
                _refuse("mapped link has no supported note target")
            replacements.append((token.destination_start, token.destination_end, destination))
            continue
        if item_type == 4:
            if token.fragment is not None or attachments is None:
                _refuse("invalid mapped resource target")
            name = attachments.vault_name(item_id, required=True)
            if name is None:
                _refuse("missing mapped resource")
            relative = quote(posixpath.relpath("attachments/" + name, start=str(note_path.parent)),
                             safe="/-._~").encode("ascii")
            if token.bang and attachments.is_image(item_id):
                # A wiki embed has nowhere to keep a title, so only a titled
                # image becomes a Markdown image; untitled output is unchanged.
                replacement = (b"![" + token.label + b"](" + relative + token.title_suffix + b")"
                               if token.title_suffix else f"![[{name}]]".encode("utf-8"))
                replacements.append((token.start, token.end, replacement))
            else:
                label = token.label or _attachment_label(name).encode("utf-8")
                replacements.append((token.start, token.end,
                    b"[" + label + b"](" + relative + token.title_suffix + b")"))
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

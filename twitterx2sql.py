#!/usr/bin/env python3
"""Import a Twitter/X archive into a SQLite notes database.

Parses the archive users download from X (Settings -> "Download an archive
of your data") without using the Twitter/X API. Tweets become notes in a
notebook chosen with --notebook (default "Twitter"), so an archive can be
merged into a database alongside Joplin notebooks and exported with
sql2joplin.py or sql2obsidian.py.

t.co short links are expanded from the URL entities stored in the archive;
any t.co link the archive cannot resolve is expanded over the network with
a HEAD request following redirects (disable with --no-expand-tco). Tweet
media (photos, GIFs, videos) become attachments embedded in the notes.
"""

#
# MIT License
#
# https://opensource.org/licenses/MIT
#
# Copyright 2020 Rene Sugar
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import common
import constants
import notesdb

__program_name__ = "twitterx2sql"
__author__ = "Rene Sugar"
__version__ = "2.33"
__license__ = "MIT License (https://opensource.org/licenses/MIT)"
__website__ = "https://github.com/renesugar"

DEFAULT_NOTEBOOK = "Twitter"
TCO_CACHE_FILENAME = "tco_cache.json"

# Tweet .js data files, newest naming first (older archives used tweet.js).
_TWEET_FILE_PATTERNS = ("tweets*.js", "tweet*.js")
_MEDIA_DIR_NAMES = ("tweets_media", "tweet_media")

_TCO_LINK_RE = re.compile(r"https?://t\.co/[A-Za-z0-9]+")

_MAX_TITLE_LENGTH = 60


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=__program_name__, description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        type=common.existing_dir,
        required=True,
        help=(
            "Path to the extracted Twitter/X archive (the directory "
            "containing data/, or the data/ directory itself)"
        ),
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        type=common.existing_dir,
        required=True,
        help="Path to the output SQLite directory",
    )
    parser.add_argument(
        "--notebook",
        dest="notebook",
        default=DEFAULT_NOTEBOOK,
        help=(
            "Notebook (folder) the tweets are imported into "
            f"(default: {DEFAULT_NOTEBOOK}); created if missing, reused if "
            "it already exists"
        ),
    )
    parser.add_argument(
        "--no-expand-tco",
        dest="expand_tco",
        action="store_false",
        help=(
            "Do not resolve leftover t.co links over the network; links "
            "covered by the archive's own URL entities are still expanded"
        ),
    )
    parser.add_argument(
        "--timezone",
        help=(
            "IANA time zone used in the visible tweet timestamp, for example "
            "America/Vancouver; defaults to the system local time zone"
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N tweets; 0 disables it (default: 1000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every imported tweet title instead of periodic progress",
    )
    return parser


# -- archive reading ----------------------------------------------------------


def read_json_from_js_file(file_path: Path) -> list:
    """Read a Twitter-produced .js data file into a list.

    Archive data files wrap a JSON array in a JavaScript assignment:
    ``window.YTD.tweets.part0 = [ ... ]``. Everything up to the first
    ``=`` is stripped.
    """
    text = file_path.read_text(encoding="utf-8")
    if text.startswith("window."):
        _, _, text = text.partition("=")
    text = text.strip().rstrip(";")
    if not text:
        return []
    return json.loads(text)


def find_data_dir(input_path: Path) -> Path:
    """Return the archive's data directory.

    The user may pass the extracted archive root (which contains ``data/``)
    or the ``data/`` directory itself.
    """
    if any(next(input_path.glob(pattern), None) for pattern in _TWEET_FILE_PATTERNS):
        return input_path
    data_dir = input_path / "data"
    if data_dir.is_dir():
        return data_dir
    common.error(
        f"no Twitter/X archive found in '{input_path}' "
        "(expected data/tweets*.js)"
    )


def find_tweet_files(data_dir: Path) -> list[Path]:
    """Return the tweet data files (tweets.js, tweets-part1.js, ...)."""
    for pattern in _TWEET_FILE_PATTERNS:
        files = sorted(p for p in data_dir.glob(pattern) if p.is_file())
        if files:
            return files
    common.error(f"no tweet data files matching {_TWEET_FILE_PATTERNS} in '{data_dir}'")


def find_media_dir(data_dir: Path) -> Path | None:
    for name in _MEDIA_DIR_NAMES:
        media_dir = data_dir / name
        if media_dir.is_dir():
            return media_dir
    return None


def read_username(data_dir: Path) -> str | None:
    """Return the account username from account.js, if present."""
    account_file = data_dir / "account.js"
    if not account_file.is_file():
        return None
    try:
        items = read_json_from_js_file(account_file)
        return items[0]["account"]["username"]
    except (json.JSONDecodeError, LookupError, TypeError):
        return None


def read_tweets(data_dir: Path) -> list[dict]:
    """Read all tweets from the archive's tweet data files."""
    tweets = []
    for file_path in find_tweet_files(data_dir):
        print(f"parsing '{file_path.name}'...")
        for item in read_json_from_js_file(file_path):
            # Each item is {"tweet": {...}} in current archives; older
            # archives stored the tweet object directly.
            tweet = item.get("tweet", item) if isinstance(item, dict) else None
            if tweet:
                tweets.append(tweet)
    return tweets


# -- t.co expansion -----------------------------------------------------------


class TcoExpander:
    """Expand t.co short links by following HTTP redirects.

    Results are cached in a JSON file so re-running the import does not
    re-fetch links. Network failures leave the original link in place.
    """

    def __init__(self, cache_path: Path, enabled: bool, timeout: float = 10.0) -> None:
        self._cache_path = cache_path
        self.enabled = enabled
        self._timeout = timeout
        self._failed: set[str] = set()
        self._cache: dict[str, str] = {}
        if enabled and cache_path.is_file():
            try:
                loaded_cache = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded_cache, dict):
                    # Older versions could leave a relative redirect target in
                    # the cache.  Such a value has lost the URL it was relative
                    # to, so discard it and resolve the t.co link again.
                    self._cache = {
                        key: value
                        for key, value in loaded_cache.items()
                        if isinstance(key, str)
                        and isinstance(value, str)
                        and self._is_absolute_http_url(value)
                    }
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    @staticmethod
    def _is_absolute_http_url(url: str) -> bool:
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError:
            return False
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    @classmethod
    def _resolve_location(cls, current_url: str, location: str) -> str | None:
        """Resolve an HTTP Location header against *current_url*.

        RFC 3986 permits redirect targets to be relative references, including
        absolute paths (``/user/status/id``) and network-path references
        (``//x.com/user/status/id``).  ``urllib.request.Request`` requires an
        absolute URL, so every hop is normalised before the next request.
        """
        try:
            candidate = urllib.parse.urljoin(current_url, location.strip())
        except ValueError:
            return None
        return candidate if cls._is_absolute_http_url(candidate) else None

    def _head_location(self, url: str) -> str | None:
        """Return the redirect Location for *url*, or None."""

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None  # do not follow; we read the Location ourselves

        opener = urllib.request.build_opener(_NoRedirect)
        request = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": f"movenotes/{__version__}"}
        )
        try:
            with opener.open(request, timeout=self._timeout) as response:
                # No redirect: the link resolves to itself.
                return response.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return e.headers.get("Location")
            return None
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def expand(self, url: str) -> str:
        """Return the expanded target of *url*, or *url* on failure."""
        if not self.enabled or url in self._failed:
            return url
        if url in self._cache:
            return self._cache[url]

        current = url
        for _hop in range(5):
            location = self._head_location(current)
            if not location:
                break
            next_url = self._resolve_location(current, location)
            if not next_url or next_url == current:
                break
            current = next_url

        if current == url:
            self._failed.add(url)  # transient failure: not cached to disk
            return url
        self._cache[url] = current
        return current

    def save_cache(self) -> None:
        if self.enabled and self._cache:
            self._cache_path.write_text(
                json.dumps(self._cache, indent=1, sort_keys=True), encoding="utf-8"
            )


# -- tweet conversion ---------------------------------------------------------


def parse_created_at(created_at: str) -> datetime:
    """Parse a tweet timestamp like 'Wed Oct 10 20:19:24 +0000 2018'."""
    return datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y").astimezone(
        timezone.utc
    )


def joplin_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def display_tweet_timestamp(created: datetime, display_timezone: tzinfo | None) -> str:
    """Format a tweet timestamp in the requested or system-local time zone."""
    local = (
        created.astimezone(display_timezone)
        if display_timezone is not None
        else created.astimezone()
    )
    return local.strftime("%I:%M %p · %b %d, %Y").lstrip("0")


def _tweet_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _tweet_reply_line(tweet: dict) -> str:
    reply_id = (
        tweet.get("in_reply_to_status_id_str")
        or tweet.get("in_reply_to_status_id")
    )
    screen_name = str(tweet.get("in_reply_to_screen_name") or "").strip()
    if not reply_id or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", screen_name):
        return ""
    return (
        f"In reply to: [@{screen_name}]"
        f"(https://x.com/i/web/status/{reply_id})"
    )


def _tweet_footer(
    tweet: dict, tweet_id: str, created: datetime,
    display_timezone: tzinfo | None,
) -> str:
    timestamp = display_tweet_timestamp(created, display_timezone)
    retweets = _tweet_count(tweet.get("retweet_count"))
    favorites = _tweet_count(tweet.get("favorite_count"))
    return (
        f"[{timestamp}](https://x.com/i/web/status/{tweet_id}) "
        f"🔁 {retweets:,} 💙 {favorites:,}"
    )


def tweet_title(text: str, created: datetime) -> str:
    """Derive a note title from the tweet text.

    The first line is truncated at a word boundary; media-only tweets fall
    back to a date-based title.
    """
    first_line = text.strip().split("\n", 1)[0].strip()
    if not first_line:
        return f"Tweet {created.strftime('%Y-%m-%d %H:%M')}"
    if len(first_line) <= _MAX_TITLE_LENGTH:
        return first_line
    truncated = first_line[:_MAX_TITLE_LENGTH].rsplit(" ", 1)[0].rstrip()
    return f"{truncated}…"


def expand_entity_urls(text: str, tweet: dict) -> str:
    """Replace t.co links with the expanded URLs recorded in the archive."""
    for url in tweet.get("entities", {}).get("urls", []):
        short, expanded = url.get("url"), url.get("expanded_url")
        if short and expanded:
            text = text.replace(short, expanded)
    return text


def tweet_media_items(tweet: dict) -> list[dict]:
    """Return the tweet's media entities (photos, GIFs, videos)."""
    extended = tweet.get("extended_entities", {}).get("media")
    return extended or tweet.get("entities", {}).get("media") or []


class ResourceImporter:
    """Creates Joplin resource rows for tweet media files.

    Resource ids are derived from the file content (first 32 hex digits of
    its SHA-256), so re-importing the same archive — or the same photo from
    two archives — produces identical embed links. Duplicate notes then
    hash identically and removedups.py can remove them.
    """

    def __init__(
        self,
        media_dir: Path | None,
        output_resources_path: Path,
        existing_ids: set[str],
    ) -> None:
        self._media_dir = media_dir
        self._output_resources_path = output_resources_path
        # Resource ids already in the database (or added this run), so a
        # file referenced twice is imported once.
        self._known_ids = set(existing_ids)
        self.rows: list[dict] = []
        self._fallback_media: dict[str, Path] = {}
        if self._media_dir is not None and self._media_dir.is_dir():
            for path in sorted(self._media_dir.iterdir()):
                if not path.is_file():
                    continue
                tweet_id, separator, _rest = path.name.partition("-")
                if separator:
                    self._fallback_media.setdefault(tweet_id, path)

    def _archive_file(self, tweet_id: str, media_url: str) -> Path | None:
        if self._media_dir is None:
            return None
        filename = f"{tweet_id}-{media_url.rsplit('/', 1)[-1]}"
        path = self._media_dir / filename
        if path.is_file():
            return path
        # Videos: the media_url is a thumbnail; the file on disk may have a
        # different extension. Fall back to any file for the tweet id.
        return self._fallback_media.get(tweet_id)

    def import_media(self, tweet_id: str, media: dict, created: datetime) -> str | None:
        """Import one media entity; return its resource id (or None)."""
        media_url = media.get("media_url_https") or media.get("media_url") or ""
        source = self._archive_file(tweet_id, media_url)
        if source is None:
            return None

        content = source.read_bytes()
        resource_id = hashlib.sha256(content).hexdigest()[:32]
        extension = source.suffix.lstrip(".").lower()

        self._output_resources_path.mkdir(parents=True, exist_ok=True)
        common.copy_file_if_changed(
            source,
            self._output_resources_path,
            f"{resource_id}.{extension}" if extension else resource_id,
        )

        if resource_id in self._known_ids:
            return resource_id  # row already exists (this run or a prior one)
        self._known_ids.add(resource_id)

        mime_type, _encoding = mimetypes.guess_type(source.name)
        timestamp = joplin_timestamp(created)
        title = source.name.removeprefix(f"{tweet_id}-")

        self.rows.append(
            {
                "note_type": "resource",
                "note_uuid": resource_id,
                "note_original_format": "twitter",
                "note_internal_date": created,
                "note_hash": hashlib.sha512(content).hexdigest(),
                "note_title": title,
                # Joplin RAW bodies end with a newline before the blank
                # separator line the exporter adds.
                "note_data": f"{title}\n",
                "note_data_format": "text/markdown",
                "joplin_id": resource_id,
                "joplin_type_": int(constants.JoplinType.RESOURCE),
                "joplin_created_time": timestamp,
                "joplin_updated_time": timestamp,
                "joplin_user_created_time": timestamp,
                "joplin_user_updated_time": timestamp,
                "joplin_mime": mime_type or "application/octet-stream",
                "joplin_file_extension": extension,
                "joplin_size": source.stat().st_size,
                "joplin_encryption_applied": 0,
                "joplin_encryption_blob_encrypted": 0,
                "joplin_is_shared": 0,
            }
        )
        return resource_id

    def take_rows(self) -> list[dict]:
        """Return pending resource rows and clear the bounded staging buffer."""
        rows, self.rows = self.rows, []
        return rows


def find_or_create_notebook(
    sqlconn: sqlite3.Connection, notebook: str
) -> tuple[str, dict | None]:
    """Return the notebook's folder id and, if new, its row to insert."""
    row = sqlconn.execute(
        "SELECT joplin_id FROM notes WHERE joplin_type_ = ? AND note_title = ?",
        (int(constants.JoplinType.FOLDER), notebook),
    ).fetchone()
    if row is not None:
        return (row["joplin_id"], None)

    folder_id = common.create_uuid_string()
    now = datetime.now(timezone.utc)
    timestamp = joplin_timestamp(now)
    columns = {
        "note_type": "folder",
        "note_uuid": folder_id,
        "note_original_format": "twitter",
        "note_internal_date": now,
        "note_hash": hashlib.sha512(notebook.encode("utf-8")).hexdigest(),
        "note_title": notebook,
        "note_data": f"{notebook}\n",
        "note_data_format": "text/markdown",
        "joplin_id": folder_id,
        "joplin_parent_id": "",
        "joplin_type_": int(constants.JoplinType.FOLDER),
        "joplin_created_time": timestamp,
        "joplin_updated_time": timestamp,
        "joplin_user_created_time": timestamp,
        "joplin_user_updated_time": timestamp,
        "joplin_encryption_applied": 0,
        "joplin_is_shared": 0,
    }
    return (folder_id, columns)


def convert_tweet(
    tweet: dict,
    folder_id: str,
    folder_title: str,
    username: str | None,
    resources: ResourceImporter,
    expander: TcoExpander,
    display_timezone: tzinfo | None = None,
) -> dict:
    """Convert one archived tweet into a note row."""
    tweet_id = tweet.get("id_str") or str(tweet.get("id", ""))
    created = parse_created_at(tweet["created_at"])
    text = html.unescape(tweet.get("full_text") or tweet.get("text") or "")

    # Expand t.co links: first from the archive's URL entities, then over
    # the network for anything left.
    text = expand_entity_urls(text, tweet)

    # Media: import files as resources, remove the t.co media link from the
    # text, and append embeds.
    embeds = []
    for media in tweet_media_items(tweet):
        short_url = media.get("url")
        if short_url:
            text = text.replace(short_url, "")
        resource_id = resources.import_media(tweet_id, media, created)
        if resource_id is not None:
            filename = (media.get("media_url_https") or "").rsplit("/", 1)[-1]
            embeds.append(f"![{filename}](:/{resource_id})")

    if expander.enabled:
        text = _TCO_LINK_RE.sub(lambda m: expander.expand(m.group(0)), text)

    text = text.strip()
    title = tweet_title(text, created)
    body_parts: list[str] = []
    reply_line = _tweet_reply_line(tweet)
    if reply_line:
        body_parts.append(reply_line)
    if text:
        body_parts.append(text)
    if embeds:
        body_parts.append("\n".join(embeds))
    if tweet_id:
        body_parts.append(_tweet_footer(tweet, tweet_id, created, display_timezone))

    body = "\n\n".join(body_parts)
    handle = username or "i"
    source_url = f"https://x.com/{handle}/status/{tweet_id}" if tweet_id else ""
    timestamp = joplin_timestamp(created)
    note_data = f"{title}\n\n{body}\n" if body else f"{title}\n"
    twitter_metadata = {
        "status_id": tweet_id,
        "created_at": tweet.get("created_at") or "",
        "in_reply_to_status_id": str(
            tweet.get("in_reply_to_status_id_str")
            or tweet.get("in_reply_to_status_id")
            or ""
        ),
        "in_reply_to_screen_name": tweet.get("in_reply_to_screen_name") or "",
        "retweet_count": _tweet_count(tweet.get("retweet_count")),
        "favorite_count": _tweet_count(tweet.get("favorite_count")),
    }

    note_id = common.create_uuid_string()
    return {
        "note_type": "note",
        "note_uuid": note_id,
        "joplin_id": note_id,
        "note_parent_uuid": folder_id,
        "note_folder": folder_title,
        "note_original_format": "twitter",
        "note_internal_date": created,
        "note_hash": hashlib.sha512(note_data.encode("utf-8")).hexdigest(),
        "note_title": title,
        "note_data": note_data,
        "note_data_format": "text/markdown",
        "note_url": source_url,
        "joplin_type_": int(constants.JoplinType.NOTE),
        "joplin_parent_id": folder_id,
        "joplin_created_time": timestamp,
        "joplin_updated_time": timestamp,
        "joplin_user_created_time": timestamp,
        "joplin_user_updated_time": timestamp,
        "joplin_is_conflict": 0,
        "joplin_latitude": 0.0,
        "joplin_longitude": 0.0,
        "joplin_altitude": 0.0,
        "joplin_author": "",
        "joplin_source_url": source_url,
        "joplin_is_todo": 0,
        "joplin_todo_due": 0,
        "joplin_todo_completed": 0,
        "joplin_source": "twitterx2sql",
        "joplin_source_application": "com.github.renesugar.movenotes",
        "joplin_application_data": json.dumps(
            {"movenotes": {"twitter": twitter_metadata}},
            ensure_ascii=False, separators=(",", ":"),
        ),
        "joplin_order": 0,
        "joplin_encryption_applied": 0,
        "joplin_markup_language": 1,
        "joplin_is_shared": 0,
    }


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)
    if args.progress_every < 0:
        common.error("--progress-every cannot be negative")

    output_path: Path = args.output_path
    display_timezone: tzinfo | None = None
    if args.timezone:
        try:
            display_timezone = ZoneInfo(args.timezone)
        except ZoneInfoNotFoundError:
            common.error(f"unknown IANA time zone: {args.timezone}")
    data_dir = find_data_dir(args.input_path)
    media_dir = find_media_dir(data_dir)
    username = read_username(data_dir)

    database_path = output_path / notesdb.DATABASE_FILENAME
    if database_path.is_file():
        sqlconn = notesdb.open_database(database_path, __program_name__)
    else:
        sqlconn = notesdb.connect(database_path)
        notesdb.create_database(sqlconn)

    tweets = read_tweets(data_dir)
    print(f"found {len(tweets)} tweet(s)" + (f" for @{username}" if username else ""))

    # Notes get fresh ids each run; re-importing the same archive creates
    # duplicates that removedups.py removes (identical bodies hash
    # identically).
    folder_id, folder_row = find_or_create_notebook(sqlconn, args.notebook)
    if folder_row is not None:
        notesdb.add_joplin_notes(sqlconn, [folder_row])

    existing_resource_ids = {
        row["joplin_id"]
        for row in sqlconn.execute(
            "SELECT joplin_id FROM notes WHERE joplin_type_ = ?",
            (int(constants.JoplinType.RESOURCE),),
        )
    }
    resources = ResourceImporter(
        media_dir, output_path / "resources", existing_resource_ids
    )
    expander = TcoExpander(output_path / TCO_CACHE_FILENAME, args.expand_tco)

    batch: list[dict] = []
    imported_count = 0
    for tweet in sorted(tweets, key=lambda t: t.get("id_str") or str(t.get("id", ""))):
        columns = convert_tweet(
            tweet, folder_id, args.notebook, username, resources, expander,
            display_timezone,
        )
        if args.verbose:
            print(f"processing '{columns['note_title']}'")
        batch.append(columns)
        imported_count += 1
        if len(batch) >= 500:
            notesdb.add_joplin_notes(sqlconn, batch)
            batch.clear()
        if len(resources.rows) >= 500:
            notesdb.add_joplin_notes(sqlconn, resources.take_rows())
        if (
            not args.verbose
            and args.progress_every
            and imported_count % args.progress_every == 0
        ):
            print(f"processed {imported_count:,} tweet(s)")

    if batch:
        notesdb.add_joplin_notes(sqlconn, batch)
    if resources.rows:
        notesdb.add_joplin_notes(sqlconn, resources.take_rows())
    sqlconn.commit()
    sqlconn.close()

    expander.save_cache()
    print(f"imported {len(tweets)} tweet(s) into notebook '{args.notebook}'")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

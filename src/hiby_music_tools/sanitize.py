#!/usr/bin/env python3
"""Sanitize a local music library for HiBy R1 use.

Output layout:
    DEST/<Album Artist or Artist>/<Year>-<Album>/<Title>.<ext>
    DEST/<Album Artist or Artist>/<Album>/<Title>.<ext>   (when year is unknown)

Tracks missing both Album Artist and Artist are copied unchanged to:
    DEST/missing-author/<original relative path>

The source library is never modified. A JPEG/PNG cover in the same source
folder as a track takes precedence over existing embedded artwork. External
covers are embedded as baseline JPEG, resized to a configurable maximum
(600 px by default). Existing embedded covers are still resized when no
unambiguous external cover is present.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from hiby_music_tools.paths import metadata_dir
from hiby_music_tools.core.metadata import TrackMetadata
from hiby_music_tools.core.naming import (
    INVALID_COMPONENT_CHARS, build_destination, safe_component, unique_destination,
)
from typing import Iterable, Optional

try:
    from PIL import Image, UnidentifiedImageError
except ImportError as exc:
    raise SystemExit(
        "Missing Pillow. On CachyOS/Arch install it with: sudo pacman -S python-pillow"
    ) from exc

try:
    from mutagen import File as MutagenFile
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3
    from mutagen.mp4 import MP4, MP4Cover
except ImportError as exc:
    raise SystemExit(
        "Missing Mutagen. On CachyOS/Arch install it with: sudo pacman -S python-mutagen"
    ) from exc


AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus",
    ".wav", ".wave", ".aif", ".aiff", ".ape", ".wma", ".wv", ".dsf", ".dff",
}

YEAR_RE = re.compile(r"(?<!\d)(18|19|20|21)\d{2}(?!\d)")
DOMAIN_LIKE_RE = re.compile(
    r"(?:https?://|www\.|(?:^|\s)[A-Za-z0-9_-]+\.(?:com|net|org|io|co|me|tv|cc|to)(?:\s|$))",
    re.IGNORECASE,
)
PLACEHOLDER_ARTISTS = {
    "unknown", "unknown artist", "no artist", "n/a", "none", "artist", "www",
}
TRACK_PREFIX_RE = re.compile(r"^(?:track\s*)?\d{1,3}[ ._-]+", re.IGNORECASE)
MB_BASE = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = "HiByMusicSanitizer/0.6 (personal local music library tagger)"
# MusicBrainz asks clients to average no more than one request per second.  A
# little extra headroom helps avoid bursts and shared-IP throttling.
MB_MIN_INTERVAL = 1.25
MB_MAX_ATTEMPTS = 6
MB_BACKOFF_START = 2.0
MB_BACKOFF_MAX = 30.0
MB_RETRY_HTTP_CODES = {429, 500, 502, 503, 504}
_MB_LAST_REQUEST = 0.0
_MB_LOOKUP_CACHE_DB: Optional[Path] = None

CACHE_ARTIST_ALIASES_KEY = "__artist_aliases__"
CACHE_ARTIST_REVIEWS_KEY = "__artist_reviews__"
CACHE_ALBUM_YEARS_KEY = "__album_year_overrides__"
VARIOUS_ARTISTS_NAMES = {
    "various artists", "various", "va", "v.a.", "soundtrack",
}


@dataclass
class MetadataCorrection:
    artist: str
    album_artist: str
    title: str
    album: str
    year: Optional[str]
    musicbrainz_recording_id: Optional[str] = None
    musicbrainz_release_id: Optional[str] = None


@dataclass
class MBRecordingCandidate:
    recording_id: str
    score: int
    title: str
    artist: str
    first_release_date: Optional[str]
    length_ms: Optional[int]
    adjusted_score: float = 0.0


@dataclass
class MBReleaseCandidate:
    release_id: str
    title: str
    artist: str
    date: Optional[str]
    status: Optional[str]
    primary_type: Optional[str]


@dataclass
class ArtistSuggestion:
    current_artist: str
    suggested_artist: str
    recording: MBRecordingCandidate
    release: Optional[MBReleaseCandidate] = None


@dataclass
class ArtworkResult:
    resized: int = 0
    found: int = 0
    error: Optional[str] = None
    external_embedded: int = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a HiBy-friendly sanitized copy of a local music library."
    )
    p.add_argument("source", type=Path, help="Messy/source music library")
    p.add_argument("destination", type=Path, help="Sanitized output library")
    p.add_argument(
        "--art-max",
        type=int,
        default=600,
        metavar="PX",
        help="Limit embedded/folder covers to PX pixels (default: 600)",
    )
    p.add_argument(
        "--jpeg-quality",
        type=int,
        default=88,
        metavar="N",
        help="JPEG quality for resized artwork, 1-95 (default: 88)",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Delete the destination tree before rebuilding it",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned destinations without copying or modifying files",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print each file as it is processed",
    )
    p.add_argument(
        "--online-review",
        action="store_true",
        help=(
            "Run a one-track-per-artist MusicBrainz sanity check, then interactively "
            "repair tracks with missing/suspicious artist, title, album, or year metadata"
        ),
    )
    p.add_argument(
        "--online-review-all",
        action="store_true",
        help="Interactively offer MusicBrainz lookup for every track (slow for large libraries)",
    )
    p.add_argument(
        "--no-artist-review",
        action="store_true",
        help=(
            "With --online-review, skip the one-track-per-artist MusicBrainz sanity check. "
            "Useful after the artist names have already been cleaned up."
        ),
    )
    p.add_argument(
        "--metadata-cache",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "JSON cache for approved metadata corrections. Default: "
            "~/.cache/hiby-music-tools/corrections.json"
        ),
    )
    p.add_argument(
        "--lookup-cache",
        type=Path,
        default=None,
        metavar="DB",
        help=(
            "SQLite cache for MusicBrainz lookup responses. Default: "
            "~/.cache/hiby-music-tools/musicbrainz.sqlite3"
        ),
    )
    return p.parse_args()


def first_tag(tags, keys: Iterable[str]) -> Optional[str]:
    if not tags:
        return None
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:
            continue
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def extract_metadata(path: Path) -> TrackMetadata:
    """Read common tags without altering the file."""
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return TrackMetadata(None, None, None, None, None, None, "Mutagen could not identify the file")

        tags = audio.tags or {}
        track_artist = first_tag(tags, ("artist",))
        album_artist = first_tag(tags, ("albumartist", "album artist"))
        # Album Artist is preferred so compilation / featured-artist albums stay together.
        artist = album_artist or track_artist
        title = first_tag(tags, ("title",))
        album = first_tag(tags, ("album",))
        date_text = first_tag(tags, ("date", "year", "originaldate", "originalyear"))

        year = None
        if date_text:
            match = YEAR_RE.search(date_text)
            if match:
                year = match.group(0)

        return TrackMetadata(artist, track_artist, album_artist, title, album, year)
    except Exception as exc:
        return TrackMetadata(None, None, None, None, None, None, str(exc))


def clean_filename_stem(path: Path) -> str:
    stem = unicodedata.normalize("NFC", path.stem).strip()
    stem = TRACK_PREFIX_RE.sub("", stem).strip()
    return stem


def filename_hints(path: Path) -> tuple[Optional[str], str]:
    """Best-effort Artist - Title parsing used only as a search hint, never auto-applied."""
    stem = clean_filename_stem(path)
    if " - " not in stem:
        return None, stem
    left, right = stem.split(" - ", 1)
    left = left.strip()
    right = right.strip()
    if not left or not right:
        return None, stem
    if re.fullmatch(r"(?:disc|cd|track)?\s*\d+", left, re.IGNORECASE):
        return None, stem
    return left, right


def simplified_title_hint(title: str) -> str:
    """Remove common DJ-pool mix labels for a broader second MusicBrainz search."""
    simplified = re.sub(
        r"\s*[\(\[](?:original|extended|radio|club|album|single|clean|dirty|explicit)?\s*"
        r"(?:mix|edit|version)[^\)\]]*[\)\]]\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    return simplified or title


def normalize_artist_key(value: Optional[str]) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value.strip())
    return value.casefold()


def normalize_album_key(value: Optional[str]) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value.strip())
    return value.casefold()


def album_group_key(meta: TrackMetadata) -> Optional[str]:
    """Stable key for album-wide decisions such as a corrected release year."""
    if not meta.artist or not meta.album:
        return None
    return f"{normalize_artist_key(meta.artist)}\x1f{normalize_album_key(meta.album)}"


def apply_album_year_override(
    meta: TrackMetadata, overrides: dict[str, str]
) -> tuple[TrackMetadata, bool]:
    key = album_group_key(meta)
    if not key:
        return meta, False
    year = overrides.get(key)
    if not year or year == meta.year:
        return meta, False
    return replace(meta, year=year), True


def apply_album_year_to_correction(
    correction: MetadataCorrection, overrides: dict[str, str]
) -> tuple[MetadataCorrection, bool]:
    meta = metadata_from_correction(correction)
    key = album_group_key(meta)
    if not key:
        return correction, False
    year = overrides.get(key)
    if not year or year == correction.year:
        return correction, False
    return replace(correction, year=year), True


def artist_text_is_suspicious(value: Optional[str]) -> bool:
    if not value:
        return True
    normalized = normalize_artist_key(value)
    return normalized in PLACEHOLDER_ARTISTS or bool(DOMAIN_LIKE_RE.search(value))


def artist_is_suspicious(meta: TrackMetadata) -> tuple[bool, str]:
    if not meta.artist:
        return True, "artist is missing"
    normalized = normalize_artist_key(meta.artist)
    if normalized in PLACEHOLDER_ARTISTS:
        return True, f"artist looks like a placeholder: {meta.artist!r}"
    if DOMAIN_LIKE_RE.search(meta.artist):
        return True, f"artist looks like a web/domain tag: {meta.artist!r}"
    return False, ""


def metadata_review_reasons(meta: TrackMetadata) -> list[str]:
    """Return metadata problems worth checking online.

    Artist spelling/garbage is also handled by the per-artist sanity pass, but it
    remains here so truly missing/suspicious artists still get a track lookup.
    """
    reasons: list[str] = []
    suspicious, artist_reason = artist_is_suspicious(meta)
    if suspicious:
        reasons.append(artist_reason)
    if not meta.title:
        reasons.append("title is missing")
    if not meta.album or meta.album.strip().casefold() in {"unknown album", "unknown", "n/a", "none"}:
        reasons.append("album is missing")
    if not meta.year:
        reasons.append("year is missing")
    return reasons


def apply_artist_alias(
    meta: TrackMetadata, aliases: dict[str, str]
) -> tuple[TrackMetadata, Optional[tuple[str, str]]]:
    """Apply an approved folder-artist alias without clobbering valid featured artists."""
    current = meta.artist
    if not current:
        return meta, None
    canonical = aliases.get(normalize_artist_key(current))
    if not canonical or canonical.strip() == current.strip():
        return meta, None

    old_key = normalize_artist_key(current)
    track_artist = meta.track_artist
    album_artist = meta.album_artist

    # Album Artist controls the folder. Once the group correction is approved,
    # normalize it for every track in that group.
    album_artist = canonical

    # If the track artist was the same bad spelling/value (or unusable), repair it.
    # Preserve a genuinely different track artist such as a featured guest.
    if (
        not track_artist
        or normalize_artist_key(track_artist) == old_key
        or artist_text_is_suspicious(track_artist)
    ):
        track_artist = canonical

    fixed = TrackMetadata(
        artist=canonical,
        track_artist=track_artist,
        album_artist=album_artist,
        title=meta.title,
        album=meta.album,
        year=meta.year,
        metadata_error=meta.metadata_error,
    )
    return fixed, (current, canonical)


def apply_alias_to_correction(
    correction: MetadataCorrection, aliases: dict[str, str]
) -> MetadataCorrection:
    preferred = correction.album_artist or correction.artist
    canonical = aliases.get(normalize_artist_key(preferred))
    if not canonical or canonical.strip() == preferred.strip():
        return correction

    artist = correction.artist
    if normalize_artist_key(artist) == normalize_artist_key(preferred) or artist_text_is_suspicious(artist):
        artist = canonical
    return MetadataCorrection(
        artist=artist,
        album_artist=canonical,
        title=correction.title,
        album=correction.album,
        year=correction.year,
        musicbrainz_recording_id=correction.musicbrainz_recording_id,
        musicbrainz_release_id=correction.musicbrainz_release_id,
    )


def audio_duration_seconds(path: Path) -> Optional[float]:
    try:
        audio = MutagenFile(path)
        info = getattr(audio, "info", None)
        length = getattr(info, "length", None)
        if length is not None:
            return float(length)
    except Exception:
        pass
    return None


def artist_credit_text(credit) -> str:
    if not credit:
        return "Unknown Artist"
    pieces = []
    for item in credit:
        if isinstance(item, str):
            pieces.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or (item.get("artist") or {}).get("name") or ""
        pieces.append(name)
        joinphrase = item.get("joinphrase") or ""
        if joinphrase:
            pieces.append(joinphrase)
    text = "".join(pieces).strip()
    return text or "Unknown Artist"


def init_lookup_cache(path: Path) -> None:
    """Create/open the persistent MusicBrainz response cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                cache_key TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                params_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            )
            """
        )
        db.commit()


def _lookup_cache_key(endpoint: str, params: dict[str, str | int]) -> tuple[str, str]:
    params_json = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = f"{endpoint}\n{params_json}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), params_json


def lookup_cache_get(endpoint: str, params: dict[str, str | int]) -> Optional[dict]:
    if _MB_LOOKUP_CACHE_DB is None:
        return None
    key, _ = _lookup_cache_key(endpoint, params)
    try:
        with sqlite3.connect(_MB_LOOKUP_CACHE_DB) as db:
            row = db.execute(
                "SELECT response_json FROM responses WHERE cache_key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        return data if isinstance(data, dict) else None
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"Warning: lookup cache read failed: {exc}", file=sys.stderr)
        return None


def lookup_cache_put(endpoint: str, params: dict[str, str | int], data: dict) -> None:
    if _MB_LOOKUP_CACHE_DB is None:
        return
    key, params_json = _lookup_cache_key(endpoint, params)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    try:
        with sqlite3.connect(_MB_LOOKUP_CACHE_DB) as db:
            db.execute(
                """
                INSERT INTO responses(cache_key, endpoint, params_json, response_json, fetched_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response_json = excluded.response_json,
                    fetched_at = excluded.fetched_at
                """,
                (key, endpoint, params_json, payload, int(time.time())),
            )
            db.commit()
    except sqlite3.Error as exc:
        print(f"Warning: lookup cache write failed: {exc}", file=sys.stderr)


def _mb_retry_delay(attempt: int, exc: BaseException) -> float:
    """Return an exponential retry delay, honoring numeric Retry-After headers."""
    retry_after = 0.0
    headers = getattr(exc, "headers", None)
    if headers is not None:
        value = headers.get("Retry-After")
        if value:
            try:
                retry_after = max(0.0, float(value))
            except (TypeError, ValueError):
                pass

    backoff = min(MB_BACKOFF_START * (2 ** (attempt - 1)), MB_BACKOFF_MAX)
    # Small jitter keeps a retry from landing on the exact same server-side window.
    return max(retry_after, backoff) + random.uniform(0.0, 0.5)


def _mb_get(path: str, params: dict[str, str | int]) -> dict:
    """MusicBrainz GET: persistent local cache first, then paced/retried network."""
    global _MB_LAST_REQUEST

    cached = lookup_cache_get(path, params)
    if cached is not None:
        return cached

    query = urllib.parse.urlencode(params)
    url = f"{MB_BASE}{path}?{query}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": MB_USER_AGENT, "Accept": "application/json"},
    )

    for attempt in range(1, MB_MAX_ATTEMPTS + 1):
        # Pace every HTTP attempt, including retries.
        elapsed = time.monotonic() - _MB_LAST_REQUEST
        if elapsed < MB_MIN_INTERVAL:
            time.sleep(MB_MIN_INTERVAL - elapsed)

        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                data = json.load(response)
            _MB_LAST_REQUEST = time.monotonic()
            if isinstance(data, dict):
                lookup_cache_put(path, params, data)
            return data

        except urllib.error.HTTPError as exc:
            _MB_LAST_REQUEST = time.monotonic()
            retryable = exc.code in MB_RETRY_HTTP_CODES
            if not retryable or attempt >= MB_MAX_ATTEMPTS:
                raise

            delay = _mb_retry_delay(attempt, exc)
            print(
                f"\n  MusicBrainz HTTP {exc.code}; retrying in {delay:.1f}s "
                f"(retry {attempt}/{MB_MAX_ATTEMPTS - 1})...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)

        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            _MB_LAST_REQUEST = time.monotonic()
            if attempt >= MB_MAX_ATTEMPTS:
                raise

            delay = _mb_retry_delay(attempt, exc)
            reason = getattr(exc, "reason", None) or str(exc) or exc.__class__.__name__
            print(
                f"\n  MusicBrainz connection/response error ({reason}); "
                f"retrying in {delay:.1f}s (retry {attempt}/{MB_MAX_ATTEMPTS - 1})...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)

    raise RuntimeError("MusicBrainz request retry loop ended unexpectedly")


def lucene_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def first_artist_hint(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    # One strong artist token is generally better than forcing MusicBrainz to match
    # every comma/&/feat variation in a filename credit.
    first = re.split(r"\s*(?:,|&|\bx\b|\bfeat\.?\b|\bft\.?\b)\s*", value, maxsplit=1, flags=re.IGNORECASE)[0]
    first = first.strip()
    return first or None


def search_musicbrainz(path: Path, meta: TrackMetadata, limit: int = 5) -> list[MBRecordingCandidate]:
    """Search by embedded TITLE metadata, never by the filesystem filename."""
    title_hint = (meta.title or "").strip()
    if not title_hint:
        return []

    artist_hint = first_artist_hint(meta.track_artist) or first_artist_hint(meta.artist)
    simple_title = simplified_title_hint(title_hint)
    attempts: list[tuple[str, Optional[str]]] = []
    for candidate_title in (title_hint, simple_title):
        pair = (candidate_title, artist_hint)
        if pair not in attempts:
            attempts.append(pair)
    for candidate_title in (title_hint, simple_title):
        pair = (candidate_title, None)
        if pair not in attempts:
            attempts.append(pair)

    recordings_by_id: dict[str, dict] = {}
    for candidate_title, candidate_artist in attempts:
        clauses = [f'recording:"{lucene_quote(candidate_title)}"']
        if candidate_artist:
            clauses.append(f'artist:"{lucene_quote(candidate_artist)}"')
        query = " AND ".join(clauses)
        data = _mb_get(
            "/recording/",
            {"query": query, "fmt": "json", "limit": max(limit * 2, 10)},
        )
        batch = data.get("recordings", [])
        for rec in batch:
            rid = rec.get("id")
            if not rid:
                continue
            existing = recordings_by_id.get(rid)
            if existing is None or int(rec.get("score") or 0) > int(existing.get("score") or 0):
                recordings_by_id[rid] = rec

        best_raw = max((int(rec.get("score") or 0) for rec in recordings_by_id.values()), default=0)
        if best_raw >= 95:
            break

    recordings = list(recordings_by_id.values())
    local_duration = audio_duration_seconds(path)
    candidates: list[MBRecordingCandidate] = []
    for rec in recordings:
        rid = rec.get("id")
        title = rec.get("title")
        if not rid or not title:
            continue
        score = int(rec.get("score") or 0)
        length_ms = rec.get("length")
        try:
            length_ms = int(length_ms) if length_ms is not None else None
        except (TypeError, ValueError):
            length_ms = None

        adjusted = float(score)
        if local_duration is not None and length_ms is not None:
            delta = abs(local_duration - (length_ms / 1000.0))
            adjusted -= min(delta * 2.0, 35.0)

        candidates.append(
            MBRecordingCandidate(
                recording_id=rid,
                score=score,
                title=title,
                artist=artist_credit_text(rec.get("artist-credit")),
                first_release_date=rec.get("first-release-date"),
                length_ms=length_ms,
                adjusted_score=adjusted,
            )
        )

    candidates.sort(key=lambda c: (c.adjusted_score, c.score), reverse=True)
    return candidates[:limit]


def releases_for_recording(recording_id: str, current_album: Optional[str], limit: int = 8) -> list[MBReleaseCandidate]:
    data = _mb_get(
        "/release/",
        {
            "recording": recording_id,
            "fmt": "json",
            "inc": "artist-credits+release-groups",
            "limit": 50,
        },
    )
    releases = []
    for rel in data.get("releases", []):
        rid = rel.get("id")
        title = rel.get("title")
        if not rid or not title:
            continue
        rg = rel.get("release-group") or {}
        releases.append(
            MBReleaseCandidate(
                release_id=rid,
                title=title,
                artist=artist_credit_text(rel.get("artist-credit")),
                date=rel.get("date"),
                status=rel.get("status"),
                primary_type=rg.get("primary-type"),
            )
        )

    # Collapse regional/format duplicates that have the same useful tagging data.
    unique: dict[tuple[str, str, str, str], MBReleaseCandidate] = {}
    for rel in releases:
        year = (rel.date or "")[:4]
        key = (rel.title.casefold(), rel.artist.casefold(), year, (rel.primary_type or "").casefold())
        unique.setdefault(key, rel)
    releases = list(unique.values())

    current_norm = (current_album or "").strip().casefold()
    def rank(rel: MBReleaseCandidate):
        album_match = 1 if current_norm and rel.title.strip().casefold() == current_norm else 0
        official = 1 if (rel.status or "").casefold() == "official" else 0
        # Earlier dates are usually the original release rather than a later compilation.
        date_key = rel.date or "9999-99-99"
        return (-album_match, -official, date_key, rel.title.casefold())

    releases.sort(key=rank)
    return releases[:limit]


def choose_representative_track(
    paths: list[Path], metadata_by_path: dict[Path, TrackMetadata]
) -> Path:
    """Pick a track likely to give a clean MusicBrainz artist sanity check."""
    def score(path: Path) -> tuple[int, str]:
        meta = metadata_by_path[path]
        points = 0
        if meta.title:
            points += 5
        if meta.album:
            points += 4
        if meta.year:
            points += 1
        if meta.track_artist and not artist_text_is_suspicious(meta.track_artist):
            points += 2
        if (
            meta.track_artist
            and meta.artist
            and normalize_artist_key(meta.track_artist) == normalize_artist_key(meta.artist)
        ):
            points += 5
        text = f"{meta.track_artist or ''} {meta.title or ''}".casefold()
        if re.search(r"\b(?:feat|ft)\.?\b|&|\bx\b", text):
            points -= 2
        return points, str(path).casefold()

    return max(paths, key=score)


def artist_suggestion_from_sample(path: Path, meta: TrackMetadata) -> Optional[ArtistSuggestion]:
    """Identify one sample track and infer its release-level/canonical artist."""
    candidates = search_musicbrainz(path, meta, limit=5)
    if not candidates:
        return None
    recording = candidates[0]

    # Avoid acting on very weak fuzzy matches. The user can still fix the track
    # through the normal per-track metadata review if its metadata is incomplete.
    if recording.score < 80:
        return None

    # Most normal artist folders can be validated from the recording credit alone,
    # saving a second MusicBrainz request per artist. If it disagrees, inspect the
    # release artist because featured/collaboration credits often differ from the
    # album artist that should own the folder.
    if meta.artist and normalize_artist_key(recording.artist) == normalize_artist_key(meta.artist):
        return ArtistSuggestion(
            current_artist=meta.artist,
            suggested_artist=recording.artist,
            recording=recording,
            release=None,
        )

    release = None
    try:
        releases = releases_for_recording(recording.recording_id, meta.album, limit=5)
        if releases:
            release = releases[0]
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        # A recording match is still useful if the secondary release request fails.
        release = None

    suggested = (release.artist if release else recording.artist).strip()
    if not suggested or artist_text_is_suspicious(suggested):
        return None

    return ArtistSuggestion(
        current_artist=meta.artist or "",
        suggested_artist=suggested,
        recording=recording,
        release=release,
    )


def review_artist_groups(
    tracks: list[Path],
    metadata_by_path: dict[Path, TrackMetadata],
    source_root: Path,
    aliases: dict[str, str],
    reviews: dict[str, dict],
    dry_run: bool,
    cache_path: Path,
    metadata_cache: dict[str, dict],
) -> tuple[int, int, int]:
    """Check one representative recording from each current artist group.

    Accepted corrections are aliases from the bad folder artist to a canonical
    MusicBrainz artist. They are then applied to every track in that group.
    """
    groups: dict[str, list[Path]] = {}
    display_names: dict[str, str] = {}
    for path in tracks:
        meta = metadata_by_path[path]
        if not meta.artist:
            continue
        key = normalize_artist_key(meta.artist)
        groups.setdefault(key, []).append(path)
        display_names.setdefault(key, meta.artist)

    checked = 0
    changed = 0
    skipped_cached = 0
    group_items = sorted(groups.items(), key=lambda item: display_names[item[0]].casefold())

    print(f"\nArtist sanity check: {len(group_items)} artist groups")
    for number, (group_key, paths) in enumerate(group_items, start=1):
        current = display_names[group_key]

        if group_key in reviews:
            skipped_cached += 1
            continue

        # A compilation folder should not be renamed to whichever performer happens
        # to sing the representative track.
        if group_key in VARIOUS_ARTISTS_NAMES:
            reviews[group_key] = {
                "decision": "same",
                "suggested": current,
                "reason": "compilation artist",
            }
            aliases.setdefault(group_key, current)
            continue

        representative = choose_representative_track(paths, metadata_by_path)
        rep_meta = metadata_by_path[representative]
        print(
            f"\rChecking artist {number}/{len(group_items)}: {current[:60]:60}",
            end="",
            flush=True,
        )

        try:
            suggestion = artist_suggestion_from_sample(representative, rep_meta)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            print(f"\n  MusicBrainz lookup failed for {current!r}: {exc}")
            continue

        checked += 1
        if suggestion is None:
            continue

        suggested = suggestion.suggested_artist
        if normalize_artist_key(suggested) == group_key:
            reviews[group_key] = {
                "decision": "same",
                "suggested": suggested,
                "sample": representative.relative_to(source_root).as_posix(),
                "musicbrainz_recording_id": suggestion.recording.recording_id,
            }
            # Use MusicBrainz's capitalization/punctuation consistently even when the
            # name is otherwise equivalent (for example "queen" -> "Queen").
            aliases[group_key] = suggested
            for path in paths:
                metadata_by_path[path], _ = apply_artist_alias(metadata_by_path[path], aliases)
            continue

        print("\n\nArtist mismatch found")
        print("---------------------")
        print(f"Current folder artist: {current}")
        print(f"Tracks in this group:  {len(paths)}")
        print(f"Sample track:          {representative.name}")
        print(
            f"MusicBrainz match:     {suggestion.recording.artist} — "
            f"{suggestion.recording.title} [{suggestion.recording.score}%]"
        )
        if suggestion.release is not None:
            rel = suggestion.release
            print(
                f"Matched release:       {rel.artist} — {rel.title} "
                f"({rel.date or 'unknown date'})"
            )
        print(f"Suggested artist:      {suggested}")

        while True:
            answer = input(
                f"Change ALL {len(paths)} tracks from {current!r} to {suggested!r}? "
                "[Y/n/e=enter name]: "
            ).strip()
            lowered = answer.casefold()
            if lowered in {"", "y", "yes"}:
                canonical = suggested
                decision = "accepted"
                break
            if lowered in {"n", "no"}:
                canonical = current
                decision = "declined"
                break
            if lowered in {"e", "edit"}:
                manual = input("Canonical artist name: ").strip()
                if manual:
                    canonical = manual
                    decision = "manual"
                    break
                print("Artist name cannot be empty.")
                continue
            print("Enter Y, n, or e.")

        reviews[group_key] = {
            "decision": decision,
            "suggested": suggested,
            "chosen": canonical,
            "sample": representative.relative_to(source_root).as_posix(),
            "musicbrainz_recording_id": suggestion.recording.recording_id,
        }

        if decision in {"accepted", "manual"}:
            aliases[group_key] = canonical
            changed += 1
            for path in paths:
                metadata_by_path[path], _ = apply_artist_alias(metadata_by_path[path], aliases)
        else:
            aliases.setdefault(group_key, current)

        metadata_cache[CACHE_ARTIST_ALIASES_KEY] = aliases
        metadata_cache[CACHE_ARTIST_REVIEWS_KEY] = reviews
        if not dry_run:
            save_metadata_cache(cache_path, metadata_cache)

    print("\r" + " " * 100 + "\r", end="", flush=True)
    return checked, changed, skipped_cached


def fmt_duration_ms(length_ms: Optional[int]) -> str:
    if length_ms is None:
        return "?:??"
    seconds = max(0, int(round(length_ms / 1000)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def prompt_choice(prompt: str, count: int, default: Optional[int] = None) -> Optional[int]:
    while True:
        value = input(prompt).strip().casefold()
        if not value and default is not None:
            return default
        if value in {"s", "skip", "n", "no"}:
            return None
        if value in {"q", "quit"}:
            raise KeyboardInterrupt
        if value.isdigit():
            choice = int(value)
            if 1 <= choice <= count:
                return choice - 1
        print(f"Enter 1-{count}, s to skip, or q to quit.")


def prompt_recording_choice(count: int, allow_manual_year: bool) -> tuple[str, Optional[int]]:
    """Choose a MusicBrainz recording, or enter an album year without choosing one.

    Manual year entry deliberately preserves the track's current artist/title/album
    metadata.  It is intended for cases where those tags are already correct and the
    only problem is a missing/wrong release year.
    """
    while True:
        year_part = " / y=enter year" if allow_manual_year else ""
        value = input(
            f"Choose recording [1]{year_part} / s=skip / q=quit: "
        ).strip().casefold()
        if not value:
            return "recording", 0
        if allow_manual_year and value in {"y", "year", "enter year", "manual", "m"}:
            return "manual_year", None
        if value in {"s", "skip", "n", "no"}:
            return "skip", None
        if value in {"q", "quit"}:
            raise KeyboardInterrupt
        if value.isdigit():
            choice = int(value)
            if 1 <= choice <= count:
                return "recording", choice - 1
        if allow_manual_year:
            print(f"Enter 1-{count}, y to enter a year, s to skip, or q to quit.")
        else:
            print(f"Enter 1-{count}, s to skip, or q to quit.")


def prompt_manual_year(default: Optional[str] = None) -> Optional[str]:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"Enter 4-digit year{suffix} (s=skip): ").strip()
        if not value and default:
            return default
        if value.casefold() in {"s", "skip"}:
            return None
        if re.fullmatch(r"(?:18|19|20|21)\d{2}", value):
            return value
        print("Enter a 4-digit year from 1800-2199, or s to skip.")


def correction_with_manual_year(meta: TrackMetadata, year: str) -> Optional[MetadataCorrection]:
    """Create a year-only correction while preserving the current metadata."""
    artist = meta.track_artist or meta.artist
    album_artist = meta.album_artist or meta.artist or artist
    if not artist or not album_artist or not meta.title or not meta.album:
        return None
    return MetadataCorrection(
        artist=artist,
        album_artist=album_artist,
        title=meta.title,
        album=meta.album,
        year=year,
    )


def offer_manual_year_fallback(meta: TrackMetadata, reason: str) -> Optional[MetadataCorrection]:
    """Offer year-only repair when MusicBrainz cannot provide a usable lookup."""
    if meta.year or not meta.album or not meta.title or not (meta.track_artist or meta.artist):
        return None
    answer = input(f"{reason} Enter a year manually for album {meta.album!r}? [y/N]: ").strip().casefold()
    if answer not in {"y", "yes"}:
        return None
    year = prompt_manual_year()
    if year is None:
        return None
    return correction_with_manual_year(meta, year)


def prompt_release_choice(count: int) -> tuple[str, Optional[int]]:
    while True:
        value = input(
            "Choose release [1] / y=manual year / s=skip / q=quit: "
        ).strip().casefold()
        if not value:
            return "release", 0
        if value in {"y", "year", "m", "manual"}:
            return "manual_year", None
        if value in {"s", "skip", "n", "no"}:
            return "skip", None
        if value in {"q", "quit"}:
            raise KeyboardInterrupt
        if value.isdigit():
            choice = int(value)
            if 1 <= choice <= count:
                return "release", choice - 1
        print(f"Enter 1-{count}, y for a manual year, s to skip, or q to quit.")


def interactive_musicbrainz_correction(path: Path, meta: TrackMetadata) -> Optional[MetadataCorrection]:
    print("\nMetadata review")
    print("---------------")
    print(f"File:           {path.name}")
    print(f"Current artist: {meta.artist or '[missing]'}")
    print(f"Current title:  {meta.title or '[missing]'}")
    print(f"Current album:  {meta.album or '[missing]'}")
    print(f"Current year:   {meta.year or '[missing]'}")

    if not meta.title:
        print("Cannot search MusicBrainz: embedded title metadata is missing.")
        print("The filename is intentionally not used as a search title.")
        return None

    print(f"Search title:   {meta.title}")
    print("Searching local lookup cache, then MusicBrainz if needed...")

    try:
        candidates = search_musicbrainz(path, meta)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(f"MusicBrainz lookup failed: {exc}")
        return offer_manual_year_fallback(meta, "")

    if not candidates:
        print("No MusicBrainz recording matches found.")
        return offer_manual_year_fallback(meta, "")

    print("\nRecording matches:")
    for i, c in enumerate(candidates, start=1):
        date = c.first_release_date or "unknown date"
        print(
            f"  {i}. [{c.score:3d}%] {c.artist} — {c.title} "
            f"({fmt_duration_ms(c.length_ms)}, first released {date})"
        )

    # A year-only repair does not require choosing a recording. This is useful
    # when artist/title/album are already right but MusicBrainz has awkward or
    # incomplete release data. The caller handles the album-wide propagation.
    allow_manual_year = bool(meta.album and meta.title and (meta.track_artist or meta.artist))
    mode, choice = prompt_recording_choice(len(candidates), allow_manual_year)
    if mode == "skip":
        return None

    if mode == "manual_year":
        year = prompt_manual_year(meta.year)
        if year is None:
            return None
        correction = correction_with_manual_year(meta, year)
        if correction is None:
            print("Cannot apply a year-only correction because artist/title/album metadata is incomplete.")
            return None
    else:
        assert choice is not None
        recording = candidates[choice]

        print("\nFinding releases containing that recording...")
        try:
            releases = releases_for_recording(recording.recording_id, meta.album)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            print(f"Release lookup failed: {exc}")
            releases = []

        if not releases:
            print("No release records found.")
            inferred_year = None
            if recording.first_release_date:
                m = YEAR_RE.search(recording.first_release_date)
                inferred_year = m.group(0) if m else None
            manual = input(
                f"Enter a year manually? [{'Y' if not inferred_year else 'y'}/N] "
            ).strip().casefold()
            if manual in {"y", "yes"} or (manual == "" and not inferred_year):
                year = prompt_manual_year(inferred_year)
                if year is None:
                    return None
            else:
                year = inferred_year or meta.year

            album = meta.album
            if not album:
                entered = input(f"Album name [{recording.title}]: ").strip()
                album = entered or recording.title
            correction = MetadataCorrection(
                artist=recording.artist,
                album_artist=meta.album_artist or recording.artist,
                title=recording.title,
                album=album,
                year=year,
                musicbrainz_recording_id=recording.recording_id,
            )
        else:
            print("\nRelease choices:")
            for i, rel in enumerate(releases, start=1):
                date = rel.date or "unknown date"
                typ = rel.primary_type or "Release"
                status = rel.status or "unknown status"
                print(f"  {i}. {rel.artist} — {rel.title} ({date}; {typ}; {status})")
            mode, rchoice = prompt_release_choice(len(releases))
            if mode == "skip":
                return None

            if mode == "manual_year":
                year = prompt_manual_year(meta.year)
                if year is None:
                    return None
                # When entering a year manually from the release screen, preserve
                # the current album if it exists instead of silently adopting a
                # possibly-wrong MusicBrainz release title.
                if meta.album:
                    album = meta.album
                else:
                    entered = input(f"Album name [{releases[0].title}]: ").strip()
                    album = entered or releases[0].title
                correction = MetadataCorrection(
                    artist=meta.track_artist or recording.artist,
                    album_artist=meta.album_artist or meta.artist or recording.artist,
                    title=meta.title or recording.title,
                    album=album,
                    year=year,
                    musicbrainz_recording_id=recording.recording_id,
                )
            else:
                assert rchoice is not None
                release = releases[rchoice]
                year = None
                if release.date:
                    m = YEAR_RE.search(release.date)
                    year = m.group(0) if m else None
                if not year and recording.first_release_date:
                    m = YEAR_RE.search(recording.first_release_date)
                    year = m.group(0) if m else None
                correction = MetadataCorrection(
                    artist=recording.artist,
                    album_artist=release.artist or recording.artist,
                    title=recording.title,
                    album=release.title,
                    year=year,
                    musicbrainz_recording_id=recording.recording_id,
                    musicbrainz_release_id=release.release_id,
                )

    while True:
        print("\nWill use:")
        print(f"  Artist:       {correction.artist}")
        print(f"  Album artist: {correction.album_artist}")
        print(f"  Title:        {correction.title}")
        print(f"  Album:        {correction.album}")
        print(f"  Year:         {correction.year or '[missing]'}")
        confirm = input("Accept this metadata? [Y/n/e=edit year]: ").strip().casefold()
        if confirm in {"", "y", "yes"}:
            return correction
        if confirm in {"n", "no"}:
            return None
        if confirm in {"e", "edit", "year"}:
            year = prompt_manual_year(correction.year)
            if year is not None:
                correction = replace(correction, year=year)
            continue
        print("Enter Y, n, or e.")


def metadata_from_correction(c: MetadataCorrection) -> TrackMetadata:
    preferred = c.album_artist or c.artist
    return TrackMetadata(
        artist=preferred,
        track_artist=c.artist,
        album_artist=c.album_artist,
        title=c.title,
        album=c.album,
        year=c.year,
    )


def write_metadata_updates(path: Path, updates: dict[str, Optional[str]]) -> list[str]:
    """Write selected easy-tag fields to a copied file and return warnings."""
    warnings: list[str] = []
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return ["Mutagen could not identify copied file for tag writing"]
        if audio.tags is None:
            try:
                audio.add_tags()
            except Exception as exc:
                return [f"could not create tags: {exc}"]

        for key, value in updates.items():
            if not value:
                continue
            try:
                audio[key] = [value]
            except Exception as exc:
                warnings.append(f"could not write {key}: {exc}")
        audio.save()
    except Exception as exc:
        warnings.append(str(exc))
    return warnings


def write_corrected_metadata(path: Path, correction: MetadataCorrection) -> list[str]:
    """Apply an approved full MusicBrainz correction."""
    updates: dict[str, Optional[str]] = {
        "artist": correction.artist,
        "albumartist": correction.album_artist,
        "title": correction.title,
        "album": correction.album,
        "date": correction.year,
    }
    return write_metadata_updates(path, updates)


def write_artist_alias_metadata(path: Path, meta: TrackMetadata) -> list[str]:
    """Persist a group-level artist correction into the sanitized copy."""
    return write_metadata_updates(
        path,
        {
            "artist": meta.track_artist,
            "albumartist": meta.album_artist or meta.artist,
        },
    )


def cache_key(path: Path, source_root: Path) -> str:
    st = path.stat()
    rel = path.relative_to(source_root).as_posix()
    return f"{rel}|{st.st_size}|{st.st_mtime_ns}"


def load_metadata_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"Warning: could not read metadata cache {path}: {exc}")
        return {}


def save_metadata_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def correction_from_cache(raw: dict) -> Optional[MetadataCorrection]:
    try:
        return MetadataCorrection(**raw)
    except Exception:
        return None


def resized_jpeg(data: bytes, max_px: int, quality: int) -> tuple[bytes, bool, tuple[int, int], tuple[int, int]]:
    """Return artwork bytes, whether changed, old dimensions, new dimensions."""
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        old_size = img.size
        if img.width <= max_px and img.height <= max_px:
            return data, False, old_size, old_size

        # Preserve aspect ratio; HiBy's UI does not need large source artwork.
        if img.mode not in ("RGB", "L"):
            # Flatten transparency against black only if needed; normal covers are opaque.
            if "A" in img.getbands():
                base = Image.new("RGB", img.size, (0, 0, 0))
                alpha = img.getchannel("A")
                base.paste(img.convert("RGB"), mask=alpha)
                img = base
            else:
                img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        new_size = img.size
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=False)
        return out.getvalue(), True, old_size, new_size


def sanitize_id3_art(path: Path, max_px: int, quality: int) -> ArtworkResult:
    result = ArtworkResult()
    try:
        tags = ID3(path)
    except Exception:
        # WAV/AIFF may still expose ID3 through the generic Mutagen object.
        try:
            audio = MutagenFile(path)
            tags = getattr(audio, "tags", None)
            if tags is None or not hasattr(tags, "getall"):
                return result
        except Exception as exc:
            return ArtworkResult(error=str(exc))

    frames = list(tags.getall("APIC"))
    result.found = len(frames)
    if not frames:
        return result

    changed_any = False
    new_frames = []
    for frame in frames:
        try:
            new_data, changed, _, _ = resized_jpeg(frame.data, max_px, quality)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            # Preserve malformed/unknown art instead of deleting it.
            new_frames.append(frame)
            result.error = f"Could not decode one APIC image: {exc}"
            continue

        if changed:
            changed_any = True
            result.resized += 1
            new_frames.append(
                APIC(
                    encoding=frame.encoding,
                    mime="image/jpeg",
                    type=frame.type,
                    desc=frame.desc,
                    data=new_data,
                )
            )
        else:
            new_frames.append(frame)

    if changed_any:
        tags.delall("APIC")
        for frame in new_frames:
            tags.add(frame)
        tags.save(path)

    return result


def sanitize_flac_art(path: Path, max_px: int, quality: int) -> ArtworkResult:
    result = ArtworkResult()
    try:
        audio = FLAC(path)
        pictures = list(audio.pictures)
        result.found = len(pictures)
        if not pictures:
            return result

        changed_any = False
        new_pictures = []
        for pic in pictures:
            try:
                new_data, changed, _, new_size = resized_jpeg(pic.data, max_px, quality)
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                new_pictures.append(pic)
                result.error = f"Could not decode one FLAC picture: {exc}"
                continue

            if not changed:
                new_pictures.append(pic)
                continue

            changed_any = True
            result.resized += 1
            new_pic = Picture()
            new_pic.type = pic.type
            new_pic.mime = "image/jpeg"
            new_pic.desc = pic.desc
            new_pic.width, new_pic.height = new_size
            new_pic.depth = 24
            new_pic.colors = 0
            new_pic.data = new_data
            new_pictures.append(new_pic)

        if changed_any:
            audio.clear_pictures()
            for pic in new_pictures:
                audio.add_picture(pic)
            audio.save()
        return result
    except Exception as exc:
        return ArtworkResult(error=str(exc))


def sanitize_mp4_art(path: Path, max_px: int, quality: int) -> ArtworkResult:
    result = ArtworkResult()
    try:
        audio = MP4(path)
        if audio.tags is None:
            return result
        covers = list(audio.tags.get("covr", []))
        result.found = len(covers)
        if not covers:
            return result

        changed_any = False
        new_covers = []
        for cover in covers:
            raw = bytes(cover)
            try:
                new_data, changed, _, _ = resized_jpeg(raw, max_px, quality)
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                new_covers.append(cover)
                result.error = f"Could not decode one MP4 cover: {exc}"
                continue
            if changed:
                changed_any = True
                result.resized += 1
                new_covers.append(MP4Cover(new_data, imageformat=MP4Cover.FORMAT_JPEG))
            else:
                new_covers.append(cover)

        if changed_any:
            audio.tags["covr"] = new_covers
            audio.save()
        return result
    except Exception as exc:
        return ArtworkResult(error=str(exc))


def sanitize_vorbis_art(path: Path, max_px: int, quality: int) -> ArtworkResult:
    """Resize standard METADATA_BLOCK_PICTURE artwork in Ogg/Opus-style tags."""
    result = ArtworkResult()
    try:
        audio = MutagenFile(path)
        tags = getattr(audio, "tags", None)
        if tags is None:
            return result
        values = tags.get("metadata_block_picture")
        if not values:
            return result
        if not isinstance(values, list):
            values = [values]
        result.found = len(values)

        changed_any = False
        new_values = []
        for encoded in values:
            try:
                raw_picture = base64.b64decode(encoded)
                pic = Picture(raw_picture)
                new_data, changed, _, new_size = resized_jpeg(pic.data, max_px, quality)
            except Exception as exc:
                new_values.append(encoded)
                result.error = f"Could not decode one Vorbis picture: {exc}"
                continue

            if changed:
                changed_any = True
                result.resized += 1
                pic.mime = "image/jpeg"
                pic.width, pic.height = new_size
                pic.depth = 24
                pic.colors = 0
                pic.data = new_data
                new_values.append(base64.b64encode(pic.write()).decode("ascii"))
            else:
                new_values.append(encoded)

        if changed_any:
            tags["metadata_block_picture"] = new_values
            audio.save()
        return result
    except Exception as exc:
        return ArtworkResult(error=str(exc))


# Prefer an album's front artwork over booklet/back-cover images. When there
# isn't a recognizable name, a single candidate JPG/PNG in the same directory
# is reasonably unambiguous; multiple unrecognized images must not be guessed.
FOLDER_ART_EXTS = {".jpg", ".jpeg", ".png"}
FRONT_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartlarge", "albumartsmall")
NON_FRONT_NAMES = (
    "back", "rear", "disc", "disk", "cd", "booklet", "inside", "insert",
    "spine", "tray", "thumbnail", "thumb", "artist", "logo",
)


def _cover_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", value).casefold())


def find_folder_art(folder: Path, album: Optional[str]) -> tuple[Optional[Path], Optional[str]]:
    """Return (front-cover file, error for ambiguous/broken selection)."""
    try:
        pictures = sorted(
            (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in FOLDER_ART_EXTS),
            key=lambda p: p.name.casefold(),
        )
    except OSError as exc:
        return None, f"Cannot scan folder for artwork ({exc})"
    if not pictures:
        return None, None

    # Explicit filenames outrank generic, and JPEG outranks PNG for tied stems.
    suffix_rank = {".jpg": 0, ".jpeg": 1, ".png": 2}
    ranked = sorted(pictures, key=lambda p: (suffix_rank[p.suffix.lower()], p.name.casefold()))
    names = {_cover_name_key(p.stem): p for p in ranked[::-1]}
    for name in FRONT_NAMES:
        if name in names:
            return names[name], None

    # Album-name artwork commonly ships as "Album Name.jpg".
    album_key = _cover_name_key(album or "")
    if album_key and album_key in names:
        return names[album_key], None

    plausible = [
        p for p in pictures
        if not any(_cover_name_key(p.stem).startswith(n) for n in NON_FRONT_NAMES)
    ]
    if len(plausible) == 1:
        return plausible[0], None
    if len(plausible) == 0:
        return None, None  # Only non-cover images were present.

    return None, (
        "Multiple possible album covers in one folder: "
        + ", ".join(p.name for p in plausible)
        + ". Rename the intended image cover.jpg (or front.jpg)."
    )


def prepare_folder_art(path: Path, max_px: int, quality: int) -> tuple[bytes, tuple[int, int], bool]:
    """Normalize external artwork to baseline RGB JPEG, <= max_px square."""
    with Image.open(path) as img:
        img.load()
        old_size = img.size
        # Apply EXIF rotation to external photos before resizing/embedding.
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            if "A" in img.getbands():
                base = Image.new("RGB", img.size, (0, 0, 0))
                base.paste(img.convert("RGB"), mask=img.getchannel("A"))
                img = base
            else:
                img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True, progressive=False)
        return output.getvalue(), img.size, max(old_size) > max_px


def embed_folder_art(audio_path: Path, jpeg_data: bytes, image_size: tuple[int, int]) -> ArtworkResult:
    """Replace old front/embedded covers in a copied audio file."""
    ext = audio_path.suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(audio_path)
            audio.clear_pictures()
            picture = Picture()
            picture.type = 3  # Front cover.
            picture.mime = "image/jpeg"
            picture.desc = "Cover"
            picture.width, picture.height = image_size
            picture.depth = 24
            picture.colors = 0
            picture.data = jpeg_data
            audio.add_picture(picture)
            audio.save()

        elif ext in {".m4a", ".mp4"}:
            audio = MP4(audio_path)
            if audio.tags is None:
                audio.add_tags()
            audio.tags["covr"] = [MP4Cover(jpeg_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

        elif ext in {".mp3", ".wav", ".wave", ".aif", ".aiff"}:
            audio = MutagenFile(audio_path)
            if audio is None:
                raise ValueError("Mutagen cannot read this audio file")
            if audio.tags is None:
                audio.add_tags()
            if not hasattr(audio.tags, "delall"):
                raise ValueError("Audio file has no ID3 tags for APIC artwork")
            audio.tags.delall("APIC")
            audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg_data))
            audio.save()

        elif ext in {".ogg", ".oga", ".opus"}:
            audio = MutagenFile(audio_path)
            if audio is None:
                raise ValueError("Mutagen cannot read this audio file")
            if audio.tags is None:
                audio.add_tags()
            picture = Picture()
            picture.type = 3
            picture.mime = "image/jpeg"
            picture.desc = "Cover"
            picture.width, picture.height = image_size
            picture.depth = 24
            picture.colors = 0
            picture.data = jpeg_data
            audio.tags["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
            # These legacy fields can otherwise still display outdated art.
            for key in ("coverart", "coverartmime"):
                if key in audio.tags:
                    del audio.tags[key]
            audio.save()

        else:
            raise ValueError(f"Embedding external covers is not supported for {ext} files")
        return ArtworkResult(found=1, external_embedded=1)
    except Exception as exc:
        return ArtworkResult(error=str(exc))


def sanitize_artwork(path: Path, max_px: int, quality: int) -> ArtworkResult:
    ext = path.suffix.lower()
    if ext == ".flac":
        return sanitize_flac_art(path, max_px, quality)
    if ext in {".m4a", ".mp4"}:
        return sanitize_mp4_art(path, max_px, quality)
    if ext in {".ogg", ".oga", ".opus"}:
        return sanitize_vorbis_art(path, max_px, quality)
    if ext in {".mp3", ".wav", ".wave", ".aif", ".aiff"}:
        return sanitize_id3_art(path, max_px, quality)

    # APE/WMA/WavPack/DSD metadata can be read by Mutagen, but artwork storage
    # varies. Leave those files untouched rather than risk corrupting tags.
    return ArtworkResult()


def audio_files(source: Path, destination: Path) -> list[Path]:
    destination_resolved = destination.resolve(strict=False)
    found: list[Path] = []
    for root, dirs, files in os.walk(source):
        root_path = Path(root)
        # Defensive: if destination is inside source, do not recurse into it.
        dirs[:] = [
            d for d in dirs
            if (root_path / d).resolve(strict=False) != destination_resolved
        ]
        for filename in files:
            path = root_path / filename
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                found.append(path)
    found.sort(key=lambda p: str(p).casefold())
    return found


def validate_paths(source: Path, destination: Path) -> tuple[Path, Path]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve(strict=False)
    if not source.is_dir():
        raise SystemExit(f"Source is not a directory: {source}")
    if source == destination:
        raise SystemExit("Source and destination must be different directories.")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        raise SystemExit("Destination cannot be inside the source library.")
    return source, destination


def main() -> int:
    args = parse_args()
    if args.art_max < 64:
        raise SystemExit("--art-max must be at least 64 pixels")
    if not 1 <= args.jpeg_quality <= 95:
        raise SystemExit("--jpeg-quality must be between 1 and 95")

    source, destination = validate_paths(args.source, args.destination)
    online_review = args.online_review or args.online_review_all
    cache_path = (args.metadata_cache or (metadata_dir() / "corrections.json")).expanduser().resolve(strict=False)
    metadata_cache = load_metadata_cache(cache_path)

    global _MB_LOOKUP_CACHE_DB
    _MB_LOOKUP_CACHE_DB = (
        args.lookup_cache or (metadata_dir() / "musicbrainz.sqlite3")
    ).expanduser().resolve(strict=False)
    init_lookup_cache(_MB_LOOKUP_CACHE_DB)

    raw_aliases = metadata_cache.get(CACHE_ARTIST_ALIASES_KEY, {})
    artist_aliases: dict[str, str] = {
        str(k): str(v) for k, v in raw_aliases.items()
        if isinstance(k, str) and isinstance(v, str) and v.strip()
    } if isinstance(raw_aliases, dict) else {}

    raw_reviews = metadata_cache.get(CACHE_ARTIST_REVIEWS_KEY, {})
    artist_reviews: dict[str, dict] = {
        str(k): v for k, v in raw_reviews.items()
        if isinstance(k, str) and isinstance(v, dict)
    } if isinstance(raw_reviews, dict) else {}

    raw_album_years = metadata_cache.get(CACHE_ALBUM_YEARS_KEY, {})
    album_year_overrides: dict[str, str] = {
        str(k): str(v) for k, v in raw_album_years.items()
        if isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"(?:18|19|20|21)\d{2}", v)
    } if isinstance(raw_album_years, dict) else {}

    if args.clean and destination.exists() and not args.dry_run:
        # Minimal safety guard against catastrophic typos.
        if destination == Path(destination.anchor) or len(destination.parts) < 3:
            raise SystemExit(f"Refusing to --clean suspicious destination: {destination}")
        shutil.rmtree(destination)

    tracks = audio_files(source, destination)
    total = len(tracks)
    if total == 0:
        print("No supported audio files found.")
        return 0

    reserved: set[Path] = set()
    copied = 0
    missing_author = 0
    metadata_errors = 0
    art_found = 0
    art_resized = 0
    art_errors = 0
    external_embedded = 0
    cover_failures = 0
    folder_art_selection: dict[tuple[Path, str], tuple[Optional[Path], Optional[str]]] = {}
    folder_art_jpegs: dict[Path, tuple[bytes, tuple[int, int], bool]] = {}
    online_reviewed = 0
    online_corrected = 0
    cached_corrections = 0
    tag_write_warnings = 0
    group_checks = 0
    group_changes = 0
    group_cached = 0

    print(f"Source:      {source}")
    print(f"Destination: {destination}")
    print(f"Tracks:      {total}")
    print(f"Artwork max: {args.art_max}x{args.art_max}")
    if args.dry_run:
        print("Mode:        DRY RUN")
    if online_review:
        if args.online_review_all:
            mode = "artist sanity check + offer lookup for every track"
        else:
            mode = "artist sanity check + missing/suspicious artist, title, album, or year"
        if args.no_artist_review:
            mode += " (artist sanity check disabled)"
        print(f"Online review: MusicBrainz ({mode})")
    if online_review or metadata_cache:
        print(f"Metadata cache: {cache_path}")
    if online_review:
        print(f"Lookup cache:   {_MB_LOOKUP_CACHE_DB}")
    print()

    # Pre-read metadata once. This lets us reason about whole artist groups before
    # creating any destination paths.
    original_metadata: dict[Path, TrackMetadata] = {}
    metadata_by_path: dict[Path, TrackMetadata] = {}
    cached_track_corrections: dict[Path, MetadataCorrection] = {}

    for index, src in enumerate(tracks, start=1):
        raw_meta = extract_metadata(src)
        original_metadata[src] = raw_meta
        meta = raw_meta

        key = cache_key(src, source)
        cached = correction_from_cache(metadata_cache.get(key, {}))
        if cached is not None:
            cached = apply_alias_to_correction(cached, artist_aliases)
            cached_track_corrections[src] = cached
            meta = metadata_from_correction(cached)
            cached_corrections += 1

        meta, _ = apply_artist_alias(meta, artist_aliases)
        meta, _ = apply_album_year_override(meta, album_year_overrides)
        metadata_by_path[src] = meta

        if not args.verbose and index % 250 == 0:
            print(f"\rReading metadata {index}/{total}...", end="", flush=True)

    if not args.verbose and total >= 250:
        print("\r" + " " * 60 + "\r", end="", flush=True)

    try:
        # Stage 1: one representative track per artist. This catches bad-but-present
        # values such as "A Peefect Circle" or album text accidentally stored as artist.
        if online_review and not args.no_artist_review:
            group_checks, group_changes, group_cached = review_artist_groups(
                tracks=tracks,
                metadata_by_path=metadata_by_path,
                source_root=source,
                aliases=artist_aliases,
                reviews=artist_reviews,
                dry_run=args.dry_run,
                cache_path=cache_path,
                metadata_cache=metadata_cache,
            )
            metadata_cache[CACHE_ARTIST_ALIASES_KEY] = artist_aliases
            metadata_cache[CACHE_ARTIST_REVIEWS_KEY] = artist_reviews
            metadata_cache[CACHE_ALBUM_YEARS_KEY] = album_year_overrides
            for path in tracks:
                metadata_by_path[path], _ = apply_album_year_override(
                    metadata_by_path[path], album_year_overrides
                )
            if not args.dry_run:
                save_metadata_cache(cache_path, metadata_cache)

        # Stage 2: repair incomplete track metadata and build the sanitized tree.
        for index, src in enumerate(tracks, start=1):
            meta = metadata_by_path[src]
            correction = cached_track_corrections.get(src)
            if correction is not None:
                correction = apply_alias_to_correction(correction, artist_aliases)
                correction, _ = apply_album_year_to_correction(correction, album_year_overrides)
                meta = metadata_from_correction(correction)
                meta, _ = apply_artist_alias(meta, artist_aliases)
                meta, _ = apply_album_year_override(meta, album_year_overrides)
            else:
                meta, _ = apply_album_year_override(meta, album_year_overrides)

            if correction is None and online_review:
                reasons = metadata_review_reasons(meta)
                should_review = args.online_review_all or bool(reasons)

                if should_review:
                    online_reviewed += 1
                    if reasons:
                        print(f"\n[{index}/{total}] Review reason: {'; '.join(reasons)}")
                    elif args.online_review_all:
                        answer = input(
                            f"\n[{index}/{total}] Search MusicBrainz for title {meta.title!r}? [y/N]: "
                        ).strip().casefold()
                        should_review = answer in {"y", "yes"}

                    if should_review:
                        before_review = meta
                        correction = interactive_musicbrainz_correction(src, meta)
                        if correction is not None:
                            correction = apply_alias_to_correction(correction, artist_aliases)
                            online_corrected += 1
                            meta = metadata_from_correction(correction)
                            meta, _ = apply_artist_alias(meta, artist_aliases)

                            # If this lookup changed/filled the year, optionally apply it
                            # to every track in the same album so we do not ask song-by-song.
                            if correction.year and correction.year != before_review.year:
                                before_key = album_group_key(before_review)
                                after_key = album_group_key(meta)
                                group_keys = {k for k in (before_key, after_key) if k}
                                matching = [
                                    p for p, m in metadata_by_path.items()
                                    if album_group_key(m) in group_keys
                                ]
                                if len(matching) > 1:
                                    answer = input(
                                        f"Apply year {correction.year} to all {len(matching)} tracks "
                                        f"in album {correction.album!r}? [Y/n]: "
                                    ).strip().casefold()
                                    if answer in {"", "y", "yes"}:
                                        for group_key in group_keys:
                                            album_year_overrides[group_key] = correction.year
                                        for album_path in matching:
                                            metadata_by_path[album_path] = replace(
                                                metadata_by_path[album_path], year=correction.year
                                            )
                                            cached_album_correction = cached_track_corrections.get(album_path)
                                            if cached_album_correction is not None:
                                                cached_track_corrections[album_path] = replace(
                                                    cached_album_correction, year=correction.year
                                                )
                                        metadata_cache[CACHE_ALBUM_YEARS_KEY] = album_year_overrides

                            correction, _ = apply_album_year_to_correction(
                                correction, album_year_overrides
                            )
                            meta = metadata_from_correction(correction)
                            metadata_by_path[src] = meta
                            metadata_cache[cache_key(src, source)] = asdict(correction)
                            metadata_cache[CACHE_ALBUM_YEARS_KEY] = album_year_overrides
                            if not args.dry_run:
                                save_metadata_cache(cache_path, metadata_cache)

            dst, is_missing = build_destination(src, source, destination, meta, reserved)

            if is_missing:
                missing_author += 1
            if original_metadata[src].metadata_error:
                metadata_errors += 1

            if args.verbose or args.dry_run:
                rel_src = src.relative_to(source)
                rel_dst = dst.relative_to(destination)
                marker = "MISSING ARTIST" if is_missing else "OK"
                print(f"[{index:>5}/{total}] {marker}: {rel_src} -> {rel_dst}")
                if original_metadata[src].metadata_error:
                    print(f"              metadata warning: {original_metadata[src].metadata_error}")
            elif index == 1 or index == total or index % 25 == 0:
                print(f"\rProcessing {index}/{total}...", end="", flush=True)

            if args.dry_run:
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1

            warnings: list[str] = []
            if correction is not None:
                warnings = write_corrected_metadata(dst, correction)
            else:
                original = original_metadata[src]
                updates: dict[str, Optional[str]] = {}
                artist_changed = (
                    original.artist != meta.artist
                    or original.album_artist != meta.album_artist
                    or original.track_artist != meta.track_artist
                )
                if artist_changed:
                    updates["artist"] = meta.track_artist
                    updates["albumartist"] = meta.album_artist or meta.artist
                if meta.year and original.year != meta.year:
                    updates["date"] = meta.year
                if updates:
                    warnings = write_metadata_updates(dst, updates)

            tag_write_warnings += len(warnings)
            if warnings and args.verbose:
                for warning in warnings:
                    print(f"              tag-write warning: {warning}")

            # External album artwork is attached to source folders, not the
            # output artist/year/album tree; inspect BEFORE discarding the inbox.
            selection_key = (src.parent, meta.album or "")
            if selection_key not in folder_art_selection:
                folder_art_selection[selection_key] = find_folder_art(src.parent, meta.album)
            cover_path, selection_error = folder_art_selection[selection_key]

            if selection_error:
                # Importer must not discard a JPG which has not been safely
                # embedded. Finish processing, then return a failing status.
                cover_failures += 1
                art_errors += 1
                print(f"\nERROR: {src.relative_to(source)}: {selection_error}", file=sys.stderr)
                art = ArtworkResult()
            elif cover_path is not None:
                try:
                    if cover_path not in folder_art_jpegs:
                        folder_art_jpegs[cover_path] = prepare_folder_art(
                            cover_path, args.art_max, args.jpeg_quality
                        )
                    jpeg_data, cover_size, cover_resized = folder_art_jpegs[cover_path]
                    art = embed_folder_art(dst, jpeg_data, cover_size)
                    art.resized = int(cover_resized and art.external_embedded > 0)
                    if art.error:
                        raise ValueError(art.error)
                    if args.verbose:
                        print(f"              embedded folder cover: {cover_path.name}")
                except Exception as exc:
                    cover_failures += 1
                    art_errors += 1
                    print(
                        f"\nERROR: Failed to embed {cover_path.name} into "
                        f"{src.relative_to(source)}: {exc}",
                        file=sys.stderr,
                    )
                    art = ArtworkResult()
            else:
                # No folder art: retain previous behavior for embedded covers.
                art = sanitize_artwork(dst, args.art_max, args.jpeg_quality)
                if art.error:
                    art_errors += 1
                    if args.verbose:
                        print(f"              artwork warning: {art.error}")
            art_found += art.found
            art_resized += art.resized
            external_embedded += art.external_embedded

    except KeyboardInterrupt:
        print("\nStopped by user.")
        metadata_cache[CACHE_ARTIST_ALIASES_KEY] = artist_aliases
        metadata_cache[CACHE_ARTIST_REVIEWS_KEY] = artist_reviews
        metadata_cache[CACHE_ALBUM_YEARS_KEY] = album_year_overrides
        if not args.dry_run:
            save_metadata_cache(cache_path, metadata_cache)
        return 130

    metadata_cache[CACHE_ARTIST_ALIASES_KEY] = artist_aliases
    metadata_cache[CACHE_ARTIST_REVIEWS_KEY] = artist_reviews
    metadata_cache[CACHE_ALBUM_YEARS_KEY] = album_year_overrides
    if not args.dry_run and (online_review or metadata_cache):
        save_metadata_cache(cache_path, metadata_cache)

    if not args.verbose and not args.dry_run:
        print()

    print("\nSummary")
    print("-------")
    if args.dry_run:
        print(f"Would process:           {total}")
    else:
        print(f"Copied:                  {copied}")
    print(f"Missing artist:          {missing_author}")
    print(f"Metadata read warnings:  {metadata_errors}")
    if metadata_cache or online_review:
        print(f"Cached track fixes used: {cached_corrections}")
    if online_review and not args.no_artist_review:
        print(f"Artist groups checked:   {group_checks}")
        print(f"Artist groups corrected: {group_changes}")
        print(f"Artist groups cached:    {group_cached}")
    if online_review:
        print(f"Track reviews offered:   {online_reviewed}")
        print(f"New track corrections:   {online_corrected}")
    if metadata_cache or online_review:
        print(f"Tag-write warnings:      {tag_write_warnings}")
    if not args.dry_run:
        print(f"Artwork images handled:  {art_found}")
        print(f"Artwork images resized:  {art_resized}")
        print(f"Folder covers embedded:  {external_embedded}")
        print(f"Artwork warnings:        {art_errors}")

    if cover_failures:
        print(
            f"\nERROR: {cover_failures} track(s) could not be given their folder artwork. "
            "This run is not safe to import; original music/cover files must be kept.",
            file=sys.stderr,
        )
        return 4

    if missing_author:
        print(f"\nTracks still needing artist tags are under: {destination / 'missing-author'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

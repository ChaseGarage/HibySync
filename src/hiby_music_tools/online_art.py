#!/usr/bin/env python3
"""Interactive online album-art picker for a sanitized HiBy import staging tree.

Intended to run AFTER hiby-music-sanitize and BEFORE musicimport's merge/cleanup.
Only tracks without embedded covers are changed. Album searches use directory/tag
artist+album metadata, not filenames. Downloaded candidate images are cached.
"""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import io
import json
import os
from pathlib import Path

from hiby_music_tools.paths import metadata_dir
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PIL import Image, ImageOps
from mutagen import File as MutagenFile
from mutagen.flac import Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4Cover

USER_AGENT = "HiByMusicImportArtwork/1.0 (private music organizer; Python urllib)"
AUDIO = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".oga", ".opus", ".wav", ".wave", ".aif", ".aiff"}
SUFFIX_YEAR = re.compile(r"^(?:18|19|20|21)\d{2}-(.+)$")
_RETRY = {429, 500, 502, 503, 504}
LAST_MB = 0.0


@dataclass
class Album:
    artist: str
    title: str
    missing: list[Path]


@dataclass
class Candidate:
    source: str
    artist: str
    album: str
    url: str
    label: str = ""
    image_path: Path | None = None
    dimensions: tuple[int, int] = (0, 0)


def normalized(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.casefold()).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalized(a), normalized(b)).ratio()


def tag_text(tags, keys: tuple[str, ...]) -> str | None:
    if not tags:
        return None
    for key in keys:
        try:
            item = tags.get(key)
            if item:
                if hasattr(item, "text"):
                    item = item.text
                if isinstance(item, (tuple, list)):
                    item = item[0]
                if item is not None and str(item).strip():
                    return str(item).strip()
        except Exception:
            pass
    return None


def has_cover(audio, suffix: str) -> bool:
    if suffix == ".flac":
        return any(bool(x.data) for x in getattr(audio, "pictures", []))
    tags = getattr(audio, "tags", None)
    if not tags:
        return False
    if suffix in {".mp4", ".m4a"}:
        return bool(tags.get("covr"))
    if suffix in {".mp3", ".wav", ".wave", ".aif", ".aiff"}:
        return hasattr(tags, "getall") and bool(tags.getall("APIC"))
    if suffix in {".ogg", ".oga", ".opus"}:
        return bool(tags.get("metadata_block_picture") or tags.get("coverart"))
    return False


def scan(root: Path) -> dict[tuple[str, str], Album]:
    groups: dict[tuple[str, str], Album] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in AUDIO or not path.is_file():
            continue
        audio = MutagenFile(path)
        if audio is None:
            raise ValueError(f"Could not read tags to check for missing artwork: {path}")
        if has_cover(audio, path.suffix.lower()):
            continue
        rel = path.relative_to(root)
        # Sanitizer output: Artist / YYYY-Album / Title.ext.
        # Read embedded album tags preferentially, then fallback to folder name.
        artist = rel.parts[0] if len(rel.parts) >= 3 else None
        folder_album = path.parent.name
        folder_album = SUFFIX_YEAR.sub(r"\1", folder_album)
        tags = getattr(audio, "tags", None)
        album = tag_text(tags, ("album", "\xa9alb", "TALB")) or folder_album
        artist = artist or tag_text(tags, ("albumartist", "aART", "TPE2", "artist", "\xa9ART", "TPE1"))
        if not artist or artist.casefold() == "missing-author" or not album or album.casefold() in {"unknown", "unknown album"}:
            print(f"Skipping online cover lookup (missing artist/album): {rel}")
            continue
        key = (normalized(artist), normalized(album))
        if key not in groups:
            groups[key] = Album(artist=artist, title=album, missing=[])
        groups[key].missing.append(path)
    return groups


class Cache:
    def __init__(self, directory: Path):
        self.root = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / "online-art.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS lookups (key TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched INTEGER NOT NULL)")
        self.db.commit()
        (directory / "images").mkdir(exist_ok=True)

    def json_get(self, url: str) -> dict | None:
        row = self.db.execute("SELECT payload, fetched FROM lookups WHERE key=?", (url,)).fetchone()
        if row and time.time() - row[1] < 30 * 86400:
            return json.loads(row[0])
        return None

    def json_put(self, url: str, data: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO lookups VALUES(?,?,?)", (url, json.dumps(data), int(time.time())))
        self.db.commit()

    def image_file(self, url: str) -> Path:
        return self.root / "images" / (hashlib.sha256(url.encode()).hexdigest() + ".img")


def request_bytes(url: str, *, max_bytes: int = 12 * 1024 * 1024) -> bytes:
    global LAST_MB
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS artwork/API URLs are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,image/*;q=0.9,*/*;q=0.1"})
    for attempt in range(5):
        if urllib.parse.urlparse(url).hostname == "musicbrainz.org":
            delay = 1.25 - (time.monotonic() - LAST_MB)
            if delay > 0:
                time.sleep(delay)
        try:
            with urllib.request.urlopen(request, timeout=25) as resp:
                data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(f"Response exceeds {max_bytes // (1024*1024)} MiB: {url}")
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if e.code not in _RETRY or attempt == 4:
                raise
            retry_after = e.headers.get("Retry-After")
            try:
                wait = max(2 ** (attempt + 1), float(retry_after)) if retry_after else 2 ** (attempt + 1)
            except ValueError:
                wait = 2 ** (attempt + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == 4:
                raise
            wait = 2 ** (attempt + 1)
        finally:
            if urllib.parse.urlparse(url).hostname == "musicbrainz.org":
                LAST_MB = time.monotonic()
        print(f"  Network issue; retrying in {wait:.0f}s ({attempt + 1}/4)...")
        time.sleep(min(wait, 30))
    raise RuntimeError("Network retry limit exceeded")


def json_request(url: str, cache: Cache) -> dict:
    cached = cache.json_get(url)
    if cached is not None:
        return cached
    doc = json.loads(request_bytes(url, max_bytes=2 * 1024 * 1024))
    if not isinstance(doc, dict):
        raise ValueError("JSON response was not an object")
    cache.json_put(url, doc)
    return doc


def secure_art_url(url: str) -> str:
    # CAA JSON can contain http:// links to the same official archive host.
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in {"coverartarchive.org", "archive.org", "www.archive.org"}:
        raise ValueError(f"Unsupported Cover Art Archive URL host: {parsed.hostname}")
    return parsed._replace(scheme="https").geturl()


def musicbrainz_candidates(artist: str, album: str, cache: Cache) -> list[Candidate]:
    query = 'releasegroup:"' + album.replace('"', '\\"') + '" AND artist:"' + artist.replace('"', '\\"') + '"'
    url = "https://musicbrainz.org/ws/2/release-group/?" + urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 12})
    data = json_request(url, cache)
    matches = []
    for row in data.get("release-groups", []):
        title = row.get("title", "")
        credit = row.get("artist-credit", [])
        credited = "".join(x if isinstance(x, str) else x.get("name", "") for x in credit)
        score_artist = similarity(artist, credited) if credited else 0.0
        if similarity(album, title) < 0.83 or score_artist < 0.68:
            continue
        matches.append((score_artist + similarity(album, title), row, credited))
    matches.sort(key=lambda x: x[0], reverse=True)
    found = []
    for _score, row, credited in matches[:5]:
        rid = row.get("id")
        if not rid:
            continue
        art_url = f"https://coverartarchive.org/release-group/{rid}"
        try:
            art = json_request(art_url, cache)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            print(f"  Cover Art Archive error ({exc}); checking other candidates")
            continue
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"  Cover Art Archive unavailable ({exc}); checking other candidates")
            continue
        for cover in art.get("images", []):
            if not cover.get("front"):
                continue
            thumbnails = cover.get("thumbnails") or {}
            thumb = thumbnails.get("1200") or thumbnails.get("500") or thumbnails.get("large")
            if not thumb:
                continue
            try:
                image_url = secure_art_url(thumb)
            except ValueError:
                continue
            found.append(Candidate("Cover Art Archive", credited or artist, row.get("title") or album, image_url, row.get("first-release-date", "")))
            if len(found) >= 2:
                return found
    return found


def itunes_candidates(artist: str, album: str, cache: Cache) -> list[Candidate]:
    params = {"term": f"{artist} {album}", "entity": "album", "media": "music", "limit": 20, "country": "US"}
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(params)
    doc = json_request(url, cache)
    found = []
    for row in doc.get("results", []):
        ra = row.get("artistName", "")
        rt = row.get("collectionName", "")
        if similarity(artist, ra) < 0.68 or similarity(album, rt) < 0.73:
            continue
        artwork = row.get("artworkUrl100", "")
        parsed = urllib.parse.urlparse(artwork)
        if parsed.scheme not in {"http", "https"} or not (parsed.hostname or "").endswith("mzstatic.com"):
            continue
        # Apple's image CDN generally supports requested image dimensions.
        higher = re.sub(r"100x100", "1200x1200", parsed._replace(scheme="https").geturl())
        found.append(Candidate("Apple Music artwork", ra, rt, higher, str(row.get("releaseDate", "")[:10])))
    return found


def image_info(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return im.size


def download_candidate(candidate: Candidate, cache: Cache) -> bool:
    path = cache.image_file(candidate.url)
    if not path.is_file():
        urls = [candidate.url]
        # If Apple's CDN cannot serve the requested 1200px image, try smaller
        # official CDN sizes rather than silently dropping that candidate.
        if candidate.source == "Apple Music artwork" and "1200x1200" in candidate.url:
            urls += [candidate.url.replace("1200x1200", dim) for dim in ("600x600", "100x100")]
        for trial_url in urls:
            try:
                raw = request_bytes(trial_url)
                with Image.open(io.BytesIO(raw)) as im:
                    im.verify()
                tmp = path.with_suffix(".part")
                tmp.write_bytes(raw)
                tmp.replace(path)
                break
            except (OSError, urllib.error.HTTPError, ValueError) as exc:
                if trial_url == urls[-1]:
                    print(f"  Artwork unavailable ({exc})")
                    return False
    try:
        candidate.dimensions = image_info(path)
    except (OSError, ValueError) as exc:
        print(f"  Invalid cached image ({exc})")
        path.unlink(missing_ok=True)
        return False
    candidate.image_path = path
    return True


def show_preview(path: Path) -> None:
    if not sys.stdout.isatty():
        return
    if not shutil.which("chafa"):
        return
    try:
        subprocess.run(["chafa", "--size", "22x11", str(path)], check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  (Terminal image preview unavailable: {exc})")


def prepare_jpeg(path: Path, size: int, quality: int) -> tuple[bytes, tuple[int, int]]:
    with Image.open(path) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            if "A" in img.getbands():
                background = Image.new("RGB", img.size, (0, 0, 0))
                background.paste(img.convert("RGB"), mask=img.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=False)
        return out.getvalue(), img.size


def embed_one(path: Path, jpeg: bytes, size: tuple[int, int]) -> None:
    """Safely embed into a working copy and verify before replacing the file."""
    tmp = path.with_name(f".{path.stem}.art-{uuid.uuid4().hex}{path.suffix}")
    try:
        shutil.copy2(path, tmp)
        audio = MutagenFile(tmp)
        ext = path.suffix.lower()
        if audio is None:
            raise ValueError("Unrecognized audio format")
        if has_cover(audio, ext):
            return
        if ext == ".flac":
            pic = Picture()
            pic.type, pic.mime, pic.desc = 3, "image/jpeg", "Cover"
            pic.width, pic.height = size
            pic.depth, pic.colors, pic.data = 24, 0, jpeg
            audio.add_picture(pic)
        elif ext in {".mp4", ".m4a"}:
            if audio.tags is None:
                audio.add_tags()
            audio.tags["covr"] = [MP4Cover(jpeg, imageformat=MP4Cover.FORMAT_JPEG)]
        elif ext in {".mp3", ".wav", ".wave", ".aif", ".aiff"}:
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg))
        elif ext in {".ogg", ".oga", ".opus"}:
            if audio.tags is None:
                audio.add_tags()
            pic = Picture()
            pic.type, pic.mime, pic.desc = 3, "image/jpeg", "Cover"
            pic.width, pic.height = size
            pic.depth, pic.colors, pic.data = 24, 0, jpeg
            audio.tags["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
        else:
            raise ValueError(f"Unsupported audio format: {ext}")
        audio.save()
        check = MutagenFile(tmp)
        if check is None or not has_cover(check, ext):
            raise ValueError("Cover embedding could not be verified")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def find_candidates(artist: str, album: str, cache: Cache) -> list[Candidate]:
    choices = []
    try:
        choices = musicbrainz_candidates(artist, album, cache)
    except Exception as exc:
        print(f"  MusicBrainz lookup failed: {exc}")
    # Include an alternate catalog when possible; every result is manually reviewed.
    try:
        choices.extend(itunes_candidates(artist, album, cache))
    except Exception as exc:
        print(f"  Apple album artwork search failed: {exc}")
    ready = []
    seen_images: set[str] = set()
    for candidate in choices:
        if not download_candidate(candidate, cache):
            continue
        # Deduplicate same image returned by several releases/sources.
        with Image.open(candidate.image_path) as im:
            thumb = im.convert("RGB").resize((16, 16))
            fingerprint = hashlib.sha256(thumb.tobytes()).hexdigest()
        if fingerprint in seen_images:
            continue
        seen_images.add(fingerprint)
        ready.append(candidate)
        if len(ready) == 3:
            break
    return ready


def main() -> int:
    p = argparse.ArgumentParser(description="Interactively search and embed missing album art in a sanitized HiBy music staging folder")
    p.add_argument("library", type=Path, help="sanitized staging library produced by hiby-music-sanitize")
    p.add_argument("--cache", type=Path, default=metadata_dir() / "artwork")
    p.add_argument("--art-max", type=int, default=600)
    p.add_argument("--jpeg-quality", type=int, default=88)
    p.add_argument("--no-preview", action="store_true", help="suppress chafa inline previews")
    args = p.parse_args()
    root = args.library.expanduser().resolve()
    if not root.is_dir():
        p.error(f"Not a library folder: {root}")
    if args.art_max < 64 or args.art_max > 1024 or not 1 <= args.jpeg_quality <= 95:
        p.error("--art-max must be 64..1024 and --jpeg-quality must be 1..95")
    cache = Cache(args.cache.expanduser())
    groups = scan(root)
    print(f"\nOnline album art: {len(groups)} album(s) with missing embedded covers")
    if not groups:
        return 0
    fixed = 0
    skipped = 0
    try:
        for num, album in enumerate(groups.values(), 1):
            print(f"\n[{num}/{len(groups)}] {album.artist} — {album.title} ({len(album.missing)} missing covers)")
            print("  Searching MusicBrainz / Cover Art Archive and Apple...")
            candidates = find_candidates(album.artist, album.title, cache)
            if not candidates:
                print("  No suitable downloadable covers found; leaving tracks unchanged.")
                skipped += len(album.missing)
                continue
            for i, candidate in enumerate(candidates, 1):
                print(f"\n  {i}. {candidate.source}: {candidate.artist} — {candidate.album}")
                print(f"     Resolution: {candidate.dimensions[0]}×{candidate.dimensions[1]} px (downloaded candidate)")
                if candidate.label:
                    print(f"     Release: {candidate.label}")
                if not args.no_preview:
                    show_preview(candidate.image_path)
            # Default is skip: avoid accidentally accepting a wrong cover.
            # If the user declines an album-wide choice, continue to the
            # remaining tracks with the same cached candidates and previews.
            remaining = list(album.missing)
            while remaining:
                print(f"\n  Track: {remaining[0].name} ({len(remaining)} needing covers)")
                response = input(
                    f"  Choose [1-{len(candidates)}] / s=skip album / q=quit [s]: "
                ).strip().casefold()
                if response in {"", "s", "skip"}:
                    skipped += len(remaining)
                    break
                if response in {"q", "quit"}:
                    print("  Online artwork review cancelled. Inbox will be retained.")
                    return 130
                if response not in {str(i) for i in range(1, len(candidates)+1)}:
                    print("  Please choose a number, s, or q.")
                    continue
                chosen = candidates[int(response)-1]
                jpeg, dimensions = prepare_jpeg(chosen.image_path, args.art_max, args.jpeg_quality)
                print(f"  Selected {chosen.source} cover; embedding as {dimensions[0]}×{dimensions[1]} JPEG.")
                if len(remaining) > 1:
                    answer = input(
                        f"  Apply to all {len(remaining)} missing-cover tracks in this album? [Y/n]: "
                    ).strip().casefold()
                    all_tracks = answer in {"", "y", "yes"}
                else:
                    all_tracks = True
                targets = list(remaining) if all_tracks else [remaining[0]]
                for track in targets:
                    embed_one(track, jpeg, dimensions)
                    fixed += 1
                print(f"  Embedded in {len(targets)} track(s).")
                remaining = [] if all_tracks else remaining[1:]
    except (KeyboardInterrupt, EOFError):
        print("\nArtwork review interrupted; import will not clear the inbox.")
        return 130
    except Exception as exc:
        print(f"\nERROR: Artwork embedding/review failed: {exc}", file=sys.stderr)
        print("The importer will retain the Nicotine inbox.", file=sys.stderr)
        return 1
    print(f"\nOnline art complete: {fixed} track(s) updated, {skipped} still missing artwork.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

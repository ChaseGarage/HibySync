"""Shared HiBy destination rules, extracted unchanged from the sanitizer."""

import hashlib
from pathlib import Path
import re
import unicodedata

from .metadata import TrackMetadata

INVALID_COMPONENT_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_component(value: str, max_len: int = 140) -> str:
    """Make a metadata value safe as a single exFAT/FAT-friendly path component."""
    value = unicodedata.normalize("NFC", value).strip()
    value = INVALID_COMPONENT_CHARS.sub("-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        return "Unknown"

    if len(value) <= max_len:
        return value

    digest = hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{value[: max_len - 11].rstrip()} - {digest}"



def unique_destination(path: Path, source_relative: Path, reserved: set[Path]) -> Path:
    """Resolve collisions deterministically while keeping the normal name when possible."""
    if path not in reserved:
        reserved.add(path)
        return path

    digest = hashlib.sha1(str(source_relative).encode("utf-8", "replace")).hexdigest()[:8]
    candidate = path.with_name(f"{path.stem}__{digest}{path.suffix}")
    i = 2
    while candidate in reserved:
        candidate = path.with_name(f"{path.stem}__{digest}_{i}{path.suffix}")
        i += 1
    reserved.add(candidate)
    return candidate



def build_destination(
    source_file: Path,
    source_root: Path,
    destination_root: Path,
    meta: TrackMetadata,
    reserved: set[Path],
) -> tuple[Path, bool]:
    rel = source_file.relative_to(source_root)
    extension = source_file.suffix
    title_stem = safe_component(meta.title or source_file.stem)
    song_name = f"{title_stem}{extension}"

    if not meta.artist:
        # Keep the source subfolder context, but normalize the filename to TITLE.
        target = destination_root / "missing-author" / rel.parent / song_name
        return unique_destination(target, rel, reserved), True

    artist = safe_component(meta.artist)
    album = safe_component(meta.album or "Unknown Album")
    # If year is unknown, do not create "Unknown Year-Album". Use Album alone.
    album_dir = safe_component(f"{meta.year}-{album}") if meta.year else album
    target = destination_root / artist / album_dir / song_name
    return unique_destination(target, rel, reserved), False


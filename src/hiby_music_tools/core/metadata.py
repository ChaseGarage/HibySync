"""Shared metadata value object; imported by the CLI for compatibility."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TrackMetadata:
    # artist is the preferred folder artist (album artist first, then track artist).
    artist: Optional[str]
    track_artist: Optional[str]
    album_artist: Optional[str]
    title: Optional[str]
    album: Optional[str]
    year: Optional[str]
    metadata_error: Optional[str] = None


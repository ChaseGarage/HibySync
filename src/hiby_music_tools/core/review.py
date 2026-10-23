"""Pending review models and destination planning, with no filesystem writes."""

from dataclasses import dataclass, field, replace
from pathlib import Path

from hiby_music_tools import sanitize
from .interaction import Operation
from .metadata import TrackMetadata
from .naming import build_destination
from .files import optional_signature


@dataclass(frozen=True)
class Artwork:
    label: str
    thumbnail: bytes
    width: int
    height: int
    origin: str
    # Only a reference/preview is kept. Execution must reopen and validate art.
    path: Path
    index: int = 0
    signature: tuple[int, ...] | None = None


@dataclass
class Track:
    path: Path
    original: TrackMetadata
    proposed: TrackMetadata
    track_number: str = ""
    disc_number: str = ""
    original_track_number: str = ""
    original_disc_number: str = ""
    artwork: list[Artwork] = field(default_factory=list)
    selected_art: Artwork | None = None
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    artwork_warnings: list[str] = field(default_factory=list)
    artwork_approved: bool = False
    provenance: str = "Original tags"
    skip: bool = False
    signature: tuple[int, ...] | None = None

    @property
    def reasons(self):
        reasons = sanitize.metadata_review_reasons(self.proposed)
        if self.proposed.year and not sanitize.YEAR_RE.fullmatch(self.proposed.year):
            reasons.append("year must contain four digits")
        for label, value in (("track", self.track_number), ("disc", self.disc_number)):
            parts = value.split('/')
            if value and (len(parts) not in (1, 2) or
                          not all(p.isdecimal() and len(p) <= 6 and int(p) > 0 for p in parts)):
                reasons.append(f"invalid {label} number")
        if not self.selected_art:
            reasons.append("artwork is missing")
        return reasons + self.warnings + ([] if self.artwork_approved else self.artwork_warnings)


@dataclass
class Album:
    tracks: list[Track]
    skip: bool = False

    @property
    def artist(self):
        return self.tracks[0].proposed.artist or "Missing artist"

    @property
    def title(self):
        return self.tracks[0].proposed.album or self.tracks[0].path.parent.name

    @property
    def year(self):
        years = {t.proposed.year for t in self.tracks}
        if len(years) == 1:
            return next(iter(years)) or "Unknown year"
        return "Mixed years"

    @property
    def status(self):
        if any(t.error for t in self.tracks):
            return "Error"
        values = {(t.proposed.artist, t.proposed.album, t.proposed.year) for t in self.tracks}
        if len(values) > 1 or any(t.reasons for t in self.tracks):
            return "Needs Review"
        return "Ready"


@dataclass
class Session:
    source: Path
    library: Path
    albums: list[Album]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlanRow:
    source: Path
    destination: Path
    metadata_changes: str
    artwork_change: str
    warning: str
    action: str
    exists: bool = False
    destination_signature: tuple[int, ...] | None = None


def edit_album(album: Album, artist: str, title: str, year: str):
    """Explicit album-wide manual changes; preserve individual track artists."""
    for track in album.tracks:
        track.proposed = replace(track.proposed, artist=artist or track.proposed.track_artist,
                                 album_artist=artist or None, album=title or None,
                                 year=year or None)
        track.provenance = "Manual edit"


def build_plan(session: Session, operation: Operation | None = None) -> list[PlanRow]:
    """Use the CLI's exact naming/collision rules; never hash or modify files."""
    rows = []
    reserved = set()
    op = operation or Operation()
    # Match sanitizer ordering even though the UI groups albums separately.
    tracks = sorted(((album, t) for album in session.albums for t in album.tracks),
                    key=lambda pair: str(pair[1].path).casefold())
    for index, (album, track) in enumerate(tracks):
        op.progress('Building preview', index, len(tracks), str(track.path))
        destination, _ = build_destination(
            track.path, session.source, session.library, track.proposed, reserved)
        changes = []
        for name in ("album_artist", "track_artist", "album", "title", "year"):
            old, new = getattr(track.original, name), getattr(track.proposed, name)
            if old != new:
                changes.append(f"{name}: {old or '∅'} → {new or '∅'}")
        for name in ("track_number", "disc_number"):
            old, new = getattr(track, 'original_' + name), getattr(track, name)
            if old != new:
                changes.append(f"{name}: {old or '∅'} → {new or '∅'}")
        art = track.selected_art
        original_art = art and art.origin == 'embedded' and art.path == track.path and art.index == 0 and not track.artwork_approved
        artwork = (f"Selected {art.label} ({art.path}); HiBy JPEG ≤600 px, quality 88"
                   if art and not original_art else "Keep embedded artwork; resize if >600 px")
        if not art:
            artwork = "No artwork selected"
        issues = [track.error] if track.error else list(track.reasons)
        # Only path-existence warnings in milestone one. Byte/audio duplicate
        # detection and sanitized-output comparison belong to import planning.
        existing = None
        blocked = bool(track.error)
        try:
            existing = optional_signature(destination)
            if existing is not None:
                issues.append("Destination exists — conflict; duplicate comparison pending")
        except (OSError, ValueError) as exc:
            issues.append(f"Cannot inspect destination: {exc}")
            blocked = True
        action = "Skip" if album.skip or track.skip else "Blocked" if blocked else "Pending review"
        rows.append(PlanRow(track.path, destination, '; '.join(changes) or "Unchanged",
                            artwork, '; '.join(issues), action, existing is not None, existing))
    op.progress('Preview complete', len(tracks), len(tracks))
    return rows

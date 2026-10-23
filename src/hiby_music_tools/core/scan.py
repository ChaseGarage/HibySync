"""Read-only scan service. No subprocesses, network, prompts, or cache writes."""

from dataclasses import replace
import json
import os
from pathlib import Path

from mutagen import File as MutagenFile

from hiby_music_tools import sanitize
from hiby_music_tools.online_art import tag_text
from hiby_music_tools.paths import metadata_dir
from .artwork import embedded_previews, folder_previews
from .interaction import Operation
from .review import Album, Session, Track
from .files import signature


def validate_roots(source: Path, library: Path):
    source, library = source.expanduser().resolve(), library.expanduser().resolve()
    if source == library or source in library.parents or library in source.parents:
        raise ValueError('Incoming folder and library must be separate, non-nested directories.')
    if not source.is_dir():
        raise ValueError(f'Incoming folder does not exist: {source}')
    return source, library


def read_track(path: Path) -> Track:
    original = sanitize.extract_metadata(path)
    track = Track(path, original, replace(original))
    try:
        before = signature(path)
        audio = MutagenFile(path)
        if audio is None:
            raise ValueError('Unrecognized or damaged audio file')
        if original.metadata_error:
            raise ValueError(original.metadata_error)
        # The CLI easy-tag reader does not expose WAV/AIFF ID3 fields. Read
        # native frames for display/editing without changing CLI extraction.
        tags = audio.tags or {}
        def value(*keys):
            return tag_text(tags, keys)
        meta = replace(original,
                       track_artist=original.track_artist or value('artist', 'TPE1', '\xa9ART'),
                       album_artist=original.album_artist or value('albumartist', 'TPE2', 'aART'),
                       title=original.title or value('title', 'TIT2', '\xa9nam'),
                       album=original.album or value('album', 'TALB', '\xa9alb'))
        meta.artist = meta.album_artist or meta.track_artist
        date = value('date', 'TDRC', '\xa9day') or ''
        year = sanitize.YEAR_RE.search(date)
        meta.year = meta.year or (year.group(0) if year else None)
        track.original, track.proposed = meta, replace(meta)
        track.track_number = value('tracknumber', 'TRCK') or ''
        track.disc_number = value('discnumber', 'TPOS') or ''
        # MP4 stores number/total pairs instead of text.
        for key, attribute in (('trkn', 'track_number'), ('disk', 'disc_number')):
            pairs = tags.get(key)
            if pairs:
                number, total = pairs[0]
                setattr(track, attribute, f'{number}/{total}' if total else str(number))
        track.original_track_number = track.track_number
        track.original_disc_number = track.disc_number
        track.artwork, warnings = embedded_previews(audio, path)
        track.artwork_warnings.extend(warnings)
        if track.artwork:
            track.selected_art = track.artwork[0]
        track.signature = signature(path)
        if before != track.signature:
            raise ValueError('File changed while scanning; scan again')
    except Exception as exc:
        track.error = str(exc)
    return track


def approved_metadata(track: Track, cache: dict, source: Path):
    """Use previously approved decisions, retaining original tags separately."""
    correction = sanitize.correction_from_cache(cache.get(sanitize.cache_key(track.path, source), {}))
    if correction and (not all(isinstance(getattr(correction, field), str)
                               for field in ('artist', 'album_artist', 'title', 'album')) or
                       (correction.year is not None and not isinstance(correction.year, str))):
        track.warnings.append('Saved correction has invalid field types; original tags retained')
        correction = None
    aliases = cache.get(sanitize.CACHE_ARTIST_ALIASES_KEY, {})
    aliases = {k: v for k, v in aliases.items() if isinstance(v, str)} if isinstance(aliases, dict) else {}
    if correction:
        track.proposed = sanitize.metadata_from_correction(
            sanitize.apply_alias_to_correction(correction, aliases))
    track.proposed, _ = sanitize.apply_artist_alias(track.proposed, aliases)
    years = cache.get(sanitize.CACHE_ALBUM_YEARS_KEY, {})
    years = {k: v for k, v in years.items() if isinstance(v, str) and sanitize.YEAR_RE.fullmatch(v)} if isinstance(years, dict) else {}
    track.proposed, _ = sanitize.apply_album_year_override(track.proposed, years)
    if track.proposed != track.original:
        track.provenance = 'Previously approved correction cache'


def scan_inbox(source: Path, library: Path, operation: Operation | None = None,
               correction_cache: Path | None = None) -> Session:
    op = operation or Operation()
    source, library = validate_roots(source, library)
    warnings, files = [], []
    op.progress('Discovering audio', 0)
    def walk_error(exc):
        warnings.append(str(exc))
    for current, dirs, names in os.walk(source, onerror=walk_error, followlinks=False):
        op.checkpoint()
        # Never follow symlinks out of the inbox or into another library.
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
        for name in names:
            path = Path(current) / name
            if path.suffix.lower() in sanitize.AUDIO_EXTENSIONS and not path.is_symlink() and path.is_file():
                files.append(path)
        op.progress('Discovering audio', len(files), current=current)
    files.sort(key=lambda path: str(path).casefold())
    cache = {}
    cache_path = correction_cache or metadata_dir() / 'corrections.json'
    try:
        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding='utf-8'))
            if not isinstance(cache, dict):
                raise ValueError('Correction cache must be a JSON object')
    except (OSError, ValueError) as exc:
        cache = {}
        warnings.append(f'Could not read correction cache: {exc}')
    groups, folders = {}, {}
    for index, path in enumerate(files, 1):
        op.progress('Reading metadata and artwork', index - 1, len(files), str(path))
        track = read_track(path)
        try:
            if not track.error:
                approved_metadata(track, cache, source)
            if path.parent not in folders:
                folders[path.parent] = folder_previews(path.parent)
            art, art_warnings = folders[path.parent]
            track.artwork.extend(art)
            track.artwork_warnings.extend(art_warnings)
            # Preserve acceptable embedded art by default. Folder art remains
            # an explicit selectable alternative, rather than a silent replacement.
            if not track.selected_art:
                selected, error = sanitize.find_folder_art(path.parent, track.proposed.album)
                if error:
                    track.artwork_warnings.append(error)
                track.selected_art = next((a for a in art if a.path == selected), None)
        except Exception as exc:
            track.error = str(exc)
        # Folder boundary prevents unrelated similarly named albums merging.
        key = (path.parent, sanitize.normalize_album_key(track.original.album))
        groups.setdefault(key, []).append(track)
    albums = [Album(tracks) for tracks in groups.values()]
    for album in albums:
        # A declared track total is evidence of missing files. Without totals,
        # completeness is unknown; never invent a track list from filenames.
        discs = {}
        for track in album.tracks:
            discs.setdefault(track.disc_number.split('/')[0], []).append(track)
        for tracks in discs.values():
            totals = {t.track_number.split('/')[1] for t in tracks if '/' in t.track_number}
            numbers = [t.track_number.split('/')[0] for t in tracks if t.track_number]
            if len(totals) == 1 and next(iter(totals)).isdecimal() and len(next(iter(totals))) <= 6:
                expected = int(next(iter(totals)))
                if expected != len(set(numbers)):
                    for track in tracks:
                        track.warnings.append(f'Incomplete album: {len(set(numbers))} of {expected} declared tracks present')
            if len(numbers) != len(set(numbers)):
                for track in tracks:
                    track.warnings.append('Duplicate track numbers within disc')
    op.progress('Scan complete', len(files), len(files))
    return Session(source, library, albums, warnings)
